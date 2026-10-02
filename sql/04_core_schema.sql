-- =====================================================================
-- 04_core_schema.sql
-- Clean, constrained star schema. Nothing reaches these tables
-- without passing the data-quality layer (05/06).
--
-- Grain of every fact table: ONE ROW PER PROJECT PER CALENDAR MONTH.
-- The composite primary key (project_id, month_start_date) enforces
-- that grain physically: a duplicate month cannot be inserted.
--
-- Design decision: investment_amount lives in dim_project, NOT in
-- fact_financials. Capex is paid once per project; repeating it on 36
-- monthly rows would make SUM(investment) 36x too large. ROI is
-- computed from dim_project.investment_amount_inr and fact profit.
-- =====================================================================

USE solar_analytics;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS fact_sustainability, fact_financials, fact_energy_generation,
                     dim_project, dim_location, dim_date,
                     ref_emission_factor, ref_assumption, ref_text_alias, ref_capex_benchmark, dq_issue_log;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- dim_date: daily calendar with Indian fiscal attributes (FY = Apr-Mar)
-- ---------------------------------------------------------------------
CREATE TABLE dim_date (
    calendar_date       DATE        NOT NULL PRIMARY KEY,
    date_key            INT         NOT NULL UNIQUE,          -- yyyymmdd
    calendar_year       SMALLINT    NOT NULL,
    calendar_month      TINYINT     NOT NULL,
    month_name          CHAR(3)     NOT NULL,
    month_start_date    DATE        NOT NULL,
    year_month_label    CHAR(8)     NOT NULL,                 -- e.g. 2024-Apr
    fiscal_year         CHAR(9)     NOT NULL,                 -- e.g. FY2024-25
    fiscal_year_end     SMALLINT    NOT NULL,                 -- e.g. 2025
    fiscal_quarter      CHAR(2)     NOT NULL,                 -- Q1 = Apr-Jun
    fiscal_month_no     TINYINT     NOT NULL,                 -- 1 = April
    is_month_start      TINYINT(1)  NOT NULL,
    INDEX ix_dim_date_month (month_start_date),
    CONSTRAINT ck_dim_date_fm CHECK (fiscal_month_no BETWEEN 1 AND 12)
);

SET SESSION cte_max_recursion_depth = 5000;

INSERT INTO dim_date
WITH RECURSIVE days AS (
    SELECT DATE('2023-04-01') AS d
    UNION ALL
    SELECT d + INTERVAL 1 DAY FROM days WHERE d < '2027-03-31'
)
SELECT
    d,
    CAST(DATE_FORMAT(d, '%Y%m%d') AS UNSIGNED),
    YEAR(d),
    MONTH(d),
    DATE_FORMAT(d, '%b'),
    DATE_FORMAT(d, '%Y-%m-01'),
    DATE_FORMAT(d, '%Y-%b'),
    CONCAT('FY', IF(MONTH(d) >= 4, YEAR(d), YEAR(d) - 1), '-',
           RIGHT(IF(MONTH(d) >= 4, YEAR(d) + 1, YEAR(d)), 2)),
    IF(MONTH(d) >= 4, YEAR(d) + 1, YEAR(d)),
    CONCAT('Q', FLOOR(MOD(MONTH(d) + 8, 12) / 3) + 1),
    MOD(MONTH(d) + 8, 12) + 1,
    DAY(d) = 1
FROM days;

-- ---------------------------------------------------------------------
-- dim_location
-- ---------------------------------------------------------------------
CREATE TABLE dim_location (
    location_id             SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    location_code           CHAR(4)        NOT NULL,
    country                 VARCHAR(60)    NOT NULL,
    state                   VARCHAR(60)    NOT NULL,
    region                  VARCHAR(30)    NOT NULL,
    city                    VARCHAR(60)    NOT NULL,
    latitude                DECIMAL(9,6)   NOT NULL,
    longitude               DECIMAL(9,6)   NOT NULL,
    annual_ghi_kwh_m2_day   DECIMAL(4,2)   NOT NULL,
    solar_zone              VARCHAR(40)    NOT NULL,
    CONSTRAINT uq_location_code  UNIQUE (location_code),
    CONSTRAINT uq_location_city  UNIQUE (state, city),
    CONSTRAINT ck_location_lat   CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT ck_location_lon   CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_location_ghi   CHECK (annual_ghi_kwh_m2_day BETWEEN 2 AND 8),
    CONSTRAINT ck_location_region CHECK (region IN ('North','West','South','Central','East','North-East'))
);

