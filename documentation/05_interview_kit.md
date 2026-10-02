# 05 — Interview Kit

> Say this before anyone asks: **"The data is synthetic. I generated it with a physics-based model and planted known problems, so I could prove my pipeline finds them."** Interviewers respect this; they penalise discovering it themselves.

## 1. The pitch

### 30 seconds
> "I built a decision-support analytics system for a fictional Indian solar company with 60 projects and ₹12,000 crore invested. MySQL cleans and validates the data, Python models expected generation, and a six-page Power BI design answers where the next rupee should go. The headline: the biggest region by output ranks fifth on return, and the '+7 % growth' in the board pack is actually −2 % on a like-for-like basis."

### 1 minute
> "The business question was capital allocation: a renewable IPP had to decide where to invest next while its ROI was falling.
> I generated three years of monthly data from a physics model (irradiation, temperature, degradation, downtime), deliberately injected 67 data-quality defects, and planted seven operational problems.
> In MySQL I built a staging-to-star-schema pipeline. It detects every defect, logs it, and rebuilds broken SCADA readings from the billing meter. It reconciles to the source exactly, and 41 automated checks pass.
> In Python I built a weather-normalised expected-generation model (R² 0.94) that identified the root cause of all seven planted problems, from curtailment and soiling to inverter failures.
> Then I designed a Power BI model with 100 DAX measures and an Investment Priority Score with adjustable weights.
> The key insights were that return is driven by tariff, not sunshine, and that half the operating capital sits in below-average-return projects."

### 3 minutes: problem → approach → findings → impact
1. **Problem (20 s):** Falling ROI, a "growing" generation figure nobody could reconcile, and a capital decision pending.
2. **Data (30 s):** Synthetic but physics-based. 28 cities, 6 regions, 1,820 project-months per fact table. 67 injected defects and 7 planted scenarios, with ground truth kept separate so I could measure my own pipeline.
3. **SQL (40 s):** All-text staging, so bad rows land and can be logged. A strict date parser, because MySQL's `STR_TO_DATE` silently accepts 30 February. The billing meter as the system of record. Composite primary keys to enforce grain. Profit as a generated column. Time-weighted ROI.
4. **Analytics (40 s):** The temperature paradox: raw correlation +0.21, partial −0.24. The expected-generation model splits each loss into downtime and unexplained. Two plants dropped in the same month with no downtime, which is the signature of curtailment.
5. **Power BI (30 s):** A star schema, single-direction filters, like-for-like growth in DAX, and a percentile-based priority score with what-if weights and a sensitivity table.
6. **Results (20 s):** Seven of seven root causes found, ₹65.9 Cr of avoidable loss quantified (in the simulation), and a recommendation that West/South C&I gets the next tranche, robust to the weighting.

### 5 minutes
The 3-minute version, plus:
- **One trade-off:** cleaning in SQL vs Power Query, and why SQL won (versioned, testable, preserves folding).
- **One mistake:** my first root-cause rules labelled curtailment as soiling. I fixed the rule order and disclosed that the fix came after evaluation (over-fitting risk).
- **One limitation:** a single national emission factor, so the CO₂ ranking mirrors the energy ranking.
- **What I'd do next:** real data from public plant-level sources, state emission factors, IRR/NPV with debt, and a built `.pbix` with CI-validated DAX.

## 2. Project story by topic

