# 01 — Project Design

**Solar Energy Data Analysis & Investment Intelligence Dashboard**
MySQL 8.0 · SQL · Python · Power BI · DAX · Power Query

> Stage 1 deliverable: architecture, business case and questions, dataset and table design, plus the roadmap.
> Every number in this document comes from the generated data (`data/ground_truth/expected_clean_totals.json`).

---

## 1. Business case

**Arka Renewables** is a fictional Indian independent power producer (IPP). It owns 60 solar projects across 6 regions: 56 are operating and 4 are under construction.
Over three fiscal years (FY2023-24 to FY2025-26) it has invested **₹12,263 Cr** in **2,927 MW** of capacity, and it now has to decide where the next round of capital goes.

The Investment Committee has asked five questions:

| # | Management question | What a good answer looks like |
|---|---|---|
| 1 | Which regions are performing well, and on which measure? | Regions ranked on return as well as volume, because the two rankings disagree |
| 2 | Which projects need investigation? | A shortlist of projects, each with its probable root cause (weather, availability, cost or capex) |
| 3 | Where should future capital be allocated? | A transparent, re-weightable **prioritisation framework**. It is not a financial recommendation |
| 4 | Which projects generate the highest returns, and why? | Return drivers split into tariff, capex/MW, capacity factor and cost |
| 5 | Which projects provide the greatest sustainability impact? | CO₂ avoided in total and per ₹ invested, with the method documented |

**Out of scope, stated so the project never over-claims:** debt, interest, tax, IRR/NPV modelling, merchant power prices and real asset data. ROI here is **unlevered, pre-tax, accounting ROI**.

---

## 2. Architecture

```
 SOURCE SYSTEMS (simulated)          python/generate_data.py
 ┌────────────┬────────────┬──────────────┬─────────────┬───────────────┐
 │Site register│Asset regist.│ SCADA        │ ERP/billing │ Client meters │
 └─────┬──────┴─────┬──────┴──────┬───────┴──────┬──────┴───────┬───────┘
       ▼            ▼             ▼              ▼              ▼
 data/raw/*.csv  ── raw exports, contain 67 deliberate defects ──
       │
       ▼  sql/03_load_raw.sql  (LOAD DATA LOCAL INFILE, '' → NULL)
 ┌──────────────────────────────────────────────────────────────────────┐
 │ MySQL: solar_analytics                                               │
 │  stg_*   all-VARCHAR landing tables (bad data must land to be seen)  │
 │    │  05 data-quality checks  →  dq_issue_log (audit trail)          │
 │    ▼  06 transform: standardise, dedupe, repair, reconstruct         │
 │  dim_date · dim_location · dim_project            (conformed dims)   │
 │  fact_energy_generation · fact_financials · fact_sustainability      │
 │  ref_emission_factor · ref_assumption             (assumptions)      │
 │    ▼  07 views (vw_*)        08 analytical queries                   │
 └──────────────────────────────────────────────────────────────────────┘
       │  Power BI Import mode (views/tables)
       ▼
 Power Query: light typing, Date table, validation queries (folding kept)
       ▼
 Star schema model → DAX measures (energy, financial, sustainability, ranking, time)
       ▼
 6-page dashboard → Insights (observation → evidence → interpretation → action)
       ▼
 Investment Priority Score (transparent, weight-adjustable framework)

 Python (side path): correlation, Pareto/ABC, anomaly detection, and
 validation that SQL, Python and DAX totals agree.
```

### Key architecture decisions

| Decision | Options considered | Choice and reason |
|---|---|---|
| Where cleaning happens | (a) Power Query only (b) SQL, with Power Query kept thin | **(b)**. Rules written in SQL are versioned, testable and reusable by any tool. Power Query keeps typing and the date table, which preserves query folding. In interviews, *"I pushed transformations upstream"* is the stronger answer |
| Staging design | Typed staging vs all-text staging | **All-text.** A typed staging table rejects `2024-02-30` at load time and the defect is never logged. Text staging lets every defect land, be counted and be fixed visibly |
| Layers | Separate databases per layer vs one database with prefixes | **One database with prefixes** (`stg_`, `dim_`, `fact_`, `ref_`, `dq_`, `vw_`). It is simpler to deploy, and the layering is still obvious |
| System of record for energy | SCADA vs billing meter | **The billing meter wins.** SCADA is an operational feed and can glitch. Revenue = metered MWh × fixed PPA tariff, so energy can be **reconstructed and reconciled** from billing. This is the central idea of the data-quality strategy |
| Power BI connection | Import vs DirectQuery | **Import.** About 2k rows per fact with monthly refresh, so DirectQuery's latency and DAX limits bring no benefit |
| Profit definition | Store it or compute it everywhere | **A stored generated column** in MySQL, so there is one definition that cannot drift between SQL and Power BI |

