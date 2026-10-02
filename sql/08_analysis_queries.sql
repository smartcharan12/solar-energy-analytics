-- =====================================================================
-- 08_analysis_queries.sql
-- Analytical query pack. Each query starts with the business question
-- it answers. Techniques used: CTEs, window functions (RANK, DENSE_RANK,
-- ROW_NUMBER, NTILE, PERCENT_RANK, LAG, running SUM), WITH ROLLUP +
-- GROUPING(), conditional aggregation, peer z-scores, like-for-like growth.
-- =====================================================================

USE solar_analytics;

-- Q01. Portfolio headline: what did the operating fleet deliver in 3 years?
SELECT
    COUNT(DISTINCT project_id)                                            AS operating_projects,
    ROUND(SUM(energy_generated_mwh) / 1e6, 3)                             AS energy_twh,
    ROUND(SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month), 4) AS capacity_factor,
    ROUND(SUM(revenue_inr) / 1e7, 1)                                      AS revenue_cr,
    ROUND(SUM(ebitda_inr) / 1e7, 1)                                       AS ebitda_cr,
    ROUND(SUM(ebit_inr) / 1e7, 1)                                         AS ebit_cr,
    ROUND(100 * SUM(ebit_inr) / (SUM(investment_amount_inr) / 12), 2)     AS roi_pct_annualised,
    ROUND(SUM(co2_avoided_tonnes) / 1e6, 3)                               AS co2_avoided_mt
FROM vw_project_month;

-- Q02. Average generation: what does a typical MW produce, by technology?
--      Specific yield normalises for size, so a 2 MW rooftop and a 300 MW park compare fairly.
SELECT
    project_type,
    COUNT(DISTINCT project_id)                                            AS projects,
    ROUND(AVG(energy_generated_mwh), 1)                                   AS avg_mwh_per_project_month,
    -- each row is one MW-month of capacity, so SUM(capacity_mw) = MW-months
    ROUND(SUM(energy_generated_mwh) / SUM(capacity_mw) * 12, 0)           AS specific_yield_kwh_per_kwp_yr,
    ROUND(SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month), 4) AS capacity_factor
FROM vw_project_month
GROUP BY project_type
ORDER BY specific_yield_kwh_per_kwp_yr DESC;

-- Q03. Regional performance: does the biggest region also earn the best return?
SELECT region, operating_projects, energy_gwh, energy_share_pct, capacity_factor,
       realised_tariff_inr_kwh, roi_pct, energy_rank, roi_rank,
       CAST(energy_rank AS SIGNED) - CAST(roi_rank AS SIGNED) AS rank_gap  -- negative = volume outranks return
FROM vw_region_performance
ORDER BY roi_rank;

-- Q04. Region > State drill-down with subtotals (WITH ROLLUP)
SELECT
    IF(GROUPING(region), 'ALL REGIONS', region)                           AS region,
    IF(GROUPING(state),  IF(GROUPING(region), '', '  subtotal'), state)   AS state,
    COUNT(DISTINCT project_id)                                            AS projects,
    ROUND(SUM(energy_generated_mwh) / 1000, 1)                            AS energy_gwh,
    ROUND(SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month), 4) AS capacity_factor,
    ROUND(100 * SUM(ebit_inr) / (SUM(investment_amount_inr) / 12), 2)     AS roi_pct
FROM vw_project_month
GROUP BY region, state WITH ROLLUP;

-- Q05. City performance: best cities by return, with at least 2 operating projects
--      (a single project is an asset story, not a location story).
SELECT
    city, state, region,
    COUNT(DISTINCT project_id)                                            AS projects,
    ROUND(SUM(energy_generated_mwh) / 1000, 1)                            AS energy_gwh,
    ROUND(SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month), 4) AS capacity_factor,
    ROUND(100 * SUM(ebit_inr) / (SUM(investment_amount_inr) / 12), 2)     AS roi_pct,
    DENSE_RANK() OVER (ORDER BY SUM(ebit_inr) / SUM(investment_amount_inr) DESC) AS roi_rank