| Topic | What to say |
|---|---|
| **Problem statement** | Capital allocation under falling ROI. Which regions and projects earn their capital, which are underperforming and why, and where should the next tranche go? |
| **Dataset** | 60 projects (56 operating), 28 cities, 18 states, 6 regions, Apr-23 to Mar-26. Energy, financial and sustainability facts at project × month. Physics-based generation; INR, Indian fiscal year |
| **Architecture** | CSV → MySQL staging (text) → DQ checks + audit log → star schema → views → Python (model, write-back) → Power BI (thin Power Query, DAX) → insights → priority framework |
| **SQL** | Strict validation functions, `ROW_NUMBER` dedupe, billing reconstruction, window-function analytics (RANK, NTILE, LAG, rolling windows, ROLLUP), like-for-like growth, peer z-scores |
| **Power Query** | Parameterised connection, a fiscal date table derived from the facts, 1:1 merges into the dimension, a validation query, error-audit query, folding notes |
| **Data model** | 2 dimensions, 4 facts, 8 one-to-many single-direction relationships; location flattened; investment on the dimension |
| **DAX** | 100 measures: time-weighted ROI, fiscal-year time intelligence, like-for-like growth, percentile scoring, dynamic narrative |
| **Dashboard** | 6 pages, each answering one question; no dual axes; disclaimers on scores |
| **Insights** | Scale ≠ return; tariff > sunshine; like-for-like decline; ₹38.6 Cr suspected curtailment; ~₹3 Cr cleaning "saving" vs ~₹18 Cr loss; 52 % of capital in High-inv/Low-ROI |
| **Business impact** | On this simulated portfolio: ₹65.9 Cr avoidable loss quantified, 8 projects with an owner and an action, and a capital recommendation robust to weighting. **No real-world savings claimed** |
| **Challenges** | MySQL date traps; designing ROI for mid-window commissioning; separating weather from operations; keeping SQL, Python and DAX definitions identical |
| **Limitations** | Synthetic data; GHI not POA; no debt or tax; national emission factor; n = 56 for ROI drivers; `.pbix` not yet built (Linux) |
| **Future** | Real data, state emission factors, IRR/NPV, curtailment logs, CI with DAX tests (Tabular Editor / DAX Studio), Power BI Service with a gateway |

## 3. Fifty interview questions

Format: **Q**, then the answer, then ↳ a likely follow-up and how to handle it.

### SQL (1–8)

**1. Walk me through your SQL pipeline.**
Five layers: `stg_` (all-text landing), a DQ script that builds typed `wrk_` tables with one flag per rule and logs every defect to `dq_issue_log`, a transform that loads the constrained star schema, `vw_` views that hold every KPI definition, and an analysis pack of 19 queries. Staging is never edited, so every fix can be traced to its raw evidence.
↳ *Why not fix data in place?* You lose the evidence. An auditor asking "why is this number different from SCADA?" needs the original row and the rule that changed it.

**2. How did you remove duplicates?**
`ROW_NUMBER() OVER (PARTITION BY <all business columns> ORDER BY stg_row_id)`, keeping rank 1. For the project master I partitioned by `project_code` and ordered by `record_updated_at DESC`, because the duplicate was a stale *version*, not an exact copy. Then a composite primary key `(project_id, month_start_date)` makes duplicates impossible going forward.
↳ *Two rows, same key, different values?* That's a conflict, not a duplicate. I'd keep both in a quarantine table and ask the source owner, never pick one silently.

**3. Explain your ROI calculation.**
`SUM(EBIT) / (SUM(capex over operating months) / 12)`. Each fact row is one operating month, so summing capex per row and dividing by 12 gives capital-years. A project commissioned in Oct-24 is charged only for the months it was running.
↳ *Why not SUM(profit)/SUM(investment)?* It penalises new projects (a full capex but only part-year profit). It also isn't annualised, so a 3-year window would show 3× the yearly return.

**4. How did you compute year-over-year growth?**
Two ways: reported (all projects) and like-for-like (only projects with 12 months in both years), using CTEs and a self-join on fiscal year. Reported was +7.11 %, like-for-like −2.25 %.
↳ *Why does the difference matter?* Reported growth mixes new capacity with performance. Like-for-like is the honest view of how the fleet is doing.

**5. Give an example of a window function you used, and why.**
`SUM(energy) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)` for the rolling 3-month total. `LAG(energy, 12)` for monthly YoY. `NTILE(4)` for ROI quartiles. `PERCENT_RANK` for multi-criteria regional ranking.
↳ *ROWS vs RANGE?* ROWS counts physical rows; RANGE uses value ranges and treats ties as peers. With one row per month they agree, but ROWS is explicit and safer.

**6. How do you find underperforming projects in SQL without punishing cloudy regions?**
I compare the weather-normalised performance ratio (energy ÷ capacity × irradiation) with same-technology peers using z-scores, only where the peer group has at least 5 projects. Raw capacity factor would flag every North-East plant for its weather.
↳ *Why at least 5 peers?* With 2 floating plants the z-scores are always ±1; the statistic is meaningless. For capex I used an external benchmark instead.

