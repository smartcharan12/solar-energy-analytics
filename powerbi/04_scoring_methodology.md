# 04 — Scoring Methodology

> **These scores are an analytical prioritisation framework built on this project's (synthetic) dataset. They are not investment advice and not a financial recommendation.** They rank regions on the evidence available and make the trade-offs explicit, so that a human decision can be discussed with numbers.

## 1. Why percentile ranks

Each component is converted to a **percentile rank among the selected regions**: the share of *other* regions with a strictly lower value. That gives 0 for the worst region and 1 for the best.

| Option | Problem | Verdict |
|---|---|---|
| Raw values | Units differ (%, kWh/m², t/₹ Cr), so they cannot be added | ✗ |
| Min–max scaling | One extreme region compresses everyone else | ✗ |
| Z-score | With 6 regions the mean and SD are unstable, and the result is hard to explain | ✗ |
| **Percentile rank** | Unit-free, outlier-proof, explainable ("better than 4 of 5 others"). It loses the *size* of gaps, which is why the raw values are shown beside the score | ✓ |

Implemented identically in DAX (`Pctl …` measures) and Python (`pctl_rank`), and validated in `05_dax_expected_values.md` §E.

## 2. Investment Priority Score (IPS), region level

**Question it answers:** *If the next unit of capital had to go into one region, which region's track record supports it best?*

| Component | Measure | Weight | Why it is included |
|---|---|---|---|
| Return | ROI % (time-weighted EBIT / capital) | **25 %** | The primary investment criterion |
| Reliability | Availability | **20 %** | Downtime is the most controllable risk to cash flow |
| Solar resource | Capacity-weighted long-term GHI | **15 %** | A 25-year asset; resource quality outlasts current contracts |
| Profitability | EBITDA margin % | 10 % | Cost discipline, independent of capital intensity |
| Productivity | Capacity factor | 10 % | Realised output per MW |
| Performance trend | PR last FY ÷ PR first FY − 1 | 10 % | Weather-normalised direction of travel; catches curtailment and soiling |
| Impact | CO₂ avoided per ₹ Cr-year | 10 % | Decarbonisation per rupee (ESG mandate) |

**Weighting rationale:** about 45 % financial (return and margin), 35 % resource and operations (reliability, resource, productivity), 10 % trend, 10 % impact. Weights are **what-if sliders** on Page 6. The score renormalises by the slider total, so any combination is valid.

```
IPS(region) = 100 × Σ (weight_i × percentile_i) / Σ weight_i
```

### Default result

| Region | IPS | Rank | What drives it |
|---|---|---|---|
| West | 87 | 1 | Best ROI, margin, CF and CO₂ per ₹ Cr |
| South | 62 | 2 | Balanced; high availability |
| North | 48 | 3 (tie) | Best resource and scale, but **lowest PR trend (−9.4 %)** and low ROI |
| Central | 48 | 3 (tie) | Best availability, weakest margin |
| East | 39 | 5 | 2nd-best ROI (high tariffs) but lowest availability and weak resource |
| North-East | 16 | 6 | Weakest resource, CF and ROI |

### Sensitivity: is the ranking robust?

| Region | Default | Equal weights | Return-heavy | Resource & ESG-heavy |
|---|---|---|---|---|
| West | #1 | #1 | #1 | #1 |
| South | #2 | #2 | #2 | #3 |
| North | #3 | #3 | **#5** | **#2** |
| Central | #3 | #4 | #4 | #4 |
| East | #5 | #5 | **#3** | #5 |
| North-East | #6 | #6 | #6 | #6 |

**Reading:** West (#1) and North-East (#6) are **robust**: no reasonable weighting changes them. North is **weighting-dependent**: an investor who values resource and scale ranks it #2, while one who values return ranks it #5. That is a judgement for the investment committee, not something the data can settle, and the dashboard says so.

## 3. Sustainability Score, region level

**Question it answers:** *Which regions deliver the most decarbonisation, per rupee, per MW and in total?*

| Component | Measure | Weight |
|---|---|---|
| Capital efficiency of impact | CO₂ avoided per ₹ Cr-year | **35 %** |
| Asset productivity of impact | CO₂ avoided per MW-year | 25 % |
| Scale of impact | Total CO₂ avoided | 25 % |
| Client decarbonisation | Renewable share of captive (C&I, rooftop) demand | 15 % |

```
Sustainability Score(region) = 100 × (0.35 p_CO2/₹Cr + 0.25 p_CO2/MW + 0.25 p_CO2 total + 0.15 p_RE share)
```

| Region | Score | Note |
|---|---|---|
| North | 82 | Largest absolute impact and high CO₂ per ₹ Cr |
| West | 78 | Best CO₂ per ₹ Cr and per MW |
| South | 64 | Highest captive RE share (45.6 %) |
| Central | 47 | |
| East | 29 | |
| North-East | 0 | Last on every component except RE share |

**A stated limitation.** One national grid emission factor (0.716 tCO₂/MWh) is used, so CO₂ is energy × a constant, and the first three components rank regions by energy efficiency. A region displacing coal-heavy power avoids more CO₂ per MWh than one displacing hydro. State-level emission factors would make the score genuinely different from the energy ranking. That is listed as a future improvement.

## 4. Investment quadrant, project level (Page 3)

| Axis | Threshold | Why this threshold |
|---|---|---|
| Investment | Median operational project capex (₹ 152.4 Cr) | Splits the portfolio into two equal halves by count |
| ROI | Portfolio ROI (5.83 %) | "Above or below what the portfolio earns on average" |

| Quadrant | Projects | Capex | Median ROI | Business interpretation | Typical action |
|---|---|---|---|---|---|
| High Investment / High ROI | 13 | ₹ 3,398 Cr | 6.56 % | Large assets earning above-portfolio returns: the core: 6 large C&I plants plus utility parks in Gujarat, the South, Central and Punjab | **Protect.** Keep availability high; these carry the return |
| High Investment / Low ROI | 15 | ₹ 5,628 Cr | 5.21 % | **52 % of operating capital** earning below average. Low-tariff Rajasthan parks, curtailment, soiling, hail, capex overruns | **Fix or explain.** The largest value pool; 7 of the 8 projects with a root-cause flag are here |
| Low Investment / High ROI | 18 | ₹ 1,120 Cr | 7.83 % | Small C&I and rooftop projects at high tariffs: efficient but small | **Replicate.** The model to scale, constrained by offtaker demand |
| Low Investment / Low ROI | 10 | ₹ 593 Cr | 4.82 % | Small projects with weak resource or reliability (NE, East rooftop) | **Monitor.** Low capital at stake; fix reliability before divesting |

A low-ROI quadrant does **not** mean "bad project". A Rajasthan utility park below the 5.83 % line is still EBITDA-positive with a 10–12-year payback. "Low" means *below this portfolio's average*. The quadrant is a **static calculated column** over the full window (slicers do not move it), so a project's classification cannot change just because someone filtered a month.
