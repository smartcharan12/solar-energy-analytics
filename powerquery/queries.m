// =====================================================================
// Solar Energy Analytics: Power Query (M) queries
// ---------------------------------------------------------------------
// One block per query. In Power BI Desktop: Transform data > New Source >
// Blank Query > Advanced Editor, paste the block, rename the query to the
// name in its header.
//
// Design rule: CLEANING HAPPENS IN MYSQL (sql/05-06), NOT HERE.
// Power Query only (1) connects, (2) sets types, (3) adds cheap derived
// columns, (4) merges 1:1 project attributes, (5) builds the Date table and
// (6) runs defensive validation. This keeps query folding intact for
// as long as possible and keeps one version of each business rule.
//
// Prerequisite: the MySQL connector needs "MySQL Connector/NET" installed
// on the Windows machine running Power BI Desktop.
// =====================================================================


// ---------------------------------------------------------------------
// Query: MySqlServer            (Manage Parameters > New, type Text)
// ---------------------------------------------------------------------
"localhost:3307" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]


// ---------------------------------------------------------------------
// Query: MySqlDatabase          (Manage Parameters > New, type Text)
// ---------------------------------------------------------------------
"solar_analytics" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]


// ---------------------------------------------------------------------
// Query: fnGetTable             (function; disable load)
// Returns a MySQL table or view by name. Folding is preserved: the
// navigation step becomes SELECT ... FROM <name> on the server.
// If your Navigator generates a different record shape, open one table
// through the UI and copy its navigation step here.
// ---------------------------------------------------------------------
(TableName as text) as table =>
let
    Source = MySQL.Database(MySqlServer, MySqlDatabase, [ReturnSingleDatabase = true]),
    Data   = Source{[Schema = MySqlDatabase, Item = TableName]}[Data]
in
    Data


