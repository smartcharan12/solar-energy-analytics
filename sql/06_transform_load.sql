-- =====================================================================
-- 06_transform_load.sql
-- Apply the rules logged in 05 and load the star schema.
-- Load order follows foreign keys: dim_location -> dim_project ->
-- fact_financials -> fact_energy_generation -> fact_sustainability.
-- Every INSERT reads wrk_* tables built in 05; staging is never edited
-- in place, so the raw evidence for every fix stays queryable.
-- =====================================================================

USE solar_analytics;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE fact_sustainability;
TRUNCATE TABLE fact_energy_generation;
TRUNCATE TABLE fact_financials;
TRUNCATE TABLE dim_project;
TRUNCATE TABLE dim_location;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- 1. dim_location: first occurrence of each code, standardised text
-- ---------------------------------------------------------------------
INSERT INTO dim_location (location_code, country, state, region, city, latitude, longitude,
                          annual_ghi_kwh_m2_day, solar_zone)
SELECT location_code, country, state, region, city, latitude, longitude,
       annual_ghi_kwh_m2_day, solar_zone
FROM wrk_locations
WHERE dup_rank = 1
  AND latitude IS NOT NULL AND longitude IS NOT NULL
ORDER BY location_code;

-- ---------------------------------------------------------------------
-- 2. dim_project: latest version, valid code, sign-corrected capex
--    (negative capex only reaches here if 05 logged it as FIXED)
-- ---------------------------------------------------------------------
INSERT INTO dim_project (project_code, project_name, location_id, project_type, installation_date,
                         capacity_mw, investment_amount_inr, ppa_tariff_inr_per_kwh,
                         project_status, source_updated_at)
SELECT p.project_code, p.project_name, l.location_id, p.project_type, p.installation_date,
       p.capacity_mw, ABS(p.investment_raw_inr), p.tariff_inr_per_kwh,
       p.project_status, p.record_updated_at
FROM wrk_projects_clean p
JOIN dim_location l ON l.location_code = p.location_code
WHERE p.investment_raw_inr > 0
   OR p.project_code IN (SELECT record_key FROM dq_issue_log
                         WHERE check_name = 'negative_investment' AND action_taken = 'FIXED')
ORDER BY p.project_code;

-- ---------------------------------------------------------------------
-- 3. fact_financials: deduplicated, sign-corrected, median-imputed
-- ---------------------------------------------------------------------
INSERT INTO fact_financials (project_id, month_start_date, revenue_inr, operating_cost_inr,
                             maintenance_cost_inr, depreciation_inr, maintenance_imputed)
SELECT d.project_id,
       f.month_start_date,
       f.revenue_inr,
       ABS(f.operating_cost_inr),
       COALESCE(f.maintenance_cost_inr, m.median_maintenance_inr),
       f.depreciation_inr,
       f.maintenance_cost_inr IS NULL
FROM wrk_financials_checked f
JOIN dim_project d ON d.project_code = f.project_code
LEFT JOIN wrk_maintenance_median m ON m.project_code = f.project_code
WHERE NOT f.is_orphan AND NOT f.is_duplicate AND NOT f.is_invalid_date;

-- ---------------------------------------------------------------------
-- 4. fact_energy_generation
--    Rule: the billing meter is the system of record for energy.
--      * SCADA value accepted when within 2% of billing (sign corrected)
--      * NULL, implausible (CF > 35%) or mismatching values are replaced
--        by billing energy and marked BILLING_RECONSTRUCTED
--      * capacity factor is ALWAYS recomputed from clean energy, which
--        fixes the "CF stored as percent" defect by construction
-- ---------------------------------------------------------------------
INSERT INTO fact_energy_generation (project_id, month_start_date, energy_generated_mwh, capacity_factor,
                                    irradiation_kwh_m2, avg_temperature_c, cloud_cover_pct,
                                    downtime_hours, data_source)
SELECT project_id, month_start_date, energy_mwh,
       ROUND(energy_mwh / (capacity_mw * hours_in_month), 4),
       irradiation_kwh_m2, avg_temperature_c, cloud_cover_pct, downtime_hours, data_source