**7. What does `WITH ROLLUP` do and where did you use it?**
It adds subtotal rows per region and a grand total. I used `GROUPING()` to label them, because a NULL from ROLLUP and a genuine NULL look the same otherwise.
↳ *Alternative?* `UNION ALL` of grouped queries, which is more verbose. Or `GROUPING SETS`, which MySQL 8.0 does not support.

**8. How did you validate the SQL output?**
Post-load assertions in SQL: orphans, energy × tariff = revenue, CF ≤ 0.35, depreciation = capex/300. Then a Python script with 41 checks reconciles totals to the generator's ground truth and matches every injected defect *by record key*.
↳ *In a real job there's no ground truth. Then what?* Reconcile against independent systems (billing vs SCADA, ERP vs bank), and use control totals from the source export.

### MySQL (9–13)

**9. What MySQL-specific traps did you hit?**
`STR_TO_DATE('2024-02-30')` returns an invalid date instead of NULL. `STR_TO_DATE('01-10-2024', '%Y-%m-%d')` silently becomes 2001-10-20. And with a case-insensitive collation, `'BENGALURU' = 'Bengaluru'`, which hid text fixes from the log. A naive check found 0 bad dates; there were 11.
↳ *How did you detect invalid dates, then?* A regex for the format, then a round trip: `DATE_FORMAT(STR_TO_DATE(x) + INTERVAL 0 DAY) = x`. Adding 0 days normalises 30-Feb to 1-Mar, so the round trip fails.

**10. Why is staging all VARCHAR?**
So bad data *lands*. A typed staging table rejects or coerces `2024-02-30` at load time, and that defect is never counted or logged.

**11. Why CHECK constraints instead of ENUM?**
CHECK is standard SQL (enforced in MySQL since 8.0.16), portable, and easy to change. ENUM is MySQL-only, and changing its list rewrites the table.
↳ *What can't a CHECK do?* Reference other rows or non-deterministic functions like `CURRENT_DATE`. So "Operational projects must have a past COD" is a DQ query, not a constraint.

**12. Why is profit a generated column?**
One definition, impossible to drift. Nobody can load a profit that doesn't equal revenue − costs. `STORED` means it's computed once at write time.

**13. Surrogate or natural keys?**
Both. `project_id` (integer surrogate) for joins and Power BI relationships; `project_code` (natural) is UNIQUE for traceability. If the source renames codes, facts don't break.

### Data quality (14–17)

**14. How did you handle missing values?**
It depends on what is missing. Missing energy is **rebuilt** from billing, because it is recoverable exactly. Missing maintenance cost is **imputed** with the project *median* and flagged. Missing weather is **left NULL**, because I never invent observations.
↳ *Why median, not mean?* One hail-repair month would inflate a mean. The median is robust to that.

**15. Outlier vs error: how do you tell them apart?**
Physics and corroboration. A ×10 meter spike implies CF > 35 %, which is impossible for PV, and billing disagrees, so it's an error and gets rebuilt. A hail month has 290 hours of downtime *and* a repair bill, so it's a real event: flagged, never deleted.

**16. You fixed a negative investment with ABS(). Isn't that risky?**
It would be on its own. I only applied it because two independent checks agreed: capex/MW fell in the plausible band, and ERP depreciation × 300 equals |capex|. Without both, it would have been quarantined.

**17. What does "billing meter is the system of record" mean?**
Revenue = metered MWh × a fixed PPA tariff, so every SCADA reading has an independent check. SCADA within 2 % of billing is accepted; otherwise the billing value is used and tagged `BILLING_RECONSTRUCTED` (0.6 % of months).

### Power Query (18–21)

**18. What did you do in Power Query, and why so little?**
Parameterised connection, types, a fiscal-year date table derived from the facts, 1:1 merges into the dimension, and validation queries. The cleaning is in SQL, where it's versioned, testable and reusable by non-Power BI users.
↳ *When would you clean in Power Query?* When the source is a file or API you can't change, or for a self-service analyst without database access.

**19. What is query folding, and where does it break in your queries?**
Folding means Power Query translates steps into SQL that runs on the server. Mine folds through navigation and typing; `Date.DaysInMonth` (hours in month) does not fold, so it's the last step.
↳ *How do you check?* Right-click a step → View Native Query. If it's greyed out, folding stopped before that step.