// ---------------------------------------------------------------------
// Query: Date                   (load; then Table tools > Mark as date table)
// Daily calendar, Indian fiscal year (April-March). Mirrors MySQL dim_date.
// Built in M, so it exists even when the source has no calendar.
// Range: derived from the facts and padded to whole fiscal years, so it
// never needs editing when new months arrive.
// ---------------------------------------------------------------------
let
    FactDates  = fnGetTable("fact_energy_generation")[month_start_date],
    MinDate    = List.Min(FactDates),
    MaxDate    = List.Max(FactDates),
    // pad to fiscal-year boundaries: 1 Apr .. 31 Mar
    StartDate  = #date(if Date.Month(MinDate) >= 4 then Date.Year(MinDate) else Date.Year(MinDate) - 1, 4, 1),
    EndDate    = #date(if Date.Month(MaxDate) >= 4 then Date.Year(MaxDate) + 1 else Date.Year(MaxDate), 3, 31),
    Dates      = List.Dates(StartDate, Duration.Days(EndDate - StartDate) + 1, #duration(1, 0, 0, 0)),
    Base       = Table.FromList(Dates, Splitter.SplitByNothing(), type table [Date = date]),
    AddCols    = Table.AddColumn(Base, "Attrs", each
        let
            d     = [Date],
            m     = Date.Month(d),
            fyEnd = if m >= 4 then Date.Year(d) + 1 else Date.Year(d),
            fm    = Number.Mod(m + 8, 12) + 1
        in
            [
                Year            = Date.Year(d),
                MonthNo         = m,
                MonthName       = Date.ToText(d, [Format = "MMM", Culture = "en-IN"]),
                MonthStart      = Date.StartOfMonth(d),
                YearMonth       = Date.ToText(d, [Format = "MMM-yy", Culture = "en-IN"]),
                YearMonthSort   = Date.Year(d) * 100 + m,
                FiscalYearEnd   = fyEnd,
                FiscalYear      = "FY" & Text.From(fyEnd - 1) & "-" & Text.End(Text.From(fyEnd), 2),
                FiscalMonthNo   = fm,
                FiscalQuarter   = "Q" & Text.From(Number.IntegerDivide(fm - 1, 3) + 1),
                FiscalYearQtr   = "FY" & Text.End(Text.From(fyEnd), 2) & " Q" & Text.From(Number.IntegerDivide(fm - 1, 3) + 1),
                IsMonthStart    = Date.Day(d) = 1
            ]),
    Expanded   = Table.ExpandRecordColumn(AddCols, "Attrs",
        {"Year", "MonthNo", "MonthName", "MonthStart", "YearMonth", "YearMonthSort", "FiscalYearEnd",
         "FiscalYear", "FiscalMonthNo", "FiscalQuarter", "FiscalYearQtr", "IsMonthStart"}),
    Typed      = Table.TransformColumnTypes(Expanded, {
        {"Year", Int64.Type}, {"MonthNo", Int64.Type}, {"MonthName", type text}, {"MonthStart", type date},
        {"YearMonth", type text}, {"YearMonthSort", Int64.Type}, {"FiscalYearEnd", Int64.Type},
        {"FiscalYear", type text}, {"FiscalMonthNo", Int64.Type}, {"FiscalQuarter", type text},
        {"FiscalYearQtr", type text}, {"IsMonthStart", type logical}})
in
    Typed
// After load: sort MonthName by FiscalMonthNo, YearMonth by YearMonthSort.


// ---------------------------------------------------------------------
// Query: Project                (load) — the single project dimension
// vw_dim_project already flattens dim_project + dim_location (the MySQL
// snowflake), so the Power BI model is a pure star. 1:1 project attributes
// from Stage 3 are MERGED in here instead of being loaded as separate tables
// with 1:1 relationships, which add model complexity for no benefit.
// ---------------------------------------------------------------------
let
    Source     = fnGetTable("vw_dim_project"),
    Typed      = Table.TransformColumnTypes(Source, {
        {"project_id", Int64.Type}, {"project_code", type text}, {"project_name", type text},
        {"project_type", type text}, {"project_status", type text}, {"installation_date", type date},
        {"vintage", type text}, {"capacity_mw", type number}, {"capacity_band", type text},
        {"investment_amount_inr", Currency.Type}, {"investment_cr", type number}, {"capex_cr_per_mw", type number},
        {"ppa_tariff_inr_per_kwh", type number}, {"location_id", Int64.Type}, {"location_code", type text},
        {"country", type text}, {"region", type text}, {"state", type text}, {"city", type text},
        {"latitude", type number}, {"longitude", type number}, {"annual_ghi_kwh_m2_day", type number},
        {"solar_zone", type text}}),
    // Defensive standardisation (SQL already did this; a cheap guard, folds as TRIM)
    Trimmed    = Table.TransformColumns(Typed, {{"region", Text.Trim, type text}, {"state", Text.Trim, type text},
                                                {"city", Text.Trim, type text}}),
    // Guard: the dimension key must be unique, or every relationship becomes many-to-many
    Distinct   = Table.Distinct(Trimmed, {"project_id"}),
    // ---- merge Stage 3 diagnostics (1:1, left outer: pipeline projects have none)
    Diag       = fnGetTable("ana_project_diagnostics"),
    MergedDiag = Table.NestedJoin(Distinct, {"project_id"}, Diag, {"project_id"}, "diag", JoinKind.LeftOuter),
    ExpDiag    = Table.ExpandTableColumn(MergedDiag, "diag",
        {"suspected_root_cause", "loss_onset", "loss_shape", "downtime_loss_pct", "unexplained_loss_pct",
         "latest_fy_residual_pct", "capex_vs_benchmark", "lost_revenue_inr"}),
    Seg        = fnGetTable("ana_project_segments"),
    MergedSeg  = Table.NestedJoin(ExpDiag, {"project_id"}, Seg, {"project_id"}, "seg", JoinKind.LeftOuter),
    ExpSeg     = Table.ExpandTableColumn(MergedSeg, "seg", {"abc_revenue"}),
    Bench      = fnGetTable("ref_capex_benchmark"),
    MergedB    = Table.NestedJoin(ExpSeg, {"project_type"}, Bench, {"project_type"}, "bench", JoinKind.LeftOuter),
    ExpBench   = Table.ExpandTableColumn(MergedB, "bench", {"benchmark_cr_per_mw"}),
    // Missing-value handling: blanks become explicit categories for slicers
    Filled     = Table.ReplaceValue(ExpBench, null, "None", Replacer.ReplaceValue, {"suspected_root_cause"}),
    FilledAbc  = Table.ReplaceValue(Filled, null, "Pipeline", Replacer.ReplaceValue, {"abc_revenue"}),
    // Derived columns for display
    AddLabel   = Table.AddColumn(FilledAbc, "Project Label", each [project_code] & " " & [project_name], type text),
    TypedOut   = Table.TransformColumnTypes(AddLabel, {
        {"loss_onset", type date}, {"downtime_loss_pct", Percentage.Type}, {"unexplained_loss_pct", Percentage.Type},
        {"latest_fy_residual_pct", Percentage.Type}, {"capex_vs_benchmark", type number},
        {"lost_revenue_inr", Currency.Type}, {"benchmark_cr_per_mw", type number}})
in
    TypedOut
// Data category (Column tools): latitude = Latitude, longitude = Longitude,
// city = City, state = State or Province, country = Country.
// Hierarchy for drill-down: region > state > city > Project Label.


// ---------------------------------------------------------------------
// Query: Energy                 (load)
// ---------------------------------------------------------------------
let
    Source   = fnGetTable("fact_energy_generation"),
    Typed    = Table.TransformColumnTypes(Source, {
        {"project_id", Int64.Type}, {"month_start_date", type date}, {"energy_generated_mwh", type number},
        {"capacity_factor", type number}, {"irradiation_kwh_m2", type number}, {"avg_temperature_c", type number},
        {"cloud_cover_pct", type number}, {"downtime_hours", type number}, {"data_source", type text}}),
    // Up to here everything folds into one SELECT. The next step does not
    // fold (Date.DaysInMonth has no MySQL translation), so it is LAST.
    // On ~2k rows this costs nothing; on millions, compute it in the SQL view.
    Hours    = Table.AddColumn(Typed, "hours_in_month", each Date.DaysInMonth([month_start_date]) * 24, Int64.Type),
    Reconstructed = Table.AddColumn(Hours, "is_reconstructed", each [data_source] = "BILLING_RECONSTRUCTED", type logical)
in
    Reconstructed


// ---------------------------------------------------------------------
// Query: Financials             (load)
// ---------------------------------------------------------------------
let
    Source = fnGetTable("fact_financials"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"project_id", Int64.Type}, {"month_start_date", type date},
        {"revenue_inr", Currency.Type}, {"operating_cost_inr", Currency.Type},
        {"maintenance_cost_inr", Currency.Type}, {"depreciation_inr", Currency.Type},
        {"maintenance_imputed", type logical}, {"ebitda_inr", Currency.Type}, {"profit_inr", Currency.Type}})
