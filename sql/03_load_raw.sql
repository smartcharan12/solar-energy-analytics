-- =====================================================================
-- 03_load_raw.sql
-- Bulk-load the raw CSV exports into staging.
-- Run from the repository root (paths are relative to the client):
--     mysql --local-infile=1 solar_analytics < sql/03_load_raw.sql
-- Empty CSV fields are converted to SQL NULL with NULLIF(@x, '') so that
-- "missing" is represented one way only.
-- =====================================================================

USE solar_analytics;

TRUNCATE TABLE stg_locations;
LOAD DATA LOCAL INFILE 'data/raw/raw_locations.csv'
INTO TABLE stg_locations
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(@location_code, @country, @state, @region, @city, @latitude, @longitude, @ghi, @zone)
SET location_code         = NULLIF(@location_code, ''),
    country               = NULLIF(@country, ''),
    state                 = NULLIF(@state, ''),
    region                = NULLIF(@region, ''),
    city                  = NULLIF(@city, ''),
    latitude              = NULLIF(@latitude, ''),
    longitude             = NULLIF(@longitude, ''),
    annual_ghi_kwh_m2_day = NULLIF(@ghi, ''),
    solar_zone            = NULLIF(TRIM(TRAILING '\r' FROM @zone), '');

TRUNCATE TABLE stg_projects;
LOAD DATA LOCAL INFILE 'data/raw/raw_projects.csv'
INTO TABLE stg_projects
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(@code, @name, @loc, @type, @install, @cap, @inv, @tariff, @status, @updated)
SET project_code           = NULLIF(@code, ''),
    project_name           = NULLIF(@name, ''),
    location_code          = NULLIF(@loc, ''),
    project_type           = NULLIF(@type, ''),
    installation_date      = NULLIF(@install, ''),
    capacity_mw            = NULLIF(@cap, ''),
    investment_amount_inr  = NULLIF(@inv, ''),
    ppa_tariff_inr_per_kwh = NULLIF(@tariff, ''),
    project_status         = NULLIF(@status, ''),
    record_updated_at      = NULLIF(TRIM(TRAILING '\r' FROM @updated), '');

TRUNCATE TABLE stg_energy_generation;
LOAD DATA LOCAL INFILE 'data/raw/raw_energy_generation.csv'
INTO TABLE stg_energy_generation
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(@code, @month, @energy, @cf, @irr, @temp, @cloud, @down, @src)
SET project_code         = NULLIF(@code, ''),
    reading_month        = NULLIF(@month, ''),
    energy_generated_mwh = NULLIF(@energy, ''),
    capacity_factor      = NULLIF(@cf, ''),
    irradiation_kwh_m2   = NULLIF(@irr, ''),
    avg_temperature_c    = NULLIF(@temp, ''),
    cloud_cover_pct      = NULLIF(@cloud, ''),
    downtime_hours       = NULLIF(@down, ''),
    source_system        = NULLIF(TRIM(TRAILING '\r' FROM @src), '');

TRUNCATE TABLE stg_financials;
LOAD DATA LOCAL INFILE 'data/raw/raw_financials.csv'
INTO TABLE stg_financials
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(@code, @month, @rev, @opex, @maint, @dep, @cur)
SET project_code         = NULLIF(@code, ''),
    period_month         = NULLIF(@month, ''),
    revenue_inr          = NULLIF(@rev, ''),
    operating_cost_inr   = NULLIF(@opex, ''),
    maintenance_cost_inr = NULLIF(@maint, ''),
    depreciation_inr     = NULLIF(@dep, ''),
    currency             = NULLIF(TRIM(TRAILING '\r' FROM @cur), '');

TRUNCATE TABLE stg_offtaker_consumption;
LOAD DATA LOCAL INFILE 'data/raw/raw_offtaker_consumption.csv'
INTO TABLE stg_offtaker_consumption
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(@code, @month, @cons)
SET project_code         = NULLIF(@code, ''),
    period_month         = NULLIF(@month, ''),
    site_consumption_mwh = NULLIF(TRIM(TRAILING '\r' FROM @cons), '');

-- Load reconciliation: these counts must equal the CSV line counts minus headers.
SELECT 'stg_locations' AS table_name, COUNT(*) AS rows_loaded FROM stg_locations
UNION ALL SELECT 'stg_projects',             COUNT(*) FROM stg_projects
UNION ALL SELECT 'stg_energy_generation',    COUNT(*) FROM stg_energy_generation
UNION ALL SELECT 'stg_financials',           COUNT(*) FROM stg_financials
UNION ALL SELECT 'stg_offtaker_consumption', COUNT(*) FROM stg_offtaker_consumption;
