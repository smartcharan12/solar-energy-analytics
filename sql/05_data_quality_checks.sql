-- =====================================================================
-- 05_data_quality_checks.sql
-- Detect every data-quality issue in staging, decide the handling rule,
-- and write one audit row per defect to dq_issue_log.
-- 06_transform_load.sql then APPLIES the rules logged here.
--
-- Flow:  stg_* (text)  ->  wrk_* (typed + flags)  ->  dq_issue_log
--
-- Check precedence (a row is logged once, under its most severe issue):
--   1 orphan key  ->  2 exact duplicate  ->  3 invalid date  ->  4 value checks
-- =====================================================================

USE solar_analytics;

TRUNCATE TABLE dq_issue_log;

-- ---------------------------------------------------------------------
-- A. Reusable parsing functions
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_parse_date_strict;
DROP FUNCTION IF EXISTS fn_to_number;
DROP FUNCTION IF EXISTS fn_proper_case;

DELIMITER $$

-- Accepts YYYY-MM-DD or DD-MM-YYYY. Returns NULL for anything else,
-- INCLUDING calendar-impossible dates such as 2024-02-30.
-- Why not just STR_TO_DATE(...) IS NULL? In MySQL 8:
--   STR_TO_DATE('2024-02-30','%Y-%m-%d')  -> '2024-02-30' (invalid, no error)
--   STR_TO_DATE('01-10-2024','%Y-%m-%d')  -> '2001-10-20' (silent mis-parse)
-- Adding INTERVAL 0 DAY normalises an impossible date (-> 2024-03-01), so
-- a round trip that does not return the original text proves it invalid.
CREATE FUNCTION fn_parse_date_strict(p_text VARCHAR(30))
RETURNS DATE
DETERMINISTIC NO SQL
BEGIN
    DECLARE v_text VARCHAR(30) DEFAULT TRIM(p_text);

    IF v_text REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
       AND DATE_FORMAT(STR_TO_DATE(v_text, '%Y-%m-%d') + INTERVAL 0 DAY, '%Y-%m-%d') = v_text THEN
        RETURN STR_TO_DATE(v_text, '%Y-%m-%d');
    END IF;

    IF v_text REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$'
       AND DATE_FORMAT(STR_TO_DATE(v_text, '%d-%m-%Y') + INTERVAL 0 DAY, '%d-%m-%Y') = v_text THEN
        RETURN STR_TO_DATE(v_text, '%d-%m-%Y');
    END IF;

    RETURN NULL;
END$$