FROM vw_project_month
GROUP BY city, state, region
HAVING COUNT(DISTINCT project_id) >= 2
ORDER BY roi_rank;

-- Q06. ROI by technology: which business model earns its capital?
--      Capex is summed from the project grain (one row per project), never
--      from monthly fact rows, where it would repeat once per month.
WITH capex AS (
    SELECT project_type,
           SUM(investment_amount_inr) AS investment_inr,
           SUM(capacity_mw)           AS capacity_mw
    FROM vw_dim_project
    WHERE project_status = 'Operational'
    GROUP BY project_type
),
ops AS (
    SELECT project_type,
           SUM(revenue_inr) / (SUM(energy_generated_mwh) * 1000)           AS realised_tariff,
           SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month)   AS capacity_factor,
           100 * SUM(ebitda_inr) / SUM(revenue_inr)                        AS ebitda_margin_pct,
           100 * SUM(ebit_inr) / (SUM(investment_amount_inr) / 12)         AS roi_pct
    FROM vw_project_month
    GROUP BY project_type
)
SELECT o.project_type,
       ROUND(c.investment_inr / 1e7, 0)                                   AS capex_cr,
       ROUND(c.investment_inr / 1e7 / c.capacity_mw, 3)                   AS capex_cr_per_mw,
       ROUND(o.realised_tariff, 2)                                        AS realised_tariff_inr_kwh,
       ROUND(o.capacity_factor, 4)                                        AS capacity_factor,
       ROUND(o.ebitda_margin_pct, 1)                                      AS ebitda_margin_pct,
       ROUND(o.roi_pct, 2)                                                AS roi_pct
FROM ops o
JOIN capex c ON c.project_type = o.project_type
ORDER BY roi_pct DESC;

-- Q07. Fiscal-year P&L: is profitability improving or eroding?
SELECT
    fiscal_year,
    COUNT(DISTINCT project_id)                                            AS operating_projects,
    ROUND(SUM(revenue_inr) / 1e7, 1)                                      AS revenue_cr,
    ROUND(SUM(operating_cost_inr) / 1e7, 1)                               AS operating_cost_cr,
    ROUND(SUM(maintenance_cost_inr) / 1e7, 1)                             AS maintenance_cr,
    ROUND(SUM(ebitda_inr) / 1e7, 1)                                       AS ebitda_cr,
    ROUND(SUM(depreciation_inr) / 1e7, 1)                                 AS depreciation_cr,
    ROUND(SUM(ebit_inr) / 1e7, 1)                                         AS ebit_cr,
    ROUND(100 * SUM(ebitda_inr) / SUM(revenue_inr), 2)                    AS ebitda_margin_pct,
    ROUND(100 * SUM(ebit_inr) / (SUM(investment_amount_inr) / 12), 2)     AS roi_pct
FROM vw_project_month
GROUP BY fiscal_year
ORDER BY fiscal_year;

-- Q08. Investment efficiency: what does each rupee of capex buy, and why does ROI differ?
--      ROI decomposes into tariff x yield / capex, minus costs. This shows which lever drives it.
SELECT
    project_code, project_name, project_type, region,
    capex_cr_per_mw, ppa_tariff_inr_per_kwh, capacity_factor,
    revenue_yield_pct, mwh_per_cr_invested_yr, ebitda_margin_pct, roi_pct, simple_payback_years,
    RANK() OVER (ORDER BY revenue_yield_pct DESC)                         AS efficiency_rank
FROM vw_project_performance
ORDER BY efficiency_rank;

-- Q09. Capacity utilisation and availability.
--      CUF (India's term for capacity factor) mixes weather and operations;
--      availability isolates operations (time the plant was able to run).
SELECT
    region, project_type,
    COUNT(DISTINCT project_id)                                            AS projects,
    ROUND(100 * SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month), 2) AS cuf_pct,
    ROUND(100 * (1 - SUM(downtime_hours) / SUM(CASE WHEN downtime_hours IS NOT NULL
                                                    THEN hours_in_month / 2 END)), 2) AS availability_pct,
    ROUND(SUM(downtime_hours) / COUNT(downtime_hours), 1)                 AS avg_downtime_h_per_month