FROM (
    SELECT d.project_id,
           e.month_start_date,
           e.capacity_mw,
           e.hours_in_month,
           CASE WHEN e.is_energy_null OR e.is_implausible_energy OR e.is_billing_mismatch
                THEN e.billing_energy_mwh
                ELSE ROUND(ABS(e.energy_mwh), 3)
           END                                                     AS energy_mwh,
           e.irradiation_kwh_m2, e.avg_temperature_c, e.cloud_cover_pct, e.downtime_hours,
           IF(e.is_energy_null OR e.is_implausible_energy OR e.is_billing_mismatch,
              'BILLING_RECONSTRUCTED', 'SCADA')                    AS data_source
    FROM wrk_energy_checked e
    JOIN dim_project d ON d.project_code = e.project_code
    WHERE NOT e.is_orphan AND NOT e.is_duplicate AND NOT e.is_invalid_date
      AND NOT e.is_before_cod AND NOT e.is_not_month_grain
      AND e.billing_energy_mwh IS NOT NULL
) x;

-- 4b. Months billed but with no usable SCADA row (e.g. the quarantined
--     invalid-date rows): rebuild energy from billing. Weather and
--     downtime stay NULL; they are never invented.
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'missing_scada_month', 'fact_energy_generation',
       CONCAT(p.project_code, '|', f.month_start_date),
       CONCAT('Energy rebuilt from billing: ', ROUND(f.revenue_inr / (p.ppa_tariff_inr_per_kwh * 1000), 3), ' MWh'),
       'RECONSTRUCTED'
FROM fact_financials f
JOIN dim_project p ON p.project_id = f.project_id
LEFT JOIN fact_energy_generation e
       ON e.project_id = f.project_id AND e.month_start_date = f.month_start_date
WHERE e.project_id IS NULL;

INSERT INTO fact_energy_generation (project_id, month_start_date, energy_generated_mwh, capacity_factor,
                                    irradiation_kwh_m2, avg_temperature_c, cloud_cover_pct,
                                    downtime_hours, data_source)
SELECT f.project_id,
       f.month_start_date,
       ROUND(f.revenue_inr / (p.ppa_tariff_inr_per_kwh * 1000), 3),
       ROUND(f.revenue_inr / (p.ppa_tariff_inr_per_kwh * 1000)
             / (p.capacity_mw * DAY(LAST_DAY(f.month_start_date)) * 24), 4),
       NULL, NULL, NULL, NULL,
       'BILLING_RECONSTRUCTED'
FROM fact_financials f
JOIN dim_project p ON p.project_id = f.project_id
LEFT JOIN fact_energy_generation e
       ON e.project_id = f.project_id AND e.month_start_date = f.month_start_date
WHERE e.project_id IS NULL;

-- ---------------------------------------------------------------------
-- 5. fact_sustainability (derived)
--    co2      = MWh x grid emission factor of that fiscal year
--    homes    = MWh / household MWh per month   (non-additive over time)
--    RE share = min(solar, site demand) / site demand, captive projects only
--               (assumes solar is consumed on site first; surplus exported)
-- ---------------------------------------------------------------------
INSERT INTO fact_sustainability (project_id, month_start_date, energy_generated_mwh, grid_ef_tco2_per_mwh,
                                 co2_avoided_tonnes, equivalent_households,
                                 site_consumption_mwh, renewable_energy_pct)
SELECT e.project_id,
       e.month_start_date,
       e.energy_generated_mwh,
       ef.grid_ef_tco2_per_mwh,
       ROUND(e.energy_generated_mwh * ef.grid_ef_tco2_per_mwh, 3),
       ROUND(e.energy_generated_mwh / hh.assumption_value, 1),
       c.site_consumption_mwh,
       CASE WHEN p.project_type IN ('C&I Open Access', 'Rooftop') AND c.site_consumption_mwh > 0
            THEN ROUND(100 * LEAST(e.energy_generated_mwh, c.site_consumption_mwh) / c.site_consumption_mwh, 2)
       END
