"""Shared helpers for the notebooks in this folder.

A notebook starts a run through ``stress.cli.execute``, the entry point behind ``stress run``,
so it writes an ordinary sealed run folder under ``runs/``. Every intermediate result is then
read back from that folder: the notebooks show what the engine wrote and sealed, and never
recompute or edit it.

    import nbtools as nb
    run = nb.run_engine("inputs/d62d0386f2c5256e")    # or nb.open_run("latest")
    run.table("drivers")                              # results/drivers.parquet
    run.data("facilities")                            # data/facilities.parquet
    run.report("stage_migration")                     # results/reports/stage_migration.csv
"""

import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pyarrow.parquet as pq
import yaml
from matplotlib.colors import LinearSegmentedColormap

from stress import cli
from stress.contracts.run import (
    DATA_DIR,
    MODE_SYNTHETIC,
    REPORTS_DIR,
    RESULTS_DIR,
    RUN_CONFIG,
    RUN_LOG,
    RUN_MANIFEST,
    STATUS_BLOCKED,
    RunConfig,
)
from stress.contracts.tables import SLICE_S3_ORIGINAL
from stress.lineage import compare_outputs, read_manifest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
RUNS_DIR = ROOT / "runs"
INPUTS_DIR = ROOT / "inputs"
INPUT_SET_NAME = re.compile(r"[0-9a-f]{16}")  # inputs/<hash>/; any other folder is skipped
MILLION = 1_000_000.0

# Chart colours from the reference data-viz palette. Each scenario keeps its colour in every
# chart; stages use an ordinal ramp of one hue, light S1 to dark S3.
SCENARIO_COLOURS = {"baseline": "#2a78d6", "adverse": "#eb6834"}
STAGE_COLOURS = {1: "#86b6ef", 2: "#2a78d6", 3: "#104281"}
INK, INK_SECONDARY, MUTED, GRID, AXIS, SURFACE = (
    "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb")
# Sign of a change: blue below zero, grey at zero, red above.
DIVERGING = LinearSegmentedColormap.from_list("diverging", ["#2a78d6", "#f0efec", "#e34948"])


def setup() -> None:
    """Display options for wide tables and a quiet chart style."""
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 80)
    pd.set_option("display.precision", 6)
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "figure.dpi": 110, "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "semibold",
        "text.color": INK, "axes.labelcolor": INK_SECONDARY,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
        "grid.linestyle": "-", "axes.axisbelow": True,
        "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
        "legend.frameon": False, "legend.fontsize": 8.5,
    })


# --- running the engine --------------------------------------------------------------------------

@contextmanager
def _at_root():
    """The command line resolves inputs/ against the working directory, so run from the root."""
    before = Path.cwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(before)