-- ---------------------------------------------------------------------
-- dim_project
-- Surrogate key (project_id) for joins; natural key (project_code)
-- kept UNIQUE for traceability back to the source asset register.
-- ---------------------------------------------------------------------
CREATE TABLE dim_project (
    project_id              SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    project_code            VARCHAR(10)    NOT NULL,
    project_name            VARCHAR(120)   NOT NULL,
    location_id             SMALLINT UNSIGNED NOT NULL,
    project_type            VARCHAR(30)    NOT NULL,
    installation_date       DATE           NOT NULL,          -- actual or expected COD
    capacity_mw             DECIMAL(8,2)   NOT NULL,
    investment_amount_inr   DECIMAL(16,2)  NOT NULL,
    ppa_tariff_inr_per_kwh  DECIMAL(5,2)   NOT NULL,
    project_status          VARCHAR(20)    NOT NULL,
    source_updated_at       DATETIME       NOT NULL,
    CONSTRAINT uq_project_code    UNIQUE (project_code),
    CONSTRAINT fk_project_location FOREIGN KEY (location_id) REFERENCES dim_location (location_id),
    CONSTRAINT ck_project_type    CHECK (project_type IN ('Utility-Scale','C&I Open Access','Rooftop','Floating')),
    CONSTRAINT ck_project_status  CHECK (project_status IN ('Operational','Under Construction')),
    CONSTRAINT ck_project_capacity CHECK (capacity_mw > 0),
    CONSTRAINT ck_project_invest  CHECK (investment_amount_inr > 0),
    CONSTRAINT ck_project_tariff  CHECK (ppa_tariff_inr_per_kwh BETWEEN 1 AND 15),
    INDEX ix_project_location (location_id)
);

-- ---------------------------------------------------------------------
-- fact_energy_generation  (source: SCADA)
-- data_source = 'BILLING_RECONSTRUCTED' marks months where SCADA was
-- unusable and energy was rebuilt from the billing meter (see 06).
-- ---------------------------------------------------------------------
CREATE TABLE fact_energy_generation (
    project_id              SMALLINT UNSIGNED NOT NULL,
    month_start_date        DATE           NOT NULL,
    energy_generated_mwh    DECIMAL(12,3)  NOT NULL,
    capacity_factor         DECIMAL(6,4)   NOT NULL,
    irradiation_kwh_m2      DECIMAL(6,1)   NULL,              -- NULL = sensor outage
    avg_temperature_c       DECIMAL(4,1)   NULL,
    cloud_cover_pct         DECIMAL(4,1)   NULL,
    downtime_hours          DECIMAL(6,1)   NULL,
    data_source             VARCHAR(25)    NOT NULL DEFAULT 'SCADA',
    PRIMARY KEY (project_id, month_start_date),
    CONSTRAINT fk_energy_project FOREIGN KEY (project_id)       REFERENCES dim_project (project_id),
    CONSTRAINT fk_energy_date    FOREIGN KEY (month_start_date) REFERENCES dim_date (calendar_date),
    CONSTRAINT ck_energy_nonneg  CHECK (energy_generated_mwh >= 0),
    CONSTRAINT ck_energy_cf      CHECK (capacity_factor BETWEEN 0 AND 1),
    CONSTRAINT ck_energy_irr     CHECK (irradiation_kwh_m2 IS NULL OR irradiation_kwh_m2 >= 0),
    CONSTRAINT ck_energy_temp    CHECK (avg_temperature_c IS NULL OR avg_temperature_c BETWEEN -30 AND 60),
    CONSTRAINT ck_energy_cloud   CHECK (cloud_cover_pct IS NULL OR cloud_cover_pct BETWEEN 0 AND 100),
    CONSTRAINT ck_energy_down    CHECK (downtime_hours IS NULL OR downtime_hours BETWEEN 0 AND 744),
    CONSTRAINT ck_energy_source  CHECK (data_source IN ('SCADA','BILLING_RECONSTRUCTED')),
    INDEX ix_energy_month (month_start_date)
);

