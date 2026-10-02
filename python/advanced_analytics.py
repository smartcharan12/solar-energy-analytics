"""
Stage 3 - Advanced analytics on the clean MySQL star schema.

  1. Correlation analysis at two grains (project-month and project), with a
     partial correlation that separates temperature from irradiation.
  2. Expected-generation model: what SHOULD each plant have produced given its
     weather? The gap is split into downtime loss and unexplained loss (INR).
  3. Anomaly detection with robust z-scores (median / MAD) and root-cause rules.
  4. Pareto and ABC classification.
  5. Results written back to MySQL (ana_* tables) for Power BI, plus CSVs and charts.
  6. A SEPARATE evaluation against data/ground_truth/. The analysis above never
     reads ground truth; thresholds are fixed constants chosen before evaluation.

Run (MySQL running, after sql/run_all.sh):  python python/advanced_analytics.py
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from sqlalchemy import text

from db import get_engine

ROOT = Path(__file__).resolve().parents[1]
OUT_DATA = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"

# Detection thresholds, fixed up front (Iglewicz & Hoaglin robust-z convention).
ROBUST_Z = 3.5              # |robust z| above this is an outlier
ONSET_LOSS = -0.05          # 3-month mean residual below -5% marks the onset of a loss
PROGRESSIVE_GAP = -0.03     # later residual >= 3 pp worse than at onset = progressive loss
CAPEX_PREMIUM = 1.15        # capex above 115% of benchmark
MIN_PEERS = 5               # peer statistics need at least this many projects

# Chart tokens (reference palette, light mode; validated with the dataviz validator)
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
DIVERGING = LinearSegmentedColormap.from_list("blue_red", ["#e34948", "#f0efec", "#2a78d6"])
CRITICAL = "#d03b3b"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def to_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """PyMySQL returns DECIMAL as Python Decimal objects; convert to float."""
    for col in df.columns:
        if df[col].dtype == object:
            sample = df[col].dropna()
            if len(sample) and isinstance(sample.iloc[0], Decimal):
                df[col] = df[col].astype(float)
    return df


def robust_z(x: pd.Series) -> pd.Series:
    """(x - median) / (1.4826 * MAD). Insensitive to the outliers it is hunting."""
    med = x.median()
    mad = (x - med).abs().median()
    if not mad or np.isnan(mad):
        return pd.Series(np.nan, index=x.index)
    return (x - med) / (1.4826 * mad)


def pearson_with_p(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    """Pearson r with a two-sided p-value (normal approximation, fine for n > 100)."""
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    r = float(np.corrcoef(x, y)[0, 1])
    t = r * math.sqrt((n - 2) / max(1e-12, 1 - r * r))
    return r, math.erfc(abs(t) / math.sqrt(2)), n


def residualise(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return y - X1 @ beta


def style_axes(ax, grid_axis="y"):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=9)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)


def new_figure(*args, **kwargs):
    fig, axes = plt.subplots(*args, **kwargs)
    fig.patch.set_facecolor(SURFACE)
    return fig, axes


def save(fig, name: str) -> None:
    fig.savefig(FIG_DIR / name, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


# --------------------------------------------------------------------------
# 0. Load
# --------------------------------------------------------------------------

def load(conn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pm = to_numeric(pd.read_sql(text("""
        SELECT m.*, d.installation_date, d.capex_cr_per_mw, d.project_status
        FROM vw_project_month m
        JOIN vw_dim_project d ON d.project_id = m.project_id"""), conn))
    pm["month_start_date"] = pd.to_datetime(pm.month_start_date)
    pm["installation_date"] = pd.to_datetime(pm.installation_date)
    pm = pm.sort_values(["project_id", "month_start_date"]).reset_index(drop=True)
    # Operating month number since commissioning: 1 = first month of output.
    # Only meaningful for plants commissioned inside the window; older plants
    # get 99 so the ramp-up dummies never fire for them.
    k = (pm.month_start_date.dt.to_period("M") - pm.installation_date.dt.to_period("M")).apply(lambda x: x.n)
    new_build = pm.installation_date >= pm.month_start_date.min()
    pm["op_month_no"] = np.where(new_build, k - k.groupby(pm.project_id).transform("min") + 1, 99)

    pp = to_numeric(pd.read_sql(text("SELECT * FROM vw_project_performance"), conn))
    bench = to_numeric(pd.read_sql(text("SELECT * FROM ref_capex_benchmark"), conn))
    return pm, pp, bench


# --------------------------------------------------------------------------
# 1. Correlation analysis
# --------------------------------------------------------------------------

def correlation_analysis(pm: pd.DataFrame, pp: pd.DataFrame) -> dict:
    results = {}

    # 1a. Project-month grain: physical drivers of generation
    month_vars = {
        "irradiation_kwh_m2": "Irradiation", "avg_temperature_c": "Temperature",
        "cloud_cover_pct": "Cloud cover", "downtime_hours": "Downtime",
        "capacity_mw": "Capacity", "energy_generated_mwh": "Generation",
        "capacity_factor": "Capacity factor", "revenue_inr": "Revenue",
    }
    m = pm[list(month_vars)].dropna().rename(columns=month_vars)
    results["month_pearson"] = m.corr(method="pearson").round(3)
    results["month_spearman"] = m.corr(method="spearman").round(3)
    results["month_n"] = len(m)

    # 1b. Project grain: what drives ROI? (ROI only exists per project)
    proj_vars = {
        "capacity_mw": "Capacity", "capex_cr_per_mw": "Capex/MW", "ppa_tariff_inr_per_kwh": "Tariff",
        "capacity_factor": "Capacity factor", "performance_ratio_ghi": "Performance ratio",
        "availability": "Availability", "maintenance_lakh_per_mw_yr": "O&M/MW", "roi_pct": "ROI",
    }
    p = pp[list(proj_vars)].rename(columns=proj_vars)
    results["project_spearman"] = p.corr(method="spearman").round(3)
    results["project_n"] = len(p)

    # 1c. Temperature: raw vs partial correlation with capacity factor.
    #     Hot months are also sunny months, so the raw correlation is confounded.
    w = pm.dropna(subset=["irradiation_kwh_m2", "avg_temperature_c"]).copy()
    # irradiation per day, so 28- and 31-day months are comparable with CF
    w["irr_day"] = w.irradiation_kwh_m2 / (w.hours_in_month / 24)
    r_raw, p_raw, n = pearson_with_p(w.avg_temperature_c.values, w.capacity_factor.values)
    t_res = residualise(w.avg_temperature_c.values, w[["irr_day"]].values)
    cf_res = residualise(w.capacity_factor.values, w[["irr_day"]].values)
    r_partial, p_partial, _ = pearson_with_p(t_res, cf_res)
    # within-project: remove each plant's own level (technology, location) first
    for col in ("avg_temperature_c", "capacity_factor", "irr_day"):
        w[col + "_dm"] = w[col] - w.groupby("project_id")[col].transform("mean")
    t_res2 = residualise(w.avg_temperature_c_dm.values, w[["irr_day_dm"]].values)
    cf_res2 = residualise(w.capacity_factor_dm.values, w[["irr_day_dm"]].values)
    r_within, p_within, _ = pearson_with_p(t_res2, cf_res2)
    results["temperature"] = {
        "n": n,
        "raw_r": round(r_raw, 3), "raw_p": p_raw,
        "partial_r_given_irradiation": round(r_partial, 3), "partial_p": p_partial,
        "within_project_partial_r": round(r_within, 3), "within_p": p_within,
    }

    # 1d. Cloud cover vs irradiation (is cloud just a proxy for less sun?)
    r_cloud, _, _ = pearson_with_p(w.cloud_cover_pct.values, w.irr_day.values)
    results["cloud_vs_irradiation_r"] = round(r_cloud, 3)
    return results


# --------------------------------------------------------------------------
# 2. Expected-generation model
# --------------------------------------------------------------------------

def expected_generation(pm: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Model the weather-normalised performance ratio:
        pr_eff = energy / (capacity x irradiation x availability)
    Removing availability makes downtime a separate, measured loss.
    pr_eff ~ technology + (temperature - 25) + plant age + commissioning ramp-up

    Fitted with trimmed least squares: fit, drop rows with |robust z| > 3.5,
    refit. Plants with genuine problems would otherwise drag the 'healthy'
    benchmark down and hide themselves.
    """
    d = pm.copy()
    d["days"] = d.hours_in_month / 24
    d["availability"] = 1 - d.downtime_hours / (d.days * 12)
    d["pr_eff"] = d.energy_generated_mwh / (d.capacity_mw * d.irradiation_kwh_m2 * d.availability)
    d["age_years"] = (d.month_start_date - d.installation_date).dt.days / 365.25
    usable = d.dropna(subset=["pr_eff"]).index

    def design(frame: pd.DataFrame) -> np.ndarray:
        return np.column_stack([
            np.ones(len(frame)),
            (frame.project_type == "C&I Open Access").astype(float),
            (frame.project_type == "Rooftop").astype(float),
            (frame.project_type == "Floating").astype(float),
            frame.avg_temperature_c - 25,
            frame.age_years,
            (frame.op_month_no == 1).astype(float),
            (frame.op_month_no == 2).astype(float),
        ])

    names = ["intercept (utility)", "C&I", "Rooftop", "Floating", "temp_minus_25C",
             "age_years", "first_month", "second_month"]
    fit_rows = usable
    for _ in range(2):
        X, y = design(d.loc[fit_rows]), d.loc[fit_rows, "pr_eff"].values
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = pd.Series(y - X @ beta, index=fit_rows)
        fit_rows = resid.index[robust_z(resid).abs() <= ROBUST_Z]

    X_all = design(d.loc[usable])
    d.loc[usable, "pr_expected"] = X_all @ beta
    y_fit = d.loc[fit_rows, "pr_eff"].values
    pred_fit = design(d.loc[fit_rows]) @ beta
    r2 = 1 - ((y_fit - pred_fit) ** 2).sum() / ((y_fit - y_fit.mean()) ** 2).sum()

    d["potential_mwh"] = d.pr_expected * d.capacity_mw * d.irradiation_kwh_m2      # at 100% availability
    d["expected_mwh"] = d.potential_mwh * d.availability
    d["downtime_loss_mwh"] = d.potential_mwh - d.expected_mwh
    d["unexplained_loss_mwh"] = d.expected_mwh - d.energy_generated_mwh          # > 0 = shortfall
    d["residual_pct"] = d.energy_generated_mwh / d.expected_mwh - 1
    d["downtime_loss_inr"] = d.downtime_loss_mwh * d.ppa_tariff_inr_per_kwh * 1000
    d["unexplained_loss_inr"] = d.unexplained_loss_mwh * d.ppa_tariff_inr_per_kwh * 1000

    mean_pr = d.loc[fit_rows, "pr_eff"].mean()
    info = {
        "coefficients": dict(zip(names, np.round(beta, 5))),
        "r2_on_fit_rows": round(float(r2), 3),
        "rows_usable": int(len(usable)),
        "rows_fitted_after_trim": int(len(fit_rows)),
        "temp_coeff_pct_per_c": round(100 * beta[4] / mean_pr, 3),
        "degradation_pct_per_year": round(100 * beta[5] / mean_pr, 3),
        "residual_sd_pct": round(100 * float(d.loc[fit_rows, "residual_pct"].std()), 2),
    }
    return d, info