---

## 3. Business questions → dashboard pages

Each page answers one question. A chart that does not serve its page's question is cut.

| Page | Core business question | Primary KPIs |
|---|---|---|
| 1 Executive Overview | *Is the portfolio healthy, and where should I look?* | Energy, Investment, Revenue, EBIT, ROI %, CO₂ avoided |
| 2 Regional Performance | *Which regions perform best, on volume vs efficiency?* | Generation, CF, Revenue/MW, ROI by Region → State → City → Project |
| 3 Investment & ROI | *Which projects earn their capital, and why?* | ROI quadrant, capex/MW, tariff, EBITDA margin, payback |
| 4 Energy Performance | *Is underperformance caused by weather or by operations?* | CF vs irradiation, Performance-ratio proxy, downtime, availability |
| 5 Sustainability | *What is our environmental impact per unit of capital?* | CO₂ avoided, CO₂/MW, CO₂ per ₹ Cr, RE share (captive), Sustainability Score |
| 6 Investment Recommendation | *Where should the next rupee go, and with what risks?* | Investment Priority Score, risk flags, opportunity table |

The full question list from the brief is mapped below. Each one is answered on the page shown.

| Question | Page | How it is answered |
|---|---|---|
| Which regions/cities perform best? | 2 | Rank on ROI and CF, not only on MWh |
| Which regions generate the most energy? | 1, 2 | Total MWh with contribution % |
| Which regions have the highest investment efficiency? | 2, 3 | Revenue per ₹ invested, ROI % |
| Where should the company invest next? | 6 | Investment Priority Score (framework) |
| Which projects have poor ROI? | 3 | Bottom-N ROI and the quadrant |
| What factors affect generation? | 4, plus the Python correlation analysis | Irradiation, cloud, temperature (partial effect), downtime |
| How much CO₂ has been avoided? | 1, 5 | MWh × grid emission factor |
| Strongest solar potential? | 2, 4 | Solar zone, irradiation, CF |
| Which projects are underperforming? | 4 | Expected-vs-actual CF and anomaly flags |
| Investment → capacity → generation → revenue → ROI relationship | 3 | Value-chain decomposition |
| Major business risks | 6 | Concentration, curtailment, cost and capex risk flags |
| Management recommendations | 6, plus `reports/` | Insight → action table |

---

## 4. Dataset

### 4.1 Why synthetic, and why it is still defensible

No public dataset combines plant-level generation, capex, tariff and O&M cost for Indian solar assets, because that data is commercially confidential. The data is therefore **simulated from physics and published benchmark ranges**, so its relationships behave like the real world:

```
energy_MWh = capacity_MW × GHI_month × POA_gain × PR_ex_temp
             × (1 − temp_coeff × max(0, T_amb + ΔT_cell − 25))
             × (1 − degradation × age) × availability × ramp-up × (1 − hidden losses)
```

| Assumption | Value used | Note |
|---|---|---|
| Annual mean GHI | 4.3 (Guwahati) to 5.95 (Jaisalmer) kWh/m²/day | Approximate, by city |
| Seasonality | 5 monsoon profiles (SW, NE, Deccan, Kerala, North-East) | Monsoon dip from Jun to Sep, NE-monsoon dip from Oct to Dec in Tamil Nadu |
| Temperature loss | 0.38 % per °C above 25 °C cell temperature | Floating panels run about 7 °C cooler |
| Degradation | 0.6 % per year | |
| Capex | Utility ₹3.7–4.2 Cr/MW · C&I 4.1–4.7 · Rooftop 4.6–5.4 · Floating 5.6–6.3 | +12 % North-East, +5 % East (logistics) |
| PPA tariff | Utility ₹2.42–3.00/kWh (Rajasthan lowest) · C&I 3.7–4.75 · Rooftop 4.2–5.4 · Floating 3.25–3.6 | Fixed for the contract term |
| Costs | Fixed opex and preventive O&M per MW, plus corrective cost tied to downtime, plus 5 % inflation per year | |
| Depreciation | Straight-line over 25 years, no salvage | |
| Grid emission factor | 0.716 tCO₂/MWh | Approximation of the CEA grid average; stored in `ref_emission_factor` |
| Household consumption | 0.1 MWh/month | Illustrative; stored in `ref_assumption` |

