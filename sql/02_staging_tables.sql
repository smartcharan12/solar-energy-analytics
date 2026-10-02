-- =====================================================================
-- 02_staging_tables.sql
-- Raw landing zone. Every business column is VARCHAR on purpose:
-- a bad date or a stray minus sign must LAND here so it can be
-- detected, logged and fixed in SQL. If staging were strictly typed,
-- bad rows would be rejected silently at load time and never audited.
-- =====================================================================

USE solar_analytics;

DROP TABLE IF EXISTS stg_locations;
CREATE TABLE stg_locations (
    stg_row_id              INT AUTO_INCREMENT PRIMARY KEY,
    location_code           VARCHAR(20),
    country                 VARCHAR(60),
    state                   VARCHAR(60),
    region                  VARCHAR(30),
    city                    VARCHAR(60),
    latitude                VARCHAR(20),
    longitude               VARCHAR(20),
    annual_ghi_kwh_m2_day   VARCHAR(20),
    solar_zone              VARCHAR(40),
    loaded_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_projects;
CREATE TABLE stg_projects (
    stg_row_id              INT AUTO_INCREMENT PRIMARY KEY,
    project_code            VARCHAR(20),
    project_name            VARCHAR(120),
    location_code           VARCHAR(20),
    project_type            VARCHAR(40),
    installation_date       VARCHAR(20),
    capacity_mw             VARCHAR(20),
    investment_amount_inr   VARCHAR(30),
    ppa_tariff_inr_per_kwh  VARCHAR(20),
    project_status          VARCHAR(30),
    record_updated_at       VARCHAR(30),
    loaded_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_energy_generation;
CREATE TABLE stg_energy_generation (
    stg_row_id              INT AUTO_INCREMENT PRIMARY KEY,
    project_code            VARCHAR(20),
    reading_month           VARCHAR(20),
    energy_generated_mwh    VARCHAR(30),
    capacity_factor         VARCHAR(20),
    irradiation_kwh_m2      VARCHAR(20),
    avg_temperature_c       VARCHAR(20),
    cloud_cover_pct         VARCHAR(20),
    downtime_hours          VARCHAR(20),
    source_system           VARCHAR(20),
    loaded_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_stg_energy_project (project_code)
);

DROP TABLE IF EXISTS stg_financials;
CREATE TABLE stg_financials (
    stg_row_id              INT AUTO_INCREMENT PRIMARY KEY,
    project_code            VARCHAR(20),
    period_month            VARCHAR(20),
    revenue_inr             VARCHAR(30),
    operating_cost_inr      VARCHAR(30),
    maintenance_cost_inr    VARCHAR(30),
    depreciation_inr        VARCHAR(30),
    currency                VARCHAR(5),
    loaded_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_stg_fin_project (project_code)
);

DROP TABLE IF EXISTS stg_offtaker_consumption;
CREATE TABLE stg_offtaker_consumption (
    stg_row_id              INT AUTO_INCREMENT PRIMARY KEY,
    project_code            VARCHAR(20),
    period_month            VARCHAR(20),
    site_consumption_mwh    VARCHAR(30),
    loaded_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
