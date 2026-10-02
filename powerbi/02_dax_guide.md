# 02 — DAX Guide: what each important measure does, and why it is written that way

The full library is in [`dax/measures.dax`](../dax/measures.dax): 100 measures in 8 display folders. The expected value of every measure is in [`05_dax_expected_values.md`](05_dax_expected_values.md).

## 1. Five rules the library follows

1. **Ratio of sums, never average of ratios.** `Capacity Factor = DIVIDE([Total Energy], [Theoretical Max Energy])`. `AVERAGE(Energy[capacity_factor])` would weight a 0.5 MW rooftop like a 300 MW park. Here the correct value is 18.13 %; the simple mean of the monthly CF column is 17.17 %, because hundreds of small rooftop rows pull it down.
2. **`DIVIDE`, never `/`.** It returns BLANK instead of an error, so visuals stay clean when a filter leaves no rows.
3. **Blank, not zero, when a comparison is undefined.** `Energy YoY %` returns BLANK when there is no prior-year data. Returning −100 % or +∞ would be wrong.
4. **Variables (`VAR`)** for anything used twice. Each is evaluated once, and the measure reads like a formula.
5. **Explicit filter logic instead of bidirectional relationships.** Where a measure needs "periods that have data", it uses `SUMMARIZE(Energy, …)` rather than turning on two-way filtering.

## 2. Energy

| Measure | Logic | Why |
|---|---|---|
| `MW-Months` | `SUMX(Energy, RELATED(Project[capacity_mw]))` | Each Energy row is one project-month, so summing capacity over rows gives capacity × months. It is the denominator for every "per MW per year" metric |
| `Capacity Factor` | Energy ÷ Σ(MW × hours in month) | Capacity-weighted, and correct for 28- vs 31-day months |
| `Performance Ratio` | `FILTER(Energy, NOT ISBLANK(irradiation))` on both numerator and denominator | Months without a weather reading are dropped from **both** sides. Dropping them from one side only would inflate PR |
| `Availability` | 1 − downtime ÷ daylight hours (hours/2) | Isolates operations from weather. Guarded with `COUNTROWS(…) > 0` so an empty context returns BLANK, not 100 % |
| `Operating Capacity (MW)` | `CALCULATE(SUM(capacity), status = "Operational", installation_date <= MAX('Date'[Date]))` | Project has no relationship to Date (capacity is not a monthly fact), so the measure reads the selected date explicitly. Picking FY2023-24 shows the capacity that existed then |

## 3. Time intelligence (Indian fiscal year)

| Measure | Key point |
|---|---|
| `Energy FYTD (MWh)` | `TOTALYTD(…, 'Date'[Date], "3/31")`. The third argument moves the year end to 31 March. Without it, "YTD" resets in January, which is wrong for an Indian company |
| `Energy YoY %` | `SAMEPERIODLASTYEAR` needs a marked, continuous daily date table. Facts on the 1st of the month work because a month in the filter context includes day 1 |
| `Energy Rolling 3M / 12M` | The window ends at `EOMONTH(MAX(Energy[month_start_date]), 0)`, the **last month with data**. With `MAX('Date'[Date])` the grand total would end on 31-Mar-2027 (padded calendar) and show an empty future window |
| `LFL Energy YoY %` | Keeps only projects with data in **every** month of both periods (`COUNTROWS = MonthsInPeriod`). FY26 reported +7.11 % vs like-for-like −2.25 %: growth comes from new plants, and the existing fleet produced less |

**Interview line:** *"Reported growth is +7 %, but like-for-like it's −2 %. I wrote a measure that separates new capacity from performance, because a manager reading +7 % would draw the wrong conclusion."*

## 4. Financial