FROM fact_energy_generation e
JOIN dim_project p          ON p.project_id = e.project_id
JOIN dim_date dt            ON dt.calendar_date = e.month_start_date
JOIN ref_emission_factor ef ON ef.fiscal_year_end = dt.fiscal_year_end
JOIN ref_assumption hh      ON hh.assumption_key = 'household_mwh_per_month'
LEFT JOIN wrk_consumption c
       ON c.project_code = p.project_code
      AND c.month_start_date = e.month_start_date
      AND c.dup_rank = 1;

-- ---------------------------------------------------------------------
-- 6. Post-load validation. Every check below must return 0 (or the
--    stated expectation); python/validate_pipeline.py asserts them.
-- ---------------------------------------------------------------------
SELECT 'dim_location'           AS table_name, COUNT(*) AS row_count FROM dim_location
UNION ALL SELECT 'dim_project',             COUNT(*) FROM dim_project
UNION ALL SELECT 'fact_energy_generation',  COUNT(*) FROM fact_energy_generation
UNION ALL SELECT 'fact_financials',         COUNT(*) FROM fact_financials
UNION ALL SELECT 'fact_sustainability',     COUNT(*) FROM fact_sustainability;

SELECT 'energy rows without financials' AS check_name, COUNT(*) AS failures
FROM fact_energy_generation e
LEFT JOIN fact_financials f USING (project_id, month_start_date)
WHERE f.project_id IS NULL
UNION ALL
SELECT 'financial rows without energy', COUNT(*)
FROM fact_financials f
LEFT JOIN fact_energy_generation e USING (project_id, month_start_date)
WHERE e.project_id IS NULL
UNION ALL
SELECT 'energy x tariff <> revenue (> INR 1)', COUNT(*)
FROM fact_energy_generation e
JOIN fact_financials f USING (project_id, month_start_date)
JOIN dim_project p USING (project_id)
WHERE ABS(e.energy_generated_mwh * p.ppa_tariff_inr_per_kwh * 1000 - f.revenue_inr) > 1
UNION ALL
SELECT 'capacity factor > 0.35', COUNT(*) FROM fact_energy_generation WHERE capacity_factor > 0.35
UNION ALL
SELECT 'depreciation <> capex / 300', COUNT(*)
FROM fact_financials f JOIN dim_project p USING (project_id)
WHERE ABS(f.depreciation_inr - p.investment_amount_inr / 300) > 1
UNION ALL
SELECT 'operational project with no facts', COUNT(*)
FROM dim_project p
WHERE p.project_status = 'Operational'
  AND NOT EXISTS (SELECT 1 FROM fact_energy_generation e WHERE e.project_id = p.project_id)
UNION ALL
SELECT 'under-construction project with facts', COUNT(*)
FROM dim_project p
WHERE p.project_status = 'Under Construction'
  AND EXISTS (SELECT 1 FROM fact_energy_generation e WHERE e.project_id = p.project_id);

SELECT data_source, COUNT(*) AS energy_rows
FROM fact_energy_generation
GROUP BY data_source;

-- Control totals (compared with data/ground_truth/expected_clean_totals.json)
SELECT
    (SELECT ROUND(SUM(energy_generated_mwh), 3) FROM fact_energy_generation) AS total_energy_mwh,
    (SELECT ROUND(SUM(revenue_inr), 2)          FROM fact_financials)        AS total_revenue_inr,
    (SELECT ROUND(SUM(operating_cost_inr), 2)   FROM fact_financials)        AS total_operating_cost_inr,
    (SELECT ROUND(SUM(maintenance_cost_inr), 2) FROM fact_financials)        AS total_maintenance_cost_inr,
    (SELECT ROUND(SUM(depreciation_inr), 2)     FROM fact_financials)        AS total_depreciation_inr,
    (SELECT SUM(investment_amount_inr)          FROM dim_project)            AS total_investment_inr,
    (SELECT SUM(capacity_mw)                    FROM dim_project)            AS total_capacity_mw;