@contextmanager
def _progress(quiet: bool):
    """The step log on the cell output (stdout); runs/<run_id>/run.log keeps every line."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(cli.CONSOLE_FORMAT))
    handler.setLevel(logging.WARNING if quiet else logging.INFO)
    cli.LOG.addHandler(handler)
    cli.LOG.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        cli.LOG.removeHandler(handler)


def run_engine(inputs: str, scenarios=("baseline", "adverse"), variant: str = "core",
               quiet: bool = False, raise_if_blocked: bool = True) -> "Run":
    """Run R1-R11 as `uv run stress run` does from the repository root; return the sealed run.

    A blocked run is sealed too (status BLOCKED). By default that raises here, with the
    reason, so "Run all" stops at the run cell; open the folder with ``open_run`` to inspect it.
    """
    config = RunConfig(inputs=Path(inputs).as_posix(), scenarios=tuple(scenarios),
                       variant=variant, mode=MODE_SYNTHETIC)
    with _at_root(), _progress(quiet):
        ctx, _ = cli.execute(config, RUNS_DIR)
    run = Run(ctx.run_dir)
    if run.blocked and raise_if_blocked:
        b = run.blocked
        raise RuntimeError(f"run {run.run_id} BLOCKED at {b['step']}: {b['code']}: {b['message']} "
                           f"(folder {run.path.as_posix()})")
    return run


# --- reading runs --------------------------------------------------------------------------------

class Run:
    """One sealed run folder: manifest, inputs copy (data/), results tables, reports and log."""

    def __init__(self, path):
        self.path = Path(path)
        self.manifest = read_manifest(self.path)
        self._cache = {}

    def __repr__(self) -> str:
        return f"Run({self.run_id!r}, status={self.status}, folder={self.path.as_posix()!r})"

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]

    @property
    def status(self) -> str:
        return self.manifest["status"]

    @property
    def blocked(self) -> dict | None:
        return self.manifest.get("blocked")

    @property
    def config(self) -> dict:
        return self.manifest["config"]

    @property
    def scenarios(self) -> list[str]:
        return list(self.config["scenarios"])

    def _read(self, key: str, loader):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def table(self, name: str) -> pd.DataFrame:
        """A results table, e.g. ``table("slices")`` reads results/slices.parquet."""
        path = self.path / RESULTS_DIR / f"{name}.parquet"
        return self._read(f"results/{name}", lambda: pd.read_parquet(path))

    def data(self, name: str):
        """A dataset of the input-set copy: a DataFrame for Parquet, a dict for YAML or JSON."""
        base = self.path / DATA_DIR
        for suffix, loader in ((".parquet", pd.read_parquet),
                               (".yaml", lambda p: yaml.safe_load(p.read_text(encoding="utf-8"))),
                               (".json", lambda p: json.loads(p.read_text(encoding="utf-8")))):
            path = base / f"{name}{suffix}"
            if path.is_file():
                return self._read(f"data/{name}", lambda path=path, loader=loader: loader(path))
        raise FileNotFoundError(f"no dataset {name!r} in {base.as_posix()}")

    def report(self, name: str) -> pd.DataFrame:
        """An R10 report, e.g. ``report("impairment")`` reads results/reports/impairment.csv."""
        path = self.path / RESULTS_DIR / REPORTS_DIR / f"{name}.csv"
        return self._read(f"reports/{name}", lambda: pd.read_csv(path))

    def summary(self) -> str:
        path = self.path / RESULTS_DIR / REPORTS_DIR / "summary.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def log(self) -> str:
        path = self.path / RUN_LOG
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def config_yaml(self) -> str:
        return (self.path / RUN_CONFIG).read_text(encoding="utf-8")

    def overview(self) -> pd.Series:
        """What R1 fixed and R11 sealed, one line each."""
        m = self.manifest
        ps = m.get("parameter_set", {})
        return pd.Series({
            "run_id": m["run_id"], "status": m["status"], "label": m["label"], "mode": m["mode"],
            "variant": self.config["variant"], "scenarios": ", ".join(self.scenarios),
            "input set": m["input_set_hash"], "input generator": m["input_manifest"]["generator"],
            "parameter set": f"{ps.get('parameter_set_id')} v{ps.get('version')} ({ps.get('status')})",
            "code version": m["code_version"], "git SHA": m["git_sha"],
            "spec version": m["spec_version"], "created": m["created_at"], "sealed": m["sealed_at"],
        }, name="run")

    def outputs(self) -> pd.DataFrame:
        """Every file R11 hashed, with its size and, for Parquet, rows and columns."""
        rows = []
        for name, digest in sorted(self.manifest["outputs"].items()):
            path = self.path / name
            row = {"file": name, "kB": round(path.stat().st_size / 1024, 1), "sha256": digest[:16]}
            if path.suffix == ".parquet":
                meta = pq.read_metadata(path)
                row.update(rows=meta.num_rows, columns=meta.num_columns)
            rows.append(row)
        return pd.DataFrame(rows)

    def grades(self) -> list[str]:
        """Performing master-scale grades in rank order, G1 first."""
        return list(self.data("parameter_set")["master_scale"]["grades"])

    def book(self) -> pd.DataFrame:
        """The input facilities with their obligor's country and sector."""
        def load():
            obligors = self.data("obligors")[["obligor_id", "country", "counterparty_sector"]]
            return self.data("facilities").merge(obligors, on="obligor_id", how="left")
        return self._read("book", load)

    def portfolio_names(self) -> dict[str, str]:
        """A plain label per portfolio from its products and counterparty sectors."""
        names = {}
        for p, part in self.book().groupby("portfolio"):
            products = ", ".join(sorted(part["product"].unique())).replace("_", " ")
            sectors = ", ".join(sorted(part["counterparty_sector"].unique())).replace("_", " ")
            names[p] = f"{products} ({sectors})"
        return names


def _sealed(path: Path) -> bool:
    return (path / RUN_MANIFEST).is_file()


