# 04 — Business Case, Insights & Recommendations

> All figures come from the project's SQL views, Python analysis and DAX validation sheet. The company and data are **synthetic** (see [01_project_design.md](01_project_design.md) §4), so the insights demonstrate the method; they are not claims about real Indian solar assets.
> Every insight separates **Fact** (what the data shows) from **Interpretation** (what it probably means). Interpretations are hypotheses to confirm, not findings.

## 1. The business case

**Arka Renewables** (fictional) is an Indian solar IPP with 60 projects: 56 operating, 4 under construction, 2,927 MW, ₹12,263 Cr invested. Over FY2023-24 to FY2025-26 the fleet produced 11.45 TWh, ₹3,395 Cr revenue and ₹1,747 Cr EBIT.

**Trigger.** The Investment Committee must approve the next capital tranche. Two signals worry the CFO: portfolio ROI has fallen every year, and the latest board pack reported "+7 % generation growth", which nobody could reconcile with weaker returns.

| Stakeholder | Needs to know |
|---|---|
| Investment Committee | Where should the next tranche go, and what are the risks? |
| CFO | Why is ROI falling while generation "grows"? |
| Head of O&M | Which plants are underperforming, why, and what is it costing? |
| ESG lead | What is our CO₂ impact, and how efficient is it per rupee? |

## 2. Answers to the five management questions