**Resulting benchmarks (sanity check).** The mean monthly capacity factor is 14.7 % for rooftop and 18.6 % for utility-scale. EBITDA yield on capex is about 9–12 % for utility-scale, C&I and rooftop. Floating is lower (≈5.5 %) because of its high capex. These figures sit within published ranges for Indian solar.

### 4.2 Volumes

| Item | Count |
|---|---|
| Regions / states / cities | 6 / 18 / 28 |
| Projects | 60 (56 operational, 4 under construction; 11 commissioned during the window) |
| Window | Apr-2023 to Mar-2026 (36 months, 3 Indian fiscal years) |
| fact_energy_generation | 1,820 clean rows (1,835 raw) |
| fact_financials | 1,820 clean rows (1,826 raw) |
| Offtaker consumption | 976 rows (captive projects only) |

### 4.3 Planted business scenarios

Seven projects carry realistic problems. Each one leaves a **signature** in the data, and the analysis has to find them **without being told** where they are. The ground truth sits in `data/ground_truth/`, which the pipeline never reads; only the tests read it, to confirm the detection methods work.

| Scenario | Signature an analyst should be able to see |
|---|---|
| Panel soiling (cleaning contract lapsed) | CF declines for months while irradiation and downtime look normal and maintenance cost *falls* |
| Grid curtailment (2 projects) | CF is low *relative to irradiation* with no logged downtime, and appears in the same region at the same time |
| Chronic inverter failures | Very high downtime hours with matching corrective-maintenance cost |
| Hailstorm | A one-off downtime and cost spike that is legitimate, so it must **not** be "cleaned away" |
| O&M contract overrun | Maintenance cost per MW is far above peers with normal downtime |
| Capex overrun | Generation is normal but capex/MW is very high, so ROI is low |
| *Structural pattern, not a defect* | Utility-scale plants dominate volume, while C&I at higher tariffs dominates return |

### 4.4 Deliberate data-quality defects (raw layer only)

| Defect | Rows | Intended handling (Stage 2) |
|---|---|---|
| Exact duplicate rows (energy 12, financials 6, locations 1) | 19 | Remove, then enforce with a composite primary key |
| Stale duplicate project with an older `record_updated_at` | 1 | Keep the latest record (`ROW_NUMBER()`) |
| Negative energy (sign error) | 6 | ABS(), **verified against billing** |
| Capacity factor stored as a percentage (18.5 instead of 0.185) | 5 | Recompute CF from energy, capacity and hours |
| Meter spike ×10 (CF > 0.35 is physically implausible) | 4 | Rebuild energy from billing |
| NULL energy | 4 | Rebuild from billing (`data_source = BILLING_RECONSTRUCTED`) |
| Invalid date string (`2024-02-30`) | 3 | Quarantine the SCADA row, rebuild the month from billing |
| Date in DD-MM-YYYY format | 8 | Parse with the alternate format after strict validation |
| Orphan project code (`P999`) | 3 | Quarantine (referential integrity) |
| Weather sensor NULL | 2 | Keep NULL, exclude from correlation (never invent weather) |
| Inconsistent city/state/type/code text | 5 | Standardise (TRIM, case mapping, alias table) |
| Negative investment (sign error) | 1 | ABS() after a capex/MW plausibility check |
| Test record in the production export (`P_TEST`) | 1 | Remove |
| NULL maintenance cost | 3 | Impute the project median and flag `maintenance_imputed = 1` |
| Negative operating cost (sign error) | 2 | ABS(), logged |

**Acceptance test for Stage 2:** after cleaning, total energy, revenue and costs must equal `expected_clean_totals.json` exactly. Every defect has a provably correct fix or a documented quarantine.

**A MySQL trap found in Stage 1.** `STR_TO_DATE('2024-02-30', '%Y-%m-%d')` *succeeds* and returns an invalid date. `STR_TO_DATE('01-10-2024', '%Y-%m-%d')` parses silently as **2001-10-20**. A naive `IS NULL` check finds 0 bad dates, when there are actually 11. Stage 2 therefore validates with a strict regex plus a round-trip check: `DATE_FORMAT(STR_TO_DATE(x, fmt), fmt) = x`.

---

## 5. MySQL table design

### 5.1 Star schema

```
                      dim_date (daily, Indian FY attributes)
                         │ 1
                         │
                         │ *  (month_start_date)
 dim_location 1 ─── * dim_project 1 ─┬─ * fact_energy_generation   grain: project × month
   (region › state                   ├─ * fact_financials          grain: project × month
    › city, zone)                    └─ * fact_sustainability      grain: project × month
```

