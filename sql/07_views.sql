-- =====================================================================
-- 07_views.sql
-- Analytical views: the single definition of every KPI.
-- Power BI imports vw_dim_project + the fact tables; Python and the
-- ad-hoc queries in 08 read the aggregated views.
--
-- KPI rules applied everywhere (the classic mistakes they avoid):
--  * Ratios are ratios of sums, never averages of ratios.
--    Capacity factor = SUM(MWh) / SUM(MW x hours)  -- capacity-weighted
--    AVG(capacity_factor) would weight a 0.5 MW rooftop like a 300 MW park.
--  * ROI is time-weighted: SUM(EBIT) / SUM(capex x months operated / 12).
--    Each fact row is one operating month, so SUM(capex)/12 over fact rows
--    = capital-years employed. A project commissioned mid-window is not
--    charged for capital it had not yet deployed.
--  * Annualised = value x 12 / operating months.
-- =====================================================================

USE solar_analytics;

-- ---------------------------------------------------------------------
-- vw_dim_project: dim_project + dim_location flattened.
-- This is the single "Project" dimension of the Power BI star schema.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_dim_project AS
SELECT
    p.project_id,
    p.project_code,
    p.project_name,
    p.project_type,
    p.project_status,
    p.installation_date,
    CASE
        WHEN p.project_status = 'Under Construction'      THEN 'Pipeline'
        WHEN p.installation_date >= '2023-04-01'          THEN 'Commissioned FY24-FY26'
        ELSE 'Pre-FY24 fleet'
    END                                                      AS vintage,
    p.capacity_mw,
    CASE
        WHEN p.capacity_mw < 5    THEN '1: < 5 MW'
        WHEN p.capacity_mw < 50   THEN '2: 5-50 MW'
        WHEN p.capacity_mw < 150  THEN '3: 50-150 MW'
        ELSE '4: >= 150 MW'
    END                                                      AS capacity_band,
    p.investment_amount_inr,
    ROUND(p.investment_amount_inr / 1e7, 2)                  AS investment_cr,
    ROUND(p.investment_amount_inr / 1e7 / p.capacity_mw, 3)  AS capex_cr_per_mw,
    p.ppa_tariff_inr_per_kwh,
    l.location_id,
    l.location_code,
    l.country,
    l.region,
    l.state,
    l.city,
    l.latitude,
    l.longitude,
    l.annual_ghi_kwh_m2_day,
    l.solar_zone
FROM dim_project p
JOIN dim_location l ON l.location_id = p.location_id;

-- ---------------------------------------------------------------------
-- vw_project_month: one row per project-month, all three facts joined
-- (1:1:1 on the same composite key, so the join cannot fan out).
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_project_month AS
SELECT
    d.project_id, d.project_code, d.project_name, d.project_type, d.vintage,
    d.region, d.state, d.city, d.solar_zone,
    d.capacity_mw, d.investment_amount_inr, d.ppa_tariff_inr_per_kwh,
    e.month_start_date,
    dt.fiscal_year,
    dt.fiscal_quarter,
    dt.fiscal_month_no,
    DAY(LAST_DAY(e.month_start_date)) * 24                    AS hours_in_month,
    e.energy_generated_mwh,
    e.capacity_factor,
    e.irradiation_kwh_m2,
    e.avg_temperature_c,
    e.cloud_cover_pct,
    e.downtime_hours,
    e.data_source,
    -- Specific yield (kWh per kWp) and performance ratio on GHI (IEC 61724 style):
    -- PR = (E / P_rated) / H. Weather-normalised: separates weather from operations.
    ROUND(e.energy_generated_mwh / d.capacity_mw, 2)          AS specific_yield_kwh_kwp,
    ROUND(e.energy_generated_mwh / (d.capacity_mw * e.irradiation_kwh_m2), 4)
                                                              AS performance_ratio_ghi,
    ROUND(1 - e.downtime_hours / (DAY(LAST_DAY(e.month_start_date)) * 12), 4)
                                                              AS availability,
    f.revenue_inr,
    f.operating_cost_inr,
    f.maintenance_cost_inr,
    f.depreciation_inr,
    f.ebitda_inr,
    f.profit_inr                                              AS ebit_inr,
    f.maintenance_imputed,
    s.co2_avoided_tonnes,
    s.equivalent_households,
    s.site_consumption_mwh,
    s.renewable_energy_pct
