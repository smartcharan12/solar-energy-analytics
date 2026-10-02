"""
Stage 4 reference implementation.

Computes, in pandas, every KPI that the DAX library defines, using the same
definitions, plus the two composite scores:

  * Investment Priority Score (IPS), region level
  * Sustainability Score, region level

Outputs
  powerbi/05_dax_expected_values.md   expected value per DAX measure (validation sheet)
  data/processed/region_scores.csv    scores and components
  MySQL ana_region_scores             same, for Power BI cross-checking

If a DAX measure in the report does not match this file, the DAX is wrong
(or the filter context differs from the one stated).

Run after advanced_analytics.py:  python python/scoring_and_expected_values.py
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from db import get_engine

ROOT = Path(__file__).resolve().parents[1]

# Weights: identical to the default values of the what-if parameters in Power BI.
IPS_WEIGHTS = {
    "roi_pct": 0.25,            # financial return
    "ebitda_margin": 0.10,      # profitability / cost control
    "capacity_factor": 0.10,    # realised asset productivity
    "solar_resource": 0.15,     # long-term resource quality (GHI)
    "pr_trend": 0.10,           # weather-normalised performance trend
    "co2_per_cr": 0.10,         # sustainability impact per rupee
    "availability": 0.20,       # operational reliability
}
SUST_WEIGHTS = {
    "co2_per_cr": 0.35,         # decarbonisation per rupee of capital
    "co2_per_mw": 0.25,         # decarbonisation per MW installed
    "co2_total": 0.25,          # absolute scale of impact
    "re_share_captive": 0.15,   # share of client demand met by solar
}
ALT_WEIGHTINGS = {
    "Default": IPS_WEIGHTS,
    "Equal weights": {k: 1 / 7 for k in IPS_WEIGHTS},
    "Return-heavy": {"roi_pct": 0.45, "ebitda_margin": 0.15, "capacity_factor": 0.05, "solar_resource": 0.10,
                     "pr_trend": 0.05, "co2_per_cr": 0.05, "availability": 0.15},
    "Resource & ESG-heavy": {"roi_pct": 0.15, "ebitda_margin": 0.05, "capacity_factor": 0.15, "solar_resource": 0.25,
                             "pr_trend": 0.10, "co2_per_cr": 0.20, "availability": 0.10},
}


def to_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if df[col].dtype == object:
            s = df[col].dropna()
            if len(s) and isinstance(s.iloc[0], Decimal):
                df[col] = df[col].astype(float)
    return df


def kpis(pm: pd.DataFrame) -> dict:
    """Every non-time KPI, exactly as the DAX measures define them."""
    e = pm.energy_generated_mwh.sum()
    w = pm.dropna(subset=["irradiation_kwh_m2"])
    dt = pm.dropna(subset=["downtime_hours"])
    capital_years = pm.investment_amount_inr.sum() / 12
    mw_months = pm.capacity_mw.sum()
    captive = pm.dropna(subset=["renewable_energy_pct"])
    return {
        "Total Energy (MWh)": e,
        "Avg Energy per Project-Month (MWh)": e / len(pm),
        "Capacity Factor": e / (pm.capacity_mw * pm.hours_in_month).sum(),
        "Performance Ratio": w.energy_generated_mwh.sum() / (w.capacity_mw * w.irradiation_kwh_m2).sum(),
        "Availability": 1 - dt.downtime_hours.sum() / (dt.hours_in_month / 2).sum(),
        "Revenue": pm.revenue_inr.sum(),
        "Operating Cost": pm.operating_cost_inr.sum(),
        "Maintenance Cost": pm.maintenance_cost_inr.sum(),
        "Depreciation": pm.depreciation_inr.sum(),
        "EBITDA": pm.ebitda_inr.sum(),
        "EBIT (Profit)": pm.ebit_inr.sum(),
        "Capital Employed (capital-years)": capital_years,
        "ROI %": pm.ebit_inr.sum() / capital_years,
        "EBITDA Yield %": pm.ebitda_inr.sum() / capital_years,
        "Profit Margin %": pm.ebit_inr.sum() / pm.revenue_inr.sum(),
        "EBITDA Margin %": pm.ebitda_inr.sum() / pm.revenue_inr.sum(),
        "Revenue per MW (₹ lakh/yr)": pm.revenue_inr.sum() / mw_months * 12 / 1e5,
        "Profit per MW (₹ lakh/yr)": pm.ebit_inr.sum() / mw_months * 12 / 1e5,
        "Investment Efficiency (revenue yield %)": pm.revenue_inr.sum() / capital_years,
        "MWh per ₹ Cr per year": e / (capital_years / 1e7),
        "Payback (years)": capital_years / pm.ebitda_inr.sum(),
        "Realised Tariff (₹/kWh)": pm.revenue_inr.sum() / (e * 1000),
        "CO2 Avoided (t)": pm.co2_avoided_tonnes.sum(),
        "CO2 per MW-year (t)": pm.co2_avoided_tonnes.sum() / mw_months * 12,
        "CO2 per ₹ Cr-year (t)": pm.co2_avoided_tonnes.sum() / (capital_years / 1e7),
        "Equivalent Households (avg/month)": pm.groupby("month_start_date").equivalent_households.sum().mean(),
        "Renewable Share, captive %": ((captive.renewable_energy_pct / 100 * captive.site_consumption_mwh).sum()
                                       / captive.site_consumption_mwh.sum()) if len(captive) else np.nan,
    }


def pctl_rank(s: pd.Series) -> pd.Series:
    """Share of OTHER members strictly below this one: 0 = worst, 1 = best.
    Same as the DAX pattern COUNTROWS(FILTER(tbl, [@v] < cur)) / (n - 1)."""
    n = len(s)
    return s.apply(lambda v: (s < v).sum() / (n - 1))


def region_scores(pm: pd.DataFrame, proj: pd.DataFrame) -> pd.DataFrame:
    rows = []
    fys = sorted(pm.fiscal_year.unique())
    for region, g in pm.groupby("region"):
        k = kpis(g)
        op = proj[(proj.region == region) & (proj.project_status == "Operational")]
        w_first = g[(g.fiscal_year == fys[0])].dropna(subset=["irradiation_kwh_m2"])
        w_last = g[(g.fiscal_year == fys[-1])].dropna(subset=["irradiation_kwh_m2"])
        pr_first = w_first.energy_generated_mwh.sum() / (w_first.capacity_mw * w_first.irradiation_kwh_m2).sum()
        pr_last = w_last.energy_generated_mwh.sum() / (w_last.capacity_mw * w_last.irradiation_kwh_m2).sum()
        rows.append({
            "region": region,
            "projects": op.project_id.nunique(),
            "energy_gwh": k["Total Energy (MWh)"] / 1000,
            "roi_pct": k["ROI %"],
            "ebitda_margin": k["EBITDA Margin %"],
            "capacity_factor": k["Capacity Factor"],
            "solar_resource": (op.annual_ghi_kwh_m2_day * op.capacity_mw).sum() / op.capacity_mw.sum(),
            "pr_trend": pr_last / pr_first - 1,
            "co2_per_cr": k["CO2 per ₹ Cr-year (t)"],
            "availability": k["Availability"],
            "co2_per_mw": k["CO2 per MW-year (t)"],
            "co2_total": k["CO2 Avoided (t)"],
            "re_share_captive": k["Renewable Share, captive %"],
        })
    r = pd.DataFrame(rows).set_index("region")
    for c in set(IPS_WEIGHTS) | set(SUST_WEIGHTS):
        r[f"p_{c}"] = pctl_rank(r[c])
    for name, weights in ALT_WEIGHTINGS.items():
        r[f"IPS {name}"] = 100 * sum(r[f"p_{c}"] * wt for c, wt in weights.items()) / sum(weights.values())
        r[f"Rank {name}"] = r[f"IPS {name}"].rank(ascending=False, method="min").astype(int)
    r["Investment Priority Score"] = r["IPS Default"]
    r["Sustainability Score"] = 100 * sum(r[f"p_{c}"] * wt for c, wt in SUST_WEIGHTS.items())
    return r.sort_values("Investment Priority Score", ascending=False)


def time_kpis(pm: pd.DataFrame) -> dict:
    by_month = pm.groupby("month_start_date").energy_generated_mwh.sum().sort_index()
    rev_month = pm.groupby("month_start_date").revenue_inr.sum().sort_index()
    last = by_month.index.max()
    fy = pm.groupby("fiscal_year").energy_generated_mwh.sum()
    fy_rev = pm.groupby("fiscal_year").revenue_inr.sum()

    # like-for-like: projects with 12 months in both FY2024-25 and FY2025-26
    months = pm.groupby(["project_id", "fiscal_year"]).size().unstack()
    lfl = months.index[(months.get("FY2024-25") == 12) & (months.get("FY2025-26") == 12)]
    l = pm[pm.project_id.isin(lfl)].groupby("fiscal_year").energy_generated_mwh.sum()

    return {
        "Energy FY2025-26 (MWh)": fy["FY2025-26"],
        "Energy PY (FY2024-25) (MWh)": fy["FY2024-25"],
        "Energy YoY % (FY2025-26)": fy["FY2025-26"] / fy["FY2024-25"] - 1,
        "Energy Variance vs PY (MWh)": fy["FY2025-26"] - fy["FY2024-25"],
        "LFL Energy YoY % (FY2025-26)": l["FY2025-26"] / l["FY2024-25"] - 1,
        "LFL projects (FY2025-26)": len(lfl),
        "Energy MoM % (Mar-2026)": by_month[last] / by_month.iloc[-2] - 1,
        "Rolling 3M Energy at Mar-2026 (MWh)": by_month.iloc[-3:].sum(),
        "Rolling 12M Energy at Mar-2026 (MWh)": by_month.iloc[-12:].sum(),
        "Energy FYTD at Mar-2026 (MWh)": fy["FY2025-26"],
        "Energy FYTD at Sep-2025 (MWh)": by_month.loc["2025-04-01":"2025-09-01"].sum(),
        "Revenue YTD at Mar-2026 (₹)": fy_rev["FY2025-26"],
        "Revenue YoY % (FY2025-26)": fy_rev["FY2025-26"] / fy_rev["FY2024-25"] - 1,
        "Revenue Rolling 12M at Mar-2026 (₹)": rev_month.iloc[-12:].sum(),
    }


def fmt(name: str, v: float) -> str:
    if "%" in name and "₹" not in name:
        return f"{100 * v:.2f} %"
    if name.endswith("(₹)") or name in {"Revenue", "Operating Cost", "Maintenance Cost", "Depreciation", "EBITDA",
                                        "EBIT (Profit)", "Capital Employed (capital-years)"}:
        return f"₹ {v / 1e7:,.2f} Cr  ({v:,.0f})"
    if name in {"Capacity Factor", "Performance Ratio", "Availability"}:
        return f"{v:.4f}  ({100 * v:.2f} %)"
    if "projects" in name.lower() or name == "Flagged Months":
        return f"{int(v)}"
    return f"{v:,.2f}"


def main() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        pm = to_numeric(pd.read_sql(text("""
            SELECT m.*, d.project_status, d.annual_ghi_kwh_m2_day
            FROM vw_project_month m JOIN vw_dim_project d ON d.project_id = m.project_id"""), conn))
        proj = to_numeric(pd.read_sql(text("SELECT * FROM vw_dim_project"), conn))
        perf = to_numeric(pd.read_sql(text("SELECT * FROM vw_project_performance"), conn))
        diag_m = to_numeric(pd.read_sql(text("SELECT * FROM ana_month_diagnostics"), conn))
        diag_p = to_numeric(pd.read_sql(text("SELECT * FROM ana_project_diagnostics"), conn))
    pm["month_start_date"] = pd.to_datetime(pm.month_start_date)

    portfolio = kpis(pm)
    portfolio["Total Investment, all 60 projects (₹)"] = proj.investment_amount_inr.sum()
    portfolio["Total Investment, operational (₹)"] = proj.loc[proj.project_status == "Operational",
                                                              "investment_amount_inr"].sum()
    op = proj[proj.project_status == "Operational"]
    portfolio["Capex per MW (₹ Cr)"] = op.investment_amount_inr.sum() / op.capacity_mw.sum() / 1e7
    portfolio["Median Project ROI %"] = perf.roi_pct.median() / 100
    portfolio["Installed Capacity incl. pipeline (MW)"] = proj.capacity_mw.sum()
    portfolio["Operating Capacity at Mar-2026 (MW)"] = proj.loc[
        (proj.project_status == "Operational") & (pd.to_datetime(proj.installation_date) <= "2026-03-31"),
        "capacity_mw"].sum()
    modelled = diag_m.dropna(subset=["potential_mwh"])
    portfolio["Actual vs Potential %"] = modelled.energy_generated_mwh.sum() / modelled.potential_mwh.sum() - 1
    portfolio["Downtime Loss (₹ Cr)"] = diag_m.downtime_loss_inr.sum() / 1e7
    portfolio["Unexplained Loss (₹ Cr)"] = diag_m.unexplained_loss_inr.sum() / 1e7
    portfolio["Avoidable Loss (₹ Cr)"] = diag_p.lost_revenue_inr.sum() / 1e7
    portfolio["Flagged Months"] = (diag_m.month_flags.fillna("") != "").sum()
    portfolio["Projects With Root-Cause Flag"] = (diag_p.suspected_root_cause.fillna("") != "").sum()
    tk = time_kpis(pm)
    fy26 = kpis(pm[pm.fiscal_year == "FY2025-26"])
    west = kpis(pm[pm.region == "West"])
    scores = region_scores(pm, proj)

    perf = perf.sort_values("roi_pct", ascending=False)
    energy_share = pm.groupby("region").energy_generated_mwh.sum() / pm.energy_generated_mwh.sum()

    # ---- persist scores -------------------------------------------------------
    out = scores.reset_index()
    out.to_csv(ROOT / "data/processed/region_scores.csv", index=False)
    with engine.begin() as conn:
        out.to_sql("ana_region_scores", conn, if_exists="replace", index=False)

    # ---- validation sheet -------------------------------------------------------
    L = ["# 05 — DAX Expected Values (validation sheet)", "",
         "> Generated by `python/scoring_and_expected_values.py` from the MySQL views. Do not edit by hand.",
         "> Build the measure in Power BI, set the filter context shown, and compare. A mismatch beyond rounding "
         "means the DAX or the relationships are wrong.", "",
         "## A. Portfolio, no filters (all fiscal years, all projects)", "",
         "| Measure | Expected value |", "|---|---|"]
    L += [f"| {k} | {fmt(k, v)} |" for k, v in portfolio.items()]
    L += ["", "## B. Time intelligence (Date table marked, fiscal year ends 31 March)", "",
          "| Measure and context | Expected value |", "|---|---|"]
    L += [f"| {k} | {fmt(k, v)} |" for k, v in tk.items()]
    L += ["", "## C. Filter context checks", "", "| Measure | FY2025-26 only | Region = West |", "|---|---|---|"]
    for k in ["Total Energy (MWh)", "Capacity Factor", "Revenue", "EBIT (Profit)", "ROI %", "EBITDA Margin %",
              "CO2 Avoided (t)", "Availability"]:
        L.append(f"| {k} | {fmt(k, fy26[k])} | {fmt(k, west[k])} |")
    L += ["", "## D. Ranking", "",
          f"- **Top Project (ROI):** {perf.iloc[0].project_code} {perf.iloc[0].project_name} — "
          f"{perf.iloc[0].roi_pct:.2f} %",
          f"- **Bottom Project (ROI):** {perf.iloc[-1].project_code} {perf.iloc[-1].project_name} — "
          f"{perf.iloc[-1].roi_pct:.2f} %",
          "- **Top 5 projects by ROI:** " + ", ".join(f"{r.project_code} ({r.roi_pct:.2f} %)"
                                                      for r in perf.head(5).itertuples()),
          "", "| Region | Energy Contribution % | ROI % | Region Rank (ROI) |", "|---|---|---|---|"]
    roi_rank = scores.roi_pct.rank(ascending=False, method="dense").astype(int)
    for region in scores.sort_values("roi_pct", ascending=False).index:
        L.append(f"| {region} | {100 * energy_share[region]:.2f} % | {100 * scores.loc[region, 'roi_pct']:.2f} % | "
                 f"{roi_rank[region]} |")
    L += ["", "## E. Investment Priority Score and Sustainability Score (region, default weights)", "",
          "| Region | IPS | Rank | Sustainability Score | ROI pctl | Margin pctl | CF pctl | Resource pctl | "
          "PR-trend pctl | CO2/₹Cr pctl | Availability pctl |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for region, r in scores.iterrows():
        L.append(f"| {region} | {r['Investment Priority Score']:.1f} | {r['Rank Default']} | "
                 f"{r['Sustainability Score']:.1f} | " + " | ".join(
                     f"{r['p_' + c]:.1f}" for c in IPS_WEIGHTS) + " |")
    L += ["", "### Raw component values", "",
          "| Region | ROI % | EBITDA margin % | CF % | GHI kWh/m²/day | PR trend FY24→FY26 % | CO2 t per ₹Cr-yr | "
          "Availability % | CO2 t per MW-yr | CO2 kt | RE share captive % |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for region, r in scores.iterrows():
        L.append(f"| {region} | {100 * r.roi_pct:.2f} | {100 * r.ebitda_margin:.2f} | {100 * r.capacity_factor:.2f} | "
                 f"{r.solar_resource:.2f} | {100 * r.pr_trend:+.2f} | {r.co2_per_cr:.1f} | {100 * r.availability:.2f} | "
                 f"{r.co2_per_mw:.0f} | {r.co2_total / 1000:,.1f} | {100 * r.re_share_captive:.1f} |")
    L += ["", "### Ranking stability under alternative weightings", "",
          "| Region | " + " | ".join(ALT_WEIGHTINGS) + " |", "|---|" + "---|" * len(ALT_WEIGHTINGS)]
    for region, r in scores.iterrows():
        L.append(f"| {region} | " + " | ".join(f"#{int(r['Rank ' + n])} ({r['IPS ' + n]:.0f})" for n in ALT_WEIGHTINGS) + " |")
    # ---- F. Investment quadrant (static, full window) ---------------------------
    portfolio_roi = portfolio["ROI %"]
    median_inv = perf.investment_cr.median()
    perf["quadrant"] = (np.where(perf.investment_cr >= median_inv, "High Investment", "Low Investment") + " / "
                        + np.where(perf.roi_pct / 100 >= portfolio_roi, "High ROI", "Low ROI"))
    perf[["project_id", "project_code", "investment_cr", "roi_pct", "quadrant"]].to_csv(
        ROOT / "data/processed/project_quadrants.csv", index=False)
    L += ["", "## F. Investment Quadrant (calculated column, full window)", "",
          f"Thresholds: median operational project investment = ₹ {median_inv:,.2f} Cr; "
          f"portfolio ROI = {100 * portfolio_roi:.2f} %", "",
          "| Quadrant | Projects | Capex ₹ Cr | Median ROI % | Projects |", "|---|---|---|---|---|"]
    for q, g in perf.groupby("quadrant"):
        L.append(f"| {q} | {len(g)} | {g.investment_cr.sum():,.0f} | {g.roi_pct.median():.2f} | "
                 + ", ".join(g.sort_values("roi_pct", ascending=False).project_code) + " |")

    (ROOT / "powerbi" / "05_dax_expected_values.md").write_text("\n".join(L) + "\n")

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    print("\n".join(L))


if __name__ == "__main__":
    main()