**20. How is your date table built?**
In M with `List.Dates`, ranging from the minimum to the maximum fact date padded to fiscal-year boundaries, with fiscal columns (FY Apr–Mar, fiscal month, quarter). It is marked as the date table, and auto date/time is off.

**21. How do you handle errors in Power Query?**
`Table.ReplaceErrorValues` so a bad cell doesn't fail the refresh, plus a separate audit query using `Table.SelectRowsWithErrors`, so errors are visible rather than silently dropped.

### Data modelling (22–26)

**22. Describe your model.**
A star schema: Date and Project dimensions; Energy, Financials, Sustainability and Month Diagnostics facts at project × month. Eight one-to-many, single-direction relationships.

**23. Why not one combined fact table?**
They come from different systems (SCADA, ERP, derived) with different quality paths. Separate facts keep lineage clear; shared dimensions still allow cross-fact measures.
↳ *Doesn't that cost performance?* Not at this size, and VertiPaq handles star joins well.

**24. Why is investment on the dimension and not on the fact?**
It's paid once per project. On 36 monthly rows, SUM overstates it 36 times. It's a classic semi-additive trap.

**25. Why no bidirectional relationships?**
With several facts sharing dimensions, bidirectional filters create ambiguous paths and silently wrong totals. Where I need "only periods with data", I do it explicitly in DAX.

**26. You flattened location into Project. When would you keep the snowflake?**
If Location were large, shared by other facts (e.g. weather stations), or had its own attributes maintained separately. At 28 rows, flattening is simpler and faster.

### DAX (27–34)

**27. Why `SUMX` with `RELATED` for capital employed?**
It iterates the monthly fact rows and picks up each project's capex per row, which time-weights it automatically. `SUM(Project[investment])` would ignore how long each project operated in the selected period.

**28. Explain your like-for-like DAX measure.**
It filters `VALUES(Project[project_id])` to projects whose row count equals the number of months in the period, both now and in `SAMEPERIODLASTYEAR`, then compares energy for that set only.
↳ *Limitation?* It's meant for a fiscal year or month on rows. With no date filter, the period is the whole calendar and no project qualifies, so it returns blank. That's intended.

**29. Why `TOTALYTD(…, "3/31")`?**
The Indian fiscal year ends 31 March. Without the year-end argument, YTD resets in January.

**30. Your rolling 12-month measure doesn't use `MAX('Date'[Date])`. Why?**
The date table is padded to Mar-2027. At the grand total, `MAX` would be 31-Mar-27 and the window would be empty. I anchor to the last month *with data*.

**31. How does `RANKX` with `ALLSELECTED` behave?**
It ranks within the user's current slicer selection: select three regions and they're ranked 1–3. With `ALL` they'd keep their global rank. I also exclude blanks so pipeline projects don't take last place.

**32. Explain context transition in your percentile measures.**
`ADDCOLUMNS(ALLSELECTED(Project[region]), "@v", [ROI %])`. Calling a measure inside the row context of ADDCOLUMNS converts the current region into a filter, so `[ROI %]` is evaluated per region while keeping the date and type slicers.

**33. Why `DIVIDE` instead of `/`?**
It returns BLANK on division by zero, so visuals don't show errors and blank rows disappear naturally.

**34. Measure vs calculated column: give an example of each from your project.**
`ROI %` is a measure because it must respond to slicers. `Investment Quadrant` is a column because a scatter legend needs a column, and I wanted classification to be stable rather than change when someone filters a month.

### Statistics (35–40)

**35. Tell me about the temperature finding.**
Raw correlation with capacity factor was +0.21, which suggests heat helps. Controlling for irradiation it flips to −0.24, and −0.33 within each plant. Hot months are the sunniest, so irradiation confounds the relationship. The regression's −0.44 %/°C matches silicon datasheets.
↳ *Are your p-values valid?* Not strictly. Monthly rows from one plant are autocorrelated, so p-values are optimistic. I relied on effect size and the sign reversal.

**36. Pearson or Spearman?**
Spearman as the headline: capacity has a long tail (0.5–300 MW), and rank correlation is robust to it. I reported both; they agreed on every sign.