FROM fact_energy_generation e
JOIN fact_financials f       ON f.project_id = e.project_id AND f.month_start_date = e.month_start_date
JOIN fact_sustainability s   ON s.project_id = e.project_id AND s.month_start_date = e.month_start_date
JOIN vw_dim_project d        ON d.project_id = e.project_id
JOIN dim_date dt             ON dt.calendar_date = e.month_start_date;

-- ---------------------------------------------------------------------
-- vw_project_performance: whole-window KPIs per operating project
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_project_performance AS
SELECT
    project_id, project_code, project_name, project_type, vintage,
    region, state, city, solar_zone,
    capacity_mw,
    ROUND(investment_amount_inr / 1e7, 2)                             AS investment_cr,
    ROUND(investment_amount_inr / 1e7 / capacity_mw, 3)               AS capex_cr_per_mw,
    ppa_tariff_inr_per_kwh,
    COUNT(*)                                                          AS operating_months,
    ROUND(SUM(energy_generated_mwh), 1)                               AS energy_mwh,
    ROUND(SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month), 4)
                                                                      AS capacity_factor,
    ROUND(SUM(CASE WHEN irradiation_kwh_m2 IS NOT NULL THEN energy_generated_mwh END)
          / SUM(capacity_mw * irradiation_kwh_m2), 4)                 AS performance_ratio_ghi,
    ROUND(1 - SUM(downtime_hours) / SUM(CASE WHEN downtime_hours IS NOT NULL
                                             THEN hours_in_month / 2 END), 4)
                                                                      AS availability,
    ROUND(SUM(downtime_hours) / COUNT(downtime_hours), 1)             AS avg_downtime_hours,
    ROUND(SUM(revenue_inr) / 1e7, 3)                                  AS revenue_cr,
    ROUND(SUM(operating_cost_inr) / 1e7, 3)                           AS operating_cost_cr,
    ROUND(SUM(maintenance_cost_inr) / 1e7, 3)                         AS maintenance_cost_cr,
    ROUND(SUM(ebitda_inr) / 1e7, 3)                                   AS ebitda_cr,
    ROUND(SUM(ebit_inr) / 1e7, 3)                                     AS ebit_cr,
    ROUND(100 * SUM(ebitda_inr) / NULLIF(SUM(revenue_inr), 0), 2)     AS ebitda_margin_pct,
    -- time-weighted returns on capital
    ROUND(100 * SUM(ebit_inr)   / (SUM(investment_amount_inr) / 12), 2) AS roi_pct,
    ROUND(100 * SUM(ebitda_inr) / (SUM(investment_amount_inr) / 12), 2) AS ebitda_yield_pct,
    ROUND(100 * SUM(revenue_inr) / (SUM(investment_amount_inr) / 12), 2) AS revenue_yield_pct,
    ROUND(investment_amount_inr / (SUM(ebitda_inr) * 12 / COUNT(*)), 1) AS simple_payback_years,
    -- intensity metrics, annualised
    ROUND(SUM(revenue_inr) * 12 / COUNT(*) / capacity_mw / 1e5, 2)    AS revenue_lakh_per_mw_yr,
    ROUND(SUM(maintenance_cost_inr) * 12 / COUNT(*) / capacity_mw / 1e5, 2)
                                                                      AS maintenance_lakh_per_mw_yr,
    ROUND(SUM(energy_generated_mwh) * 12 / COUNT(*) / (investment_amount_inr / 1e7), 1)
                                                                      AS mwh_per_cr_invested_yr,
    ROUND(SUM(co2_avoided_tonnes), 1)                                 AS co2_avoided_t,
    ROUND(SUM(co2_avoided_tonnes) * 12 / COUNT(*) / capacity_mw, 1)   AS co2_t_per_mw_yr,
    ROUND(SUM(co2_avoided_tonnes) * 12 / COUNT(*) / (investment_amount_inr / 1e7), 1)
                                                                      AS co2_t_per_cr_invested_yr,
    -- renewable share for captive projects: solar used on site / site demand
    ROUND(100 * SUM(renewable_energy_pct * site_consumption_mwh / 100)
          / NULLIF(SUM(CASE WHEN renewable_energy_pct IS NOT NULL THEN site_consumption_mwh END), 0), 2)
                                                                      AS renewable_share_pct,
    SUM(data_source = 'BILLING_RECONSTRUCTED')                        AS reconstructed_months,
    SUM(maintenance_imputed)                                          AS imputed_cost_months
FROM vw_project_month
GROUP BY project_id, project_code, project_name, project_type, vintage, region, state, city,
         solar_zone, capacity_mw, investment_amount_inr, ppa_tariff_inr_per_kwh;