`dim_location → dim_project` is a snowflake in MySQL, which is normal for a normalised source. In Power BI it is **flattened** into a single `Project` dimension (Stage 4), so the published model is a pure star.

### 5.2 Tables

| Table | Grain / role | Keys | Important constraints |
|---|---|---|---|
| `dim_date` | One row per day, 2023-04-01 to 2027-03-31 | PK `calendar_date`, UQ `date_key` | Fiscal year, quarter and month built with a recursive CTE |
| `dim_location` | One row per city | PK `location_id` (surrogate), UQ `location_code`, UQ (`state`, `city`) | Lat/long range, GHI range, region in an allowed list |
| `dim_project` | One row per project | PK `project_id`, UQ `project_code`, FK → `dim_location` | capacity > 0, investment > 0, tariff 1–15, type and status in allowed lists |
| `fact_energy_generation` | Project × month | PK (`project_id`, `month_start_date`), FKs → project and date | energy ≥ 0, 0 ≤ CF ≤ 1, cloud 0–100, downtime 0–744 h, `data_source` lineage |
| `fact_financials` | Project × month | Same composite PK | All amounts ≥ 0; `ebitda_inr` and `profit_inr` are **generated columns** |
| `fact_sustainability` | Project × month | Same composite PK | Derived in SQL; stores the emission factor used (lineage) |
| `ref_emission_factor` | One row per fiscal year | PK `fiscal_year_end` | 0–2 tCO₂/MWh |
| `ref_assumption` | Named assumptions | PK `assumption_key` | — |
| `dq_issue_log` | One row per detected defect | PK `issue_id` | `action_taken` from a controlled list |

### 5.3 Deviations from the brief, and why

| Brief | Implemented | Reason |
|---|---|---|
| `investment_amount` in `fact_financials` | Kept **only in `dim_project`** | Capex is a one-off. Repeated on monthly rows, `SUM` overstates it 36×. This is the classic semi-additive trap |
| `profit` column | `ebitda_inr` and `profit_inr` (EBIT) as generated columns | A single, explicit definition. EBITDA shows operating performance; EBIT accounts for the capital consumed |
| `renewable_energy_percentage` for every project | Only for **captive** (C&I and Rooftop) projects: solar used on site ÷ site consumption | A grid-export plant has no site demand, so a percentage there would be invented |
| `equivalent_households` as a fact | Stored per month, documented as **non-additive** | Adding households across 12 months counts the same homes 12 times. DAX averages over months |
| `project_id` as text | Integer surrogate key plus `project_code` natural key | Faster joins, stable if codes change, and traceable to the source |
| ENUM types | `VARCHAR` + `CHECK` | CHECK constraints (enforced since MySQL 8.0.16) are more portable than ENUM, and easier to change |
| Investment ROI over a period | **Time-weighted:** `Σ EBIT × 12 / Σ(capex × operating months)` | Projects commissioned mid-window were not using capital all year. Plain `Σprofit/Σcapex` penalises new projects unfairly |

---

## 6. Implementation roadmap

| Stage | Scope (brief sections) | Output | Status |
|---|---|---|---|
| **1** | Architecture, business case, dataset, schema (1–4 design) | `python/generate_data.py`, `data/raw/`, `sql/01–04`, this document | ✅ Done, executed on MySQL 8.0.33 |
| **2** | Data quality and SQL (4, 5) | `sql/05–08`, `dq_issue_log`, `python/validate_pipeline.py`, [02_sql_and_data_quality.md](02_sql_and_data_quality.md) | ✅ Done, 41/41 checks pass |
| **3** | Advanced analytics in Python (10) | `python/advanced_analytics.py`, `ana_*` tables, `reports/figures/`, [03_advanced_analytics.md](03_advanced_analytics.md) | ✅ Done, 7/7 planted root causes identified |
| **4** | Power BI (6–9) | `powerquery/queries.m`, `dax/measures.dax`, `powerbi/01–05`, `powerbi/mockups/` (6 page mockups) | ✅ Done (spec, DAX and mockups; `.pbix` to be built on Windows) |
| **5** | Story and portfolio (11–17) | `README.md`, `documentation/04–07`, `run_pipeline.sh` | ✅ Done |

**Platform note.** Power BI Desktop is Windows-only. Stage 4 produces everything up to the `.pbix` (M, DAX, model and layout specification, plus expected values for every measure). The report itself is assembled on a Windows machine and checked against those expected values.
