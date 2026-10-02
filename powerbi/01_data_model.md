# 01 — Power BI Data Model

## 1. The model at a glance

```
                               ┌──────────────────────────┐
                               │ Date  (daily, FY Apr-Mar)│
                               │ PK: Date                 │
                               └────────────┬─────────────┘
                     1 ──────────────┬──────┴──────┬──────────────┬────────── 1
                     │               │             │              │
                     * month_start   * month_start * month_start  * month_start
              ┌──────┴─────┐  ┌──────┴─────┐ ┌─────┴────────┐ ┌───┴─────────────┐
              │  Energy    │  │ Financials │ │Sustainability│ │Month Diagnostics│
              │ proj×month │  │ proj×month │ │ proj×month   │ │ proj×month      │
              └──────┬─────┘  └──────┬─────┘ └─────┬────────┘ └───┬─────────────┘
                     * project_id    *             *              *
                     │               │             │              │
                     1 ──────────────┴──────┬──────┴──────────────┴────────── 1
                               ┌────────────┴─────────────┐
                               │ Project (flattened)      │
                               │ PK: project_id           │
                               │ region›state›city›project│
                               │ + diagnostics, ABC, bench│
                               └──────────────────────────┘

 Disconnected (no relationships): Top N, W ROI, W Margin, W CF, W Resource,
 W PR Trend, W CO2, W Availability (what-if parameters), Region Scores,
 DQ Summary, _Measures (measure container)
```

**2 dimensions, 4 fact tables, 8 relationships, all one-to-many and single-direction.**

## 2. Tables

| Table | Type | Grain | Rows | Source |
|---|---|---|---|---|
| Date | Dimension | Day | 1,461 | Built in Power Query (mirrors MySQL `dim_date`) |
| Project | Dimension | Project | 60 | `vw_dim_project` + `ana_project_diagnostics` + `ana_project_segments` + `ref_capex_benchmark` |
| Energy | Fact | Project × month | 1,820 | `fact_energy_generation` |
| Financials | Fact | Project × month | 1,820 | `fact_financials` |
| Sustainability | Fact | Project × month | 1,820 | `fact_sustainability` |
| Month Diagnostics | Fact | Project × month | 1,820 | `ana_month_diagnostics` |

## 3. Relationships

| From (many) | To (one) | Cardinality | Cross-filter | Active |
|---|---|---|---|---|
| Energy[project_id] | Project[project_id] | Many-to-one | Single (Project → Energy) | Yes |
| Financials[project_id] | Project[project_id] | Many-to-one | Single | Yes |
| Sustainability[project_id] | Project[project_id] | Many-to-one | Single | Yes |
| Month Diagnostics[project_id] | Project[project_id] | Many-to-one | Single | Yes |
| Energy[month_start_date] | Date[Date] | Many-to-one | Single (Date → Energy) | Yes |
| Financials[month_start_date] | Date[Date] | Many-to-one | Single | Yes |
| Sustainability[month_start_date] | Date[Date] | Many-to-one | Single | Yes |
| Month Diagnostics[month_start_date] | Date[Date] | Many-to-one | Single | Yes |

Monthly facts are keyed on the **first day of the month**, and Date is daily. A month slicer selects the whole month, so the key matches day 1. Time-intelligence functions need a continuous daily calendar, and they get one.

## 4. Design decisions

| Decision | Alternatives | Choice and reason |
|---|---|---|
| **Flatten location into Project** | Keep the MySQL snowflake (Project → Location) | **Flatten.** Each extra hop is another relationship to traverse. A 60-row dimension costs nothing to denormalise, and region › state › city › project becomes one clean hierarchy in one table |
| **Four separate fact tables** | One wide fact (energy + money + CO₂) | **Separate.** They come from different source systems (SCADA, ERP, derived) with different refresh and quality paths. Because they share conformed dimensions, cross-fact measures (₹ per MWh) still work. A merged fact would hide lineage |
| **Merge 1:1 Stage-3 attributes into Project** | Load them as separate tables with 1:1 relationships | **Merge in Power Query.** 1:1 relationships add a table to every filter path and default to bidirectional filtering, for no benefit |
| **Single-direction filters only** | Bidirectional so facts filter dimensions | **Single.** Bidirectional filters between two facts and shared dimensions create ambiguous paths and silent wrong totals. Where a "projects with data" filter is needed, the DAX does it explicitly (`SUMMARIZE(Energy, …)`) |
| **No many-to-many** | Fact-to-fact on (project, month) | Never relate facts to each other. Filters flow from dimensions to facts only |
| **Investment lives on Project** | Repeat it on monthly rows | Repeating it makes SUM 36× too big. `Capital Employed` uses `SUMX(Financials, RELATED(investment)) / 12`, which is deliberately time-weighted |
| **Date built in M** | Import MySQL `dim_date`, or DAX `CALENDAR()` | **M.** The range is derived from the facts and padded to fiscal years, so it is refresh-safe. `dim_date` stays the SQL-side source of truth; the fiscal logic is identical |
| **What-if parameters disconnected** | — | They only feed `SELECTEDVALUE` in score measures. A relationship would filter the facts |
| **Measures in `_Measures`** | Measures on fact tables | One home and display folders: `1 Energy`, `2 Time Intelligence`, `3 Financial`, `4 Sustainability`, `5 Ranking`, `6 Diagnostics`, `7 Scores`, `8 Narrative & Formatting` |

## 5. Model hygiene checklist

- [ ] Date marked as date table (column `Date`).
- [ ] Sort `MonthName` by `FiscalMonthNo` and `YearMonth` by `YearMonthSort`, so April comes first.
- [ ] Hide all foreign keys (`project_id`, `month_start_date`) and raw INR columns on facts; users see measures only.
- [ ] Hierarchy on Project: `region › state › city › Project Label`.
- [ ] Data categories set: latitude, longitude, city, state, country.
- [ ] Summarisation set to "Don't summarize" on `capacity_mw`, `investment_amount_inr`, `ppa_tariff_inr_per_kwh`, `latitude`, `longitude`, so a drag-and-drop cannot create a wrong implicit SUM.
- [ ] Turn off Auto date/time (File › Options › Data load). It creates a hidden date table per date column.
- [ ] Calculated column `Investment Quadrant` on Project (DAX in `dax/measures.dax`, bottom of the file).
- [ ] Validation query shows all PASS after refresh.