# --------------------------------------------------------------------------
# 3. Anomaly detection and root-cause rules
# --------------------------------------------------------------------------

def month_anomalies(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["z_residual"] = d.groupby("project_id").residual_pct.transform(robust_z)
    d["z_downtime"] = d.groupby("project_type").downtime_hours.transform(robust_z)
    d["maint_per_mw"] = d.maintenance_cost_inr / d.capacity_mw
    d["z_maintenance"] = d.groupby("project_id").maint_per_mw.transform(robust_z)
    d["maint_median"] = d.groupby("project_id").maint_per_mw.transform("median")
    flags = []
    for r in d.itertuples():
        f = []
        # Statistical AND practical significance: a robust z alone over-flags
        # projects with few months, whose MAD is tiny.
        if r.z_residual < -ROBUST_Z and r.residual_pct < ONSET_LOSS:
            f.append("generation far below expected")
        if r.z_downtime > ROBUST_Z and r.downtime_hours > 48:
            f.append("downtime spike")
        if r.z_maintenance > ROBUST_Z and r.maint_per_mw > 2 * r.maint_median:
            f.append("maintenance cost spike")
        flags.append("; ".join(f))
    d["month_flags"] = flags
    return d


def loss_onset(series: pd.DataFrame) -> tuple[pd.Timestamp | None, str | None]:
    """First month whose forward 3-month mean residual < ONSET_LOSS, and the loss shape."""
    s = series.dropna(subset=["residual_pct"]).set_index("month_start_date").residual_pct
    fwd = s.rolling(3).mean().shift(-2)
    hits = fwd.index[fwd < ONSET_LOSS]
    if not len(hits):
        return None, None
    window = s.loc[hits[0]:].iloc[:3]
    below = window.index[window < ONSET_LOSS]
    onset = below[0] if len(below) else hits[0]
    after = s.loc[onset:]
    early, late = after.iloc[:3].mean(), after.iloc[3:9].mean()
    shape = "progressive" if len(after) > 6 and late - early < PROGRESSIVE_GAP else "step"
    return onset, shape


def project_diagnostics(d: pd.DataFrame, pp: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    g = d.groupby("project_id")
    diag = pd.DataFrame({
        "project_code": g.project_code.first(),
        "project_name": g.project_name.first(),
        "project_type": g.project_type.first(),
        "region": g.region.first(),
        "state": g.state.first(),
        "potential_mwh": g.potential_mwh.sum(),
        "expected_mwh": g.expected_mwh.sum(),
        "actual_mwh_modelled_months": g.apply(lambda x: x.loc[x.expected_mwh.notna(), "energy_generated_mwh"].sum(),
                                              include_groups=False),
        "downtime_loss_mwh": g.downtime_loss_mwh.sum(),
        "unexplained_loss_mwh": g.unexplained_loss_mwh.sum(),
        "downtime_loss_inr": g.downtime_loss_inr.sum(),
        "unexplained_loss_inr": g.unexplained_loss_inr.sum(),
    })
    diag["downtime_loss_pct"] = diag.downtime_loss_mwh / diag.potential_mwh
    diag["unexplained_loss_pct"] = diag.unexplained_loss_mwh / diag.expected_mwh

    # Latest fiscal year: what is the situation NOW?
    latest = d[d.fiscal_year == d.fiscal_year.max()].groupby("project_id")
    diag["latest_fy_residual_pct"] = latest.energy_generated_mwh.sum() / latest.expected_mwh.sum() - 1
    diag["z_latest_residual"] = robust_z(diag.latest_fy_residual_pct)
    diag["z_downtime_loss"] = robust_z(diag.downtime_loss_pct)

    diag = diag.join(pp.set_index("project_id")[["maintenance_lakh_per_mw_yr", "capex_cr_per_mw", "roi_pct"]])
    peer_n = diag.groupby("project_type").project_code.transform("count")
    diag["z_maintenance_vs_peers"] = diag.groupby("project_type").maintenance_lakh_per_mw_yr.transform(robust_z)
    diag.loc[peer_n < MIN_PEERS, "z_maintenance_vs_peers"] = np.nan
    diag = diag.join(bench.set_index("project_type").benchmark_cr_per_mw, on="project_type")
    diag["capex_vs_benchmark"] = diag.capex_cr_per_mw / diag.benchmark_cr_per_mw

    onsets = {pid: loss_onset(grp) for pid, grp in d.groupby("project_id")}
    diag["loss_onset"] = [onsets[pid][0] for pid in diag.index]
    diag["loss_shape"] = [onsets[pid][1] for pid in diag.index]

    # Root-cause rules (a project can carry several)
    reliability = diag.z_downtime_loss > ROBUST_Z
    unexplained = diag.z_latest_residual < -ROBUST_Z
    cost = diag.z_maintenance_vs_peers > ROBUST_Z
    capital = diag.capex_vs_benchmark > CAPEX_PREMIUM

    # Regional co-onset: >= 2 unexplained-loss projects in the same state whose
    # losses start within one month of each other point at a shared external
    # cause (grid curtailment) rather than at a site problem.
    co_onset = {}
    flagged = diag[unexplained & diag.loss_onset.notna()]
    for pid, r in flagged.iterrows():
        peers = flagged[(flagged.state == r.state) & (flagged.index != pid)]
        gaps = (peers.loss_onset.dt.to_period("M") - r.loss_onset.to_period("M")).apply(lambda x: abs(x.n))
        co_onset[pid] = bool((gaps <= 1).any())
    diag["regional_co_onset"] = pd.Series(co_onset).reindex(diag.index).fillna(False).astype(bool)

    causes = []
    for pid, r in diag.iterrows():
        c = []
        if reliability[pid]:
            c.append("Reliability: downtime loss")
        if unexplained[pid]:
            # Revised after evaluation (v1 checked shape first): losses starting in the
            # same month at separate sites are stronger evidence than the curve shape,
            # which seasonal effects can distort.
            if r.regional_co_onset:
                c.append("Grid curtailment suspected (loss shared with same-state plants, same onset, no downtime)")
            elif r.loss_shape == "progressive":
                c.append("Soiling/degradation suspected (progressive loss, no downtime)")
            else:
                c.append("Unexplained loss: site inspection needed")
        if cost[pid]:
            c.append("O&M cost driven by downtime" if reliability[pid] else "O&M cost anomaly vs peers")
        if capital[pid]:
            c.append("Capital: capex above benchmark")
        causes.append(" | ".join(c))
    diag["suspected_root_cause"] = causes
    # Avoidable loss: downtime beyond the technology's median downtime loss, and
    # unexplained loss only where the unexplained-loss rule fired. Normal downtime
    # and model noise are not "lost revenue".
    typical = diag.groupby("project_type").downtime_loss_pct.transform("median")
    diag["excess_downtime_loss_inr"] = ((diag.downtime_loss_pct - typical).clip(lower=0)
                                        * diag.potential_mwh * diag.downtime_loss_inr
                                        / diag.downtime_loss_mwh.replace(0, np.nan)).fillna(0)
    diag["avoidable_unexplained_loss_inr"] = np.where(unexplained, diag.unexplained_loss_inr.clip(lower=0), 0)
    diag["lost_revenue_inr"] = diag.excess_downtime_loss_inr + diag.avoidable_unexplained_loss_inr
    return diag.reset_index()


# --------------------------------------------------------------------------
# 4. Pareto and ABC
# --------------------------------------------------------------------------

def pareto_abc(pp: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    seg = pp[["project_id", "project_code", "project_name", "project_type", "region",
              "energy_mwh", "revenue_cr", "ebit_cr", "roi_pct", "investment_cr"]].copy()
    summary = {}
    for col, label in [("energy_mwh", "energy"), ("revenue_cr", "revenue"), ("ebit_cr", "ebit")]:
        ordered = seg.sort_values(col, ascending=False)
        cum = ordered[col].cumsum() / ordered[col].sum()
        seg.loc[ordered.index, f"cum_share_{label}"] = cum.values
        n80 = int((cum < 0.80).sum() + 1)
        summary[label] = {"projects_for_80pct": n80, "of": len(seg), "pct_of_projects": round(100 * n80 / len(seg), 1),
                          "top10_share_pct": round(100 * float(cum.iloc[9]), 1)}

    # ABC on revenue: class decided by cumulative share BEFORE the item,
    # so the project that crosses 80% is still an A.
    ordered = seg.sort_values("revenue_cr", ascending=False)
    prev = (ordered.revenue_cr.cumsum() - ordered.revenue_cr) / ordered.revenue_cr.sum()
    seg.loc[ordered.index, "abc_revenue"] = np.select([prev < 0.80, prev < 0.95], ["A", "B"], "C")

    portfolio_roi = None  # filled by caller for the crosstab
    abc = seg.groupby("abc_revenue").agg(
        projects=("project_code", "count"),
        revenue_cr=("revenue_cr", "sum"),
        investment_cr=("investment_cr", "sum"),
        median_roi_pct=("roi_pct", "median"),
        utility_scale=("project_type", lambda s: int((s == "Utility-Scale").sum())),
    ).round(2)
    abc["revenue_share_pct"] = (100 * abc.revenue_cr / abc.revenue_cr.sum()).round(1)
    summary["abc"] = abc
    return seg, summary


# --------------------------------------------------------------------------
# 5. Charts
# --------------------------------------------------------------------------

def chart_correlation(corr: pd.DataFrame, n: int) -> None:
    fig, ax = new_figure(figsize=(8, 6.4))
    ax.imshow(corr.values, cmap=DIVERGING, vmin=-1, vmax=1)
    labels = list(corr.columns)
    ax.set_xticks(range(len(labels)), labels, rotation=40, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            v = corr.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                    color="#ffffff" if abs(v) > 0.6 else INK)
    ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=9, length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(f"Spearman correlation, project-month grain (n = {n:,})",
                 loc="left", color=INK, fontsize=12, pad=12)
    fig.text(0.01, -0.02, "Blue = positive, red = negative. Generation tracks capacity (scale); "
             "capacity factor tracks irradiation (weather).", color=INK2, fontsize=8.5)
    save(fig, "01_correlation_matrix.png")


def chart_temperature(pm: pd.DataFrame, model: pd.DataFrame) -> None:
    w = model.dropna(subset=["avg_temperature_c", "pr_eff"]).copy()
    w["temp_bin"] = (w.avg_temperature_c // 2 * 2).astype(int)
    raw = w.groupby("temp_bin").agg(cf=("capacity_factor", "mean"), n=("capacity_factor", "size"))
    pr = w.groupby("temp_bin").pr_eff.mean()
    raw, pr = raw[raw.n >= 20], pr[raw[raw.n >= 20].index]

    fig, (a1, a2) = new_figure(1, 2, figsize=(10, 3.8))
    for ax in (a1, a2):
        style_axes(ax)
    a1.plot(raw.index, raw.cf * 100, color=SERIES[0], linewidth=2, marker="o", markersize=5)
    a1.set_title("Raw view: hotter months show HIGHER capacity factor", loc="left", color=INK, fontsize=10.5)
    a1.set_ylabel("Capacity factor (%)", color=INK2, fontsize=9)
    a2.plot(pr.index, pr.values, color=SERIES[0], linewidth=2, marker="o", markersize=5)
    a2.set_title("Weather-normalised: hotter months have LOWER PR", loc="left", color=INK, fontsize=10.5)
    a2.set_ylabel("Performance ratio (excl. downtime)", color=INK2, fontsize=9)
    for ax in (a1, a2):
        ax.set_xlabel("Average ambient temperature (°C, 2° bins)", color=INK2, fontsize=9)
    fig.text(0.01, -0.06, "Hot months are also the sunniest (Mar-May), which hides the heat penalty. "
             "Bins with < 20 project-months omitted.", color=INK2, fontsize=8.5)
    fig.tight_layout()
    save(fig, "02_temperature_confounding.png")


def chart_diagnostics(model: pd.DataFrame, diag: pd.DataFrame) -> None:
    flagged = diag[diag.suspected_root_cause.str.contains("Reliability|curtailment|Soiling|Unexplained")]
    flagged = flagged.sort_values("lost_revenue_inr", ascending=False).head(6)  # reliability + unexplained
    n = len(flagged)
    if not n:
        return
    cols = 3
    rows = math.ceil(n / cols)
    fig, axes = new_figure(rows, cols, figsize=(12, 3.2 * rows), sharey=True)
    axes = np.atleast_1d(axes).ravel()
    for ax, (_, r) in zip(axes, flagged.iterrows()):
        s = model[model.project_id == r.project_id].dropna(subset=["potential_mwh"])
        vs_potential = (s.energy_generated_mwh / s.potential_mwh - 1) * 100
        style_axes(ax)
        ax.axhline(0, color=AXIS, linewidth=1)
        ax.axhline(ONSET_LOSS * 100, color=MUTED, linewidth=1, linestyle=(0, (3, 3)))
        ax.plot(s.month_start_date, vs_potential, color=SERIES[0], linewidth=2)
        ax.set_title(f"{r.project_code}  {r.project_name}", loc="left", color=INK, fontsize=9.5)
        cause = r.suspected_root_cause.split(" (")[0].split(" |")[0]
        ax.text(0.02, 0.04, cause, transform=ax.transAxes, color=INK2, fontsize=8)
        ax.tick_params(axis="x", labelrotation=0, labelsize=8)
        ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(bymonth=(4, 10)))
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b-%y"))
    for ax in axes[n:]:
        ax.set_visible(False)
    for ax in axes[::cols]:
        ax.set_ylabel("Actual vs potential (%)", color=INK2, fontsize=9)
    fig.suptitle("Actual generation vs weather-adjusted potential: projects with root-cause flags",
                 x=0.01, ha="left", color=INK, fontsize=12)
    fig.text(0.01, -0.03, "0 = the output the model expects for that month's sun, temperature and plant age at 100% "
             "availability. Outages, soiling and curtailment all show as dips. Dashed line = -5%.",
             color=INK2, fontsize=8.5)
    fig.tight_layout()
    save(fig, "03_underperformance_diagnostics.png")


def chart_losses(diag: pd.DataFrame) -> None:
    top = diag.sort_values("lost_revenue_inr", ascending=False).head(10).iloc[::-1]
    top = top[top.lost_revenue_inr > 0]
    down = top.excess_downtime_loss_inr / 1e7
    unexp = top.avoidable_unexplained_loss_inr / 1e7
    fig, ax = new_figure(figsize=(9, 4.8))
    style_axes(ax, grid_axis="x")
    y = np.arange(len(top))
    ax.barh(y, down, color=SERIES[0], height=0.6, edgecolor=SURFACE, linewidth=2, label="Excess downtime")
    ax.barh(y, unexp, left=down, color=SERIES[1], height=0.6, edgecolor=SURFACE, linewidth=2,
            label="Unexplained (no downtime)")
    ax.set_yticks(y, [f"{c}  {n}" for c, n in zip(top.project_code, top.project_name)])
    for yi, total in zip(y, down + unexp):
        ax.text(total + 0.03, yi, f"₹{total:.2f} Cr", va="center", color=INK2, fontsize=8.5)
    ax.set_xlabel("Avoidable revenue loss vs weather-adjusted expectation, FY24-FY26 (₹ Cr)", color=INK2, fontsize=9)
    ax.set_title("Where avoidable generation losses cost the most revenue", loc="left", color=INK, fontsize=12)
    ax.legend(frameon=False, loc="lower right", fontsize=9, labelcolor=INK2)
    ax.set_xlim(0, float((down + unexp).max()) * 1.18)
    save(fig, "04_revenue_lost_by_project.png")


def chart_pareto(seg: pd.DataFrame) -> None:
    fig, ax = new_figure(figsize=(8, 4.6))
    style_axes(ax)
    n = len(seg)
    for color, label, col in zip(SERIES, ["Energy", "Revenue", "EBIT"], ["energy", "revenue", "ebit"]):
        cum = np.sort(seg[f"cum_share_{col}"].values)
        x = np.arange(1, n + 1) / n * 100
        n80 = int((cum < 0.80).sum() + 1)
        ax.plot(x, cum * 100, color=color, linewidth=2, label=f"{label}: {n80} projects ({100 * n80 / n:.0f}%) reach 80%")
    ax.axhline(80, color=MUTED, linewidth=1, linestyle=(0, (3, 3)))
    ax.plot([0, 100], [0, 100], color=AXIS, linewidth=1)
    ax.text(62, 56, "perfectly even", color=MUTED, fontsize=8, rotation=33)
    ax.set_xlabel("Share of projects, largest first (%)", color=INK2, fontsize=9)
    ax.set_ylabel("Cumulative share (%)", color=INK2, fontsize=9)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 102)
    ax.set_title("Pareto: how concentrated are energy, revenue and EBIT?", loc="left", color=INK, fontsize=12)
    ax.legend(frameon=False, loc="lower right", fontsize=9, labelcolor=INK2)
    fig.text(0.01, -0.04, "No 80/20 pattern: about 40-45% of projects are needed for 80% of each measure. "
             "Revenue and EBIT curves almost coincide.", color=INK2, fontsize=8.5)
    save(fig, "05_pareto.png")


# --------------------------------------------------------------------------
# 6. Evaluation against ground truth (reads data/ground_truth/ ONLY here)
# --------------------------------------------------------------------------

def evaluate(diag: pd.DataFrame, model: pd.DataFrame) -> list[str]:
    truth = json.loads((ROOT / "data/ground_truth/expected_clean_totals.json").read_text())["planted_scenarios"]
    months = pd.read_csv(ROOT / "data/ground_truth/planted_scenario_months.csv", parse_dates=["month"])
    expected_label = {
        "SOILING": "Soiling", "CURTAILMENT": "curtailment", "INVERTER_FAILURES": "Reliability",
        "HAILSTORM": "Reliability", "OM_COST_OVERRUN": "O&M cost anomaly", "CAPEX_OVERRUN": "Capital",
    }
    lines = []
    by_code = diag.set_index("project_code")
    hits = 0
    for code, scenario in truth.items():
        cause = by_code.loc[code, "suspected_root_cause"]
        ok = expected_label[scenario] in cause
        hits += ok
        lines.append(f"{'PASS' if ok else 'MISS'}  {code} {scenario:<18} -> {cause or '(not flagged)'}")
    false_pos = [c for c in by_code.index[by_code.suspected_root_cause != ""] if c not in truth]
    lines.append(f"Root cause correctly identified: {hits}/{len(truth)}; "
                 f"flagged but not planted: {len(false_pos)} {false_pos}")

    # How well did the model QUANTIFY hidden losses (soiling, curtailment)?
    m = model.merge(months, left_on=["project_code", "month_start_date"], right_on=["project_code", "month"])
    m = m.dropna(subset=["expected_mwh"])
    m["true_lost_mwh"] = m.energy_generated_mwh * (m.hidden_loss_pct / 100) / (1 - m.hidden_loss_pct / 100)
    for scenario, grp in m.groupby("scenario"):
        est, true = grp.unexplained_loss_mwh.sum(), grp.true_lost_mwh.sum()
        lines.append(f"{scenario}: model estimated {est:,.0f} MWh lost vs true {true:,.0f} MWh "
                     f"({100 * (est / true - 1):+.1f}%)")
    return lines


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    with engine.connect() as conn:
        pm, pp, bench = load(conn)

    corr = correlation_analysis(pm, pp)
    model, model_info = expected_generation(pm)
    model = month_anomalies(model)
    diag = project_diagnostics(model, pp, bench)
    seg, pareto = pareto_abc(pp)
    seg = seg.merge(diag[["project_id", "suspected_root_cause"]], on="project_id", how="left")

    # Cross-check: Python recomputation equals the SQL view definitions
    roi_py = 100 * pm.ebit_inr.sum() / (pm.investment_amount_inr.sum() / 12)
    cf_py = pm.energy_generated_mwh.sum() / (pm.capacity_mw * pm.hours_in_month).sum()

    # ---- write back for Power BI -------------------------------------------
    month_cols = ["project_id", "month_start_date", "energy_generated_mwh", "pr_eff", "pr_expected", "availability", "potential_mwh",
                  "expected_mwh", "downtime_loss_mwh", "unexplained_loss_mwh", "residual_pct",
                  "downtime_loss_inr", "unexplained_loss_inr", "z_residual", "z_downtime", "z_maintenance",
                  "month_flags"]
    proj_cols = ["project_id", "project_code", "potential_mwh", "expected_mwh", "downtime_loss_mwh",
                 "excess_downtime_loss_inr", "avoidable_unexplained_loss_inr",
                 "unexplained_loss_mwh", "downtime_loss_pct", "unexplained_loss_pct", "latest_fy_residual_pct",
                 "z_latest_residual", "z_downtime_loss", "z_maintenance_vs_peers", "capex_vs_benchmark",
                 "loss_onset", "loss_shape", "regional_co_onset", "suspected_root_cause",
                 "downtime_loss_inr", "unexplained_loss_inr", "lost_revenue_inr"]
    seg_cols = ["project_id", "project_code", "abc_revenue", "cum_share_energy", "cum_share_revenue",
                "cum_share_ebit"]
    with engine.begin() as conn:
        model[month_cols].to_sql("ana_month_diagnostics", conn, if_exists="replace", index=False)
        diag[proj_cols].to_sql("ana_project_diagnostics", conn, if_exists="replace", index=False)
        seg[seg_cols].to_sql("ana_project_segments", conn, if_exists="replace", index=False)
    model[["project_code"] + month_cols[1:]].to_csv(OUT_DATA / "month_diagnostics.csv", index=False)
    diag.to_csv(OUT_DATA / "project_diagnostics.csv", index=False)
    seg.to_csv(OUT_DATA / "project_segments.csv", index=False)
    corr["month_spearman"].to_csv(OUT_DATA / "correlation_month_spearman.csv")
    corr["project_spearman"].to_csv(OUT_DATA / "correlation_project_spearman.csv")

    # ---- charts ---------------------------------------------------------------
    chart_correlation(corr["month_spearman"], corr["month_n"])
    chart_temperature(pm, model)
    chart_diagnostics(model, diag)
    chart_losses(diag)
    chart_pareto(seg)

    # ---- report ---------------------------------------------------------------
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print("=== 1. CORRELATION ===")
    print(f"Project-month Spearman (n={corr['month_n']}):\n{corr['month_spearman']}\n")
    print(f"Project-month Pearson:\n{corr['month_pearson']}\n")
    print(f"Project-level Spearman (n={corr['project_n']}):\n{corr['project_spearman']}\n")
    print("Temperature vs capacity factor:", json.dumps(corr["temperature"], default=float))
    print("Cloud cover vs daily irradiation r =", corr["cloud_vs_irradiation_r"])
    print("\n=== 2. EXPECTED-GENERATION MODEL ===")
    print(json.dumps(model_info, indent=2, default=float))
    print("\n=== 3. PROJECT DIAGNOSTICS (flagged) ===")
    show = diag[diag.suspected_root_cause != ""].sort_values("lost_revenue_inr", ascending=False)
    print(show.assign(loss_onset=show.loss_onset.dt.strftime("%Y-%m"))[["project_code", "project_name",
                "downtime_loss_pct", "unexplained_loss_pct",
                "latest_fy_residual_pct", "z_latest_residual", "loss_onset", "loss_shape",
                "suspected_root_cause"]].round(3).to_string(index=False), "")
    print("\nAvoidable revenue loss FY24-FY26 (₹ Cr): excess downtime "
          f"{diag.excess_downtime_loss_inr.sum() / 1e7:.2f}, unexplained (flagged projects) "
          f"{diag.avoidable_unexplained_loss_inr.sum() / 1e7:.2f}")
    print(diag[diag.lost_revenue_inr > 0].sort_values("lost_revenue_inr", ascending=False)
          [["project_code", "excess_downtime_loss_inr", "avoidable_unexplained_loss_inr", "lost_revenue_inr"]]
          .assign(**{c: lambda x, c=c: (x[c] / 1e7).round(2) for c in
                     ["excess_downtime_loss_inr", "avoidable_unexplained_loss_inr", "lost_revenue_inr"]})
          .head(10).to_string(index=False))
    mf = model[model.month_flags != ""]
    print(f"\nMonth-level anomalies: {len(mf)}")
    print(mf[["project_code", "residual_pct", "downtime_hours", "maintenance_cost_inr"]].round(3)
          .assign(month=mf.month_start_date.dt.strftime("%Y-%m"), flags=mf.month_flags).to_string(index=False))
    print("\n=== 4. PARETO / ABC ===")
    print(json.dumps({k: v for k, v in pareto.items() if k != "abc"}, indent=2))
    print(pareto["abc"])
    print("\n=== CROSS-CHECK (Python vs SQL views) ===")
    print(f"Portfolio ROI python {roi_py:.4f}% | CF python {cf_py:.6f}")
    print("\n=== 6. EVALUATION AGAINST GROUND TRUTH ===")
    for line in evaluate(diag, model):
        print(line)


if __name__ == "__main__":
    main()