in
    Typed


// ---------------------------------------------------------------------
// Query: Sustainability         (load)
// ---------------------------------------------------------------------
let
    Source = fnGetTable("fact_sustainability"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"project_id", Int64.Type}, {"month_start_date", type date}, {"energy_generated_mwh", type number},
        {"grid_ef_tco2_per_mwh", type number}, {"co2_avoided_tonnes", type number},
        {"equivalent_households", type number}, {"site_consumption_mwh", type number},
        {"renewable_energy_pct", type number}}),
    // energy is already in Energy; drop the copy so nobody sums it twice
    Removed = Table.RemoveColumns(Typed, {"energy_generated_mwh"})
in
    Removed


// ---------------------------------------------------------------------
// Query: Month Diagnostics      (load) — Stage 3 model output
// ---------------------------------------------------------------------
let
    Source = fnGetTable("ana_month_diagnostics"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"project_id", Int64.Type}, {"month_start_date", type date}, {"energy_generated_mwh", type number},
        {"pr_eff", type number}, {"pr_expected", type number}, {"availability", type number},
        {"potential_mwh", type number}, {"expected_mwh", type number}, {"downtime_loss_mwh", type number},
        {"unexplained_loss_mwh", type number}, {"residual_pct", type number},
        {"downtime_loss_inr", Currency.Type}, {"unexplained_loss_inr", Currency.Type},
        {"z_residual", type number}, {"z_downtime", type number}, {"z_maintenance", type number},
        {"month_flags", type text}}),
    // Error handling: a failed numeric conversion becomes null, not a refresh failure.
    // Rows that had errors are kept for audit in the "Audit - Diagnostics Errors" query.
    NoErrors = Table.ReplaceErrorValues(Typed, {{"residual_pct", null}, {"z_residual", null}}),
    Flags    = Table.ReplaceValue(NoErrors, null, "", Replacer.ReplaceValue, {"month_flags"})