-- ---------------------------------------------------------------------
-- fact_financials  (source: ERP / billing)
-- Profit is a GENERATED column: one definition, impossible to drift.
--   ebitda_inr = revenue - operating cost - maintenance cost
--   profit_inr = ebitda - depreciation        (EBIT: pre-interest, pre-tax)
-- ---------------------------------------------------------------------
CREATE TABLE fact_financials (
    project_id              SMALLINT UNSIGNED NOT NULL,
    month_start_date        DATE           NOT NULL,
    revenue_inr             DECIMAL(16,2)  NOT NULL,
    operating_cost_inr      DECIMAL(16,2)  NOT NULL,
    maintenance_cost_inr    DECIMAL(16,2)  NOT NULL,
    depreciation_inr        DECIMAL(16,2)  NOT NULL,
    maintenance_imputed     TINYINT(1)     NOT NULL DEFAULT 0,
    ebitda_inr              DECIMAL(16,2)  AS (revenue_inr - operating_cost_inr - maintenance_cost_inr) STORED,
    profit_inr              DECIMAL(16,2)  AS (revenue_inr - operating_cost_inr - maintenance_cost_inr - depreciation_inr) STORED,
    PRIMARY KEY (project_id, month_start_date),
    CONSTRAINT fk_fin_project FOREIGN KEY (project_id)       REFERENCES dim_project (project_id),
    CONSTRAINT fk_fin_date    FOREIGN KEY (month_start_date) REFERENCES dim_date (calendar_date),
    CONSTRAINT ck_fin_revenue CHECK (revenue_inr >= 0),
    CONSTRAINT ck_fin_opex    CHECK (operating_cost_inr >= 0),
    CONSTRAINT ck_fin_maint   CHECK (maintenance_cost_inr >= 0),
    CONSTRAINT ck_fin_dep     CHECK (depreciation_inr >= 0),
    INDEX ix_fin_month (month_start_date)
);

-- ---------------------------------------------------------------------
-- fact_sustainability  (derived in SQL from energy + reference tables)
--   co2_avoided_tonnes     = energy_mwh x grid emission factor (by FY)
--   equivalent_households  = energy_mwh / household MWh per month
--                            NON-ADDITIVE across months: average, never sum
--   renewable_energy_pct   = solar MWh used on site / site consumption
--                            only for captive (C&I, Rooftop) projects;
--                            NULL for grid-export projects, where a
--                            "share of demand" has no meaning.
-- ---------------------------------------------------------------------
CREATE TABLE fact_sustainability (
    project_id              SMALLINT UNSIGNED NOT NULL,
    month_start_date        DATE           NOT NULL,
    energy_generated_mwh    DECIMAL(12,3)  NOT NULL,
    grid_ef_tco2_per_mwh    DECIMAL(5,3)   NOT NULL,          -- lineage: factor used
    co2_avoided_tonnes      DECIMAL(12,3)  NOT NULL,
    equivalent_households   DECIMAL(12,1)  NOT NULL,
    site_consumption_mwh    DECIMAL(12,3)  NULL,
    renewable_energy_pct    DECIMAL(5,2)   NULL,
    PRIMARY KEY (project_id, month_start_date),
    CONSTRAINT fk_sus_project FOREIGN KEY (project_id)       REFERENCES dim_project (project_id),
    CONSTRAINT fk_sus_date    FOREIGN KEY (month_start_date) REFERENCES dim_date (calendar_date),
    CONSTRAINT ck_sus_co2     CHECK (co2_avoided_tonnes >= 0),
    CONSTRAINT ck_sus_re      CHECK (renewable_energy_pct IS NULL OR renewable_energy_pct BETWEEN 0 AND 100)
);

-- ---------------------------------------------------------------------
-- Reference tables: every assumption is data, not a magic number.
-- ---------------------------------------------------------------------
CREATE TABLE ref_emission_factor (
    fiscal_year_end         SMALLINT       NOT NULL PRIMARY KEY,
    grid_ef_tco2_per_mwh    DECIMAL(5,3)   NOT NULL,
    source_note             VARCHAR(200)   NOT NULL,
    CONSTRAINT ck_ef_range CHECK (grid_ef_tco2_per_mwh BETWEEN 0 AND 2)
);