def list_runs() -> pd.DataFrame:
    """Every run folder, oldest first. A folder without a manifest was never sealed."""
    rows = []
    for path in sorted(p for p in RUNS_DIR.iterdir() if p.is_dir()):
        if not _sealed(path):
            rows.append({"run_id": path.name, "status": "UNSEALED"})
            continue
        m = read_manifest(path)
        rows.append({
            "run_id": m["run_id"], "status": m["status"], "variant": m["config"]["variant"],
            "scenarios": ",".join(m["config"]["scenarios"]), "input_set": m["input_set_hash"][:16],
            "code_version": m["code_version"], "created_at": m["created_at"],
            "outputs_digest": m["outputs_digest"][:16],
        })
    return pd.DataFrame(rows)


def open_run(ref: str = "latest", variant: str = "core") -> Run:
    """A sealed run by run ID, by folder path, or "latest" (the newest sealed run of a variant)."""
    if ref == "latest":
        runs = list_runs()
        runs = runs[(runs["status"] != "UNSEALED") & (runs["status"] != STATUS_BLOCKED)
                    & (runs["variant"] == variant)]
        if runs.empty:
            raise FileNotFoundError(f"no sealed {variant} run in {RUNS_DIR.as_posix()}")
        ref = runs.sort_values(["created_at", "run_id"]).iloc[-1]["run_id"]
    path = Path(ref) if Path(ref).is_absolute() else RUNS_DIR / Path(ref).name
    return Run(path)


def input_sets() -> pd.DataFrame:
    """The input sets under inputs/<hash>/, with generator, parameter set and approval status."""
    rows = []
    for path in sorted(p for p in INPUTS_DIR.iterdir() if p.is_dir() and INPUT_SET_NAME.fullmatch(p.name)):
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        approval = path / "approval.json"
        approval = json.loads(approval.read_text(encoding="utf-8")) if approval.is_file() else {}
        rows.append({
            "inputs": f"inputs/{path.name}", "status": manifest.get("status"),
            "parameter_set": manifest.get("parameter_set_id"),
            "generator": manifest.get("generator", {}).get("version"),
            "approval": approval.get("status", "none"),
        })
    return pd.DataFrame(rows)


def reproduction(run: Run) -> pd.DataFrame:
    """Every other sealed run of the same input set, scenarios and variant, and whether its output
    hashes equal this run's. Equal code versions must give identical outputs (section 12.2)."""
    rows = []
    for path in sorted(p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name != run.run_id):
        if not _sealed(path):
            continue
        other = read_manifest(path)
        same = all(other["config"][k] == run.config[k] for k in ("variant", "scenarios"))
        if not same or other["input_set_hash"] != run.manifest["input_set_hash"]:
            continue
        differing = compare_outputs(other, run.manifest)
        rows.append({
            "run_id": other["run_id"], "status": other["status"], "code_version": other["code_version"],
            "same_code_version": other["code_version"] == run.manifest["code_version"],
            "outputs_differing": len(differing), "identical": not differing,
        })
    return pd.DataFrame(rows, columns=["run_id", "status", "code_version", "same_code_version",
                                       "outputs_differing", "identical"])


# --- presentation --------------------------------------------------------------------------------

def millions(df: pd.DataFrame, columns=None, digits: int = 1):
    """EUR amounts shown in millions; ``columns`` defaults to every numeric column. Display only:
    the results stay unrounded EUR."""
    columns = list(df.select_dtypes("number").columns if columns is None else columns)
    out = df.copy()
    out[columns] = out[columns] / MILLION
    return out.style.format(f"{{:,.{digits}f}}", subset=columns, na_rep="")


def grade_order(values, grades: list[str]) -> list[str]:
    """Grade labels in rank order (G1..GN, then D), not in string order (G1, G10, G2...)."""
    rank = {g: i for i, g in enumerate([*grades, "D"])}
    return sorted(set(values), key=lambda g: rank.get(g, len(rank)))


def slice_order(values, grades: list[str]) -> list[str]:
    """Slices as the projection holds them: performing grades in rank order, then the original
    S3 slice, then the new S3 cohorts by entry year and origin stage."""
    rank = {g: (0, i, "") for i, g in enumerate(grades)} | {SLICE_S3_ORIGINAL: (1, 0, "")}
    return sorted(set(values), key=lambda s: rank.get(s, (2, 0, s)))