in
    Flags


// ---------------------------------------------------------------------
// Query: Region Scores          (load; reference/cross-check only, no relationships)
// Python reference values of the IPS; the DAX measure must match at default weights.
// ---------------------------------------------------------------------
let
    Source = fnGetTable("ana_region_scores"),
    Keep   = Table.SelectColumns(Source, {"region", "Investment Priority Score", "Sustainability Score",
                                          "Rank Default", "Rank Equal weights", "Rank Return-heavy",
                                          "Rank Resource & ESG-heavy"})
in
    Keep


// ---------------------------------------------------------------------
// Query: DQ Summary             (load; data-quality appendix page)
// ---------------------------------------------------------------------
let
    Source = fnGetTable("vw_dq_summary"),
    Typed  = Table.TransformColumnTypes(Source, {{"issues", Int64.Type}})
in
    Typed


// ---------------------------------------------------------------------
// Query: Audit - Diagnostics Errors   (disable load) — error handling
// Lists rows whose type conversion failed, instead of silently dropping them.
// ---------------------------------------------------------------------
let
    Source = fnGetTable("ana_month_diagnostics"),
    Typed  = Table.TransformColumnTypes(Source, {{"residual_pct", type number}, {"z_residual", type number}}),
    Errors = Table.SelectRowsWithErrors(Typed, {"residual_pct", "z_residual"})
in
    Errors


// ---------------------------------------------------------------------
// Query: Validation             (disable load; open it after every refresh)
// Re-checks the contract between MySQL and the model. Every row must say PASS.
// Expected values come from data/ground_truth and powerbi/05_dax_expected_values.md.
// ---------------------------------------------------------------------
let
    E      = Energy,
    F      = Financials,
    P      = Project,
    Check  = (name as text, actual as any, expected as any, tolerance as number) =>
        [Check = name, Actual = actual, Expected = expected,
         Result = if actual = null then "FAIL (null)"
                  else if Number.Abs(actual - expected) <= tolerance then "PASS" else "FAIL"],
    Rows   = {
        Check("Project rows",            Table.RowCount(P), 60, 0),
        Check("Distinct project_id",     List.Count(List.Distinct(P[project_id])), 60, 0),
        Check("Energy rows",             Table.RowCount(E), 1820, 0),
        Check("Financial rows",          Table.RowCount(F), 1820, 0),
        Check("Total energy (MWh)",      List.Sum(E[energy_generated_mwh]), 11448424.312, 0.01),
        Check("Total revenue (INR)",     List.Sum(F[revenue_inr]), 33953354662.48, 1),
        Check("Energy rows w/o project", Table.RowCount(Table.NestedJoin(E, {"project_id"}, P, {"project_id"}, "p",
                                             JoinKind.LeftAnti)), 0, 0),
        Check("Duplicate project-month", Table.RowCount(E) - Table.RowCount(Table.Distinct(E,
                                             {"project_id", "month_start_date"})), 0, 0),
        Check("Negative energy rows",    Table.RowCount(Table.SelectRows(E, each [energy_generated_mwh] < 0)), 0, 0),
        Check("CF > 0.35 rows",          Table.RowCount(Table.SelectRows(E, each [capacity_factor] > 0.35)), 0, 0)
    },
    Result = Table.FromRecords(Rows)
in
    Result


// =====================================================================
// QUERY FOLDING NOTES
// ---------------------------------------------------------------------
// * Right-click a step > "View Native Query". If enabled, the step folds.
// * Folds:   navigation, Table.SelectColumns, Table.TransformColumnTypes,
//            Table.SelectRows on simple comparisons, Text.Trim, joins between
//            two tables from the SAME MySQL source.
// * Breaks:  Date.DaysInMonth, Table.AddColumn with M-only functions,
//            try ... otherwise, Text.Proper, Table.Buffer, merges with a
//            query that has itself stopped folding.
// * Rule:    put non-folding steps LAST, after every filter, so the server
//            still does the heavy lifting. Here the data is small, so
//            folding is about good practice, not about speed.
// * Why the cleaning is in SQL: done in M, the strict date parse (try ...
//            otherwise), the alias mapping and the dedupe would all break
//            folding at step 1 and would be invisible to anyone using MySQL.
// =====================================================================
