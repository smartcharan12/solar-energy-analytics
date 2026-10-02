"""
Stage 2 acceptance tests: does the MySQL pipeline produce the right answer?

Checks
  1. Row counts of every core table.
  2. Control totals equal the generator's ground truth.
  3. Referential and business integrity checks return zero failures.
  4. Every injected data-quality defect was detected (matched on record key).
  5. Every planted business scenario is surfaced by an analytical query
     from sql/08_analysis_queries.sql (the real deliverable, not a copy).

Run after sql/run_all.sh:   python python/validate_pipeline.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from db import get_engine

ROOT = Path(__file__).resolve().parents[1]
TRUTH = json.loads((ROOT / "data/ground_truth/expected_clean_totals.json").read_text())
DEFECTS = pd.read_csv(ROOT / "data/ground_truth/injected_defects.csv")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def scalar(conn, sql: str):
    return conn.execute(text(sql)).scalar()


def analysis_query(number: str) -> str:
    """Extract one query (e.g. 'Q14') from the analysis pack."""
    sql = (ROOT / "sql/08_analysis_queries.sql").read_text()
    blocks = re.split(r"\n(?=-- Q\d{2}\.)", sql)
    block = next(b for b in blocks if b.startswith(f"-- {number}."))
    return block.strip().rstrip(";")


def main() -> int:
    engine = get_engine()
    with engine.connect() as conn:
        # 1. Row counts
        counts = {t: scalar(conn, f"SELECT COUNT(*) FROM {t}") for t in
                  ["dim_location", "dim_project", "fact_energy_generation", "fact_financials", "fact_sustainability"]}
        check("dim_location rows", counts["dim_location"] == TRUTH["locations"], str(counts["dim_location"]))
        check("dim_project rows", counts["dim_project"] == TRUTH["projects"], str(counts["dim_project"]))
        for t in ["fact_energy_generation", "fact_financials", "fact_sustainability"]:
            check(f"{t} rows", counts[t] == TRUTH["energy_rows"], str(counts[t]))

        # 2. Control totals (exact, except maintenance: 3 imputed values are estimates)
        totals = conn.execute(text("""
            SELECT (SELECT SUM(energy_generated_mwh) FROM fact_energy_generation),
                   (SELECT SUM(revenue_inr) FROM fact_financials),
                   (SELECT SUM(operating_cost_inr) FROM fact_financials),
                   (SELECT SUM(maintenance_cost_inr) FROM fact_financials),
                   (SELECT SUM(depreciation_inr) FROM fact_financials),
                   (SELECT SUM(investment_amount_inr) FROM dim_project),
                   (SELECT SUM(capacity_mw) FROM dim_project)""")).one()
        energy, revenue, opex, maint, dep, invest, cap = (float(v) for v in totals)
        check("total energy = truth", abs(energy - TRUTH["total_energy_mwh"]) < 0.01, f"{energy:,.3f} MWh")
        check("total revenue = truth", abs(revenue - TRUTH["total_revenue_inr"]) < 1, f"INR {revenue:,.2f}")
        check("total operating cost = truth", abs(opex - TRUTH["total_operating_cost_inr"]) < 1, f"INR {opex:,.2f}")
        check("total depreciation = truth", abs(dep - TRUTH["total_depreciation_inr"]) < 1, f"INR {dep:,.2f}")
        check("total investment = truth", abs(invest - TRUTH["total_investment_inr"]) < 1, f"INR {invest:,.0f}")
        check("total capacity = truth", abs(cap - TRUTH["total_capacity_mw"]) < 0.01, f"{cap:,.1f} MW")
        maint_gap = (maint - TRUTH["total_maintenance_cost_inr"]) / TRUTH["total_maintenance_cost_inr"]
        check("maintenance within 0.01% (3 imputed months)", abs(maint_gap) < 1e-4, f"gap {maint_gap:+.5%}")

        # 3. Integrity
        integrity = {
            "energy rows without financials": """
                SELECT COUNT(*) FROM fact_energy_generation e
                LEFT JOIN fact_financials f USING (project_id, month_start_date) WHERE f.project_id IS NULL""",
            "energy x tariff = revenue": """
                SELECT COUNT(*) FROM fact_energy_generation e
                JOIN fact_financials f USING (project_id, month_start_date) JOIN dim_project p USING (project_id)
                WHERE ABS(e.energy_generated_mwh * p.ppa_tariff_inr_per_kwh * 1000 - f.revenue_inr) > 1""",
            "no capacity factor > 0.35": "SELECT COUNT(*) FROM fact_energy_generation WHERE capacity_factor > 0.35",
            "no generation before COD": """
                SELECT COUNT(*) FROM fact_energy_generation e JOIN dim_project p USING (project_id)
                WHERE e.month_start_date < DATE_FORMAT(p.installation_date, '%Y-%m-01')""",
            "no facts for under-construction projects": """
                SELECT COUNT(*) FROM fact_energy_generation e JOIN dim_project p USING (project_id)
                WHERE p.project_status = 'Under Construction'""",
        }
        for name, sql in integrity.items():
            n = scalar(conn, sql)
            check(name, n == 0, f"{n} failures")

        # 4. Every injected defect detected, matched on record key
        log = pd.read_sql(text("SELECT check_name, source_table, record_key FROM dq_issue_log"), conn)
        mapping = {
            "exact duplicate":            ("duplicate_row", None),
            "negative energy":            ("negative_energy", "stg_energy_generation"),
            "capacity_factor in percent": ("capacity_factor_in_percent", "stg_energy_generation"),
            "meter spike":                ("implausible_energy_spike", "stg_energy_generation"),
            "energy NULL":                ("null_energy", "stg_energy_generation"),
            "invalid date":               ("missing_scada_month", "fact_energy_generation"),
            "DD-MM-YYYY":                 ("alternate_date_format", "stg_energy_generation"),
            "weather sensor NULL":        ("missing_weather", "stg_energy_generation"),
            "maintenance_cost NULL":      ("null_maintenance_cost", "stg_financials"),
            "negative operating cost":    ("negative_operating_cost", "stg_financials"),
            "negative investment":        ("negative_investment", "stg_projects"),
            "stale duplicate":            ("stale_project_version", "stg_projects"),
            "test record":                ("invalid_project_record", "stg_projects"),
        }
        for pattern, (check_name, source) in mapping.items():
            injected = DEFECTS[DEFECTS.defect.str.contains(pattern, regex=False)]
            logged = log[log.check_name == check_name]
            if source:
                logged = logged[logged.source_table == source]
            if pattern == "exact duplicate":
                # duplicates are matched per file on count; the key is not unique by definition
                for f, src in [("raw_energy_generation", "stg_energy_generation"), ("raw_financials", "stg_financials"),
                               ("raw_locations", "stg_locations")]:
                    n_inj = (injected.file == f).sum()
                    n_log = len(log[(log.source_table == src) & log.check_name.isin(["duplicate_row", "duplicate_location"])])
                    check(f"defect detected: duplicates in {f}", n_inj == n_log, f"injected {n_inj}, logged {n_log}")
                continue
            missing = set(injected.record) - set(logged.record_key)
            check(f"defect detected: {pattern}", not missing and len(injected) > 0,
                  f"injected {len(injected)}, logged {len(logged)}" + (f", missing {sorted(missing)}" if missing else ""))
        orphans_logged = log[(log.check_name == "orphan_project_code") & (log.source_table == "stg_energy_generation")]
        check("defect detected: orphan project codes",
              len(orphans_logged) == (DEFECTS.defect == "orphan project_code").sum(), f"logged {len(orphans_logged)}")
        text_fixes = log[log.check_name == "non_standard_text"]
        n_text = DEFECTS.defect.str.contains("case|spelling|format 'l-19'").sum()
        check("defect detected: non-standard text", len(text_fixes) == n_text, f"injected {n_text}, logged {len(text_fixes)}")

        # 5. Planted scenarios surfaced by the analysis queries themselves
        flagged = pd.read_sql(text(analysis_query("Q14")), conn)
        decline = pd.read_sql(text(analysis_query("Q15")), conn)
        decliners = set(decline.loc[decline.pr_change_pct < -10, "project_code"])
        rule_hits = {
            r.project_code: r.flags for r in flagged.itertuples()
            if r.flags and r.flags != "bottom ROI quartile"
        }
        for code, scenario in TRUTH["planted_scenarios"].items():
            found_by = []
            if code in rule_hits:
                found_by.append(f"Q14: {rule_hits[code]}")
            if code in decliners:
                found_by.append("Q15: PR fell > 10%")
            check(f"planted {scenario} ({code}) surfaced", bool(found_by), "; ".join(found_by) or "NOT FOUND")

        # False-positive view: projects flagged with a root cause that were NOT planted
        extra = sorted(set(rule_hits) - set(TRUTH["planted_scenarios"]))
        print(f"\nProjects flagged by Q14 root-cause rules but not planted ({len(extra)}): "
              + ", ".join(f"{c} [{rule_hits[c]}]" for c in extra))

    width = max(len(n) for n, _, _ in results)
    print()
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