| Measure | Logic | Why |
|---|---|---|
| `Total Investment` | `SUM(Project[investment_amount_inr])` | Capex lives on the dimension, once per project. It does not move with the date slicer, by design |
| `Capital Employed` | `SUMX(Financials, RELATED(Project[investment]))/12` | Capital-years: each monthly row charges one month of that project's capex. A plant commissioned in Oct-24 carries only the months it actually operated |
| `ROI %` | `DIVIDE([EBIT], [Capital Employed])` | **Annualised, time-weighted, EBIT-basis.** The same definition as the SQL view and Python (5.83 %) |
| `Payback (Years)` | `DIVIDE([Capital Employed], [EBITDA])` | Capital-years ÷ EBITDA over the same months = capex ÷ annual EBITDA. One line, and correct under any date filter |
| `Realised Tariff (₹/kWh)` | Revenue ÷ (MWh × 1000) | Energy-weighted. An average of the tariff column would treat a 1 MW and a 300 MW contract equally |
| `Investment Efficiency %` | Revenue ÷ capital employed | Annual revenue per rupee of capital |

## 5. Sustainability

| Measure | Why it is written this way |
|---|---|
| `Equivalent Households` | `AVERAGEX(VALUES('Date'[MonthStart]), …)`. Households are a *stock*, not a *flow*: 3.2 M homes powered each month. Summing 36 months would claim 114 M homes |
| `Renewable Share (Captive) %` | Only rows where the share exists (C&I and rooftop), weighted by site consumption. A grid-export plant has no "share of demand" |
| `CO2 per ₹ Cr-Year (t)` | CO₂ ÷ capital-years in ₹ Cr: impact per rupee per year, comparable between old and new projects |

## 6. Ranking

| Measure | Key point |
|---|---|
| `Region Rank (ROI)` | `RANKX(ALLSELECTED(Project[region]), …, DENSE)`. `ALLSELECTED` ranks within the slicer selection, so picking 3 regions ranks them 1–3. `HASONEVALUE` returns BLANK on the total row instead of a meaningless "rank 1" |
| `Project Rank (ROI)` | Ranks over `FILTER(…, NOT ISBLANK([ROI %]))`, so the 4 pipeline projects (no ROI yet) do not take the last places |
| `Top / Bottom Project (ROI)` | `TOPN(1, …)` inside `CONCATENATEX`. If two projects tie, both are shown instead of one being picked at random |
| `Is In Top N (ROI)` | Used as a **visual-level filter = 1**, driven by a what-if parameter (5–20). Power BI's built-in Top N filter cannot be driven by a slicer |
| `Contribution %` | ÷ `CALCULATE(…, ALLSELECTED(Project))`: the share of what is currently selected |

## 7. Scores

The `Pctl …` measures share one pattern:

```dax
VAR Cur = [ROI %]
VAR Tbl = ADDCOLUMNS ( ALLSELECTED ( Project[region] ), "@v", [ROI %] )
VAR N   = COUNTROWS ( Tbl )
RETURN DIVIDE ( COUNTROWS ( FILTER ( Tbl, [@v] < Cur ) ), N - 1 )
```

- `ADDCOLUMNS` + context transition evaluates `[ROI %]` for each region while keeping the date and type filters, so the score responds to a fiscal-year slicer.
- `Investment Priority Score` combines 7 percentiles with **what-if slider weights**, renormalised by their sum. Users can explore their own priorities without breaking the 0–100 scale.
- The Python reference (`pctl_rank`) uses the same rule, and the default-weight values match `ana_region_scores`.

**Design choice: calculation groups vs repeated measures.** The 9 `Pctl` measures differ only in the base measure. A calculation group (Tabular Editor) would remove the repetition. Plain measures were kept because they work in Power BI Desktop with no external tool and can be read in an interview without explaining calculation groups. Calculation groups are listed as a future refactor.

## 8. Narrative and formatting

- `Headline Volume vs Return` builds the Page 1 sentence from the data. If a filter makes the energy leader also the ROI leader, the sentence changes to say so. A static text box would go stale.
- `ROI vs Portfolio Colour` returns a hex colour for conditional formatting (Format › Font colour › Field value). Above-portfolio ROI is blue and below is orange, the same two colours as the quadrant scatter.

## 9. Calculated column: `Investment Quadrant`

It is a column because a scatter legend needs a column; a measure cannot be a legend. It is **static** over the full window: a project's quadrant does not change when someone filters a month. The thresholds (median capex ₹152.4 Cr, portfolio ROI 5.83 %) are printed on the page. The trade-off is stated openly: a dynamic version would need a disconnected quadrant table plus a measure, which is more complex and less stable to read.