-- Single factor applied to all years: an approximation of the Indian
-- grid weighted-average CO2 factor (CEA CO2 Baseline Database). Replace
-- with the year-specific published values before any external use.
INSERT INTO ref_emission_factor VALUES
    (2024, 0.716, 'Approx. CEA CO2 Baseline Database grid weighted average; project assumption'),
    (2025, 0.716, 'Approx. CEA CO2 Baseline Database grid weighted average; project assumption'),
    (2026, 0.716, 'Approx. CEA CO2 Baseline Database grid weighted average; project assumption');

CREATE TABLE ref_assumption (
    assumption_key          VARCHAR(50)    NOT NULL PRIMARY KEY,
    assumption_value        DECIMAL(12,4)  NOT NULL,
    unit                    VARCHAR(30)    NOT NULL,
    note                    VARCHAR(250)   NOT NULL
);

INSERT INTO ref_assumption VALUES
    ('household_mwh_per_month', 0.1000, 'MWh/household/month',
     'Approx. 1,200 kWh per Indian household per year; illustrative assumption'),
    ('max_plausible_capacity_factor', 0.3500, 'ratio',
     'Fixed-tilt / single-axis PV in India does not sustain CF above ~35% monthly'),
    ('asset_life_years', 25.0000, 'years',
     'Straight-line depreciation life, no salvage value'),
    ('daylight_hours_per_day', 12.0000, 'hours',
     'Used to convert downtime hours into availability');

-- Capex benchmark per technology. Peer groups can be too small to judge
-- a project (only 2 floating plants), so capex is compared to a market
-- benchmark instead. Illustrative values in the style of a regulator's
-- benchmark capital cost order; update from the latest published source.
CREATE TABLE ref_capex_benchmark (
    project_type            VARCHAR(30)    NOT NULL PRIMARY KEY,
    benchmark_cr_per_mw     DECIMAL(5,2)   NOT NULL,
    note                    VARCHAR(200)   NOT NULL
);

INSERT INTO ref_capex_benchmark VALUES
    ('Utility-Scale',   4.00, 'Illustrative benchmark, ground-mounted, excl. land'),
    ('C&I Open Access', 4.40, 'Illustrative benchmark, incl. dedicated evacuation'),
    ('Rooftop',         5.00, 'Illustrative benchmark, RESCO rooftop'),
    ('Floating',        6.00, 'Illustrative benchmark, floating PV on reservoir');

-- Known spelling variants -> standard value. Matching is on
-- UPPER(TRIM(raw)), so case and whitespace variants need no rows here.
-- New variants are fixed by adding a row, not by editing SQL.
CREATE TABLE ref_text_alias (
    domain                  VARCHAR(30)    NOT NULL,
    raw_value               VARCHAR(60)    NOT NULL,          -- stored upper case
    standard_value          VARCHAR(60)    NOT NULL,
    PRIMARY KEY (domain, raw_value)
);

INSERT INTO ref_text_alias VALUES
    ('state',        'TAMILNADU',          'Tamil Nadu'),
    ('state',        'TN',                 'Tamil Nadu'),
    ('state',        'ORISSA',             'Odisha'),
    ('city',         'BANGALORE',          'Bengaluru'),
    ('city',         'COCHIN',             'Kochi'),
    ('project_type', 'UTILITY-SCALE',      'Utility-Scale'),
    ('project_type', 'UTILITY SCALE',      'Utility-Scale'),
    ('project_type', 'C&I OPEN ACCESS',    'C&I Open Access'),
    ('project_type', 'C&I',                'C&I Open Access'),
    ('project_type', 'ROOFTOP',            'Rooftop'),
    ('project_type', 'FLOATING',           'Floating');

-- ---------------------------------------------------------------------
-- dq_issue_log: every detected defect and what was done about it
-- ---------------------------------------------------------------------
CREATE TABLE dq_issue_log (
    issue_id                INT AUTO_INCREMENT PRIMARY KEY,
    check_name              VARCHAR(60)    NOT NULL,
    source_table            VARCHAR(40)    NOT NULL,
    record_key              VARCHAR(80)    NULL,
    issue_detail            VARCHAR(250)   NULL,
    action_taken            VARCHAR(30)    NOT NULL,
    logged_at               TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_dq_action CHECK (action_taken IN
        ('FIXED','REMOVED_DUPLICATE','QUARANTINED','IMPUTED','RECONSTRUCTED','FLAGGED_ONLY'))
);
