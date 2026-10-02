# 06 — Resume Bullets

**Project title line:** *Solar Energy Investment Intelligence: MySQL · Python · Power BI/DAX (simulated 60-asset portfolio)*

Rules followed:
- Every number is reproducible from this repository.
- "Simulated" or "synthetic" appears in each version.
- No real-world savings are claimed.

## Version A: ATS-focused (keyword-dense)

- Built an end-to-end **data analytics** pipeline in **MySQL**, **SQL**, **Python (pandas, NumPy)** and **Power BI** for a simulated 60-project solar portfolio (1,820 project-months × 3 fact tables), using a **star schema**, **ETL**, **data validation** and **KPI** reporting.
- Wrote **SQL** with **CTEs**, **window functions** (RANK, NTILE, LAG, rolling averages), **stored functions** and **constraints**. Automated **data-quality** checks detected 67 of 67 injected defects and reconciled totals to the source exactly (41 automated tests).
- Developed **100 DAX measures** (time intelligence, like-for-like growth, RANKX, what-if parameters) and **Power Query (M)** transformations for a 6-page **Power BI dashboard** covering ROI, capacity factor, CO₂ and an investment priority score.
- Applied **statistics** (Spearman and partial correlation, regression with R² 0.94, robust z-score **anomaly detection**, **Pareto/ABC**), correctly identifying the root cause of 7 of 7 planted operational issues.

## Version B: Data Analyst-focused (method and rigour)

- Engineered a MySQL staging-to-star-schema pipeline that logs every data defect to an audit table and rebuilds faulty SCADA readings from the billing meter. Energy and revenue reconcile to the source exactly; 0.6 % of months were reconstructed, all tagged.
- Caught silent MySQL failures (`STR_TO_DATE` accepting 30-Feb and mis-parsing DD-MM-YYYY into 2001) that a naive check missed (0 of 11 found), and built a strict round-trip validator.
- Built a weather-normalised expected-generation model (R² 0.94; recovered a −0.44 %/°C temperature coefficient) that split losses into downtime vs unexplained. It quantified hidden losses within +4–7 % of ground truth and flagged suspected curtailment from a shared same-month onset at two sites.
- Showed that reported FY26 generation growth (+7.1 %) was −2.3 % like-for-like, and that a raw +0.21 temperature–output correlation reverses to −0.24 once irradiation is controlled, both implemented in SQL and DAX.

## Version C: Business Analyst / Consulting-focused (decisions and impact)

- Built a capital-allocation decision tool for a simulated ₹12,263 Cr, 60-asset solar portfolio. The finding: the largest region by output (39 % of energy) ranks 5th of 6 on ROI, and contracted tariff, not solar resource, drives return.
- Quantified ₹65.9 Cr of avoidable revenue loss across the simulated fleet and traced 86 % of it to three assets with distinct root causes (suspected grid curtailment and panel soiling). Each finding came with an owner, a KPI and an action.
- Designed a transparent, weight-adjustable Investment Priority Score with sensitivity testing. Its recommendation (West/South C&I first) held under all 4 weighting scenarios, and the analysis showed which regional rankings were judgement calls.
- Found that 52 % of operating capital sat in "high investment / below-average return" assets, reframing the decision from "where to build next" to "fix the existing fleet first".

## One-line versions (for a projects list)

- *Solar portfolio analytics (MySQL, Python, Power BI): star schema, 100 DAX measures, anomaly detection that found 7/7 planted root causes; simulated data.*
- *Built an investment-priority dashboard showing that tariff, not sunshine, drives solar ROI; like-for-like analysis turned a reported +7 % growth into −2 %.*