| # | Question | Short answer | Where |
|---|---|---|---|
| 1 | Which regions perform well? | **West** on return (7.66 % ROI, #1 under every weighting). **North** on volume only (39 % of energy, ROI #5) | Page 2; insights 1, 2 |
| 2 | Which projects need investigation? | 8 flagged. Urgent: **P004/P006** (suspected curtailment), **P001** (suspected soiling), **P055** (reliability). Also **P047** (O&M cost) and **P039** (capex) | Page 4; insights 5–8 |
| 3 | Where should future capital go? | Framework result: **C&I in West and South**. North is weighting-dependent; North-East is last under every weighting | Page 6; insight 14 |
| 4 | Which projects earn the highest returns? | All **top 9 are C&I open-access** (Solapur, Pune, Ahmedabad, Jhansi, Hisar, Neemuch, Kurnool, Coimbatore, Bengaluru) | Page 3; insight 2 |
| 5 | Greatest sustainability impact? | **North** in absolute CO₂ (3.2 Mt, 39 %); **West** per rupee (290 t per ₹ Cr-year) | Page 5; insight 16 |

## 3. Insights

### Portfolio and strategy

**1. Scale does not translate into return.**
- *Fact:* North produces 39.2 % of energy but ranks #5 of 6 on ROI (5.22 %). West produces 14.9 % and ranks #1 (7.66 %). Their capacity factors are almost the same (18.4 % vs 18.9 %); their realised tariffs are not (₹2.66 vs ₹3.25/kWh). *(Q03, Page 2)*
- *Interpretation:* North's weakness is commercial (low-tariff auction PPAs in Rajasthan), not technical. More sun does not fix a low tariff.
- *Action:* Rank regions on ROI and performance ratio, never on MWh alone. Board KPIs should lead with return per rupee.

**2. Return is driven by the business model, not by sunshine.**
- *Fact:* C&I open-access earns 8.29 % ROI against 5.42 % for utility-scale, despite a *lower* capacity factor (17.3 % vs 18.4 %). Its realised tariff is 53 % higher (₹4.11 vs ₹2.68). All top-9 projects by ROI are C&I. Across projects, ROI correlates with tariff (ρ = 0.40) and availability (0.36) far more than with capacity factor (0.19). *(Q06, Q13, Stage 3 §1.4)*
- *Interpretation:* Contract structure (who buys the power, and at what price) separates good investments from average ones more than the solar resource does.
- *Caveat:* Tariff, capex/MW and project size move together (ρ ≈ 0.75–0.8), and n = 56. This is an association, not a measured causal effect.
- *Action:* Weight offtaker quality and tariff heavily in new-project screening. C&I growth is capped by offtaker demand and credit risk, which this dataset does not cover.

**3. Reported growth hides a declining fleet.**
- *Fact:* FY26 energy is **+7.11 %** reported, but **−2.25 %** for the 48 plants that operated all 12 months of both years. FY25 was +0.51 % reported against −3.79 % like-for-like. *(Q11, DAX `LFL Energy YoY %`)*
- *Interpretation:* All the growth comes from new capacity. The existing assets are producing less, from weather, degradation and the losses in insights 5–6.
- *Action:* Report like-for-like generation next to reported growth in every board pack. This answers the CFO's "growth vs falling ROI" puzzle.

**4. ROI is eroding on the existing fleet, from both revenue and cost.**
- *Fact:* Portfolio ROI fell 6.21 % → 5.79 % → 5.54 % (FY24–FY26). For the 45 plants that operated all 36 months, ROI fell 6.18 % → 5.74 % → 5.35 %. Revenue per MW fell 48.3 → 45.5 lakh (−5.8 %) while cash cost per MW rose 5.95 → 6.62 lakh (+11 %). Plants commissioned in the window earn *more* (6.75 % vs 5.76 %). *(Q07, ad-hoc query)*
- *Interpretation:* Not a mix effect from new projects. Fixed-tariff PPAs cannot absorb cost inflation (cash cost per MW up about 5–6 % a year on the like-for-like fleet), and output losses compound it. This structural squeeze will continue unless costs are controlled.
- *Action:* Set a cost-per-MW target for O&M and fixed opex, and index new contracts where the market allows it.

### Operations

**5. Two Rajasthan parks lost ₹38.6 Cr to a shared, external-looking cause.**
- *Fact:* P004 (Jodhpur) and P006 (Bikaner) dropped 7–17 % below weather-adjusted expectation **in the same month (Oct-24)**, with **no increase in logged downtime**. FY26 output was 10.9 % and 12.1 % below expectation. *(Stage 3 §3.3, Page 4)*
- *Interpretation:* A simultaneous step loss at two separate sites without outages is the signature of **grid curtailment** (transmission congestion), not equipment failure. *Suspected, not confirmed.*
- *Action:* Request curtailment logs from the state load dispatch centre (SLDC). Check the PPAs for deemed-generation compensation clauses, which may make part of the ₹38.6 Cr recoverable.

**6. Saving about ₹3 Cr on cleaning appears to have cost about ₹18 Cr in revenue.**
- *Fact:* P001 (Jaisalmer) shows a *progressive* loss from Jul-24, reaching −15.1 % in FY26, and recovering abruptly in Jan-26. Its maintenance spend fell from ₹5.62 Cr (FY24) to ₹4.10 Cr (FY25), about ₹3 Cr below the inflation-adjusted FY24 level across the lapse. Downtime stayed normal. *(Stage 3 §3.3, Q15)*
- *Interpretation:* A gradual loss that resets suddenly, with lower maintenance spend, fits panel soiling after a cleaning contract lapsed.
- *Action:* Set the module-cleaning frequency from a cost-vs-loss calculation, and add a "performance ratio below expected for 2 months" alert so the next lapse is caught in weeks, not after 20 months.

**7. Reliability problems are severe in relative terms but small in rupees.**
- *Fact:* East has the lowest availability (94.7 % vs 97.6 % portfolio). P055 (Patna rooftop) runs at 82 % availability, with O&M 3.3σ above rooftop peers and ROI of 1.08 %. Its avoidable loss is only ₹0.45 Cr, because the plant is small. *(Q09, Page 4)*
- *Interpretation:* A rupee ranking would put P055 near the bottom of the priority list; a percentage ranking puts it at the top. Both views are needed.
- *Action:* Run an inverter replacement and warranty review at P055. Prioritise by ₹ for capital decisions and by % for O&M process fixes.

**8. A cost problem that looks like nothing is wrong.**
- *Fact:* P047 (Raipur C&I) has normal performance ratio (80.1 %) and availability (98.7 %), but O&M of ₹9.18 lakh/MW/yr, **2.2× its C&I peers** (₹4.23 lakh). Its ROI is 5.72 % against 8.29 % for C&I overall. *(Q14)*
- *Interpretation:* A procurement or contract problem, not an engineering one. Generation-based monitoring would never flag it.
- *Action:* Re-tender the O&M contract. Monitor cost per MW against peers, not only output.

**9. Temperature costs output, but the raw data says the opposite.**
- *Fact:* Raw correlation of temperature with capacity factor is +0.21. Controlling for irradiation it is −0.24, and −0.33 within each plant. The model's temperature coefficient is −0.44 %/°C. *(Stage 3 §1.3)*
- *Interpretation:* Hot months are the sunniest, which masks the heat penalty. A naive analysis would favour the hottest sites.
- *Action:* Use temperature-corrected yield (or PR) in site selection, and evaluate cooler-running designs for desert sites.

### Capital

**10. Half the operating capital earns below-average returns, and that is where the problems are.**
- *Fact:* The "High investment / Low ROI" quadrant holds 15 projects and **₹5,628 Cr (52 % of operating capital)**, including 7 of the 8 projects with a root-cause flag. *(Page 3, 04_scoring_methodology §4)*
- *Interpretation:* The largest value pool is fixing the existing fleet. Each 0.1 pp of ROI on this capital is about ₹5.6 Cr a year.
- *Action:* Before approving new capacity, set a fix-or-explain plan for every project in this quadrant.

**11. Capex overruns lock in low returns for 25 years.**
- *Fact:* P039 (Kochi floating) was built at 130 % of the technology benchmark. It earns 0.66 % ROI with a 21.5-year simple payback, although its availability (98.6 %) is normal. Floating as a whole earns 1.46 %, but there are only 2 floating projects. *(Q08, Q14)*
- *Interpretation:* The problem is the cost of entry, not operations. With n = 2, this is not a verdict on floating solar as a technology.
- *Action:* Add a capex-vs-benchmark gate to project approval. Re-examine the business case before any further floating projects.

**12. The North-East is structurally weak, but well operated.**
- *Fact:* The North-East has the lowest ROI (4.47 %), CF (14.8 %) and solar resource (4.35 kWh/m²/day), with a capex premium (P057 at 118 % of benchmark). Yet its performance-ratio trend is the *best* of all regions (+0.48 %). It ranks last under every weighting. *(Pages 2 and 6)*
- *Interpretation:* The plants are run well. The resource and the cost of building there are the problems, and operations cannot fix those.
- *Action:* Hold new North-East capital unless policy support (tariff or viability-gap funding) changes the economics.

### Portfolio structure

**13. No 80/20 rule: concentration is moderate.**
- *Fact:* It takes 25 of 56 projects (45 %) to reach 80 % of revenue; the top 10 produce 51 %. Energy and EBIT are similar (41 % and 43 % of projects for 80 %). *(Stage 3 §4)*
- *Interpretation:* No single asset is existential, but the top 10 carry half the cash flow. Their availability matters most.
- *Action:* Assign tier-1 O&M service levels (response time, spares) to ABC class A.

**14. The biggest projects are not the best investments.**
- *Fact:* ABC class C (18 small projects, 4.2 % of revenue) has the highest median ROI, 6.90 %. Class A (25 projects, 80.5 % of revenue) has 5.86 %. *(Stage 3 §4)*
- *Interpretation:* ABC tells you where to focus *operations*, not where to *invest*. Mixing the two would steer capital to scale over return.
- *Action:* Use ABC for O&M prioritisation and ROI/IPS for capital allocation.

**15. Seasonality is large but diversified by geography.**
- *Fact:* Monthly generation in FY26 ranged from 15.3 % below to 23.1 % above the monthly average. The monsoon quarter cuts CF by about 5.4 points in the North and West but only by 2.5 in the South. *(Q18)*
- *Interpretation:* The South smooths portfolio cash flow during the monsoon.
- *Action:* Plan debt-service and working-capital buffers around the July–September trough. Value southern assets for their diversification, not just their ROI.

### Sustainability and data

**16. Absolute impact and impact per rupee rank regions differently.**
- *Fact:* North avoids the most CO₂ (3.2 Mt, 39 %). West avoids the most per rupee (290 t per ₹ Cr-year), and the North-East the least (194 t). The captive renewable share is highest in the South (45.6 %) and lowest in the North-East (22.9 %). *(Page 5)*
- *Interpretation:* "Biggest impact" and "most efficient impact" are different ESG claims and should be reported separately.
- *Caveat:* One national emission factor means the CO₂ ranking mirrors the energy ranking.
- *Action:* Adopt state-level emission factors before using these numbers in external ESG reporting.

**17. Data quality was managed rather than assumed.**
- *Fact:* 67 defects were detected and logged; 11 energy months (0.6 %) were rebuilt from the billing meter; 3 cost values were imputed. Totals reconcile to the source exactly, except 0.002 % on maintenance. *(Stage 2)*
- *Interpretation:* SCADA is unreliable enough (sign errors, ×10 spikes, unit mix-ups) that an unreconciled dashboard would be wrong.
- *Action:* Automate the monthly SCADA-vs-billing reconciliation and publish the data-quality page with the dashboard.

## 4. Recommendations

These are framework-based and stated as analyst recommendations on this dataset, not investment advice.

| # | Recommendation | Evidence | Owner | KPI to track | Horizon |
|---|---|---|---|---|---|
| 1 | Direct the next tranche to **C&I in West and South** | Insights 1, 2; IPS West #1 under every weighting | Investment Committee | ROI of new C&I vs 7.5 % hurdle | Next tranche |
| 2 | Make new **Rajasthan** capacity **conditional on curtailment data**; pursue deemed-generation claims | Insight 5; Rajasthan is 32 % of energy | Regulatory / Commercial | Curtailment % by month; ₹ recovered | 1 quarter |
| 3 | Reinstate and **optimise module cleaning**; add PR alerts | Insight 6 | Head of O&M | PR vs expected ≥ −3 % | Immediate |
| 4 | **Reliability programme** at P055 and the East rooftop fleet | Insight 7 | O&M | Availability ≥ 97 % | 2 quarters |
| 5 | **Re-tender O&M** at P047; peer cost-per-MW monitoring | Insight 8 | Procurement | O&M ≤ 1.2× peer median | 2 quarters |
| 6 | **Fix-or-explain plan** for the High investment / Low ROI quadrant | Insight 10 | CFO | Quadrant ROI | 12 months |
| 7 | **Capex benchmark gate** at approval; hold new floating and North-East capex | Insights 11, 12 | Investment Committee | Capex / benchmark ≤ 1.10 | Policy |
| 8 | Report **like-for-like** generation and **cost per MW** in the board pack | Insights 3, 4 | FP&A | LFL YoY; cash cost per MW | Next board pack |

**What the data cannot tell us:** PPA terms beyond tariff, offtaker credit risk, financing costs, land and grid-connection availability, and the policy pipeline. All of these matter for real capital allocation, which is why the priority score is presented as one input to a decision, not the decision itself.

## 5. Risks

| Risk | Evidence | Likelihood × impact (analyst view) |
|---|---|---|
| Grid curtailment spreading in Rajasthan | 2 parks affected since Oct-24; Rajasthan is 32 % of energy and 27 % of revenue | High × High |
| Margin squeeze from fixed tariffs vs cost inflation | Like-for-like cash cost/MW +11 % vs revenue/MW −5.8 % | High × Medium |
| O&M discipline | Soiling loss ran about 20 months (Apr-24 to Dec-25) before recovering | Medium × Medium |
| Capex overruns on new technologies | P039 at 130 % of benchmark | Medium × High (25-year lock-in) |
| Data quality | 0.6 % of months rebuilt; sign and unit errors in SCADA | Low × Medium (now controlled) |
