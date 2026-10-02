# 02 — SQL Implementation & Data Quality

> Stage 2 deliverable. Every number here comes from running `sql/run_all.sh` on MySQL 8.0.33 and then `python/validate_pipeline.py` (**41/41 checks pass**).

## 1. Scripts

| Script | Purpose | Key techniques |
|---|---|---|
| `01_create_database.sql` | Database and layer conventions | utf8mb4, re-runnable |
| `02_staging_tables.sql` | All-text landing tables | Permissive by design |
| `03_load_raw.sql` | Bulk load CSV → staging | `LOAD DATA LOCAL INFILE`, `NULLIF(@x,'')`, load reconciliation |
| `04_core_schema.sql` | Star schema and reference data | PK/FK/UNIQUE/CHECK, composite grain keys, generated columns, recursive-CTE calendar |
| `05_data_quality_checks.sql` | Detect and log every defect | Stored functions, `ROW_NUMBER` dedupe, regex validation, median via window functions, `dq_issue_log` |
| `06_transform_load.sql` | Apply rules, load star schema, validate | Billing-meter reconstruction, anti-joins, post-load assertions, control totals |
| `07_views.sql` | One definition per KPI | Ratio of sums, time-weighted ROI, `LAG`, rolling windows, `WINDOW` clause |
| `08_analysis_queries.sql` | 19 business questions | `RANK`/`DENSE_RANK`/`NTILE`/`PERCENT_RANK`, `WITH ROLLUP` + `GROUPING()`, peer z-scores, like-for-like growth, Pareto |
| `run_all.sh` | Rebuild from scratch | — |
| `python/validate_pipeline.py` | Acceptance tests | Reconciles to `data/ground_truth/` |

Rebuild and verify:

```bash
MYSQL="mysql -uroot" sql/run_all.sh        # or point MYSQL at any MySQL 8 client
python python/validate_pipeline.py         # env vars MYSQL_HOST/PORT/USER/PASSWORD
```

## 2. Data-quality strategy

### 2.1 Principles

1. **Detect, log, then fix. Never fix silently.** Every defect produces a row in `dq_issue_log` with an action: `FIXED`, `REMOVED_DUPLICATE`, `QUARANTINED`, `IMPUTED`, `RECONSTRUCTED` or `FLAGGED_ONLY`.
2. **Staging is never edited.** Raw evidence for each fix stays queryable in `stg_*`.
3. **Fix only when the correct value can be proven.** A sign error in energy is fixed because the **billing meter confirms** the absolute value. A negative capex is fixed because **two independent checks** agree: capex/MW is plausible, and ERP depreciation = |capex| / 300.
4. **Errors and outliers are different things.** A ×10 meter spike is an error, so it is repaired. A hailstorm month with 290 downtime hours is a real event, so it is flagged and **kept**. Deleting it would hide the most important operational story in the data.
5. **Never invent observations.** Weather fields for reconstructed months stay NULL and are excluded from correlation analysis.

### 2.2 The billing meter as the system of record

Revenue = metered MWh × fixed PPA tariff. That gives every SCADA reading an independent cross-check:

```sql
billing_energy_mwh = revenue_inr / (ppa_tariff_inr_per_kwh * 1000)
```

- SCADA is accepted if it is within 2 % of billing (the tolerance allows for metering and auxiliary-consumption differences).
- If SCADA is NULL, implausible or mismatched, the billing value is used and the row is tagged `data_source = 'BILLING_RECONSTRUCTED'`.
- If a month was billed but its SCADA row was quarantined (invalid date), energy is rebuilt from billing.

As a result, **0.60 % of energy months (11 of 1,820) rest on reconstructed data**, and Q19 reports that number explicitly.

### 2.3 Every check, and what happened