-- Text -> number, NULL when not numeric (instead of a strict-mode error
-- or MySQL's silent "leading digits" conversion of e.g. '12abc' -> 12).
CREATE FUNCTION fn_to_number(p_text VARCHAR(40))
RETURNS DECIMAL(20,6)
DETERMINISTIC NO SQL
BEGIN
    DECLARE v_text VARCHAR(40) DEFAULT TRIM(p_text);
    IF v_text REGEXP '^[-+]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][-+]?[0-9]+)?$' THEN
        RETURN CAST(v_text AS DOUBLE);
    END IF;
    RETURN NULL;
END$$

-- '  jodhpur ' -> 'Jodhpur', 'BENGALURU' -> 'Bengaluru'
CREATE FUNCTION fn_proper_case(p_text VARCHAR(100))
RETURNS VARCHAR(100)
DETERMINISTIC NO SQL
BEGIN
    DECLARE v_in     VARCHAR(100) DEFAULT LOWER(TRIM(p_text));
    DECLARE v_out    VARCHAR(100) DEFAULT '';
    DECLARE v_char   VARCHAR(1);
    DECLARE v_prev   VARCHAR(1) DEFAULT ' ';
    DECLARE i        INT DEFAULT 1;
    IF p_text IS NULL THEN
        RETURN NULL;
    END IF;
    WHILE i <= CHAR_LENGTH(v_in) DO
        SET v_char = SUBSTRING(v_in, i, 1);
        SET v_out  = CONCAT(v_out, IF(v_prev IN (' ', '-'), UPPER(v_char), v_char));
        SET v_prev = v_char;
        SET i = i + 1;
    END WHILE;
    RETURN v_out;
END$$

DELIMITER ;

-- ---------------------------------------------------------------------
-- B. Profiling: NULL counts per staging column (read before deciding rules)
-- ---------------------------------------------------------------------
SELECT 'stg_energy_generation' AS table_name,
       COUNT(*)                                   AS total_rows,
       SUM(project_code IS NULL)                  AS null_project,
       SUM(reading_month IS NULL)                 AS null_month,
       SUM(energy_generated_mwh IS NULL)          AS null_energy,
       SUM(capacity_factor IS NULL)               AS null_cf,
       SUM(irradiation_kwh_m2 IS NULL)            AS null_irradiation,
       SUM(cloud_cover_pct IS NULL)               AS null_cloud,
       SUM(downtime_hours IS NULL)                AS null_downtime
FROM stg_energy_generation;

SELECT 'stg_financials' AS table_name,
       COUNT(*)                                   AS total_rows,
       SUM(revenue_inr IS NULL)                   AS null_revenue,
       SUM(operating_cost_inr IS NULL)            AS null_opex,
       SUM(maintenance_cost_inr IS NULL)          AS null_maintenance,
       SUM(depreciation_inr IS NULL)              AS null_depreciation
FROM stg_financials;

-- ---------------------------------------------------------------------
-- C. Typed working tables
-- ---------------------------------------------------------------------

-- C1. Locations
DROP TABLE IF EXISTS wrk_locations;
CREATE TABLE wrk_locations AS
SELECT
    s.stg_row_id,
    UPPER(TRIM(s.location_code))                          AS location_code,
    TRIM(s.country)                                       AS country,
    COALESCE(sa.standard_value, TRIM(s.state))            AS state,
    TRIM(s.region)                                        AS region,
    COALESCE(ca.standard_value, fn_proper_case(s.city))   AS city,
    fn_to_number(s.latitude)                              AS latitude,
    fn_to_number(s.longitude)                             AS longitude,
    fn_to_number(s.annual_ghi_kwh_m2_day)                 AS annual_ghi_kwh_m2_day,
    TRIM(s.solar_zone)                                    AS solar_zone,
    s.state                                               AS raw_state,
    s.city                                                AS raw_city,
    ROW_NUMBER() OVER (PARTITION BY UPPER(TRIM(s.location_code)) ORDER BY s.stg_row_id) AS dup_rank
FROM stg_locations s
LEFT JOIN ref_text_alias sa ON sa.domain = 'state' AND sa.raw_value = UPPER(TRIM(s.state))
LEFT JOIN ref_text_alias ca ON ca.domain = 'city'  AND ca.raw_value = UPPER(TRIM(s.city));

-- C2. Projects (all versions; version_rank = 1 is the latest record)
DROP TABLE IF EXISTS wrk_projects;
CREATE TABLE wrk_projects AS
SELECT
    s.stg_row_id,
    UPPER(TRIM(s.project_code))                           AS project_code,
    TRIM(s.project_name)                                  AS project_name,
    -- 'l-19', 'L19', 'L019' -> 'L019'
    CASE WHEN UPPER(TRIM(s.location_code)) REGEXP '^L-?[0-9]{1,3}$'
         THEN CONCAT('L', LPAD(REGEXP_REPLACE(s.location_code, '[^0-9]', ''), 3, '0'))
    END                                                   AS location_code,
    s.location_code                                       AS raw_location_code,
    ta.standard_value                                     AS project_type,
    s.project_type                                        AS raw_project_type,
    fn_parse_date_strict(s.installation_date)             AS installation_date,
    fn_to_number(s.capacity_mw)                           AS capacity_mw,
    fn_to_number(s.investment_amount_inr)                 AS investment_raw_inr,
    fn_to_number(s.ppa_tariff_inr_per_kwh)                AS tariff_inr_per_kwh,
    TRIM(s.project_status)                                AS project_status,
    STR_TO_DATE(s.record_updated_at, '%Y-%m-%d %H:%i:%s') AS record_updated_at,
    ROW_NUMBER() OVER (PARTITION BY UPPER(TRIM(s.project_code))
                       ORDER BY STR_TO_DATE(s.record_updated_at, '%Y-%m-%d %H:%i:%s') DESC,
                                s.stg_row_id DESC)         AS version_rank
FROM stg_projects s
LEFT JOIN ref_text_alias ta
       ON ta.domain = 'project_type' AND ta.raw_value = UPPER(TRIM(s.project_type));

-- C3. The project master that facts are validated against:
--     latest version, well-formed code, location resolvable.
DROP TABLE IF EXISTS wrk_projects_clean;
CREATE TABLE wrk_projects_clean AS
SELECT p.*
FROM wrk_projects p
JOIN wrk_locations l ON l.location_code = p.location_code AND l.dup_rank = 1
WHERE p.version_rank = 1
  AND p.project_code REGEXP '^P[0-9]{3}$';

ALTER TABLE wrk_projects_clean ADD PRIMARY KEY (project_code);

-- C4. Financials (ERP) — built before energy because billing is the
--     reference used to verify and repair SCADA energy.
DROP TABLE IF EXISTS wrk_financials;
CREATE TABLE wrk_financials AS
SELECT
    s.stg_row_id,
    UPPER(TRIM(s.project_code))                           AS project_code,
    s.period_month                                        AS raw_month,
    fn_parse_date_strict(s.period_month)                  AS month_start_date,
    fn_to_number(s.revenue_inr)                           AS revenue_inr,
    fn_to_number(s.operating_cost_inr)                    AS operating_cost_inr,
    fn_to_number(s.maintenance_cost_inr)                  AS maintenance_cost_inr,
    fn_to_number(s.depreciation_inr)                      AS depreciation_inr,
    ROW_NUMBER() OVER (PARTITION BY s.project_code, s.period_month, s.revenue_inr, s.operating_cost_inr,
                                    s.maintenance_cost_inr, s.depreciation_inr
                       ORDER BY s.stg_row_id)              AS exact_dup_rank
FROM stg_financials s;

DROP TABLE IF EXISTS wrk_financials_checked;
CREATE TABLE wrk_financials_checked AS
SELECT
    f.*,
    p.project_code IS NULL                                AS is_orphan,
    f.month_start_date IS NULL                            AS is_invalid_date,
    f.exact_dup_rank > 1                                  AS is_duplicate,
    f.maintenance_cost_inr IS NULL                        AS is_maintenance_null,
    f.operating_cost_inr < 0                              AS is_opex_negative,
    f.revenue_inr < 0                                     AS is_revenue_negative,
    -- energy implied by the billing meter: revenue = MWh x tariff x 1000
    ROUND(f.revenue_inr / (p.tariff_inr_per_kwh * 1000), 3) AS billing_energy_mwh
FROM wrk_financials f
LEFT JOIN wrk_projects_clean p ON p.project_code = f.project_code;

-- Project median maintenance cost (MySQL has no MEDIAN(): window functions).
-- Median, not mean: one hail-repair month would inflate a mean.
DROP TABLE IF EXISTS wrk_maintenance_median;
CREATE TABLE wrk_maintenance_median AS
WITH ranked AS (
    SELECT project_code, maintenance_cost_inr,
           ROW_NUMBER() OVER (PARTITION BY project_code ORDER BY maintenance_cost_inr) AS rn,
           COUNT(*)     OVER (PARTITION BY project_code)                           AS n
    FROM wrk_financials_checked
    WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date
      AND maintenance_cost_inr IS NOT NULL
)
SELECT project_code, ROUND(AVG(maintenance_cost_inr), 2) AS median_maintenance_inr
FROM ranked
WHERE rn IN (FLOOR((n + 1) / 2), CEIL((n + 1) / 2))
GROUP BY project_code;

-- C5. Energy (SCADA)
DROP TABLE IF EXISTS wrk_energy;
CREATE TABLE wrk_energy AS
SELECT
    s.stg_row_id,
    UPPER(TRIM(s.project_code))                           AS project_code,
    s.reading_month                                       AS raw_month,
    fn_parse_date_strict(s.reading_month)                 AS month_start_date,
    s.reading_month REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$' AS is_alt_date_format,
    fn_to_number(s.energy_generated_mwh)                  AS energy_mwh,
    fn_to_number(s.capacity_factor)                       AS capacity_factor_raw,
    fn_to_number(s.irradiation_kwh_m2)                    AS irradiation_kwh_m2,
    fn_to_number(s.avg_temperature_c)                     AS avg_temperature_c,
    fn_to_number(s.cloud_cover_pct)                       AS cloud_cover_pct,
    fn_to_number(s.downtime_hours)                        AS downtime_hours,
    ROW_NUMBER() OVER (PARTITION BY s.project_code, s.reading_month, s.energy_generated_mwh,
                                    s.capacity_factor, s.irradiation_kwh_m2, s.avg_temperature_c,
                                    s.cloud_cover_pct, s.downtime_hours
                       ORDER BY s.stg_row_id)              AS exact_dup_rank
FROM stg_energy_generation s;

DROP TABLE IF EXISTS wrk_energy_checked;
CREATE TABLE wrk_energy_checked AS
SELECT
    e.*,
    p.capacity_mw,
    DAY(LAST_DAY(e.month_start_date)) * 24                AS hours_in_month,
    b.billing_energy_mwh,
    p.project_code IS NULL                                AS is_orphan,
    e.month_start_date IS NULL                            AS is_invalid_date,
    e.exact_dup_rank > 1                                  AS is_duplicate,
    e.month_start_date IS NOT NULL
        AND DAY(e.month_start_date) <> 1                  AS is_not_month_grain,
    e.month_start_date < DATE_FORMAT(p.installation_date, '%Y-%m-01')
                                                          AS is_before_cod,
    e.energy_mwh IS NULL                                  AS is_energy_null,
    e.energy_mwh < 0                                      AS is_energy_negative,
    -- CF implied by energy itself; > 35% is physically implausible for PV in India
    ABS(e.energy_mwh) / (p.capacity_mw * DAY(LAST_DAY(e.month_start_date)) * 24) > 0.35
                                                          AS is_implausible_energy,
    -- stored CF looks like a percentage: > 1 but /100 matches the implied CF
    e.capacity_factor_raw > 1
        AND ABS(e.capacity_factor_raw / 100
                - ABS(e.energy_mwh) / (p.capacity_mw * DAY(LAST_DAY(e.month_start_date)) * 24)) < 0.001
                                                          AS is_cf_in_percent,
    e.irradiation_kwh_m2 IS NULL OR e.cloud_cover_pct IS NULL
                                                          AS is_weather_missing,
    -- SCADA vs billing reconciliation (2% tolerance for meter/aux differences)
    ABS(ABS(e.energy_mwh) - b.billing_energy_mwh) > 0.02 * b.billing_energy_mwh
                                                          AS is_billing_mismatch
FROM wrk_energy e
LEFT JOIN wrk_projects_clean p ON p.project_code = e.project_code
LEFT JOIN wrk_financials_checked b
       ON b.project_code = e.project_code
      AND b.month_start_date = e.month_start_date
      AND NOT b.is_duplicate;

-- C6. Offtaker consumption (captive projects)
DROP TABLE IF EXISTS wrk_consumption;
CREATE TABLE wrk_consumption AS
SELECT
    s.stg_row_id,
    UPPER(TRIM(s.project_code))                           AS project_code,
    fn_parse_date_strict(s.period_month)                  AS month_start_date,
    fn_to_number(s.site_consumption_mwh)                  AS site_consumption_mwh,
    ROW_NUMBER() OVER (PARTITION BY UPPER(TRIM(s.project_code)), s.period_month
                       ORDER BY s.stg_row_id)              AS dup_rank
FROM stg_offtaker_consumption s;

-- ---------------------------------------------------------------------
-- D. Log issues
-- ---------------------------------------------------------------------

-- D1. Locations
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'duplicate_location', 'stg_locations', location_code,
       'Exact duplicate location row', 'REMOVED_DUPLICATE'
FROM wrk_locations WHERE dup_rank > 1;

-- BINARY comparison: the database collation is case-insensitive, so
-- 'BENGALURU' = 'Bengaluru' would otherwise hide the defect.
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'non_standard_text', 'stg_locations', location_code,
       CONCAT('city "', raw_city, '" -> "', city, '"'), 'FIXED'
FROM wrk_locations
WHERE dup_rank = 1 AND CAST(raw_city AS BINARY) <> CAST(city AS BINARY)
UNION ALL
SELECT 'non_standard_text', 'stg_locations', location_code,
       CONCAT('state "', raw_state, '" -> "', state, '"'), 'FIXED'
FROM wrk_locations
WHERE dup_rank = 1 AND CAST(raw_state AS BINARY) <> CAST(state AS BINARY);

INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'missing_coordinates', 'stg_locations', location_code,
       'Latitude/longitude missing or out of range', 'QUARANTINED'
FROM wrk_locations
WHERE dup_rank = 1
  AND (latitude IS NULL OR longitude IS NULL OR latitude NOT BETWEEN -90 AND 90
       OR longitude NOT BETWEEN -180 AND 180);

-- D2. Projects
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'stale_project_version', 'stg_projects', project_code,
       CONCAT('Older record from ', record_updated_at, ' (capacity ', ROUND(capacity_mw, 2), ' MW) superseded'),
       'REMOVED_DUPLICATE'
FROM wrk_projects
WHERE version_rank > 1;

INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'invalid_project_record', 'stg_projects', project_code,
       CONCAT('Code not in P### format or location unresolvable: "', project_name, '"'), 'QUARANTINED'
FROM wrk_projects p
WHERE p.version_rank = 1
  AND p.project_code NOT IN (SELECT project_code FROM wrk_projects_clean);

INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'non_standard_text', 'stg_projects', project_code,
       CONCAT('location_code "', raw_location_code, '" -> "', location_code, '"'), 'FIXED'
FROM wrk_projects_clean
WHERE CAST(raw_location_code AS BINARY) <> CAST(location_code AS BINARY)
UNION ALL
SELECT 'non_standard_text', 'stg_projects', project_code,
       CONCAT('project_type "', raw_project_type, '" -> "', project_type, '"'), 'FIXED'
FROM wrk_projects_clean
WHERE CAST(raw_project_type AS BINARY) <> CAST(project_type AS BINARY);

-- Negative capex: fixed with ABS() only because two independent checks agree:
-- (1) |capex|/MW is in the plausible 2.5-9 Cr/MW band, and
-- (2) ERP depreciation = |capex| / 25 years / 12 months.
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'negative_investment', 'stg_projects', p.project_code,
       CONCAT('investment ', p.investment_raw_inr, '; |capex|/MW = ',
              ROUND(ABS(p.investment_raw_inr) / p.capacity_mw / 1e7, 2), ' Cr; ERP depreciation x 300 = ',
              ROUND(d.monthly_dep * 300, 0)),
       IF(ABS(p.investment_raw_inr) / p.capacity_mw / 1e7 BETWEEN 2.5 AND 9
          AND ABS(ABS(p.investment_raw_inr) - d.monthly_dep * 300) < 1000, 'FIXED', 'QUARANTINED')
FROM wrk_projects_clean p
LEFT JOIN (SELECT project_code, AVG(depreciation_inr) AS monthly_dep
           FROM wrk_financials_checked WHERE NOT is_duplicate GROUP BY project_code) d
       ON d.project_code = p.project_code
WHERE p.investment_raw_inr < 0;

INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'status_date_inconsistent', 'stg_projects', project_code,
       CONCAT(project_status, ' with installation_date ', installation_date), 'FLAGGED_ONLY'
FROM wrk_projects_clean
WHERE (project_status = 'Operational'        AND installation_date > '2026-04-15')
   OR (project_status = 'Under Construction' AND installation_date <= '2026-04-15');

-- D3. Energy — precedence: orphan > duplicate > invalid date > value checks
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'orphan_project_code', 'stg_energy_generation', CONCAT(project_code, '|', raw_month),
       'project_code not found in the project master', 'QUARANTINED'
FROM wrk_energy_checked WHERE is_orphan;

INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'duplicate_row', 'stg_energy_generation', CONCAT(project_code, '|', raw_month),
       'Exact duplicate of an earlier row', 'REMOVED_DUPLICATE'
FROM wrk_energy_checked WHERE NOT is_orphan AND is_duplicate;

INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'invalid_date', 'stg_energy_generation', CONCAT(project_code, '|', raw_month),
       'Calendar-impossible date; SCADA row quarantined, month rebuilt from billing in 06',
       'QUARANTINED'
FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND is_invalid_date;

-- Value checks on surviving rows (a row can carry more than one)
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT check_name, 'stg_energy_generation', record_key, issue_detail, action_taken
FROM (
    SELECT 'alternate_date_format' AS check_name, CONCAT(project_code, '|', month_start_date) AS record_key,
           CONCAT('DD-MM-YYYY "', raw_month, '" parsed as ', month_start_date) AS issue_detail, 'FIXED' AS action_taken
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_alt_date_format
    UNION ALL
    SELECT 'negative_energy', CONCAT(project_code, '|', month_start_date),
           CONCAT('energy ', energy_mwh, '; billing ', billing_energy_mwh), IF(is_billing_mismatch, 'RECONSTRUCTED', 'FIXED')
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_energy_negative
    UNION ALL
    SELECT 'implausible_energy_spike', CONCAT(project_code, '|', month_start_date),
           CONCAT('energy ', energy_mwh, ' implies CF > 35%; billing ', billing_energy_mwh), 'RECONSTRUCTED'
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_implausible_energy
    UNION ALL
    SELECT 'null_energy', CONCAT(project_code, '|', month_start_date),
           CONCAT('energy NULL; billing ', billing_energy_mwh), 'RECONSTRUCTED'
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_energy_null
    UNION ALL
    SELECT 'capacity_factor_in_percent', CONCAT(project_code, '|', month_start_date),
           CONCAT('stored CF ', capacity_factor_raw, '; CF is recomputed from energy'), 'FIXED'
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date
      AND is_cf_in_percent AND NOT is_implausible_energy
    UNION ALL
    SELECT 'scada_billing_mismatch', CONCAT(project_code, '|', month_start_date),
           CONCAT('SCADA ', energy_mwh, ' vs billing ', billing_energy_mwh), 'RECONSTRUCTED'
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date
      AND is_billing_mismatch AND NOT is_implausible_energy AND NOT is_energy_negative
    UNION ALL
    SELECT 'missing_weather', CONCAT(project_code, '|', month_start_date),
           'Irradiation/cloud NULL (sensor outage): kept NULL, excluded from correlation', 'FLAGGED_ONLY'
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_weather_missing
    UNION ALL
    SELECT 'generation_before_cod', CONCAT(project_code, '|', month_start_date),
           'Generation reported before commercial operation date', 'QUARANTINED'
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_before_cod
    UNION ALL
    SELECT 'not_month_grain', CONCAT(project_code, '|', month_start_date),
           'Date is not the first of the month', 'QUARANTINED'
    FROM wrk_energy_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_not_month_grain
) v;

-- Operational outliers: real events, NOT errors. Flag for investigation, never delete.
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'outlier_downtime', 'stg_energy_generation', CONCAT(project_code, '|', month_start_date),
       CONCAT('downtime ', downtime_hours, ' h (> 100 h threshold)'), 'FLAGGED_ONLY'
FROM wrk_energy_checked
WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND downtime_hours > 100;

-- D4. Financials
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT check_name, 'stg_financials', record_key, issue_detail, action_taken
FROM (
    SELECT 'orphan_project_code' AS check_name, CONCAT(project_code, '|', raw_month) AS record_key,
           'project_code not found in the project master' AS issue_detail, 'QUARANTINED' AS action_taken
    FROM wrk_financials_checked WHERE is_orphan
    UNION ALL
    SELECT 'duplicate_row', CONCAT(project_code, '|', raw_month), 'Exact duplicate of an earlier row', 'REMOVED_DUPLICATE'
    FROM wrk_financials_checked WHERE NOT is_orphan AND is_duplicate
    UNION ALL
    SELECT 'invalid_date', CONCAT(project_code, '|', raw_month), 'Unparseable period', 'QUARANTINED'
    FROM wrk_financials_checked WHERE NOT is_orphan AND NOT is_duplicate AND is_invalid_date
    UNION ALL
    SELECT 'null_maintenance_cost', CONCAT(f.project_code, '|', f.month_start_date),
           CONCAT('Imputed with project median ', m.median_maintenance_inr), 'IMPUTED'
    FROM wrk_financials_checked f
    JOIN wrk_maintenance_median m ON m.project_code = f.project_code
    WHERE NOT f.is_orphan AND NOT f.is_duplicate AND NOT f.is_invalid_date AND f.is_maintenance_null
    UNION ALL
    SELECT 'negative_operating_cost', CONCAT(project_code, '|', month_start_date),
           CONCAT('operating cost ', operating_cost_inr, ' -> sign corrected'), 'FIXED'
    FROM wrk_financials_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_opex_negative
    UNION ALL
    SELECT 'negative_revenue', CONCAT(project_code, '|', month_start_date),
           'Negative revenue: could be a legitimate credit note, needs Finance confirmation', 'FLAGGED_ONLY'
    FROM wrk_financials_checked WHERE NOT is_orphan AND NOT is_duplicate AND NOT is_invalid_date AND is_revenue_negative
) v;

-- Cost outlier: month > 3x the project's own median maintenance (flag only)
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'outlier_maintenance_cost', 'stg_financials', CONCAT(f.project_code, '|', f.month_start_date),
       CONCAT('maintenance ', ROUND(f.maintenance_cost_inr), ' = ',
              ROUND(f.maintenance_cost_inr / m.median_maintenance_inr, 1), 'x project median'),
       'FLAGGED_ONLY'
FROM wrk_financials_checked f
JOIN wrk_maintenance_median m ON m.project_code = f.project_code
WHERE NOT f.is_orphan AND NOT f.is_duplicate AND NOT f.is_invalid_date
  AND f.maintenance_cost_inr > 3 * m.median_maintenance_inr;

-- D5. Consumption
INSERT INTO dq_issue_log (check_name, source_table, record_key, issue_detail, action_taken)
SELECT 'duplicate_row', 'stg_offtaker_consumption', CONCAT(project_code, '|', month_start_date),
       'Duplicate project-month', 'REMOVED_DUPLICATE'
FROM wrk_consumption WHERE dup_rank > 1
UNION ALL
SELECT 'orphan_project_code', 'stg_offtaker_consumption', CONCAT(c.project_code, '|', c.month_start_date),
       'project_code not found in the project master', 'QUARANTINED'
FROM wrk_consumption c
LEFT JOIN wrk_projects_clean p ON p.project_code = c.project_code
WHERE p.project_code IS NULL;

-- ---------------------------------------------------------------------
-- E. Data-quality summary
-- ---------------------------------------------------------------------
SELECT source_table, check_name, action_taken, COUNT(*) AS issues
FROM dq_issue_log
GROUP BY source_table, check_name, action_taken
ORDER BY source_table, issues DESC;