FROM vw_project_month
GROUP BY region, project_type
ORDER BY availability_pct;

-- Q10. CO2 avoided: impact in absolute terms and per rupee invested.
SELECT
    region,
    ROUND(SUM(co2_avoided_tonnes) / 1000, 1)                              AS co2_avoided_kt,
    ROUND(100 * SUM(co2_avoided_tonnes) / SUM(SUM(co2_avoided_tonnes)) OVER (), 1) AS share_pct,
    ROUND(SUM(co2_avoided_tonnes) * 12 / SUM(capacity_mw), 0)             AS co2_t_per_mw_yr,
    ROUND(SUM(co2_avoided_tonnes) / (SUM(investment_amount_inr) / 12 / 1e7), 1) AS co2_t_per_cr_capital_yr,
    -- households: average over months, never summed across months
    ROUND(SUM(equivalent_households) / COUNT(DISTINCT month_start_date), 0) AS avg_equivalent_households
FROM vw_project_month
GROUP BY region
ORDER BY co2_t_per_cr_capital_yr DESC;

-- Q11. Year-over-year growth: reported vs LIKE-FOR-LIKE.
--      Reported growth mixes new projects with real performance change.
--      Like-for-like keeps only projects that operated all 12 months of both years.
WITH fy AS (
    SELECT project_id, fiscal_year, COUNT(*) AS months, SUM(energy_generated_mwh) AS energy_mwh,
           SUM(revenue_inr) AS revenue_inr
    FROM vw_project_month
    GROUP BY project_id, fiscal_year
),
pairs AS (
    SELECT cur.fiscal_year,
           prev.fiscal_year                                    AS prior_year,
           cur.energy_mwh, prev.energy_mwh                     AS prior_energy_mwh,
           cur.months = 12 AND prev.months = 12                AS is_like_for_like
    FROM fy cur
    JOIN fy prev ON prev.project_id = cur.project_id
                AND CAST(RIGHT(prev.fiscal_year, 2) AS UNSIGNED) + 1 = CAST(RIGHT(cur.fiscal_year, 2) AS UNSIGNED)
),
reported AS (
    SELECT fiscal_year, SUM(energy_mwh) AS energy_mwh,
           LAG(SUM(energy_mwh)) OVER (ORDER BY fiscal_year) AS prior_energy_mwh
    FROM fy GROUP BY fiscal_year
)
SELECT r.fiscal_year,
       ROUND(r.energy_mwh / 1000, 1)                                      AS energy_gwh,
       ROUND(100 * (r.energy_mwh / r.prior_energy_mwh - 1), 2)            AS reported_yoy_pct,
       l.lfl_projects,
       ROUND(100 * (l.energy / l.prior_energy - 1), 2)                    AS like_for_like_yoy_pct
FROM reported r
LEFT JOIN (SELECT fiscal_year, COUNT(*) AS lfl_projects,
                  SUM(energy_mwh) AS energy, SUM(prior_energy_mwh) AS prior_energy
           FROM pairs WHERE is_like_for_like GROUP BY fiscal_year) l
       ON l.fiscal_year = r.fiscal_year
ORDER BY r.fiscal_year;

-- Q12. Monthly trend: generation with MoM, YoY and rolling 3-month total.
SELECT month_start_date, operating_projects, energy_mwh, capacity_factor,
       energy_mom_pct, energy_yoy_pct, energy_rolling_3m_mwh, energy_fytd_mwh
FROM vw_portfolio_monthly
ORDER BY month_start_date;

-- Q13. Top 10 projects by ROI, plus the best project in every region.
SELECT 'Top 10 overall' AS list_name, project_code, project_name, region, project_type, roi_pct,
       RANK() OVER (ORDER BY roi_pct DESC) AS position