| Check | Table | Found | Action | Rule |
|---|---|---|---|---|
| Exact duplicate rows | energy / financials / locations | 12 / 6 / 1 | REMOVED_DUPLICATE | `ROW_NUMBER() OVER (PARTITION BY all columns)`; the composite PK prevents recurrence |
| Stale project version | projects | 1 | REMOVED_DUPLICATE | Keep the latest `record_updated_at` |
| Test record in production (`P_TEST`) | projects | 1 | QUARANTINED | Code must match `^P[0-9]{3}$` |
| Non-standard text (`  jodhpur `, `BENGALURU`, `Tamilnadu`, `l-19`, ` utility-scale`) | locations / projects | 5 | FIXED | TRIM, `fn_proper_case`, `ref_text_alias` lookup, regex re-format |
| Negative investment | projects | 1 | FIXED | ABS() only after a plausibility check and a depreciation cross-check |
| Orphan project codes | energy | 3 | QUARANTINED | LEFT JOIN anti-join to the clean project master |
| Calendar-impossible dates | energy | 3 | QUARANTINED → month RECONSTRUCTED | Strict parser (see 2.4) |
| DD-MM-YYYY dates | energy | 8 | FIXED | Second format accepted only after a strict round trip |
| Negative energy | energy | 6 | FIXED | ABS(), confirmed against billing |
| Meter spike (implied CF > 35 %) | energy | 4 | RECONSTRUCTED | Physical plausibility limit, stored in `ref_assumption` |
| NULL energy | energy | 4 | RECONSTRUCTED | From billing |
| CF stored as percent | energy | 5 | FIXED | CF is **always recomputed** from energy, so this defect class cannot recur |
| Missing weather | energy | 2 | FLAGGED_ONLY | Never imputed |
| NULL maintenance cost | financials | 3 | IMPUTED | Project **median** (robust to the hail-repair month), `maintenance_imputed = 1` |
| Negative operating cost | financials | 2 | FIXED | ABS(), logged |
| Downtime > 100 h | energy | 22 | FLAGGED_ONLY | Real events, investigated in the analysis |
| Maintenance > 3× project median | financials | 5 | FLAGGED_ONLY | Real events (hail repair, inverter failures) |
| Checked, nothing found | — | 0 | — | Generation before COD, non-month-start dates, status/date conflict, negative revenue, missing coordinates, consumption orphans |

**Reconciliation to ground truth.** Energy, revenue, operating cost, depreciation, investment and capacity match **exactly**. Maintenance differs by **+0.002 %**, which is the 3 imputed months. The true values cannot be recovered, so this residual is expected and documented.

### 2.4 MySQL traps found and handled

| Trap | Evidence | Handling |
|---|---|---|
| `STR_TO_DATE('2024-02-30','%Y-%m-%d')` returns an invalid date instead of NULL | A naive `IS NULL` check found **0** bad dates; there are 11 | `fn_parse_date_strict`: regex plus a round trip through `+ INTERVAL 0 DAY` |
| `STR_TO_DATE('01-10-2024','%Y-%m-%d')` → **2001-10-20** | Silent mis-parse into the wrong century | Format is decided by regex *before* parsing |
| `date + INTERVAL 0 DAY` rolls `2024-02-30` into `2024-03-01` | Converts bad data into plausible-looking data | Used deliberately as the *detector* (the round trip fails) |
| Case-insensitive collation: `'BENGALURU' = 'Bengaluru'` is TRUE | Text-standardisation fixes would not be logged | Compare with `CAST(x AS BINARY)` |
| CHECK constraints cannot use `CURRENT_DATE` | The status-vs-date rule cannot be a constraint | Enforced as a DQ check against the snapshot date |
| No `MEDIAN()` in MySQL | — | `ROW_NUMBER()` + `COUNT() OVER`, average of the middle rows |

### 2.5 The same rules in Power Query

The rules are implemented in SQL, which is the recommended approach: they are versioned, testable and reusable outside Power BI. Section 5 of the brief asks how Power Query would handle the same issues. Equivalents for the main ones are below; the full M script follows in Stage 4.

| Issue | Power Query (M) |
|---|---|
| Whitespace and case | `Table.TransformColumns(t, {{"city", each Text.Proper(Text.Trim(_)), type text}})` |
| Alias mapping | Merge with an alias table (left outer), then `each if [standard] = null then [raw] else [standard]` |
| Exact duplicates | `Table.Distinct(t)` |
| Latest version per key | `Table.Group(t, {"project_code"}, {{"latest", each Table.Max(_, "record_updated_at")}})` |
| Strict date parse | `try Date.FromText([reading_month], [Format="yyyy-MM-dd"]) otherwise try Date.FromText([reading_month], [Format="dd-MM-yyyy"]) otherwise null`. Unlike MySQL, `Date.FromText` *rejects* 2024-02-30 |
| Sign errors | `Table.TransformColumns(t, {{"operating_cost_inr", Number.Abs, type number}})` |
| Orphans | `Table.NestedJoin(... JoinKind.LeftAnti)` to list them; `JoinKind.Inner` to drop them |
| Errors from type conversion | `Table.RemoveRowsWithErrors`, or better, `Table.SelectRowsWithErrors` into a separate audit query |
| Query folding | Cleaning in Power Query on a MySQL source breaks folding at the first non-foldable step (`Text.Proper`, `try … otherwise`). This is the strongest argument for doing it in SQL and keeping Power Query thin |

