"""
Synthetic data generator for the Solar Energy Analytics project.

Produces the RAW layer (what a company would export from its source systems)
for a fictional Indian solar IPP, "Arka Renewables", covering FY2023-24 to
FY2025-26 (Apr-2023 .. Mar-2026, monthly grain).

Source systems being simulated
------------------------------
  raw_locations.csv            master data (site register)
  raw_projects.csv             asset register (capex, PPA tariff, COD)
  raw_energy_generation.csv    SCADA monthly roll-up (generation + weather)
  raw_financials.csv           ERP / billing (revenue, costs, depreciation)
  raw_offtaker_consumption.csv C&I / rooftop client meter (site demand)

Design principles
-----------------
1. Physics first: energy is derived from irradiation, performance ratio,
   temperature derating, degradation, availability and (hidden) curtailment.
   It is NOT random noise around a mean, so correlation analysis is meaningful.
2. Planted business scenarios (soiling, curtailment, inverter failures, hail,
   O&M cost overrun, capex overrun) are written to data/ground_truth/ ONLY.
   The pipeline never reads that folder; tests use it to check that the
   analysis rediscovers what was planted.
3. Data-quality defects are injected into the raw files only, each with a
   known correct answer, so the SQL cleaning layer can be verified exactly.

Run:  python python/generate_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
TRUTH_DIR = ROOT / "data" / "ground_truth"

WINDOW_START = pd.Timestamp("2023-04-01")
WINDOW_END = pd.Timestamp("2026-03-01")          # last month start in window
SNAPSHOT_DATE = pd.Timestamp("2026-04-15")       # date of the data extract
MONTHS = pd.date_range(WINDOW_START, WINDOW_END, freq="MS")

# --------------------------------------------------------------------------
# 1. Reference assumptions (all documented in documentation/01_project_design.md)
# --------------------------------------------------------------------------

# Monthly irradiation shape, fiscal order Apr..Mar (normalised to mean 1 below)
IRRADIATION_PROFILES = {
    # SW-monsoon India: peak Mar-May, trough Jul-Aug
    "monsoon_sw":     [1.22, 1.20, 1.00, 0.78, 0.78, 0.90, 1.00, 0.92, 0.85, 0.90, 1.05, 1.18],
    # Deccan interior: flatter, milder monsoon dip
    "south_interior": [1.18, 1.12, 0.92, 0.85, 0.88, 0.92, 0.92, 0.88, 0.92, 1.02, 1.12, 1.20],
    # Tamil Nadu: NE monsoon (Oct-Dec) is the cloudy season
    "monsoon_ne":     [1.15, 1.05, 0.95, 0.95, 1.00, 1.00, 0.88, 0.78, 0.85, 1.05, 1.15, 1.18],
    # Kerala: heavy SW monsoon plus NE monsoon
    "kerala":         [1.15, 1.00, 0.75, 0.75, 0.85, 0.95, 0.92, 0.92, 1.05, 1.15, 1.20, 1.22],
    # North-East: early monsoon, clear winters
    "northeast":      [1.05, 1.00, 0.85, 0.85, 0.90, 0.88, 1.00, 1.05, 1.00, 1.00, 1.15, 1.15],
}

# Average ambient temperature (deg C), fiscal order Apr..Mar
TEMPERATURE_PROFILES = {
    "north":         [31, 35, 34, 31, 30, 29, 26, 21, 16, 14, 18, 25],
    "west":          [32, 34, 31, 28, 28, 29, 29, 25, 21, 20, 23, 28],
    "central":       [33, 37, 33, 28, 28, 28, 26, 22, 18, 16, 20, 27],
    "south":         [30, 31, 28, 27, 27, 27, 26, 25, 24, 25, 27, 29],
    "coastal_south": [30, 30, 28, 28, 28, 28, 27, 27, 26, 27, 28, 30],
    "east":          [32, 33, 32, 30, 30, 30, 28, 24, 19, 18, 22, 28],
    "northeast":     [26, 27, 28, 29, 29, 28, 26, 22, 18, 17, 20, 24],
}

# code, state, region, city, lat, lon, annual mean GHI (kWh/m2/day),
# irradiation profile, temperature profile, local temperature offset
LOCATIONS = [
    ("L001", "Rajasthan",      "North",      "Jaisalmer",   26.92, 70.91, 5.95, "monsoon_sw",     "north",          1.5),
    ("L002", "Rajasthan",      "North",      "Jodhpur",     26.24, 73.02, 5.85, "monsoon_sw",     "north",          1.0),
    ("L003", "Rajasthan",      "North",      "Bikaner",     28.02, 73.31, 5.75, "monsoon_sw",     "north",          1.0),
    ("L004", "Haryana",        "North",      "Hisar",       29.15, 75.72, 5.30, "monsoon_sw",     "north",          0.0),
    ("L005", "Punjab",         "North",      "Bathinda",    30.21, 74.95, 5.20, "monsoon_sw",     "north",         -0.5),
    ("L006", "Uttar Pradesh",  "North",      "Jhansi",      25.45, 78.57, 5.30, "monsoon_sw",     "central",        0.0),
    ("L007", "Gujarat",        "West",       "Bhuj",        23.24, 69.67, 5.80, "monsoon_sw",     "west",           0.5),
    ("L008", "Gujarat",        "West",       "Palanpur",    24.17, 72.43, 5.65, "monsoon_sw",     "west",           0.5),
    ("L009", "Gujarat",        "West",       "Ahmedabad",   23.02, 72.57, 5.55, "monsoon_sw",     "west",           1.0),
    ("L010", "Maharashtra",    "West",       "Pune",        18.52, 73.86, 5.40, "monsoon_sw",     "west",          -2.0),
    ("L011", "Maharashtra",    "West",       "Solapur",     17.66, 75.91, 5.60, "south_interior", "west",           0.5),
    ("L012", "Karnataka",      "South",      "Pavagada",    14.10, 77.28, 5.75, "south_interior", "south",          1.0),
    ("L013", "Karnataka",      "South",      "Bengaluru",   12.97, 77.59, 5.30, "south_interior", "south",         -3.0),
    ("L014", "Andhra Pradesh", "South",      "Anantapur",   14.68, 77.60, 5.70, "south_interior", "south",          1.5),
    ("L015", "Andhra Pradesh", "South",      "Kurnool",     15.83, 78.04, 5.60, "south_interior", "south",          2.0),
    ("L016", "Telangana",      "South",      "Mahbubnagar", 16.74, 78.00, 5.50, "south_interior", "south",          1.5),
    ("L017", "Tamil Nadu",     "South",      "Tirunelveli",  8.71, 77.76, 5.40, "monsoon_ne",     "coastal_south",  1.0),
    ("L018", "Tamil Nadu",     "South",      "Coimbatore",  11.02, 76.96, 5.30, "monsoon_ne",     "coastal_south", -1.5),
    ("L019", "Kerala",         "South",      "Kochi",        9.93, 76.27, 4.90, "kerala",         "coastal_south",  0.0),
    ("L020", "Madhya Pradesh", "Central",    "Rewa",        24.53, 81.30, 5.25, "monsoon_sw",     "central",        0.0),
    ("L021", "Madhya Pradesh", "Central",    "Neemuch",     24.47, 74.87, 5.60, "monsoon_sw",     "central",        0.0),
    ("L022", "Madhya Pradesh", "Central",    "Khandwa",     21.82, 76.35, 5.45, "monsoon_sw",     "central",        0.5),
    ("L023", "Chhattisgarh",   "Central",    "Raipur",      21.25, 81.63, 5.00, "monsoon_sw",     "central",        0.5),
    ("L024", "Odisha",         "East",       "Bhubaneswar", 20.30, 85.82, 4.90, "monsoon_sw",     "east",           0.0),
    ("L025", "West Bengal",    "East",       "Kolkata",     22.57, 88.36, 4.60, "monsoon_sw",     "east",           0.0),
    ("L026", "Bihar",          "East",       "Patna",       25.59, 85.14, 4.80, "monsoon_sw",     "east",           0.0),
    ("L027", "Assam",          "North-East", "Guwahati",    26.14, 91.74, 4.30, "northeast",      "northeast",      0.0),
    ("L028", "Tripura",        "North-East", "Agartala",    23.83, 91.28, 4.40, "northeast",      "northeast",      0.5),
]


def solar_zone(ghi: float) -> str:
    """Zone bands on long-term mean GHI (kWh/m2/day)."""
    if ghi >= 5.7:
        return "Zone A - Excellent"
    if ghi >= 5.4:
        return "Zone B - Very Good"
    if ghi >= 5.0:
        return "Zone C - Good"
    return "Zone D - Moderate"


TYPE_LABEL = {"U": "Utility-Scale", "C": "C&I Open Access", "R": "Rooftop", "F": "Floating"}
NAME_SUFFIX = {"U": "Solar Park", "C": "C&I Solar", "R": "Rooftop Portfolio", "F": "Floating Solar"}

# Technical assumptions per project type
POA_GAIN = {"U": 1.10, "C": 1.08, "R": 1.02, "F": 1.05}       # plane-of-array / GHI
PR_EX_TEMP = {"U": 0.865, "C": 0.855, "R": 0.835, "F": 0.860}  # PR before temperature loss
CELL_TEMP_RISE = {"U": 22, "C": 22, "R": 25, "F": 15}          # floating panels run cooler
TEMP_COEFF = 0.0038             # power loss per deg C above 25 C cell temperature
DEGRADATION_PER_YEAR = 0.006    # module degradation

# Financial assumptions per project type (INR crore per MW, INR lakh per MW per year)
CAPEX_CR_PER_MW = {"U": (3.7, 4.2), "C": (4.1, 4.7), "R": (4.6, 5.4), "F": (5.6, 6.3)}
FIXED_OPEX_LAKH_PER_MW_YR = {"U": 2.2, "C": 2.6, "R": 1.8, "F": 3.0}   # lease, insurance, admin
OM_LAKH_PER_MW_YR = {"U": 3.2, "C": 3.8, "R": 4.5, "F": 4.8}           # preventive O&M
COST_INFLATION = 0.05           # per fiscal year
ASSET_LIFE_YEARS = 25           # straight-line depreciation, no salvage

CRORE = 1e7
LAKH = 1e5

# (city, type code, count). 60 projects across 28 cities and 6 regions.
PROJECT_PLAN = [
    ("Jaisalmer", "U", 3), ("Jodhpur", "U", 2), ("Bikaner", "U", 2), ("Hisar", "U", 1),
    ("Hisar", "C", 1), ("Bathinda", "U", 1), ("Jhansi", "U", 1), ("Jhansi", "C", 1),
    ("Bhuj", "U", 2), ("Palanpur", "U", 1), ("Ahmedabad", "C", 2), ("Ahmedabad", "R", 1),
    ("Pune", "R", 2), ("Pune", "C", 1), ("Solapur", "U", 1), ("Solapur", "C", 1),
    ("Pavagada", "U", 2), ("Bengaluru", "R", 2), ("Bengaluru", "C", 1), ("Anantapur", "U", 2),
    ("Kurnool", "U", 1), ("Kurnool", "C", 1), ("Mahbubnagar", "U", 1), ("Mahbubnagar", "C", 1),
    ("Tirunelveli", "U", 2), ("Coimbatore", "C", 1), ("Coimbatore", "R", 1), ("Kochi", "F", 1),
    ("Kochi", "R", 1), ("Rewa", "U", 2), ("Neemuch", "U", 1), ("Neemuch", "C", 1),
    ("Khandwa", "F", 2), ("Raipur", "C", 1), ("Raipur", "R", 1), ("Bhubaneswar", "C", 1),
    ("Bhubaneswar", "R", 1), ("Kolkata", "R", 2), ("Kolkata", "C", 1), ("Patna", "C", 1),
    ("Patna", "R", 1), ("Guwahati", "R", 1), ("Guwahati", "C", 1), ("Guwahati", "U", 1),
    ("Agartala", "R", 1), ("Agartala", "U", 1),
]

# (city, type, n-th project of that city/type) -> lifecycle
COMMISSIONED_IN_WINDOW = {
    ("Bikaner", "U", 2), ("Bhuj", "U", 2), ("Pune", "R", 2), ("Pavagada", "U", 2),
    ("Bengaluru", "R", 2), ("Rewa", "U", 2), ("Kolkata", "R", 2), ("Coimbatore", "R", 1),
    ("Neemuch", "C", 1), ("Kurnool", "C", 1), ("Agartala", "U", 1),
}
UNDER_CONSTRUCTION = {("Jaisalmer", "U", 3), ("Anantapur", "U", 2), ("Khandwa", "F", 2), ("Guwahati", "U", 1)}

# Planted scenarios: the analysis should rediscover these without being told.
PLANTED = {
    ("Jaisalmer", "U", 1): "SOILING",        # cleaning contract lapsed Apr-24..Dec-25
    ("Jodhpur", "U", 1): "CURTAILMENT",      # grid congestion from Oct-24, not logged as downtime
    ("Bikaner", "U", 1): "CURTAILMENT",
    ("Patna", "R", 1): "INVERTER_FAILURES",  # chronic downtime from Jan-24
    ("Hisar", "U", 1): "HAILSTORM",          # May-25 event: downtime + repair cost spike
    ("Raipur", "C", 1): "OM_COST_OVERRUN",   # O&M contract ~2.3x peers
    ("Kochi", "F", 1): "CAPEX_OVERRUN",      # built at ~30% over budget
}

ROMAN = ["I", "II", "III", "IV"]


# --------------------------------------------------------------------------
# 2. Masters: locations and projects
# --------------------------------------------------------------------------

def build_locations() -> pd.DataFrame:
    rows = []
    for code, state, region, city, lat, lon, ghi, *_ in LOCATIONS:
        rows.append({
            "location_code": code, "country": "India", "state": state, "region": region,
            "city": city, "latitude": lat, "longitude": lon,
            "annual_ghi_kwh_m2_day": ghi, "solar_zone": solar_zone(ghi),
        })
    return pd.DataFrame(rows)


def random_date(start: str, end: str) -> pd.Timestamp:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return s + pd.Timedelta(days=int(rng.integers(0, (e - s).days + 1)))


def build_projects(locations: pd.DataFrame) -> pd.DataFrame:
    loc_by_city = locations.set_index("city")
    rows = []
    pid = 0
    for city, t, count in PROJECT_PLAN:
        loc = loc_by_city.loc[city]
        for n in range(1, count + 1):
            pid += 1
            key = (city, t, n)

            if t == "U":
                capacity = round(float(np.exp(rng.uniform(np.log(25), np.log(300)))) / 5) * 5
                if loc.region == "North-East":
                    capacity = min(capacity, 40)
            elif t == "C":
                capacity = round(float(rng.uniform(5, 50)) * 2) / 2
            elif t == "R":
                capacity = round(float(rng.uniform(0.5, 5)), 1)
            else:
                capacity = round(float(rng.uniform(10, 100)) / 5) * 5

            lo, hi = CAPEX_CR_PER_MW[t]
            capex_per_mw = rng.uniform(lo, hi)
            capex_per_mw *= {"North-East": 1.12, "East": 1.05}.get(loc.region, 1.0)
            if t == "U" and capacity < 50:
                capex_per_mw *= 1.04                       # loss of scale economies
            if PLANTED.get(key) == "CAPEX_OVERRUN":
                capex_per_mw *= 1.30
            investment = round(capacity * capex_per_mw * CRORE, -4)   # nearest INR 10k

            if t == "U":
                if loc.state == "Rajasthan":
                    tariff = rng.uniform(2.42, 2.58)
                elif loc.state == "Gujarat":
                    tariff = rng.uniform(2.55, 2.75)
                elif loc.region == "North-East":
                    tariff = rng.uniform(3.20, 3.45)
                else:
                    tariff = rng.uniform(2.60, 3.00)
            elif t == "C":
                tariff = rng.uniform(3.70, 4.50)
                if loc.state in {"Maharashtra", "Karnataka", "Tamil Nadu"}:
                    tariff += 0.25
            elif t == "R":
                tariff = rng.uniform(4.20, 5.40)
            else:
                tariff = rng.uniform(3.25, 3.60)

            if key in UNDER_CONSTRUCTION:
                install, status = random_date("2026-05-01", "2026-12-31"), "Under Construction"
            elif key in COMMISSIONED_IN_WINDOW:
                install, status = random_date("2023-06-01", "2025-09-30"), "Operational"
            else:
                install, status = random_date("2017-01-01", "2023-02-15"), "Operational"

            rows.append({
                "project_code": f"P{pid:03d}",
                "project_name": f"{city} {NAME_SUFFIX[t]} {ROMAN[n - 1]}",
                "location_code": loc.location_code,
                "project_type": TYPE_LABEL[t],
                "installation_date": install.date().isoformat(),
                "capacity_mw": capacity,
                "investment_amount_inr": investment,
                "ppa_tariff_inr_per_kwh": round(float(tariff), 2),
                "project_status": status,
                "record_updated_at": "2026-04-10 09:00:00",
                # internal only, dropped before writing raw
                "int_type": t, "int_city": city, "int_key": key,
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 3. Monthly facts
# --------------------------------------------------------------------------

def fiscal_index(ts: pd.Timestamp) -> int:
    """0 = April ... 11 = March."""
    return (ts.month - 4) % 12


def fiscal_year(ts: pd.Timestamp) -> int:
    """FY ending year, e.g. Apr-2023 -> 2024 (FY2023-24)."""
    return ts.year + 1 if ts.month >= 4 else ts.year


def build_facts(locations: pd.DataFrame, projects: pd.DataFrame):
    loc_meta = {row[0]: row for row in LOCATIONS}
    irr_profiles = {k: np.array(v) / np.mean(v) for k, v in IRRADIATION_PROFILES.items()}

    # Year-to-year weather variation per region (e.g. a weak monsoon year)
    regions = sorted(locations.region.unique())
    year_factor = {(r, fy): rng.normal(1.0, 0.025) for r in regions for fy in (2024, 2025, 2026)}
    # Month-level weather shared by all projects in a city
    city_weather = {(code, m): rng.normal(1.0, 0.035) for code in locations.location_code for m in MONTHS}

    energy_rows, fin_rows, demand_rows, planted_log = [], [], [], []

    for p in projects.itertuples(index=False):
        if p.project_status == "Under Construction":
            continue
        _, state, region, city, _, _, ghi, irr_prof, temp_prof, temp_off = loc_meta[p.location_code]
        t, key = p.int_type, p.int_key
        scenario = PLANTED.get(key)
        install = pd.Timestamp(p.installation_date)
        first_month = (install + pd.offsets.MonthBegin(1)).normalize()
        pr_ex_temp = rng.normal(PR_EX_TEMP[t], 0.012)
        base_downtime = {"East": 9, "North-East": 12}.get(region, 5) + (2 if t == "R" else 0)
        maint_multiplier = 2.3 if scenario == "OM_COST_OVERRUN" else rng.normal(1.0, 0.06)
        demand_share = rng.uniform(0.25, 0.65) if t == "C" else rng.uniform(0.10, 0.35)

        for m in MONTHS:
            if m < first_month:
                continue
            fi, fy = fiscal_index(m), fiscal_year(m)
            days = m.days_in_month
            hours = days * 24
            months_live = (m.year - first_month.year) * 12 + m.month - first_month.month

            # --- weather ---------------------------------------------------
            weather = irr_profiles[irr_prof][fi] * year_factor[(region, fy)] * city_weather[(p.location_code, m)]
            ghi_month = ghi * weather * days                                  # kWh/m2 for the month
            cloud = float(np.clip(22 + 110 * (1 - weather) + (8 if region == "North-East" else 0)
                                  + rng.normal(0, 4), 3, 92))
            temp = TEMPERATURE_PROFILES[temp_prof][fi] + temp_off + rng.normal(0, 0.8)

            # --- availability ------------------------------------------------
            downtime = float(rng.gamma(1.5, base_downtime / 1.5))
            if rng.random() < 0.025:
                downtime += rng.uniform(30, 120)                              # random major outage
            if scenario == "INVERTER_FAILURES" and m >= pd.Timestamp("2024-01-01") and rng.random() < 0.7:
                downtime = rng.uniform(55, 130)
            if scenario == "HAILSTORM" and m == pd.Timestamp("2025-05-01"):
                downtime = 290.0
            if scenario == "HAILSTORM" and m == pd.Timestamp("2025-06-01"):
                downtime = 140.0
            downtime = min(downtime, days * 12)
            availability = 1 - downtime / (days * 12)                         # ~12 daylight hours

            # --- energy model -----------------------------------------------
            temp_loss = TEMP_COEFF * max(0.0, temp + CELL_TEMP_RISE[t] - 25)
            age_years = max(0.0, (m - install).days / 365.25)
            degradation = DEGRADATION_PER_YEAR * age_years
            ramp = {0: 0.88, 1: 0.95}.get(months_live, 1.0)                   # commissioning ramp-up

            hidden_loss = 0.0
            if scenario == "SOILING":
                if pd.Timestamp("2024-04-01") <= m <= pd.Timestamp("2025-12-01"):
                    k = (m.year - 2024) * 12 + m.month - 4 + 1
                    hidden_loss = min(0.012 * k, 0.20)
                elif m >= pd.Timestamp("2026-01-01"):
                    hidden_loss = 0.03
            if scenario == "CURTAILMENT" and m >= pd.Timestamp("2024-10-01"):
                hidden_loss = rng.uniform(0.07, 0.12) + (0.05 if fi in (0, 1, 10, 11) else 0.0)

            energy_mwh = (p.capacity_mw * ghi_month * POA_GAIN[t] * pr_ex_temp * (1 - temp_loss)
                          * (1 - degradation) * availability * ramp * (1 - hidden_loss))
            energy_mwh = round(energy_mwh, 3)
            capacity_factor = round(energy_mwh / (p.capacity_mw * hours), 4)

            if hidden_loss > 0:
                planted_log.append({"project_code": p.project_code, "month": m.date().isoformat(),
                                    "scenario": scenario, "hidden_loss_pct": round(hidden_loss * 100, 2)})

            energy_rows.append({
                "project_code": p.project_code,
                "reading_month": m.date().isoformat(),
                "energy_generated_mwh": energy_mwh,
                "capacity_factor": capacity_factor,
                "irradiation_kwh_m2": round(ghi_month, 1),
                "avg_temperature_c": round(temp, 1),
                "cloud_cover_pct": round(cloud, 1),
                "downtime_hours": round(downtime, 1),
                "source_system": "SCADA",
            })

            # --- financials -------------------------------------------------
            inflation = (1 + COST_INFLATION) ** (fy - 2024)
            revenue = round(energy_mwh * p.ppa_tariff_inr_per_kwh * 1000, 2)   # billing meter = SCADA
            fixed_opex = p.capacity_mw * FIXED_OPEX_LAKH_PER_MW_YR[t] * LAKH / 12 * inflation * rng.normal(1, 0.03)
            maint = p.capacity_mw * OM_LAKH_PER_MW_YR[t] * LAKH / 12 * inflation * rng.normal(1, 0.08)
            maint *= maint_multiplier
            if scenario == "SOILING" and pd.Timestamp("2024-04-01") <= m <= pd.Timestamp("2025-12-01"):
                maint *= 0.70                                                 # cleaning not being paid for
            maint += downtime * (2500 + 150 * p.capacity_mw)                  # corrective maintenance
            if scenario == "HAILSTORM" and m == pd.Timestamp("2025-05-01"):
                maint += 0.015 * p.investment_amount_inr * 0.6                # module replacement
            if scenario == "HAILSTORM" and m == pd.Timestamp("2025-06-01"):
                maint += 0.015 * p.investment_amount_inr * 0.4
            depreciation = p.investment_amount_inr / ASSET_LIFE_YEARS / 12

            fin_rows.append({
                "project_code": p.project_code,
                "period_month": m.date().isoformat(),
                "revenue_inr": revenue,
                "operating_cost_inr": round(fixed_opex, 2),
                "maintenance_cost_inr": round(maint, 2),
                "depreciation_inr": round(depreciation, 2),
                "currency": "INR",
            })

            # --- client site demand (captive projects only) ------------------
            if t in ("C", "R"):
                expected = p.capacity_mw * ghi * days * POA_GAIN[t] * 0.78
                summer = 1.08 if fi in (0, 1, 2) else 1.0
                demand_rows.append({
                    "project_code": p.project_code,
                    "period_month": m.date().isoformat(),
                    "site_consumption_mwh": round(expected / demand_share * summer * rng.normal(1, 0.06), 3),
                })

    return (pd.DataFrame(energy_rows), pd.DataFrame(fin_rows),
            pd.DataFrame(demand_rows), pd.DataFrame(planted_log))


# --------------------------------------------------------------------------
# 4. Data-quality defect injection (raw layer only)
# --------------------------------------------------------------------------

def pick(df: pd.DataFrame, n: int, used: set) -> list[int]:
    """Pick n row indexes not already used by another defect."""
    candidates = [i for i in df.index if i not in used]
    chosen = [int(i) for i in rng.choice(candidates, size=n, replace=False)]
    used.update(chosen)
    return chosen


def inject_defects(locations, projects, energy, fin):
    log = []
    loc, proj, en, fn = locations.copy(), projects.copy(), energy.copy(), fin.copy()

    # ---- locations ----
    i = loc.index[loc.city == "Jodhpur"][0];   loc.loc[i, "city"] = "  jodhpur ";  log.append(("raw_locations", "L002", "city whitespace/case"))
    i = loc.index[loc.city == "Bengaluru"][0]; loc.loc[i, "city"] = "BENGALURU";   log.append(("raw_locations", "L013", "city upper case"))
    i = loc.index[loc.city == "Coimbatore"][0]; loc.loc[i, "state"] = "Tamilnadu"; log.append(("raw_locations", "L018", "state spelling variant"))
    loc = pd.concat([loc, loc[loc.location_code == "L021"]], ignore_index=True)
    log.append(("raw_locations", "L021", "exact duplicate row"))

    # ---- projects ----
    stale = proj[proj.project_code == "P010"].copy()
    stale["capacity_mw"] = stale["capacity_mw"] * 0.8
    stale["investment_amount_inr"] = round(float(stale["investment_amount_inr"].iloc[0]) * 0.8, -4)
    stale["record_updated_at"] = "2024-11-02 17:45:00"
    proj = pd.concat([proj, stale], ignore_index=True)
    log.append(("raw_projects", "P010", "stale duplicate (older record_updated_at, old capacity)"))
    i = proj.index[proj.project_code == "P014"][0]; proj.loc[i, "project_type"] = " utility-scale"; log.append(("raw_projects", "P014", "project_type case/whitespace"))
    i = proj.index[proj.project_code == "P030"][0]; proj.loc[i, "location_code"] = "l-19"; log.append(("raw_projects", "P030", "location_code format 'l-19'"))
    i = proj.index[proj.project_code == "P022"][0]; proj.loc[i, "investment_amount_inr"] *= -1; log.append(("raw_projects", "P022", "negative investment (sign error)"))
    test_row = {c: None for c in proj.columns}
    test_row.update({"project_code": "P_TEST", "project_name": "TEST - do not use", "project_type": "Rooftop",
                     "installation_date": "2025-01-01", "capacity_mw": 0, "investment_amount_inr": 0,
                     "ppa_tariff_inr_per_kwh": 0, "project_status": "Operational",
                     "record_updated_at": "2025-01-01 00:00:00"})
    proj = pd.concat([proj, pd.DataFrame([test_row])], ignore_index=True)
    log.append(("raw_projects", "P_TEST", "test record with no location"))

    # ---- energy (SCADA) ----
    used: set = set()
    for idx in pick(en, 6, used):
        en.loc[idx, ["energy_generated_mwh", "capacity_factor"]] *= -1
        log.append(("raw_energy_generation", f"{en.loc[idx,'project_code']}|{en.loc[idx,'reading_month']}", "negative energy (sign error)"))
    for idx in pick(en, 5, used):
        en.loc[idx, "capacity_factor"] = round(en.loc[idx, "capacity_factor"] * 100, 2)
        log.append(("raw_energy_generation", f"{en.loc[idx,'project_code']}|{en.loc[idx,'reading_month']}", "capacity_factor in percent"))
    for idx in pick(en, 4, used):
        en.loc[idx, "energy_generated_mwh"] = round(en.loc[idx, "energy_generated_mwh"] * 10, 3)
        en.loc[idx, "capacity_factor"] = round(en.loc[idx, "capacity_factor"] * 10, 4)
        log.append(("raw_energy_generation", f"{en.loc[idx,'project_code']}|{en.loc[idx,'reading_month']}", "meter spike x10"))
    for idx in pick(en, 4, used):
        en.loc[idx, ["energy_generated_mwh", "capacity_factor"]] = np.nan
        log.append(("raw_energy_generation", f"{en.loc[idx,'project_code']}|{en.loc[idx,'reading_month']}", "energy NULL"))
    bad_dates = {"-02-": "2024-02-30", "-11-": "2023-11-31", "-06-": "2025-06-31"}
    for idx in pick(en, 3, used):
        true_month = en.loc[idx, "reading_month"]
        en.loc[idx, "reading_month"] = rng.choice(list(bad_dates.values()))
        log.append(("raw_energy_generation", f"{en.loc[idx,'project_code']}|{true_month}", "invalid date string"))
    for idx in pick(en, 8, used):
        d = pd.Timestamp(en.loc[idx, "reading_month"])
        en.loc[idx, "reading_month"] = d.strftime("%d-%m-%Y")
        log.append(("raw_energy_generation", f"{en.loc[idx,'project_code']}|{d.date()}", "date in DD-MM-YYYY"))
    for idx in pick(en, 2, used):
        en.loc[idx, ["irradiation_kwh_m2", "cloud_cover_pct"]] = np.nan
        log.append(("raw_energy_generation", f"{en.loc[idx,'project_code']}|{en.loc[idx,'reading_month']}", "weather sensor NULL"))
    orphans = en.sample(3, random_state=SEED).copy()
    orphans["project_code"] = ["P999", "P999", "P0611"]
    en = pd.concat([en, orphans], ignore_index=True)
    log += [("raw_energy_generation", c, "orphan project_code") for c in orphans.project_code]
    dups = en.loc[[i for i in en.index if i not in used]].sample(12, random_state=SEED + 1)
    en = pd.concat([en, dups], ignore_index=True)
    log += [("raw_energy_generation", f"{r.project_code}|{r.reading_month}", "exact duplicate") for r in dups.itertuples()]

    # ---- financials (ERP) ----
    used_f: set = set()
    for idx in pick(fn, 3, used_f):
        fn.loc[idx, "maintenance_cost_inr"] = np.nan
        log.append(("raw_financials", f"{fn.loc[idx,'project_code']}|{fn.loc[idx,'period_month']}", "maintenance_cost NULL"))
    for idx in pick(fn, 2, used_f):
        fn.loc[idx, "operating_cost_inr"] *= -1
        log.append(("raw_financials", f"{fn.loc[idx,'project_code']}|{fn.loc[idx,'period_month']}", "negative operating cost (sign error)"))
    fdups = fn.sample(6, random_state=SEED + 2)
    fn = pd.concat([fn, fdups], ignore_index=True)
    log += [("raw_financials", f"{r.project_code}|{r.period_month}", "exact duplicate") for r in fdups.itertuples()]

    # shuffle so defects are not clustered at the end of the files
    en = en.sample(frac=1, random_state=SEED).reset_index(drop=True)
    fn = fn.sample(frac=1, random_state=SEED).reset_index(drop=True)
    return loc, proj, en, fn, pd.DataFrame(log, columns=["file", "record", "defect"])


# --------------------------------------------------------------------------
# 5. Main
# --------------------------------------------------------------------------

def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)

    locations = build_locations()
    projects = build_projects(locations)
    energy, fin, demand, planted = build_facts(locations, projects)

    # Expected clean totals: the SQL cleaning layer must reproduce these.
    operational = projects[projects.project_status == "Operational"]
    truth = {
        "snapshot_date": SNAPSHOT_DATE.date().isoformat(),
        "window": [MONTHS[0].date().isoformat(), MONTHS[-1].date().isoformat()],
        "locations": len(locations), "cities": locations.city.nunique(),
        "states": locations.state.nunique(), "regions": locations.region.nunique(),
        "projects": len(projects), "operational_projects": len(operational),
        "under_construction_projects": int((projects.project_status == "Under Construction").sum()),
        "total_capacity_mw": round(float(projects.capacity_mw.sum()), 1),
        "operational_capacity_mw": round(float(operational.capacity_mw.sum()), 1),
        "total_investment_inr": float(projects.investment_amount_inr.sum()),
        "energy_rows": len(energy), "financial_rows": len(fin), "consumption_rows": len(demand),
        "total_energy_mwh": round(float(energy.energy_generated_mwh.sum()), 3),
        "total_revenue_inr": round(float(fin.revenue_inr.sum()), 2),
        "total_operating_cost_inr": round(float(fin.operating_cost_inr.sum()), 2),
        "total_maintenance_cost_inr": round(float(fin.maintenance_cost_inr.sum()), 2),
        "total_depreciation_inr": round(float(fin.depreciation_inr.sum()), 2),
        "planted_scenarios": {
            projects.loc[projects.int_key == k, "project_code"].iloc[0]: v for k, v in PLANTED.items()
        },
    }

    loc_raw, proj_raw, en_raw, fin_raw, defects = inject_defects(
        locations, projects.drop(columns=["int_type", "int_city", "int_key"]), energy, fin)

    loc_raw.to_csv(RAW_DIR / "raw_locations.csv", index=False)
    proj_raw.to_csv(RAW_DIR / "raw_projects.csv", index=False)
    en_raw.to_csv(RAW_DIR / "raw_energy_generation.csv", index=False)
    fin_raw.to_csv(RAW_DIR / "raw_financials.csv", index=False)
    demand.to_csv(RAW_DIR / "raw_offtaker_consumption.csv", index=False)

    defects.to_csv(TRUTH_DIR / "injected_defects.csv", index=False)
    planted.to_csv(TRUTH_DIR / "planted_scenario_months.csv", index=False)
    (TRUTH_DIR / "expected_clean_totals.json").write_text(json.dumps(truth, indent=2))

    print(f"locations={len(loc_raw)} projects={len(proj_raw)} energy={len(en_raw)} "
          f"financials={len(fin_raw)} consumption={len(demand)} defects={len(defects)}")
    print(json.dumps({k: v for k, v in truth.items() if k != "planted_scenarios"}, indent=2))
    print("planted:", truth["planted_scenarios"])


if __name__ == "__main__":
    main()
