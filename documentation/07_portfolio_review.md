# 07 — Portfolio Review: Strict Recruiter Assessment

> Written as a sceptical hiring manager for analyst roles at a bank, Big 4 or consulting firm would review it. Scores are out of 10 and judge **what a reviewer can verify in the repository today**, not what the project could become.

## 1. Scores

| Dimension | Score | Why | The weakness that costs points | Concrete fix |
|---|---|---|---|---|
| **SQL complexity** | **8.5** | Window functions, CTEs, ROLLUP + GROUPING, stored functions, generated columns, strict validation, like-for-like logic, an audit log, post-load assertions | No indexes tuned with `EXPLAIN`; no incremental (delta) load; scripts rebuild everything | Add an `EXPLAIN ANALYZE` note on two heavy queries, and an incremental-load procedure keyed on `month_start_date` |
| **Data modelling** | **8.5** | Clean star, explicit grain, composite keys, investment correctly on the dimension, every design choice reasoned | Not yet verified in a real `.pbix` (relationship warnings, cardinality detection) | Build the model in Power BI Desktop and screenshot the model view |
| **Power BI** | **5.0** | Strong spec, M code, validation query and build guide | **There is no `.pbix` and no real screenshots.** A recruiter opening the repo sees mockups. This is the single biggest gap | Build the report on Windows (about a day using the guide) and replace the mockups with real screenshots |
| **DAX** | **6.5** | 100 measures with correct patterns (time-weighted ROI, FY-aware time intelligence, like-for-like, percentile scoring, narrative) | **None of the DAX has been executed.** Syntax or context errors are possible, and the expected-value sheet exists but has never been compared | Run every measure against `05_dax_expected_values.md`; record pass/fail in the repo; optionally export with DAX Studio |
| **Business thinking** | **9.0** | Every page answers a question; insights separate fact from interpretation; recommendations carry owners and KPIs; limitations are stated | Recommendations ignore financing, offtaker credit and policy, which real investment committees weigh heavily | Add a one-page "what a real IC would also need" section with an IRR sketch, or flag it as next phase |
| **Analytical depth** | **9.0** | Confounding analysis, a physics-anchored model, loss decomposition, robust anomaly rules, evaluation against ground truth with the post-hoc revision disclosed | n = 56 limits project-level inference; no uncertainty intervals on the ₹ loss estimates | Bootstrap the residuals to put a range on the ₹65.9 Cr (e.g. "₹55–75 Cr") |
| **Visualisation** | **6.5** | Disciplined design: one question per page, no dual axes, validated palette, direct labels | Mockups, not an interactive report. Some pages are dense (Page 1 has 10 elements) | Real Power BI pages; move the management summary to a tooltip page; reduce Page 1 to 6 visuals |
| **Real-world relevance** | **7.0** | Indian context (FY, CUF, SECI-style tariffs, CEA emission factor, curtailment) is credible and domain-specific | **Synthetic data.** Some reviewers discount any synthetic project | Add a companion notebook on a real public dataset, e.g. plant-level generation from CEA/NREL or Kaggle solar data, re-using the same model |
| **Resume value** | **8.0** | Distinctive, quantified, honest bullets; uncommon skills (reconciliation, confounding, framework scoring) | Only as strong as the visible dashboard; "simulated" must be explained | Fix the Power BI gap; pin the repo with a GIF of the report |
| **Interview value** | **9.5** | Many genuine stories: MySQL traps, ROI design, temperature paradox, curtailment vs soiling, a disclosed mistake | Risk of over-talking; candidates must be able to hand-write the core DAX and SQL | Practise Q3, Q9, Q28, Q35 and Q43 from the interview kit aloud, with a timer |

**Overall: 7.8 / 10 as it stands. About 8.8 once the `.pbix` is built and validated.**

## 2. Verdict as a recruiter

> *"Shortlist. The SQL and analysis are well above a typical entry-level portfolio, and the candidate understands why a number is right, not just how to produce it. I'd probe the Power BI work in interview because there is no report file. If they can explain the DAX patterns live, this reads as a solid analyst at a bank or Big 4. Without a built dashboard it looks like a strong data-engineering and analysis project with a BI specification attached."*

## 3. Priority fixes, in order of return on effort

1. **Build the `.pbix` and validate the DAX** against the expected-value sheet. Raises Power BI, DAX and visualisation scores; about one day.
2. **Replace the mockups with real screenshots and a 30-second GIF** in the README; about one hour.
3. **Put an uncertainty range on the loss estimate** (bootstrap); about two hours.
4. **Add a real-data companion** (one public dataset, same expected-generation model); about one day.
5. **Add CI** (GitHub Actions running the SQL rebuild and `validate_pipeline.py` against a MySQL service container); about half a day. It signals engineering maturity.

## 4. How this compares with a typical beginner Power BI project

| Aspect | Typical beginner project | This project |
|---|---|---|
| Data | A clean Kaggle CSV, used as-is | Raw exports with 67 defects, detected, logged and reconciled to the source |
| Data preparation | Power Query clicks; errors removed | SQL pipeline with an audit trail; repaired from an independent system of record; nothing silently dropped |
| Model | One flat table, or auto-detected relationships | Star schema with reasoned grain, single-direction filters, investment on the dimension |
| KPIs | `SUM` and `AVERAGE`, average of ratios | Ratio of sums, time-weighted ROI, like-for-like growth, weather-normalised PR |
| DAX | A few totals, maybe YTD | 100 measures: fiscal-year time intelligence, ranking within selection, percentile scoring, dynamic narrative |
| Analysis | "Region A has the highest sales" | Confounding reversed, root causes separated (weather vs operations vs cost vs capital), loss valued in ₹ |
| Validation | None | 41 automated checks, ground-truth evaluation with recall and precision, expected value for every measure |
| Recommendations | Generic or none | Owner, KPI and horizon per recommendation; framework clearly labelled as not investment advice; sensitivity tested |
| Honesty | Implicit claims | Synthetic data declared; post-hoc rule change disclosed; mockups labelled; limitations listed |

**The difference that matters most:** a beginner project shows that the candidate can *make charts*. This one shows the candidate can **decide which number is right, prove it, and explain what to do about it**. That is what the job actually is.