-- ---------------------------------------------------------------------
-- vw_region_performance: same definitions at region grain, plus ranks.
-- Two rankings side by side show whether volume and return agree.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_region_performance AS
WITH r AS (
    SELECT
        region,
        COUNT(DISTINCT project_id)                                    AS operating_projects,
        ROUND(SUM(energy_generated_mwh) / 1000, 1)                    AS energy_gwh,
        ROUND(SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month), 4) AS capacity_factor,
        ROUND(SUM(CASE WHEN irradiation_kwh_m2 IS NOT NULL THEN energy_generated_mwh END)
              / SUM(capacity_mw * irradiation_kwh_m2), 4)             AS performance_ratio_ghi,
        ROUND(SUM(revenue_inr) / 1e7, 2)                              AS revenue_cr,
        ROUND(SUM(ebit_inr) / 1e7, 2)                                 AS ebit_cr,
        ROUND(100 * SUM(ebit_inr)   / (SUM(investment_amount_inr) / 12), 2) AS roi_pct,
        ROUND(100 * SUM(ebitda_inr) / (SUM(investment_amount_inr) / 12), 2) AS ebitda_yield_pct,
        ROUND(100 * SUM(ebitda_inr) / SUM(revenue_inr), 2)            AS ebitda_margin_pct,
        -- realised tariff = revenue / energy (INR per kWh), i.e. energy-weighted
        ROUND(SUM(revenue_inr) / (SUM(energy_generated_mwh) * 1000), 2) AS realised_tariff_inr_kwh,
        ROUND(SUM(co2_avoided_tonnes) / 1000, 1)                      AS co2_avoided_kt
    FROM vw_project_month
    GROUP BY region
)
SELECT
    r.*,
    ROUND(100 * r.energy_gwh / SUM(r.energy_gwh) OVER (), 1)          AS energy_share_pct,
    RANK() OVER (ORDER BY r.energy_gwh DESC)                          AS energy_rank,
    RANK() OVER (ORDER BY r.roi_pct DESC)                             AS roi_rank,
    RANK() OVER (ORDER BY r.capacity_factor DESC)                     AS cf_rank
FROM r;

-- ---------------------------------------------------------------------
-- vw_portfolio_monthly: portfolio trend with MoM, YoY and rolling window
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_portfolio_monthly AS
WITH m AS (
    SELECT
        month_start_date,
        fiscal_year,
        COUNT(*)                                       AS operating_projects,
        SUM(capacity_mw)                               AS operating_capacity_mw,
        SUM(energy_generated_mwh)                      AS energy_mwh,
        SUM(energy_generated_mwh) / SUM(capacity_mw * hours_in_month) AS capacity_factor,
        SUM(revenue_inr)                               AS revenue_inr,
        SUM(ebit_inr)                                  AS ebit_inr,
        SUM(co2_avoided_tonnes)                        AS co2_avoided_tonnes
    FROM vw_project_month
    GROUP BY month_start_date, fiscal_year
)
SELECT
    month_start_date,
    fiscal_year,
    operating_projects,
    ROUND(operating_capacity_mw, 1)                                   AS operating_capacity_mw,
    ROUND(energy_mwh, 1)                                              AS energy_mwh,
    ROUND(capacity_factor, 4)                                         AS capacity_factor,
    ROUND(revenue_inr / 1e7, 3)                                       AS revenue_cr,
    ROUND(ebit_inr / 1e7, 3)                                          AS ebit_cr,
    ROUND(co2_avoided_tonnes, 1)                                      AS co2_avoided_tonnes,
    ROUND(100 * (energy_mwh / LAG(energy_mwh) OVER w - 1), 2)         AS energy_mom_pct,
    ROUND(100 * (energy_mwh / LAG(energy_mwh, 12) OVER w - 1), 2)     AS energy_yoy_pct,
    ROUND(SUM(energy_mwh) OVER (w ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1)
                                                                      AS energy_rolling_3m_mwh,
    ROUND(SUM(energy_mwh) OVER (w ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 1)
                                                                      AS energy_rolling_12m_mwh,
    ROUND(SUM(energy_mwh) OVER (PARTITION BY fiscal_year ORDER BY month_start_date), 1)
                                                                      AS energy_fytd_mwh
FROM m
WINDOW w AS (ORDER BY month_start_date);

-- ---------------------------------------------------------------------
-- vw_dq_summary: data-quality scorecard (for a DQ page / appendix)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_dq_summary AS
SELECT source_table, check_name, action_taken, COUNT(*) AS issues
FROM dq_issue_log
GROUP BY source_table, check_name, action_taken;
