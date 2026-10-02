-- =====================================================================
-- 01_create_database.sql
-- Solar Energy Data Analysis & Investment Intelligence
-- Creates the database. Re-runnable: drops and recreates everything.
--
-- Layer convention (one database, prefixes instead of many schemas):
--   stg_*   raw landing tables, all text, accept anything
--   dim_*   conformed dimensions (clean, constrained)
--   fact_*  monthly facts at grain (project, month)
--   ref_*   documented assumptions (emission factor, household use)
--   dq_*    data-quality audit log
--   vw_*    analytical views consumed by Power BI
-- =====================================================================

DROP DATABASE IF EXISTS solar_analytics;

CREATE DATABASE solar_analytics
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE solar_analytics;