**37. How does your expected-generation model work?**
OLS on weather-normalised PR (energy ÷ capacity × irradiation × availability) with technology, temperature, age and ramp-up terms. It is fit with trimming: fit, drop |robust z| > 3.5, refit. R² 0.94.
↳ *Why trim?* Problem plants would drag the "healthy" benchmark down and hide themselves.
↳ *Why not ML?* I needed explainable coefficients. Recovering a physical temperature coefficient (−0.44 %/°C) is evidence the model is right; a gradient-boosting model gives no such check.

**38. Why robust z-scores (median/MAD)?**
Outliers inflate the standard deviation they're measured against (masking). The median and MAD aren't moved by the anomalies I'm trying to find.

**39. You found too many false alerts at first. What happened?**
New projects have few months, so their MAD is tiny and a ±2 % wobble gave z > 3.5. I added a materiality floor (z > 3.5 **and** residual below −5 %): statistical *and* practical significance.

**40. How accurate was your loss quantification?**
Against the generator's hidden losses: curtailment +4.2 %, soiling +6.4 %. The slight over-estimate is degradation and noise being absorbed into "unexplained".

### Business analytics (41–45)

**41. What's the single most important insight?**
Return is driven by the business model, not sunshine. C&I earns 8.3 % ROI vs 5.4 % for utility-scale despite a lower capacity factor, because its tariff is 53 % higher. It changes where you'd look for the next investment.

**42. How would you explain falling ROI to a CFO?**
"It's not the new projects; they earn more. On the 45 plants running all three years, revenue per MW fell 6 % and cash cost per MW rose 11 %. Fixed tariffs don't absorb cost inflation, and we lost output to suspected curtailment and soiling."

**43. How did you decide curtailment vs soiling?**
By signature. Curtailment is a step loss starting the *same month* at two sites in the same state with no downtime: a shared external cause. Soiling is progressive at one site, with lower maintenance spend, and resets after cleaning. Both are labelled *suspected* until SLDC logs or a site visit confirm them.

**44. What business impact can you claim?**
On the simulated portfolio: ₹65.9 Cr of avoidable revenue loss quantified and attributed, 8 projects with an owner and action, and a capital recommendation that holds under every weighting I tested. I don't claim real savings; the data is synthetic.

**45. What recommendation would you give, and how confident are you?**
Next tranche to C&I in West and South: confident, because West is #1 under every weighting. Rajasthan expansion conditional on curtailment data: confident about the risk, less so about its size. North is a judgement call: it ranks #2 to #5 depending on whether you value resource or return.

### Dashboard design (46–48)

**46. How did you decide what goes on each page?**
Each page answers one question, written as its title. A visual that doesn't serve that question is cut. Page 4, for example, exists to separate weather from operations, so every visual on it is weather-normalised or downtime-specific.

**47. Why no dual-axis charts?**
Two scales on one chart let the designer choose the visual correlation by choosing the axis ranges. I used separate small charts, like energy trend next to revenue trend, or the same region order on two bar charts.

**48. How do you make a composite score trustworthy?**
Show its formula on the page, let users change the weights, show a sensitivity table, and label it as a framework, not advice. West and North-East don't move under any weighting; North does, and the page says so.

### Case studies (49–50)

**49. If the CFO asked you to cut O&M cost by 10 %, what would you do with this model?**
Not across the board. P001 shows that cutting cleaning saved about ₹3 Cr and lost about ₹18 Cr. I'd target cost-per-MW outliers that have *normal* performance (P047 at 2.2× peers) and re-tender them, while keeping spend tied to the PR alert so cuts that hurt output show up within two months.

**50. Tomorrow, a new region shows high ROI but low availability (like the East). Invest?**
Look at why the ROI is high. In the East it comes from high C&I and rooftop tariffs, despite the weakest availability (94.7 %) and resource. That's contract-driven return with an operational risk. I'd want offtaker credit quality and tariff tenure, and an O&M fix plan, before treating it like the West. The priority score ranks the East #5 by default, but #3 when return-heavy, which tells you the case rests on tariffs.

## 4. Questions to ask the interviewer
- "How does your team reconcile operational data with finance today?"
- "When a composite score drives a decision here, who owns the weights?"
- "Would a dashboard like this sit with FP&A or with operations?"
