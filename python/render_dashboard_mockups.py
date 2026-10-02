"""
Render design mockups of the 6 Power BI report pages.

Power BI Desktop is Windows-only, so these are NOT screenshots: they are
page designs rendered with matplotlib from the same MySQL data the report
uses. Every number on them equals the DAX expected value
(powerbi/05_dax_expected_values.md). Each image is labelled as a mockup.

Output: powerbi/mockups/page{1..6}_*.png (1920 x 1080)

Run after scoring_and_expected_values.py:  python python/render_dashboard_mockups.py
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch
from sqlalchemy import text

from db import get_engine
from scoring_and_expected_values import ALT_WEIGHTINGS, IPS_WEIGHTS, kpis, region_scores, time_kpis, to_numeric

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "powerbi" / "mockups"

# Reference palette (dataviz skill), light mode
PAGE, SURFACE, INK, INK2, MUTED = "#f9f9f7", "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, BORDER = "#e1e0d9", "#c3c2b7", "#e1e0d9"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GOOD_TEXT, CRITICAL = "#006300", "#d03b3b"
HALO = [pe.withStroke(linewidth=3, foreground=SURFACE)]   # keeps labels legible on top of bubbles
SEQ = LinearSegmentedColormap.from_list("seq_blue", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])

PAGES = ["Executive Overview", "Regional Performance", "Investment & ROI", "Energy Performance",
         "Sustainability", "Investment Recommendation"]
MOCKUP_NOTE = ("DESIGN MOCKUP: rendered in Python from the project's MySQL data, values equal the DAX expected values. "
               "Not a Power BI screenshot.")

plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
                     "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2,
                     "ytick.labelcolor": INK2, "axes.titlesize": 11})


# --------------------------------------------------------------------------
# Canvas helpers
# --------------------------------------------------------------------------

def crore(v: float, dec: int = 0) -> str:
    return f"₹{v / 1e7:,.{dec}f} Cr"


def new_page(n: int, question: str, slicers: list[str] | None = None):
    fig = plt.figure(figsize=(16, 9), dpi=120)
    fig.patch.set_facecolor(PAGE)
    # header
    fig.patches.append(FancyBboxPatch((0.006, 0.915), 0.988, 0.078, boxstyle="round,pad=0,rounding_size=0.004",
                                      transform=fig.transFigure, facecolor=SURFACE, edgecolor=BORDER, lw=0.8, zorder=-1))
    fig.text(0.015, 0.962, f"{PAGES[n - 1]}", fontsize=19, color=INK, weight="bold", va="center")
    fig.text(0.015, 0.930, question, fontsize=10.5, color=INK2, va="center")
    x = 0.985
    for s in reversed(slicers or ["Fiscal year: All", "Region: All", "Project type: All"]):
        w = 0.0062 * len(s) + 0.02
        x -= w
        fig.patches.append(FancyBboxPatch((x, 0.940), w - 0.006, 0.032, boxstyle="round,pad=0,rounding_size=0.006",
                                          transform=fig.transFigure, facecolor=SURFACE, edgecolor=AXIS, lw=0.8))
        fig.text(x + (w - 0.006) / 2, 0.956, s + "  ▾", fontsize=9, color=INK2, ha="center", va="center")
    # page tabs
    tx = 0.008
    for i, name in enumerate(PAGES, start=1):
        w = 0.0058 * len(name) + 0.03
        active = i == n
        fig.patches.append(FancyBboxPatch((tx, 0.008), w, 0.028, boxstyle="round,pad=0,rounding_size=0.003",
                                          transform=fig.transFigure, facecolor=SURFACE if active else PAGE,
                                          edgecolor=BLUE if active else BORDER, lw=1.2 if active else 0.6))
        fig.text(tx + w / 2, 0.022, f"{i}  {name}", fontsize=8.5, ha="center", va="center",
                 color=INK if active else MUTED, weight="bold" if active else "normal")
        tx += w + 0.004
    fig.text(0.993, 0.046, MOCKUP_NOTE, fontsize=7.5, color=MUTED, ha="right", va="center", style="italic")
    return fig


def panel(fig, rect, title: str | None = None, subtitle: str | None = None, pad=(0.08, 0.03, 0.012, 0.075)):
    """White visual container. Returns an axes placed inside it (pad: left, bottom, right, top in panel units)."""
    x, y, w, h = rect
    fig.patches.append(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.004",
                                      transform=fig.transFigure, facecolor=SURFACE, edgecolor=BORDER, lw=0.8, zorder=-1))
    if title:
        fig.text(x + 0.008, y + h - 0.022, title, fontsize=11, color=INK, weight="bold", va="center")
    if subtitle:
        fig.text(x + 0.008, y + h - 0.045, subtitle, fontsize=8.5, color=INK2, va="center")
    l, b, r, t = pad
    ax = fig.add_axes([x + l * w, y + b * h + 0.01, w * (1 - l - r), h * (1 - b - t) - 0.045 - 0.01])
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=8.5, length=3)
    return ax


def card(fig, rect, label: str, value: str, sub: str = "", sub_color: str = INK2):
    x, y, w, h = rect
    fig.patches.append(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.004",
                                      transform=fig.transFigure, facecolor=SURFACE, edgecolor=BORDER, lw=0.8, zorder=-1))
    fig.text(x + 0.008, y + h - 0.02, label, fontsize=9, color=INK2, va="center")
    fig.text(x + 0.008, y + h * 0.42, value, fontsize=21, color=INK, weight="bold", va="center")
    if sub:
        fig.text(x + 0.008, y + 0.014, sub, fontsize=8.5, color=sub_color, va="center")


def table(ax, df: pd.DataFrame, col_widths=None, fontsize=8.5, highlight_rows=None, align=None):
    ax.axis("off")
    n_rows, n_cols = len(df) + 1, len(df.columns)
    widths = col_widths or [1 / n_cols] * n_cols
    xs = np.concatenate([[0], np.cumsum(widths)])
    row_h = 1 / n_rows
    for j, col in enumerate(df.columns):
        ha = (align or {}).get(col, "left" if j == 0 else "right")
        xt = xs[j] + 0.01 if ha == "left" else xs[j + 1] - 0.01
        ax.text(xt, 1 - row_h / 2, col, fontsize=fontsize, color=INK2, weight="bold", ha=ha, va="center",
                transform=ax.transAxes)
    ax.plot([0, 1], [1 - row_h, 1 - row_h], color=AXIS, lw=0.8, transform=ax.transAxes)
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        yc = 1 - row_h * (i + 0.5)
        if highlight_rows and (i - 1) in highlight_rows:
            ax.add_patch(plt.Rectangle((0, 1 - row_h * (i + 1)), 1, row_h, transform=ax.transAxes,
                                       facecolor="#eef4fc", edgecolor="none"))
        for j, col in enumerate(df.columns):
            ha = (align or {}).get(col, "left" if j == 0 else "right")
            xt = xs[j] + 0.01 if ha == "left" else xs[j + 1] - 0.01
            ax.text(xt, yc, str(row[col]), fontsize=fontsize, color=INK, ha=ha, va="center", transform=ax.transAxes)
        if i < n_rows - 1:
            ax.plot([0, 1], [1 - row_h * (i + 1)] * 2, color=GRID, lw=0.5, transform=ax.transAxes)


def text_box(fig, rect, title: str, lines: list[str], fontsize=9.2):
    x, y, w, h = rect
    fig.patches.append(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.004",
                                      transform=fig.transFigure, facecolor=SURFACE, edgecolor=BORDER, lw=0.8, zorder=-1))
    fig.text(x + 0.008, y + h - 0.022, title, fontsize=11, color=INK, weight="bold", va="center")
    ty = y + h - 0.052
    px_per_char = fontsize * 0.58 * fig.dpi / 72
    chars = max(20, int((w * fig.get_figwidth() * fig.dpi - 24) / px_per_char))
    line_h = fontsize * 1.35 / 72 / fig.get_figheight()
    for line in lines:
        wrapped = textwrap.fill(line, chars, subsequent_indent="   " if line[:2] in ("• ",) or line[:1].isdigit() else "")
        fig.text(x + 0.010, ty, wrapped, fontsize=fontsize, color=INK, va="top", linespacing=1.25)
        ty -= line_h * (wrapped.count("\n") + 1) + 0.010


def grid_y(ax):
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def grid_x(ax):
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def month_axis(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(4, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))


def save(fig, name: str) -> None:
    fig.savefig(OUT / name, dpi=120, facecolor=PAGE)
    plt.close(fig)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def load():
    with get_engine().connect() as conn:
        q = lambda sql: to_numeric(pd.read_sql(text(sql), conn))  # noqa: E731
        pm = q("""SELECT m.*, d.project_status, d.annual_ghi_kwh_m2_day, d.latitude, d.longitude
                  FROM vw_project_month m JOIN vw_dim_project d ON d.project_id = m.project_id""")
        proj = q("SELECT * FROM vw_dim_project")
        perf = q("SELECT * FROM vw_project_performance")
        monthly = q("SELECT * FROM vw_portfolio_monthly")
        diag = q("SELECT * FROM ana_project_diagnostics")
        diag_m = q("SELECT * FROM ana_month_diagnostics")
    for df in (pm, monthly, diag_m):
        df["month_start_date"] = pd.to_datetime(df.month_start_date)
    quad = pd.read_csv(ROOT / "data/processed/project_quadrants.csv")
    return pm, proj, perf, monthly, diag, diag_m, quad


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def page1(pm, proj, perf, monthly, scores, diag):
    k = kpis(pm)
    raj = diag[diag.project_code.isin(["P001", "P004", "P006"])].lost_revenue_inr.sum() / diag.lost_revenue_inr.sum()
    tk = time_kpis(pm)
    fig = new_page(1, "Is the portfolio healthy, and where should management look first?  FY24-FY26 · 56 operating projects")
    op_inv = proj.loc[proj.project_status == "Operational", "investment_amount_inr"].sum()
    cards = [
        ("Total Energy Generated", f"{k['Total Energy (MWh)'] / 1e6:.2f} TWh",
         f"FY26 {tk['Energy YoY % (FY2025-26)']:+.1%} YoY · like-for-like {tk['LFL Energy YoY % (FY2025-26)']:+.1%}",
         CRITICAL),
        ("Total Investment", crore(proj.investment_amount_inr.sum()), f"{crore(op_inv)} operating · rest pipeline", INK2),
        ("Revenue", crore(k["Revenue"]), f"FY26 {tk['Revenue YoY % (FY2025-26)']:+.1%} YoY", GOOD_TEXT),
        ("Profit (EBIT)", crore(k["EBIT (Profit)"]), f"EBITDA margin {k['EBITDA Margin %']:.1%}", INK2),
        ("ROI (annualised, EBIT)", f"{k['ROI %']:.2%}", "FY24 6.21% → FY26 5.54%", CRITICAL),
        ("CO₂ Avoided", f"{k['CO2 Avoided (t)'] / 1e6:.2f} Mt", f"≈ {k['Equivalent Households (avg/month)'] / 1e6:.1f} M homes / month",
         INK2),
    ]
    w = 0.988 / 6
    for i, (lab, val, sub, col) in enumerate(cards):
        card(fig, (0.006 + i * w, 0.80, w - 0.006, 0.105), lab, val, sub, col)

    # headline (dynamic narrative measure)
    fig.patches.append(FancyBboxPatch((0.006, 0.755), 0.988, 0.036, boxstyle="round,pad=0,rounding_size=0.004",
                                      transform=fig.transFigure, facecolor="#eef4fc", edgecolor="#b7d3f6", lw=0.8))
    fig.text(0.015, 0.773, "Headline:  North generates 39% of energy but ranks #5 on ROI; West earns the highest return.   "
                           "Reported FY26 growth +7.1% comes from new capacity: the same 48 plants produced 2.3% less.",
             fontsize=10, color=INK, va="center")

    # energy trend
    ax = panel(fig, (0.006, 0.415, 0.40, 0.33), "Energy generation trend", "Monthly MWh · monsoon dips Jul-Sep")
    ax.plot(monthly.month_start_date, monthly.energy_mwh / 1000, color=BLUE, lw=2)
    ax.set_ylabel("GWh", fontsize=9)
    grid_y(ax)
    month_axis(ax)
    # revenue trend (separate chart, no dual axis)
    rev = pm.groupby("month_start_date").revenue_inr.sum() / 1e7
    ax = panel(fig, (0.412, 0.415, 0.26, 0.33), "Revenue trend", "Monthly ₹ Cr")
    ax.plot(rev.index, rev.values, color=BLUE, lw=2)
    ax.set_ylim(0, rev.max() * 1.15)
    grid_y(ax)
    month_axis(ax)
    # map
    ax = panel(fig, (0.678, 0.415, 0.316, 0.33), "Where the energy comes from",
               "Map visual: bubble = city energy (GWh)", pad=(0.04, 0.03, 0.02, 0.075))
    city = pm.groupby(["city", "latitude", "longitude"]).energy_generated_mwh.sum().reset_index()
    ax.scatter(city.longitude, city.latitude, s=city.energy_generated_mwh / 1000 * 0.9 + 15, color=BLUE, alpha=0.75,
               edgecolor=SURFACE, lw=1.5)
    for _, r in city[city.city.isin(["Jodhpur", "Bhuj", "Kurnool", "Tirunelveli", "Rewa", "Guwahati"])].iterrows():
        east = r.longitude > 88
        ax.text(r.longitude + (-0.9 if east else 0.9), r.latitude - 0.3, r.city, fontsize=8, color=INK2,
                ha="right" if east else "left", path_effects=HALO, zorder=5)
    ax.set_xlim(67, 94)
    ax.set_ylim(7, 32)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.text(0.99, 0.02, "Map tiles shown in Power BI", transform=ax.transAxes, fontsize=7.5, color=MUTED, ha="right")

    # regional performance: ROI with energy share label
    r = scores.sort_values("roi_pct")
    ax = panel(fig, (0.006, 0.055, 0.30, 0.35), "Regional performance", "ROI % (bar) · share of energy (label)",
               pad=(0.2, 0.06, 0.08, 0.075))
    ax.barh(r.index, r.roi_pct * 100, color=BLUE, height=0.6)
    for yi, (reg, row) in enumerate(r.iterrows()):
        ax.text(row.roi_pct * 100 + 0.1, yi, f"{row.roi_pct:.1%} · {row.energy_gwh / r.energy_gwh.sum():.0%} of energy",
                va="center", fontsize=8, color=INK2)
    ax.set_xlim(0, 11)
    grid_x(ax)
    # investment vs ROI
    ax = panel(fig, (0.312, 0.055, 0.30, 0.35), "Investment vs ROI", "Each dot = one project · log scale",
               pad=(0.1, 0.1, 0.03, 0.075))
    ax.scatter(perf.investment_cr, perf.roi_pct, s=28, color=BLUE, edgecolor=SURFACE, lw=1)
    ax.axhline(k["ROI %"] * 100, color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.text(perf.investment_cr.min(), k["ROI %"] * 100 + 0.35, "portfolio 5.83%", fontsize=8, color=MUTED, ha="left")
    ax.set_xscale("log")
    ax.set_xlabel("Investment (₹ Cr)", fontsize=9)
    ax.set_ylabel("ROI %", fontsize=9)
    grid_y(ax)
    # top 10
    top = perf.nlargest(10, "roi_pct")
    t = pd.DataFrame({"#": range(1, 11), "Project": top.project_name.str.replace(" Solar", ""),
                      "Type": top.project_type.str.replace(" Open Access", ""), "ROI": top.roi_pct.map("{:.2f}%".format)})
    ax = panel(fig, (0.618, 0.055, 0.2, 0.35), "Top 10 projects by ROI", None, pad=(0.03, 0.02, 0.03, 0.03))
    table(ax, t, col_widths=[0.08, 0.52, 0.22, 0.18], fontsize=8, align={"#": "left", "Project": "left", "Type": "left"})
    # management summary
    text_box(fig, (0.824, 0.055, 0.170, 0.35), "Management summary", [
        "• Scale ≠ return: North 39% of energy, ROI rank 5.",
        "• C&I earns 8.3% ROI vs 5.4% utility; all top 9 projects are C&I.",
        "• ROI fell 3 years running (6.21% → 5.54%).",
        f"• {crore(diag.lost_revenue_inr.sum(), 1)} avoidable revenue loss, {raj:.0%} at 3 Rajasthan parks.",
        "• See page 6 for the prioritisation framework.",
    ], fontsize=8.6)
    save(fig, "page1_executive_overview.png")


def page2(pm, proj, perf, scores):
    fig = new_page(2, "Which regions perform best, on volume vs efficiency?  Drill: Region › State › City › Project")
    s = scores.copy()
    cards = [
        ("Best ROI region", "West", f"{s.loc['West', 'roi_pct']:.2%} ROI"),
        ("Largest energy region", "North", f"{s.loc['North', 'energy_gwh'] / s.energy_gwh.sum():.0%} of energy · ROI rank 5"),
        ("Highest capacity factor", "West", f"{s.loc['West', 'capacity_factor']:.1%} CF"),
        ("Lowest availability", "East", f"{s.loc['East', 'availability']:.1%} (portfolio 97.6%)"),
        ("Footprint", "6 · 18 · 28", "regions · states · cities"),
    ]
    w = 0.988 / 5
    for i, (lab, val, sub) in enumerate(cards):
        card(fig, (0.006 + i * w, 0.80, w - 0.006, 0.105), lab, val, sub)

    # ranking matrix
    rp = pm.groupby("region").apply(lambda g: pd.Series({
        "PR": g.dropna(subset=["irradiation_kwh_m2"]).pipe(
            lambda w: w.energy_generated_mwh.sum() / (w.capacity_mw * w.irradiation_kwh_m2).sum()),
        "Tariff": g.revenue_inr.sum() / (g.energy_generated_mwh.sum() * 1000)}), include_groups=False)
    s = s.join(rp).sort_values("roi_pct", ascending=False)
    t = pd.DataFrame({
        "Region ▸": s.index, "Proj.": s.projects, "Energy GWh": s.energy_gwh.map("{:,.0f}".format),
        "Share": (s.energy_gwh / s.energy_gwh.sum()).map("{:.1%}".format), "CF": s.capacity_factor.map("{:.1%}".format),
        "PR": s.PR.map("{:.1%}".format), "Tariff ₹/kWh": s.Tariff.map("{:.2f}".format),
        "ROI": s.roi_pct.map("{:.2%}".format),
        "Energy rank": s.energy_gwh.rank(ascending=False).astype(int), "ROI rank": s.roi_pct.rank(ascending=False).astype(int)})
    ax = panel(fig, (0.006, 0.43, 0.55, 0.36), "Regional ranking (matrix, expandable to state › city › project)",
               "Volume rank and return rank disagree: North is #1 on energy, #5 on ROI", pad=(0.02, 0.03, 0.02, 0.06))
    table(ax, t, col_widths=[0.14, 0.06, 0.12, 0.08, 0.08, 0.08, 0.12, 0.09, 0.12, 0.11], fontsize=9,
          highlight_rows=[list(s.index).index("North")])
    # map coloured by ROI
    ax = panel(fig, (0.562, 0.43, 0.432, 0.36), "Filled map: ROI by city", "Colour = city ROI % (sequential) · size = energy",
               pad=(0.02, 0.03, 0.02, 0.075))
    c = pm.groupby(["city", "latitude", "longitude"]).apply(lambda g: pd.Series({
        "roi": g.ebit_inr.sum() / (g.investment_amount_inr.sum() / 12), "e": g.energy_generated_mwh.sum()}),
        include_groups=False).reset_index()
    sc = ax.scatter(c.longitude, c.latitude, s=c.e / 1000 * 0.8 + 25, c=c.roi * 100, cmap=SEQ, vmin=0, vmax=10,
                    edgecolor=AXIS, lw=0.8)
    for _, r in c.iterrows():
        if r.city in ("Pune", "Kochi", "Jodhpur", "Kurnool", "Rewa", "Guwahati", "Bhuj"):
            east = r.longitude > 88
            ax.text(r.longitude + (-0.9 if east else 0.9), r.latitude - 0.3, f"{r.city} {r.roi:.1%}", fontsize=7.5,
                    color=INK2, ha="right" if east else "left", path_effects=HALO, zorder=5)
    cb = fig.colorbar(sc, ax=ax, fraction=0.03, pad=0.01)
    cb.ax.tick_params(labelsize=8)
    ax.set_xlim(67, 94)
    ax.set_ylim(7, 32)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.spines[["left", "bottom"]].set_visible(False)

    order = s.sort_values("energy_gwh").index
    ax = panel(fig, (0.006, 0.055, 0.20, 0.36), "Energy share", "% of portfolio MWh", pad=(0.3, 0.06, 0.1, 0.075))
    ax.barh(order, s.loc[order, "energy_gwh"] / s.energy_gwh.sum() * 100, color=BLUE, height=0.6)
    for yi, v in enumerate(s.loc[order, "energy_gwh"] / s.energy_gwh.sum() * 100):
        ax.text(v + 0.8, yi, f"{v:.0f}%", va="center", fontsize=8, color=INK2)
    ax.set_xlim(0, 50)
    grid_x(ax)
    ax = panel(fig, (0.212, 0.055, 0.20, 0.36), "ROI", "Same region order", pad=(0.3, 0.06, 0.1, 0.075))
    ax.barh(order, s.loc[order, "roi_pct"] * 100, color=BLUE, height=0.6)
    for yi, v in enumerate(s.loc[order, "roi_pct"] * 100):
        ax.text(v + 0.15, yi, f"{v:.1f}%", va="center", fontsize=8, color=INK2)
    ax.set_xlim(0, 10)
    grid_x(ax)
    # scatter CF vs ROI
    ax = panel(fig, (0.418, 0.055, 0.27, 0.36), "Capacity factor vs ROI", "Sun does not decide return: tariff does",
               pad=(0.14, 0.12, 0.05, 0.075))
    ax.scatter(s.capacity_factor * 100, s.roi_pct * 100, s=s.energy_gwh / 8 + 30, color=BLUE, alpha=0.8,
               edgecolor=SURFACE, lw=1.5)
    for reg, r in s.iterrows():
        ax.text(r.capacity_factor * 100 + 0.12, r.roi_pct * 100 + 0.12, f"{reg} (₹{r.Tariff:.2f})", fontsize=8,
                color=INK2, path_effects=HALO)
    ax.set_xlabel("Capacity factor %", fontsize=9)
    ax.set_ylabel("ROI %", fontsize=9)
    ax.set_xlim(14, 20.5)
    grid_y(ax)
    # ROI by FY heatmap
    fy = pm.groupby(["region", "fiscal_year"]).apply(
        lambda g: g.ebit_inr.sum() / (g.investment_amount_inr.sum() / 12) * 100, include_groups=False).unstack()
    fy = fy.loc[s.index]
    ax = panel(fig, (0.694, 0.055, 0.30, 0.36), "ROI trend by region", "Fiscal year matrix · darker = higher ROI",
               pad=(0.2, 0.08, 0.04, 0.075))
    ax.imshow(fy.values, cmap=SEQ, vmin=3, vmax=9, aspect="auto")
    ax.set_xticks(range(3), [c.replace("FY20", "FY") for c in fy.columns])
    ax.set_yticks(range(len(fy)), fy.index)
    for i in range(fy.shape[0]):
        for j in range(fy.shape[1]):
            v = fy.values[i, j]
            ax.text(j, i, f"{v:.2f}%", ha="center", va="center", fontsize=8.5, color="#ffffff" if v > 6.5 else INK)
    ax.tick_params(length=0)
    ax.spines[["left", "bottom"]].set_visible(False)
    save(fig, "page2_regional_performance.png")


def page3(pm, proj, perf, quad):
    k = kpis(pm)
    fig = new_page(3, "Which projects earn their capital, and why?  Investment → Revenue → Cost → Profit → ROI")
    op_inv = proj.loc[proj.project_status == "Operational", "investment_amount_inr"].sum()
    cards = [("Operating investment", crore(op_inv), "56 projects"),
             ("Capital employed", crore(k['Capital Employed (capital-years)']), "capital-years: capex × years operating"),
             ("ROI (EBIT)", f"{k['ROI %']:.2%}", f"EBITDA yield {k['EBITDA Yield %']:.2%}"),
             ("Simple payback", f"{k['Payback (years)']:.1f} yrs", "capex ÷ annual EBITDA"),
             ("Realised tariff", f"₹{k['Realised Tariff (₹/kWh)']:.2f}/kWh", "revenue ÷ energy"),
             ("Revenue per MW", f"₹{k['Revenue per MW (₹ lakh/yr)']:.1f} L", "per MW per year")]
    w = 0.988 / 6
    for i, (lab, val, sub) in enumerate(cards):
        card(fig, (0.006 + i * w, 0.80, w - 0.006, 0.105), lab, val, sub)

    # quadrant scatter
    q = quad.merge(perf[["project_code", "project_name"]], on="project_code")
    med = q.investment_cr.median()
    ax = panel(fig, (0.006, 0.36, 0.55, 0.43), "Project performance quadrant",
               f"Lines: median investment ₹{med:,.0f} Cr · portfolio ROI {k['ROI %']:.2%}  (static calculated column)",
               pad=(0.07, 0.1, 0.02, 0.075))
    hi = q.roi_pct / 100 >= k["ROI %"]
    ax.scatter(q.investment_cr[hi], q.roi_pct[hi], s=34, color=BLUE, edgecolor=SURFACE, lw=1, label="ROI ≥ portfolio")
    ax.scatter(q.investment_cr[~hi], q.roi_pct[~hi], s=34, color=ORANGE, edgecolor=SURFACE, lw=1, label="ROI < portfolio")
    ax.axvline(med, color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.axhline(k["ROI %"] * 100, color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.set_xscale("log")
    for code in ["P039", "P055", "P004", "P006", "P001", "P008", "P047", "P023"]:
        r = q[q.project_code == code].iloc[0]
        off = (-34, 2) if code == "P039" else (5, 3)
        ax.annotate(code, (r.investment_cr, r.roi_pct), xytext=off, textcoords="offset points", fontsize=7.5,
                    color=INK2)
    lab = dict(fontsize=9, color=INK2, weight="bold", transform=ax.transAxes)
    counts = q.quadrant.value_counts()
    ax.text(0.99, 0.97, f"High inv / High ROI ({counts['High Investment / High ROI']})", ha="right", va="top", **lab)
    ax.text(0.99, 0.03, f"High inv / Low ROI ({counts['High Investment / Low ROI']})", ha="right", va="bottom", **lab)
    ax.text(0.01, 0.97, f"Low inv / High ROI ({counts['Low Investment / High ROI']})", ha="left", va="top", **lab)
    ax.text(0.01, 0.03, f"Low inv / Low ROI ({counts['Low Investment / Low ROI']})", ha="left", va="bottom", **lab)
    ax.set_xlabel("Investment (₹ Cr, log scale)", fontsize=9)
    ax.set_ylabel("ROI %", fontsize=9)
    ax.legend(frameon=False, fontsize=8.5, loc="lower right", ncol=2, bbox_to_anchor=(1.0, 1.0))
    grid_y(ax)

    # ROI ranking: top and bottom 6
    rk = pd.concat([perf.nsmallest(6, "roi_pct"), perf.nlargest(6, "roi_pct").iloc[::-1]])
    ax = panel(fig, (0.006, 0.055, 0.55, 0.295), "ROI ranking: bottom 6 and top 6", "Top N slicer on the live page",
               pad=(0.25, 0.04, 0.06, 0.075))
    colors = [ORANGE] * 6 + [BLUE] * 6
    ax.barh(range(12), rk.roi_pct, color=colors, height=0.65)
    ax.set_yticks(range(12), [f"{c}  {n}" for c, n in zip(rk.project_code, rk.project_name)], fontsize=7.8)
    for yi, v in enumerate(rk.roi_pct):
        ax.text(v + 0.1, yi, f"{v:.2f}%", va="center", fontsize=7.5, color=INK2)
    ax.axhline(5.5, color=AXIS, lw=0.8)
    ax.set_xlim(0, 13.5)
    grid_x(ax)

    # waterfall revenue -> EBIT
    ax = panel(fig, (0.562, 0.52, 0.432, 0.27), "From revenue to profit (₹ Cr, FY24-FY26)", None,
               pad=(0.08, 0.1, 0.02, 0.1))
    steps = [("Revenue", k["Revenue"]), ("Operating cost", -k["Operating Cost"]),
             ("Maintenance", -k["Maintenance Cost"]), ("EBITDA", None), ("Depreciation", -k["Depreciation"]),
             ("EBIT", None)]
    run = 0
    for i, (name, v) in enumerate(steps):
        if v is None:
            ax.bar(i, run / 1e7, color=BLUE, width=0.6)
            ax.text(i, run / 1e7 + 40, f"{run / 1e7:,.0f}", ha="center", fontsize=8.5, color=INK)
        elif v > 0:
            ax.bar(i, v / 1e7, color=BLUE, width=0.6)
            ax.text(i, v / 1e7 + 40, f"{v / 1e7:,.0f}", ha="center", fontsize=8.5, color=INK)
            run += v
        else:
            ax.bar(i, v / 1e7, bottom=run / 1e7, color=ORANGE, width=0.6)
            ax.text(i, run / 1e7 + 40, f"−{-v / 1e7:,.0f}", ha="center", fontsize=8.5, color=INK)
            run += v
    ax.set_xticks(range(len(steps)), [s[0] for s in steps], fontsize=8.5)
    ax.set_ylim(0, k["Revenue"] / 1e7 * 1.15)
    grid_y(ax)

    # profitability matrix by type
    capex = proj[proj.project_status == "Operational"].groupby("project_type").agg(
        inv=("investment_amount_inr", "sum"), mw=("capacity_mw", "sum"))
    rows = []
    for t_, g in pm.groupby("project_type"):
        kk = kpis(g)
        rows.append({"Type": t_.replace(" Open Access", ""), "Capex/MW ₹Cr": f"{capex.loc[t_, 'inv'] / 1e7 / capex.loc[t_, 'mw']:.2f}",
                     "Tariff": f"₹{kk['Realised Tariff (₹/kWh)']:.2f}", "CF": f"{kk['Capacity Factor']:.1%}",
                     "EBITDA mgn": f"{kk['EBITDA Margin %']:.1%}", "ROI": f"{kk['ROI %']:.2%}", "_r": kk["ROI %"]})
    tm = pd.DataFrame(rows).sort_values("_r", ascending=False).drop(columns="_r")
    ax = panel(fig, (0.562, 0.30, 0.432, 0.205), "Profitability matrix by technology", None, pad=(0.02, 0.04, 0.02, 0.05))
    table(ax, tm, col_widths=[0.22, 0.16, 0.14, 0.12, 0.18, 0.18], fontsize=8.8)
    # quadrant interpretation
    qs = q.groupby("quadrant").agg(n=("project_code", "count"), cap=("investment_cr", "sum"), roi=("roi_pct", "median"))
    act = {"High Investment / High ROI": "Protect", "High Investment / Low ROI": "Fix or explain",
           "Low Investment / High ROI": "Replicate", "Low Investment / Low ROI": "Monitor"}
    tq = pd.DataFrame({"Quadrant": qs.index.str.replace("Investment", "inv"), "Projects": qs.n,
                       "Capex ₹Cr": qs.cap.map("{:,.0f}".format), "Median ROI": qs.roi.map("{:.2f}%".format),
                       "Action": [act[i] for i in qs.index]})
    ax = panel(fig, (0.562, 0.055, 0.432, 0.23), "Quadrant summary",
               "High inv / Low ROI holds 52% of operating capital", pad=(0.02, 0.04, 0.02, 0.07))
    table(ax, tq, col_widths=[0.34, 0.12, 0.16, 0.18, 0.2], fontsize=8.8, highlight_rows=[1],
          align={"Action": "left"})
    save(fig, "page3_investment_roi.png")


def page4(pm, perf, monthly, diag, diag_m):
    k = kpis(pm)
    modelled = diag_m.dropna(subset=["potential_mwh"])
    avp = modelled.energy_generated_mwh.sum() / modelled.potential_mwh.sum() - 1
    fig = new_page(4, "Is underperformance caused by weather or by operations?  "
                      "Weather-normalised view using the Stage 3 expected-generation model")
    cards = [("Energy generated", f"{k['Total Energy (MWh)'] / 1e6:.2f} TWh", "1,820 project-months"),
             ("Capacity factor (CUF)", f"{k['Capacity Factor']:.1%}", "weather + operations"),
             ("Performance ratio", f"{k['Performance Ratio']:.1%}", "weather-normalised"),
             ("Availability", f"{k['Availability']:.1%}", "operations only"),
             ("Actual vs potential", f"{avp:+.1%}", "vs model at 100% availability", CRITICAL),
             ("Avoidable revenue loss", crore(diag.lost_revenue_inr.sum(), 1), "excess downtime + unexplained", CRITICAL)]
    w = 0.988 / 6
    for i, c in enumerate(cards):
        card(fig, (0.006 + i * w, 0.80, w - 0.006, 0.105), *c)

    ax = panel(fig, (0.006, 0.6, 0.37, 0.19), "Monthly generation", "GWh", pad=(0.08, 0.12, 0.02, 0.1))
    ax.bar(monthly.month_start_date, monthly.energy_mwh / 1000, width=22, color=BLUE)
    grid_y(ax)
    month_axis(ax)
    ax = panel(fig, (0.006, 0.40, 0.37, 0.19), "Capacity factor trend", "%  · a separate chart, never a 2nd axis",
               pad=(0.08, 0.12, 0.02, 0.1))
    ax.plot(monthly.month_start_date, monthly.capacity_factor * 100, color=BLUE, lw=2)
    grid_y(ax)
    month_axis(ax)

    w_ = pm.dropna(subset=["irradiation_kwh_m2"])
    ax = panel(fig, (0.382, 0.40, 0.30, 0.39), "Generation vs irradiation", "CF vs daily GHI · Spearman ρ = 0.90",
               pad=(0.12, 0.1, 0.03, 0.075))
    ax.scatter(w_.irradiation_kwh_m2 / (w_.hours_in_month / 24), w_.capacity_factor * 100, s=6, color=BLUE, alpha=0.35,
               lw=0)
    flag = w_[w_.project_code.isin(["P001", "P004", "P006"]) & (w_.month_start_date >= "2024-10-01")]
    ax.scatter(flag.irradiation_kwh_m2 / (flag.hours_in_month / 24), flag.capacity_factor * 100, s=10, color=ORANGE,
               lw=0, label="P001/P004/P006 after Oct-24")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.set_xlabel("Irradiation (kWh/m²/day)", fontsize=9)
    ax.set_ylabel("Capacity factor %", fontsize=9)
    grid_y(ax)
    ax = panel(fig, (0.688, 0.40, 0.306, 0.39), "Generation vs capacity", "Annualised MWh vs MW · log-log",
               pad=(0.12, 0.1, 0.03, 0.075))
    ann = perf.energy_mwh * 12 / perf.operating_months
    ax.scatter(perf.capacity_mw, ann, s=22, color=BLUE, edgecolor=SURFACE, lw=0.8)
    xs = np.array([0.4, 350])
    ax.plot(xs, xs * 8760 * 0.18, color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.text(150, 150 * 8760 * 0.18 * 0.45, "18% CF line", fontsize=8, color=MUTED)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Capacity (MW)", fontsize=9)
    ax.set_ylabel("MWh per year", fontsize=9)
    grid_y(ax)

    # loss decomposition
    top = diag[diag.lost_revenue_inr > 0].nlargest(8, "lost_revenue_inr").iloc[::-1]
    names = perf.set_index("project_code").project_name
    ax = panel(fig, (0.006, 0.055, 0.42, 0.33), "Avoidable revenue loss by project (₹ Cr)",
               "Stacked: excess downtime · unexplained loss (no downtime logged)", pad=(0.33, 0.08, 0.06, 0.08))
    d1, d2 = top.excess_downtime_loss_inr / 1e7, top.avoidable_unexplained_loss_inr / 1e7
    yy = np.arange(len(top))
    ax.barh(yy, d1, color=BLUE, height=0.62, edgecolor=SURFACE, lw=2, label="Excess downtime")
    ax.barh(yy, d2, left=d1, color=ORANGE, height=0.62, edgecolor=SURFACE, lw=2, label="Unexplained")
    ax.set_yticks(yy, [f"{c}  {names[c]}" for c in top.project_code], fontsize=8)
    for yi, v in zip(yy, d1 + d2):
        ax.text(v + 0.2, yi, f"{v:.1f}", va="center", fontsize=8, color=INK2)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    grid_x(ax)
    # root-cause table
    flagged = diag[diag.suspected_root_cause.fillna("") != ""].copy()
    flagged["Cause"] = (flagged.suspected_root_cause.str.replace(r" \(.*?\)", "", regex=True)
                        .str.replace("Reliability: downtime loss | O&M cost driven by downtime",
                                     "Reliability: downtime (cost follows)", regex=False)
                        .str.replace(" | ", "; ", regex=False))
    flagged = flagged.sort_values("lost_revenue_inr", ascending=False)
    t = pd.DataFrame({"Project": flagged.project_code + " " + flagged.project_code.map(names).str.replace(" Solar", ""),
                      "Suspected root cause": flagged.Cause,
                      "FY26 vs exp.": flagged.latest_fy_residual_pct.map("{:+.1%}".format),
                      "Onset": pd.to_datetime(flagged.loss_onset).dt.strftime("%b-%y").fillna("—"),
                      "Loss ₹Cr": (flagged.lost_revenue_inr / 1e7).map(lambda v: f"{v:.1f}" if v >= 0.05 else "n/a*")})
    ax = panel(fig, (0.432, 0.055, 0.562, 0.33), "Root-cause diagnostics (Stage 3 rules)",
               "Suspected causes need site or grid-operator confirmation · *cost/capital issues hit ROI, not generation",
               pad=(0.015, 0.03, 0.015, 0.075))
    table(ax, t, col_widths=[0.27, 0.43, 0.1, 0.09, 0.11], fontsize=8.2, align={"Suspected root cause": "left"})
    save(fig, "page4_energy_performance.png")


def page5(pm, monthly, scores):
    k = kpis(pm)
    fig = new_page(5, "What is our environmental impact, in total and per rupee invested?  "
                      "Method: MWh × grid emission factor 0.716 tCO₂/MWh (CEA approx.)")
    cards = [("CO₂ avoided", f"{k['CO2 Avoided (t)'] / 1e6:.2f} Mt", "FY24-FY26"),
             ("CO₂ per MW-year", f"{k['CO2 per MW-year (t)']:,.0f} t", "asset productivity"),
             ("CO₂ per ₹ Cr-year", f"{k['CO2 per ₹ Cr-year (t)']:,.0f} t", "impact per rupee"),
             ("Equivalent households", f"{k['Equivalent Households (avg/month)'] / 1e6:.2f} M",
              "average month (never summed)"),
             ("Renewable share (captive)", f"{k['Renewable Share, captive %']:.1%}", "C&I + rooftop client demand")]
    w = 0.988 / 5
    for i, c in enumerate(cards):
        card(fig, (0.006 + i * w, 0.80, w - 0.006, 0.105), *c)
    s = scores.sort_values("Sustainability Score")
    ax = panel(fig, (0.006, 0.40, 0.30, 0.39), "Sustainability Score by region", "0-100 · percentile-based",
               pad=(0.22, 0.06, 0.08, 0.075))
    ax.barh(s.index, s["Sustainability Score"], color=BLUE, height=0.6)
    for yi, v in enumerate(s["Sustainability Score"]):
        ax.text(v + 1.5, yi, f"{v:.0f}", va="center", fontsize=8.5, color=INK2)
    ax.set_xlim(0, 100)
    grid_x(ax)
    s2 = scores.sort_values("co2_total")
    ax = panel(fig, (0.312, 0.40, 0.30, 0.39), "CO₂ avoided by region", "kt · share of portfolio",
               pad=(0.22, 0.06, 0.12, 0.075))
    ax.barh(s2.index, s2.co2_total / 1000, color=BLUE, height=0.6)
    for yi, v in enumerate(s2.co2_total / 1000):
        ax.text(v + 40, yi, f"{v:,.0f} kt · {v * 1000 / s2.co2_total.sum():.0%}", va="center", fontsize=8, color=INK2)
    ax.set_xlim(0, s2.co2_total.max() / 1000 * 1.35)
    grid_x(ax)
    ax = panel(fig, (0.618, 0.40, 0.376, 0.39), "Impact efficiency", "CO₂ per ₹ Cr-year vs CO₂ per MW-year",
               pad=(0.12, 0.1, 0.05, 0.075))
    ax.scatter(scores.co2_per_mw, scores.co2_per_cr, s=scores.co2_total / 8000 + 30, color=BLUE, alpha=0.8,
               edgecolor=SURFACE, lw=1.5)
    for reg, r in scores.iterrows():
        ax.text(r.co2_per_mw + 6, r.co2_per_cr + 2, reg, fontsize=8.5, color=INK2)
    ax.set_xlabel("t CO₂ per MW-year", fontsize=9)
    ax.set_ylabel("t CO₂ per ₹ Cr-year", fontsize=9)
    ax.set_xlim(900, 1230)
    grid_y(ax)
    ax = panel(fig, (0.006, 0.055, 0.49, 0.33), "Monthly CO₂ avoided", "kt · follows generation (single emission factor)",
               pad=(0.07, 0.1, 0.02, 0.08))
    ax.plot(monthly.month_start_date, monthly.co2_avoided_tonnes / 1000, color=AQUA, lw=2)
    ax.set_ylim(0, monthly.co2_avoided_tonnes.max() / 1000 * 1.15)
    grid_y(ax)
    month_axis(ax)
    text_box(fig, (0.502, 0.055, 0.492, 0.33), "Sustainability Score: transparent method", [
        "Score = 100 × (0.35 × pctl CO₂ per ₹ Cr  +  0.25 × pctl CO₂ per MW  +  0.25 × pctl total CO₂  "
        "+  0.15 × pctl captive renewable share)",
        "pctl = share of other selected regions with a lower value (0 = worst, 1 = best). "
        "Unit-free and robust to outliers.",
        "Limitation: one national grid factor makes the CO₂ terms proportional to energy. "
        "State-level emission factors (coal-heavy grids displace more CO₂) would sharpen the score.",
        "Equivalent households assumes 0.1 MWh per household per month (illustrative).",
        "Renewable share applies to captive C&I and rooftop projects only; utility plants export to the grid.",
    ], fontsize=8.8)
    save(fig, "page5_sustainability.png")


def page6(pm, scores, diag):
    fig = new_page(6, "Where should the next rupee go, and with what risks?  Investment Priority Score (IPS) by region",
                   ["Weights: Default", "Fiscal year: All", "Region: All"])
    fig.patches.append(FancyBboxPatch((0.006, 0.85), 0.988, 0.055, boxstyle="round,pad=0,rounding_size=0.004",
                                      transform=fig.transFigure, facecolor="#f4f3ef", edgecolor=AXIS, lw=0.8))
    fig.text(0.015, 0.877, "Read this first:  Analytical prioritisation framework built on this project's dataset, NOT investment advice "
                           "or a financial recommendation. It ranks regions on recorded performance and makes the "
                           "weighting explicit and adjustable.", fontsize=9.8, color=INK, va="center")
    s = scores.sort_values("Investment Priority Score")
    ax = panel(fig, (0.006, 0.45, 0.30, 0.39), "Investment Priority Score", "0-100 · default weights",
               pad=(0.22, 0.06, 0.08, 0.075))
    ax.barh(s.index, s["Investment Priority Score"], color=BLUE, height=0.6)
    for yi, (reg, r) in enumerate(s.iterrows()):
        ax.text(r["Investment Priority Score"] + 1.5, yi, f"{r['Investment Priority Score']:.0f}  (#{int(r['Rank Default'])})",
                va="center", fontsize=8.5, color=INK2)
    ax.set_xlim(0, 105)
    grid_x(ax)
    # weights panel (what-if sliders)
    x0, y0, w0, h0 = 0.006, 0.055, 0.30, 0.38
    fig.patches.append(FancyBboxPatch((x0, y0), w0, h0, boxstyle="round,pad=0,rounding_size=0.004",
                                      transform=fig.transFigure, facecolor=SURFACE, edgecolor=BORDER, lw=0.8, zorder=-1))
    fig.text(x0 + 0.008, y0 + h0 - 0.022, "Weights (what-if sliders, 0-50)", fontsize=11, weight="bold", color=INK,
             va="center")
    labels = {"roi_pct": "ROI", "availability": "Availability", "solar_resource": "Solar resource",
              "ebitda_margin": "EBITDA margin", "capacity_factor": "Capacity factor", "pr_trend": "PR trend",
              "co2_per_cr": "CO₂ per ₹ Cr"}
    for i, key in enumerate(["roi_pct", "availability", "solar_resource", "ebitda_margin", "capacity_factor",
                             "pr_trend", "co2_per_cr"]):
        yy = y0 + h0 - 0.065 - i * 0.043
        val = IPS_WEIGHTS[key] * 100
        fig.text(x0 + 0.01, yy, labels[key], fontsize=9, color=INK2, va="center")
        sx, sw = x0 + 0.105, 0.15
        fig.add_artist(plt.Line2D([sx, sx + sw], [yy, yy], transform=fig.transFigure, color=GRID, lw=4))
        fig.add_artist(plt.Line2D([sx, sx + sw * val / 50], [yy, yy], transform=fig.transFigure, color=BLUE, lw=4))
        fig.add_artist(plt.Line2D([sx + sw * val / 50], [yy], transform=fig.transFigure, marker="o", ms=8,
                                  color=SURFACE, mec=BLUE, mew=2))
        fig.text(sx + sw + 0.01, yy, f"{val:.0f}", fontsize=9, color=INK, va="center")
    # component heatmap
    comp = ["roi_pct", "availability", "solar_resource", "ebitda_margin", "capacity_factor", "pr_trend", "co2_per_cr"]
    hm = scores.sort_values("Investment Priority Score", ascending=False)[[f"p_{c}" for c in comp]]
    ax = panel(fig, (0.312, 0.45, 0.33, 0.39), "Score components (percentile among regions)",
               "1.0 = best of the selected regions", pad=(0.2, 0.16, 0.03, 0.075))
    ax.imshow(hm.values, cmap=SEQ, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(comp)), [labels[c] for c in comp], rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(hm)), hm.index, fontsize=8.5)
    for i in range(hm.shape[0]):
        for j in range(hm.shape[1]):
            v = hm.values[i, j]
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8.5, color="#ffffff" if v > 0.55 else INK)
    ax.tick_params(length=0)
    ax.spines[["left", "bottom"]].set_visible(False)
    # stability
    st = scores.sort_values("Investment Priority Score", ascending=False)
    t = pd.DataFrame({"Region": st.index, **{n: st[f"Rank {n}"].map(lambda v: f"#{int(v)}") for n in ALT_WEIGHTINGS}})
    t.columns = ["Region", "Default", "Equal", "Return-heavy", "Resource/ESG"]
    ax = panel(fig, (0.312, 0.055, 0.33, 0.38), "Ranking stability across weightings",
               "West always #1 and North-East always #6; North moves #2 to #5", pad=(0.02, 0.04, 0.02, 0.075))
    table(ax, t, col_widths=[0.24, 0.17, 0.15, 0.22, 0.22], fontsize=9, highlight_rows=[list(t.Region).index("North")])
    # risks
    raj_share = pm[pm.state == "Rajasthan"].energy_generated_mwh.sum() / pm.energy_generated_mwh.sum()
    d = diag.set_index("project_code")
    risks = pd.DataFrame([
        ["Grid curtailment", "P004, P006: step loss from Oct-24, no downtime",
         f"₹{(d.loc['P004', 'lost_revenue_inr'] + d.loc['P006', 'lost_revenue_inr']) / 1e7:.1f} Cr"],
        ["Rajasthan concentration", "Tariff ≈₹2.5/kWh; North PR trend −9%", f"{raj_share:.0%} of energy"],
        ["O&M discipline", "P001 soiling −15% in FY26", f"₹{d.loc['P001', 'lost_revenue_inr'] / 1e7:.1f} Cr"],
        ["Reliability", "East availability 94.7%; P055 at 82%", "rooftop fleet"],
        ["Capex overrun", "P039 130%, P057 118% of benchmark", "ROI 0.7%, 4.1%"],
        ["Fleet decline", "Like-for-like energy −2.3% in FY26", "ROI 6.21% → 5.54%"],
    ], columns=["Risk", "Evidence", "Exposure"])
    ax = panel(fig, (0.648, 0.45, 0.346, 0.39), "Risk indicators", None, pad=(0.02, 0.03, 0.02, 0.06))
    table(ax, risks, col_widths=[0.28, 0.5, 0.22], fontsize=8.2, align={"Evidence": "left"})
    text_box(fig, (0.648, 0.055, 0.346, 0.38), "Key recommendations (framework-based)", [
        "1. Next tranche: C&I in West and South (West #1 under every weighting; all top-9 ROI projects are C&I).",
        "2. Make new Rajasthan capacity conditional on curtailment data from the grid operator.",
        "3. Restore module cleaning at P001: ~₹18 Cr revenue lost vs ~₹2-3 Cr maintenance saved.",
        "4. Inverter overhaul at P055; re-tender O&M at P047 (≈2× C&I average cost per MW).",
        "5. Hold floating and North-East capex until it reaches the benchmark (NE ranks last under every weighting).",
    ], fontsize=8.7)
    save(fig, "page6_investment_recommendation.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pm, proj, perf, monthly, diag, diag_m, quad = load()
    scores = region_scores(pm, proj)
    page1(pm, proj, perf, monthly, scores, diag)
    page2(pm, proj, perf, scores)
    page3(pm, proj, perf, quad)
    page4(pm, perf, monthly, diag, diag_m)
    page5(pm, monthly, scores)
    page6(pm, scores, diag)
    print("written:", sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