## 3. KPI definitions (implemented in `07_views.sql`)

| KPI | Definition | Why this way |
|---|---|---|
| Capacity factor (CUF) | Σ MWh / Σ(MW × hours in month) | Capacity-weighted. `AVG(cf)` would weight a 0.5 MW rooftop like a 300 MW park |
| Performance ratio (GHI) | Σ MWh / Σ(MW × irradiation kWh/m²) | IEC 61724-style, **weather-normalised**, so operations are separated from climate |
| Availability | 1 − Σ downtime / Σ daylight hours (12 h/day) | Reliability without the effect of weather |
| EBITDA | Revenue − operating cost − maintenance | Generated column |
| EBIT (profit) | EBITDA − depreciation | Generated column |
| **ROI % (annualised)** | Σ EBIT / (Σ capex over operating months / 12) | **Time-weighted.** Capital is charged only for months in operation |
| EBITDA yield % | Σ EBITDA / capital-years | Cash-return view |
| Simple payback | Capex / annualised EBITDA | Easy for management to grasp; it ignores the time value of money |
| Realised tariff | Σ revenue / Σ kWh | Energy-weighted, not an average of tariffs |
| CO₂ avoided | MWh × grid emission factor (by FY, `ref_emission_factor`) | Assumption stored as data |
| Equivalent households | MWh / 0.1 per month, **averaged** across months | Non-additive over time |
| Renewable share (captive) | Σ min(solar, demand) / Σ demand | Only meaningful where a site demand exists |

## 4. What the SQL analysis shows (observations only)

These are **observed facts** from `08_analysis_queries.sql`. Interpretation, insight writing and recommendations come in Stage 5, once the Python analysis (Stage 3) has tested them.

| # | Observation | Query |
|---|---|---|
| 1 | The fleet delivered 11.45 TWh, ₹3,395 Cr revenue and ₹1,747 Cr EBIT, a **5.83 % annualised ROI**, with 8.2 Mt CO₂ avoided | Q01 |
| 2 | **North ranks #1 on energy (39 % share) and #5 on ROI (5.22 %).** West ranks #3 on energy and #1 on ROI (7.66 %). Realised tariff: North ₹2.66/kWh vs West ₹3.25 | Q03 |
| 3 | C&I Open Access earns 8.29 % ROI against 5.42 % for utility-scale, although its CF is lower (17.3 % vs 18.4 %), because its tariff is 53 % higher (₹4.11 vs ₹2.68) | Q06 |
| 4 | Floating earns 1.46 % ROI on capex of ₹7.2 Cr/MW. Only 2 floating projects exist, so this is not a technology verdict | Q06, Q14 |
| 5 | The top 9 projects by ROI are all C&I Open Access | Q13 |
| 6 | Portfolio ROI fell from 6.21 % to 5.79 % to 5.54 % across FY24 to FY26, while EBITDA margin fell from 87.7 % to 85.7 % | Q07 |
| 7 | **Reported energy growth in FY26 is +7.1 %, but like-for-like is −2.3 %** (48 projects running all of both years). Growth comes from new capacity; the existing fleet produced less | Q11 |
| 8 | 5 projects lost more than 10 % of their weather-normalised PR between FY24 and FY26. Three of them (P001, P004, P006) show **normal downtime**, a pattern consistent with soiling or curtailment rather than breakdowns | Q15 |
| 9 | P055 (Patna rooftop) has 82 % availability and O&M 3.3σ above peers | Q14 |
| 10 | P047 (Raipur C&I) has normal PR and availability but O&M 3.8σ above peers: a cost problem, not a performance problem | Q14 |
| 11 | P039 (Kochi floating) has capex 130 % of benchmark and a 21.5-year simple payback | Q08, Q14 |
| 12 | The North-East has the lowest ROI (4.47 %), the lowest CF (14.8 %) and the lowest CO₂ per ₹ Cr (194 t per ₹ Cr-year) | Q03, Q10 |
| 13 | Revenue is **not** concentrated: 25 of 56 projects (45 %) make up 80 % of revenue, so no classic 80/20 | Q17 |
| 14 | The monsoon quarter (Jul–Sep) lowers CF by about 5 points in the North and West, but only by 2.5 points in the South | Q18 |

**Detection quality of the root-cause rules (Q14 and Q15) against the planted ground truth:** all 7 planted problems were found (recall 7/7), each with the correct root-cause category. Three non-planted projects were also flagged (precision 7/10). Two are borderline PR z-scores (−1.5 to −1.7), and one is a genuine North-East capex premium.
