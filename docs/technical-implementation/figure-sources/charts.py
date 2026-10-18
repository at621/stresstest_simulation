"""Charts of the technical implementation document (docs/technical-implementation/).

Draws the seven charts from one sealed run and the engine's own kernels. The run is only read.
Every PNG gets a print size so Word places it at page width or less.

    uv run python docs/technical-implementation/figure-sources/charts.py <run_id>
    uv run python docs/technical-implementation/figure-sources/charts.py --print-size [--width=IN] <png> ...

The second form only sets the print size, for the diagrams drawn with the Mermaid CLI.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.colors import ListedColormap
from PIL import Image

from stress.cashflows.kernels import contractual_schedule
from stress.params.lgd import lgd_from_z
from stress.params.prepay import prepayment_rate
from stress.validate.sicr import TtcLifetime, sicr_rank

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE.parent / "images"
PAGE_WIDTH_IN = 6.3  # usable text width of an A4 or Letter page in Word
MAX_HEIGHT_IN = 8.0
DPI = 200
SCALE = 0.8  # smaller canvas at the same point sizes keeps text legible at page width

# Reference palette, as in notebooks/nbtools.py: each scenario keeps its colour in every chart.
BASE, ADV = "#2a78d6", "#eb6834"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
STAGE = {1: "#86b6ef", 2: "#2a78d6", 3: "#104281"}
INK, INK2, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#ffffff"
TTC_INK = "#52514e"
PORTFOLIO_NAMES = {"P01": "P01 Mortgages", "P02": "P02 Consumer", "P03": "P03 SME", "P04": "P04 CRE",
                   "P05": "P05 Corporate", "P06": "P06 Sovereign/bank"}

plt.switch_backend("Agg")
plt.rcParams.update({
    "font.family": ["Segoe UI", "Arial", "DejaVu Sans"],
    "font.size": 9.5,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2,
    "axes.titlesize": 10.5,
    "axes.titleweight": "semibold",
    "axes.titlecolor": INK,
    "axes.titlelocation": "left",
    "axes.titlepad": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "legend.frameon": False,
    "legend.fontsize": 9,
    "lines.linewidth": 2,
    "lines.solid_capstyle": "round",
    "lines.solid_joinstyle": "round",
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


# --- output -------------------------------------------------------------------------------------

def set_print_size(path: Path, width_in: float | None = None) -> None:
    """Record a DPI in the PNG so it prints at page width or less and at most MAX_HEIGHT_IN tall."""
    with Image.open(path) as image:
        image.load()
        copy = image.copy()
    w, h = copy.size
    width = width_in or min(PAGE_WIDTH_IN, MAX_HEIGHT_IN * w / h)
    dpi = w / width
    copy.save(path, dpi=(dpi, dpi), optimize=True)


def figure(ncols: int = 1, size: tuple[float, float] = (6.4, 4.8), **kwargs):
    return plt.subplots(1, ncols, figsize=(size[0] * SCALE, size[1] * SCALE), **kwargs)


def save(fig, name: str) -> None:
    path = OUT / name
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    set_print_size(path)
    print("wrote", path.relative_to(ROOT).as_posix())


def marker(ax, x, y, color) -> None:
    ax.plot(x, y, "o", ms=6, color=color, mec=SURFACE, mew=1.5, zorder=4)


# --- charts -------------------------------------------------------------------------------------

def z_paths(z_nl: pd.DataFrame, segments: list[str]) -> None:
    fig, (a, b) = figure(2, (9.2, 3.6), gridspec_kw={"width_ratios": [1.45, 1]})
    mean = z_nl[z_nl["year"].between(2027, 2040)].groupby(["scenario", "year"])["z"].mean().unstack(0)
    a.axvspan(2026.5, 2029.5, color="#f3f2ee", zorder=0, lw=0)
    a.text(2028, 0.62, "scenario", ha="center", color=INK2, fontsize=8.5)
    a.text(2033, 0.62, "reversion\n2030–2035", ha="center", va="center", color=INK2, fontsize=8.5)
    a.axhline(0, color=AXIS, lw=1, zorder=1)
    for scen, col in (("baseline", BASE), ("adverse", ADV)):
        a.plot(mean.index, mean[scen], color=col, label=scen.capitalize(), zorder=3)
        marker(a, mean.index[:3], mean[scen].iloc[:3], col)
    a.set_xlim(2026.5, 2040.3)
    a.set_ylim(-1.6, 0.85)
    a.set_xticks(range(2027, 2041, 2))
    a.set_ylabel("Z (mean over the 7 segments)")
    a.set_title("(a) Z-score path per scenario")
    z27 = z_nl[z_nl["year"] == 2027].pivot(index="segment", columns="scenario", values="z")
    y = np.arange(len(segments))
    h = 0.36
    b.barh(y - h / 2, z27.loc[segments, "baseline"], height=h, color=BASE, edgecolor=SURFACE, lw=1)
    b.barh(y + h / 2, z27.loc[segments, "adverse"], height=h, color=ADV, edgecolor=SURFACE, lw=1)
    b.axvline(0, color=AXIS, lw=1)
    b.set_yticks(y, segments)
    b.invert_yaxis()
    b.grid(axis="y", visible=False)
    b.set_xlabel("Z in 2027")
    b.set_title("(b) Z in 2027 by segment")
    fig.tight_layout(w_pad=3)
    handles, labels = a.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", ncols=2, bbox_to_anchor=(1.0, 1.06))
    save(fig, "fig-06-z-paths.png")


def schedule_profiles() -> None:
    fig, ax = figure(1, (7.4, 3.4))
    d0, r, mat = 100.0, 0.05, 6.5
    for prof, col in zip(("bullet", "annuity", "linear"), SERIES):
        s = contractual_schedule(d0, r, mat, prof)
        starts = np.concatenate(([0.0], s.t[:-1]))
        xs = np.concatenate([np.ravel(np.column_stack((starts, s.t))), [s.t[-1]]])
        ys = np.concatenate([np.repeat(s.opening_balance, 2), [0.0]])
        ax.plot(xs, ys, color=col, label=prof.capitalize(), zorder=3)
        marker(ax, s.t, s.opening_balance, col)
    ax.set_xlim(0, 7)
    ax.set_ylim(0, 110)
    ax.set_xticks(np.arange(0, 7.5, 1))
    ax.set_xlabel("Years from the valuation date (default dates at each marker; final stub of 0.5 years)")
    ax.set_ylabel("Contractual balance B[k]")
    ax.set_title("Contractual drawn balance by repayment profile (D = 100, r = 5%, M = 6.5 years)")
    ax.legend(loc="lower left")
    save(fig, "fig-07-schedule-profiles.png")


def pd_ttc_pit(res: Path, m_ttc: np.ndarray, grades: list[str], seg: str) -> None:
    pit = pd.read_parquet(res / "pit_matrices.parquet",
                          filters=[("segment", "==", seg), ("country", "==", "NL"), ("year", "==", 2027),
                                   ("to_grade", "==", "D")])
    fig, (a, b) = figure(2, (9.2, 3.7))
    x = np.arange(1, len(grades) + 1)
    a.plot(x, m_ttc[:-1, -1] * 100, color=TTC_INK, label="TTC (master scale)", zorder=3)
    marker(a, x, m_ttc[:-1, -1] * 100, TTC_INK)
    for scen, col in (("baseline", BASE), ("adverse", ADV)):
        p = pit[pit["scenario"] == scen].set_index("from_grade").loc[grades, "probability"].to_numpy()
        a.plot(x, p * 100, color=col, label=f"PiT 2027, {scen}", zorder=3)
        marker(a, x, p * 100, col)
    a.set_yscale("log")
    a.set_xticks(x, grades)
    a.set_yticks([0.02, 0.1, 0.5, 2, 10, 30], ["0.02%", "0.1%", "0.5%", "2%", "10%", "30%"])
    a.minorticks_off()
    a.set_ylabel("One-year PD (log scale)")
    a.set_title(f"(a) {seg}: one-year PD by grade, TTC vs PiT 2027")
    a.legend(loc="upper left")
    grade = "G6"
    gi = grades.index(grade)
    curves = pd.read_parquet(res / "pd_curves.parquet",
                             filters=[("segment", "==", seg), ("country", "==", "NL"),
                                      ("valuation_year", "==", 2026), ("cohort", "==", grade),
                                      ("fraction", "==", 1.0)])
    k = np.arange(1, 9)
    f_ttc = np.array([np.linalg.matrix_power(m_ttc, n)[gi, -1] for n in k])
    b.plot(k, f_ttc * 100, color=TTC_INK, label="TTC matrix powers", zorder=3)
    marker(b, k, f_ttc * 100, TTC_INK)
    for scen, col in (("baseline", BASE), ("adverse", ADV)):
        c = curves[curves["scenario"] == scen].set_index("default_bucket").loc[k, "f"].to_numpy()
        b.plot(k, c * 100, color=col, label=f"PiT path, {scen}", zorder=3)
        marker(b, k, c * 100, col)
    b.set_xticks(k, [str(2026 + i) for i in k])
    b.set_ylabel("Cumulative PD F[k] (%)")
    b.set_xlabel("Default bucket (year-end)")
    b.set_title(f"(b) {seg} grade {grade}: lifetime PD valued at end-2026")
    b.legend(loc="upper left")
    fig.tight_layout(w_pad=3)
    save(fig, "fig-08-pd-ttc-pit.png")


def lgd_prepayment(z_nl: pd.DataFrame, seg_par: dict) -> None:
    fig, (a, b) = figure(2, (9.2, 3.5))
    zz = np.linspace(-2.5, 1.5, 200)
    panels = (
        (a, "P04", 0.35, "lgd", 1),
        (b, "P01", seg_par["P01"]["cpr_ttc"], "cpr", -1),
    )
    for ax, seg, ttc_value, kind, dy in panels:
        p = seg_par[seg]

        def curve(zv, kind=kind, ttc_value=ttc_value, p=p):
            base = np.full_like(np.atleast_1d(zv), ttc_value, dtype=float)
            if kind == "lgd":
                return lgd_from_z(base, p["lgd_w"], zv)
            return prepayment_rate(base, p["cpr_v"], zv)

        if kind == "lgd":
            title = f"(a) LGD of the year, {seg} (LGD_TTC 35%, w = {p['lgd_w']})"
            ax.set_ylabel("LGD (%)")
        else:
            title = f"(b) Prepayment rate, {seg} (CPR_TTC {ttc_value:.0%}, v = {p['cpr_v']})"
            ax.set_ylabel("CPR (%)")
            ax.set_ylim(0, 12.5)
        ax.plot(zz, curve(zz) * 100, color=INK2, zorder=2)
        ax.axvline(0, color=AXIS, lw=1, zorder=1)
        ax.axhline(ttc_value * 100, color=GRID, lw=1, zorder=1)
        for scen, col in (("baseline", BASE), ("adverse", ADV)):
            row = z_nl[(z_nl["segment"] == seg) & (z_nl["scenario"] == scen) & (z_nl["year"] == 2027)]
            zv = float(row["z"].iloc[0])
            yv = float(curve(np.array([zv]))[0]) * 100
            marker(ax, [zv], [yv], col)
            ax.annotate(f"{scen} 2027\nZ = {zv:+.2f}: {yv:.1f}%", (zv, yv), textcoords="offset points",
                        xytext=(12, 18 * dy), fontsize=8.5, color=INK2, va="center")
        ax.set_xlabel("Z (positive = better economy)")
        ax.set_title(title)
    fig.tight_layout(w_pad=3)
    save(fig, "fig-09-lgd-prepayment.png")


def sicr_grid(m_ttc: np.ndarray, grades: list[str], seg: str, k_mult: float) -> None:
    horizon = 5.0
    life = TtcLifetime({seg: m_ttc}).pd(seg, horizon)
    n = len(grades)
    grid = np.zeros((n, n + 1), dtype=int)
    for o in range(1, n + 1):
        line, _ = sicr_rank(life, o, k_mult)
        for c in range(1, n + 2):
            grid[o - 1, c - 1] = 3 if c == n + 1 else (2 if c >= line else 1)
    fig, ax = figure(1, (7.4, 4.4))
    ax.imshow(grid, cmap=ListedColormap([STAGE[1], STAGE[2], STAGE[3]]), vmin=1, vmax=3, aspect="auto")
    for r in range(n):
        for c in range(n + 1):
            s = grid[r, c]
            ax.text(c, r, f"S{s}", ha="center", va="center", fontsize=8, color=INK if s == 1 else SURFACE)
    ax.set_xticks(range(n + 1), grades + ["D"])
    ax.set_yticks(range(n), grades)
    ax.set_xticks(np.arange(-0.5, n + 1, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n, 1), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.grid(which="major", visible=False)
    ax.tick_params(which="minor", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xlabel("Current grade of the slice")
    ax.set_ylabel("Origination grade")
    ax.set_title(f"{seg}: stage of a grade slice (k = {k_mult}, horizon {horizon:g} years, TTC matrix)")
    save(fig, "fig-11-sicr-stage-grid.png")


def stage_mix(res: Path) -> None:
    slices = pd.read_parquet(res / "slices.parquet", columns=["scenario", "year", "stage", "gca"])
    mix = slices.groupby(["scenario", "year", "stage"])["gca"].sum().unstack("stage") / 1e9
    fig, axes = figure(2, (9.2, 3.6), sharey=True)
    for ax, scen in zip(axes, ("baseline", "adverse")):
        part = mix.loc[scen]
        years = part.index.to_numpy()
        bottom = np.zeros(len(years))
        for st in (1, 2, 3):
            ax.bar(years, part[st], bottom=bottom, width=0.5, color=STAGE[st], label=f"S{st}",
                   edgecolor=SURFACE, lw=1.5, zorder=3)
            bottom += part[st].to_numpy()
        for yv, s3, s2, s1 in zip(years, part[3], part[2], part[1]):
            ax.text(yv, s1 + s2 + s3 + 0.15, f"S3 €{s3 * 1000:,.0f}m", ha="center", fontsize=8, color=INK2)
        ax.set_xticks(years, ["2026\nopening" if y == 2026 else str(y) for y in years])
        ax.grid(axis="x", visible=False)
        ax.set_title(f"{'(a)' if scen == 'baseline' else '(b)'} {scen.capitalize()}")
        ax.set_ylim(0, 12.2)
    axes[0].set_ylabel("GCA (EUR bn)")
    axes[1].legend(loc="lower right", ncols=3, bbox_to_anchor=(1.0, 1.06))
    fig.tight_layout(w_pad=2)
    save(fig, "fig-13-stage-mix.png")


def provisions_charges(res: Path) -> None:
    imp = pd.read_csv(res / "reports" / "impairment.csv")
    tot = imp[imp["portfolio"] == "Total"]
    fig, (a, b) = figure(2, (9.2, 3.8), gridspec_kw={"width_ratios": [1, 1.2]})
    for scen, col in (("baseline", BASE), ("adverse", ADV)):
        t = tot[tot["scenario"] == scen].sort_values("year")
        years = [2026] + t["year"].tolist()
        opening = (t["opening_on"].iloc[0] + t["opening_off"].iloc[0]) / 1e6
        vals = [opening] + ((t["closing_on"] + t["closing_off"]) / 1e6).tolist()
        a.plot(years, vals, color=col, label=scen.capitalize(), zorder=3)
        marker(a, years, vals, col)
        a.annotate(f"€{vals[-1]:,.0f}m", (years[-1], vals[-1]), textcoords="offset points", xytext=(8, 0),
                   va="center", fontsize=8.5, color=INK2)
    a.annotate("€279m frozen\nopening (O4)", (2026, 278.6), textcoords="offset points", xytext=(4, -14),
               fontsize=8.5, color=INK2, va="top")
    a.set_xticks([2026, 2027, 2028, 2029], ["2026", "2027", "2028", "2029"])
    a.set_xlim(2025.8, 2029.6)
    a.set_ylim(0, 900)
    a.set_ylabel("Provisions at year-end (EUR m)")
    a.set_title("(a) Total provisions, on- plus off-balance")
    a.legend(loc="upper left")
    last = imp[(imp["year"] == 2029) & (imp["portfolio"] != "Total")]
    cum = last.pivot(index="portfolio", columns="scenario", values="cumulative_charge") / 1e6
    y = np.arange(len(cum))
    h = 0.36
    b.barh(y - h / 2, cum["baseline"], height=h, color=BASE, label="Baseline", edgecolor=SURFACE, lw=1,
           zorder=3)
    b.barh(y + h / 2, cum["adverse"], height=h, color=ADV, label="Adverse", edgecolor=SURFACE, lw=1,
           zorder=3)
    for yi, (bv, av) in enumerate(zip(cum["baseline"], cum["adverse"])):
        b.text(max(bv, 0) + 3, yi - h / 2, f"{bv:,.1f}", va="center", fontsize=8, color=INK2)
        b.text(max(av, 0) + 3, yi + h / 2, f"{av:,.1f}", va="center", fontsize=8, color=INK2)
    b.axvline(0, color=AXIS, lw=1)
    b.set_yticks(y, [PORTFOLIO_NAMES[p] for p in cum.index])
    b.invert_yaxis()
    b.grid(axis="y", visible=False)
    b.set_xlim(-5, 205)
    b.set_xlabel("Cumulative charge 2027–2029 (EUR m)")
    b.set_title("(b) Cumulative charge by portfolio")
    b.legend(loc="upper right")
    fig.tight_layout(w_pad=3)
    save(fig, "fig-14-provisions-charges.png")


# --- entry point --------------------------------------------------------------------------------

def draw(run_id: str) -> None:
    run = ROOT / "runs" / run_id
    res, data = run / "results", run / "data"
    ps = yaml.safe_load((data / "parameter_set.yaml").read_text(encoding="utf-8"))
    seg_par = ps["segments"]
    grades = list(ps["master_scale"]["grades"])
    z = pd.read_parquet(res / "drivers.parquet")
    z_nl = z[z["country"] == "NL"]  # the six countries share the common section 6.2 paths
    seg = "P03"
    ttc = pd.read_parquet(data / "ttc_pd_matrix.parquet")
    cells = ttc[ttc["segment"] == seg]
    m_ttc = np.zeros((len(grades) + 1, len(grades) + 1))
    m_ttc[cells["from_rank"] - 1, cells["to_rank"] - 1] = cells["probability"]
    OUT.mkdir(exist_ok=True)
    z_paths(z_nl, list(seg_par))
    schedule_profiles()
    pd_ttc_pit(res, m_ttc, grades, seg)
    lgd_prepayment(z_nl, seg_par)
    sicr_grid(m_ttc, grades, seg, float(seg_par[seg]["sicr_k"]))
    stage_mix(res)
    provisions_charges(res)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "--print-size":
        width = None
        for arg in argv[1:]:
            if arg.startswith("--width="):
                width = float(arg.split("=", 1)[1])
            else:
                set_print_size(Path(arg), width)
        return 0
    draw(argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