FROM vw_project_performance
ORDER BY roi_pct DESC
LIMIT 10;

SELECT region, project_code, project_name, project_type, roi_pct
FROM (
    SELECT p.*, ROW_NUMBER() OVER (PARTITION BY region ORDER BY roi_pct DESC) AS rn
    FROM vw_project_performance p
) x
WHERE rn = 1
ORDER BY roi_pct DESC;

-- Q14. Underperforming projects, each with a probable root cause.
--      * PR (weather-normalised) vs peers of the same technology: raw CF
--        would punish cloudy regions for their weather.
--      * Peer z-scores only when the peer group has >= 5 projects; with 2
--        floating plants a z-score is always +/-1 and means nothing.
--      * Capex is judged against a market benchmark, not against peers.
WITH peer AS (
    SELECT p.*,
           COUNT(*)                          OVER (PARTITION BY project_type) AS peer_n,
           AVG(performance_ratio_ghi)        OVER (PARTITION BY project_type) AS peer_pr_mean,
           STDDEV_POP(performance_ratio_ghi) OVER (PARTITION BY project_type) AS peer_pr_sd,
           AVG(maintenance_lakh_per_mw_yr)        OVER (PARTITION BY project_type) AS peer_maint_mean,
           STDDEV_POP(maintenance_lakh_per_mw_yr) OVER (PARTITION BY project_type) AS peer_maint_sd,
           NTILE(4) OVER (ORDER BY roi_pct)                                AS roi_quartile
    FROM vw_project_performance p
),
scored AS (
    SELECT peer.*,
           IF(peer_n >= 5, (performance_ratio_ghi - peer_pr_mean) / peer_pr_sd, NULL)            AS pr_z,
           IF(peer_n >= 5, (maintenance_lakh_per_mw_yr - peer_maint_mean) / peer_maint_sd, NULL) AS maint_z,
           capex_cr_per_mw / b.benchmark_cr_per_mw                                               AS capex_vs_benchmark
    FROM peer
    JOIN ref_capex_benchmark b ON b.project_type = peer.project_type
)
SELECT project_code, project_name, project_type, region,
       performance_ratio_ghi, ROUND(pr_z, 2) AS pr_z, availability,
       maintenance_lakh_per_mw_yr, ROUND(maint_z, 2) AS maint_z,
       capex_cr_per_mw, ROUND(capex_vs_benchmark, 2) AS capex_vs_benchmark,
       roi_pct, roi_quartile,
       CONCAT_WS(', ',
           IF(pr_z < -1.5,               'low PR vs peers (performance)', NULL),
           IF(availability < 0.95,       'availability < 95% (reliability)', NULL),
           IF(maint_z > 1.5,             'high O&M vs peers (cost)', NULL),
           IF(capex_vs_benchmark > 1.15, 'capex > 115% of benchmark (capital)', NULL),
           IF(roi_quartile = 1,          'bottom ROI quartile', NULL))      AS flags
FROM scored
WHERE pr_z < -1.5
   OR availability < 0.95
   OR maint_z > 1.5
   OR capex_vs_benchmark > 1.15
   OR roi_quartile = 1
ORDER BY roi_pct;

-- Q15. Deterioration: whose weather-normalised performance fell between FY24 and FY26?
--      A falling PR with normal downtime suggests soiling, degradation or curtailment.
WITH fy_pr AS (
    SELECT project_id, project_code, project_name, region, fiscal_year,
           SUM(CASE WHEN irradiation_kwh_m2 IS NOT NULL THEN energy_generated_mwh END)
             / SUM(capacity_mw * irradiation_kwh_m2)                      AS pr,
           AVG(downtime_hours)                                            AS avg_downtime_h,
           COUNT(*)                                                       AS months
    FROM vw_project_month
    GROUP BY project_id, project_code, project_name, region, fiscal_year
)
SELECT a.project_code, a.project_name, a.region,
       ROUND(a.pr, 4) AS pr_fy24, ROUND(c.pr, 4) AS pr_fy26,
       ROUND(100 * (c.pr / a.pr - 1), 2)                                  AS pr_change_pct,
       ROUND(a.avg_downtime_h, 1) AS downtime_fy24, ROUND(c.avg_downtime_h, 1) AS downtime_fy26
FROM fy_pr a
JOIN fy_pr c ON c.project_id = a.project_id
WHERE a.fiscal_year = 'FY2023-24' AND c.fiscal_year = 'FY2025-26'
  AND a.months = 12 AND c.months = 12
ORDER BY pr_change_pct
LIMIT 10;

-- Q16. Regional ranking on several criteria (PERCENT_RANK: 1 = best).
SELECT region,
       ROUND(PERCENT_RANK() OVER (ORDER BY roi_pct), 2)                   AS roi_pctile,
       ROUND(PERCENT_RANK() OVER (ORDER BY capacity_factor), 2)           AS cf_pctile,
       ROUND(PERCENT_RANK() OVER (ORDER BY performance_ratio_ghi), 2)     AS pr_pctile,
       ROUND(PERCENT_RANK() OVER (ORDER BY ebitda_margin_pct), 2)         AS margin_pctile,
       roi_pct, capacity_factor, performance_ratio_ghi, ebitda_margin_pct
FROM vw_region_performance
ORDER BY roi_pct DESC;

-- Q17. Pareto: how few projects produce 80% of revenue? (running share)
WITH ranked AS (
    SELECT project_code, project_name, project_type, revenue_cr,
           ROW_NUMBER() OVER (ORDER BY revenue_cr DESC)                   AS rn,
           SUM(revenue_cr) OVER (ORDER BY revenue_cr DESC ROWS UNBOUNDED PRECEDING)
             / SUM(revenue_cr) OVER ()                                    AS cum_share,
           COUNT(*) OVER ()                                               AS n
    FROM vw_project_performance
)
SELECT MIN(rn) AS projects_for_80pct_revenue, MAX(n) AS total_projects,
       ROUND(100 * MIN(rn) / MAX(n), 1) AS pct_of_projects
FROM ranked
WHERE cum_share >= 0.80;

-- Q18. Seasonality: capacity factor by fiscal month and region (monsoon effect).
SELECT region,
       ROUND(100 * SUM(IF(fiscal_month_no IN (1, 2, 3),   energy_generated_mwh, 0))
                 / SUM(IF(fiscal_month_no IN (1, 2, 3),   capacity_mw * hours_in_month, 0)), 1) AS cf_q1_apr_jun,
       ROUND(100 * SUM(IF(fiscal_month_no IN (4, 5, 6),   energy_generated_mwh, 0))
                 / SUM(IF(fiscal_month_no IN (4, 5, 6),   capacity_mw * hours_in_month, 0)), 1) AS cf_q2_jul_sep,
       ROUND(100 * SUM(IF(fiscal_month_no IN (7, 8, 9),   energy_generated_mwh, 0))
                 / SUM(IF(fiscal_month_no IN (7, 8, 9),   capacity_mw * hours_in_month, 0)), 1) AS cf_q3_oct_dec,
       ROUND(100 * SUM(IF(fiscal_month_no IN (10, 11, 12), energy_generated_mwh, 0))
                 / SUM(IF(fiscal_month_no IN (10, 11, 12), capacity_mw * hours_in_month, 0)), 1) AS cf_q4_jan_mar
FROM vw_project_month
GROUP BY region
ORDER BY region;

-- Q19. Data lineage: how much of each KPI rests on repaired data?
SELECT
    SUM(data_source = 'BILLING_RECONSTRUCTED')                            AS reconstructed_energy_months,
    ROUND(100 * SUM(data_source = 'BILLING_RECONSTRUCTED') / COUNT(*), 2) AS reconstructed_pct,
    SUM(maintenance_imputed)                                              AS imputed_cost_months,
    SUM(irradiation_kwh_m2 IS NULL)                                       AS months_without_weather,
    COUNT(*)                                                              AS project_months
FROM vw_project_month;
