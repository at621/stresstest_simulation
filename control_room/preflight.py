"""What goes into a run, judged by the engine itself before anything is calculated.

- ``base_of``: what an input set offers the editor: its scenarios and paths, its portfolios and segments
  with each segment's models (read from stress.models, docstring and all) and settings, and its variants.
  Every value is read from the set's own files and the engine's model registry.
- ``dry_run``: the engine's own verdict on a setup. It calls R1 to R4 as ``cli.pipeline`` does, in a
  temporary folder, and stops before R5. Nothing is calculated, and nothing reaches runs/.
- ``differences``: the base input set against docs/spec/, the one check the engine does not make. The tests use it; the page does not.
- ``specification_document`` and ``parse_yaml``: the page's setup as the YAML the engine reads, and back.
"""

import json
import logging
import re
import tempfile
import threading
import traceback
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from stress import ingest, lineage, scenario, validate
from stress.contracts.errors import RUN_BLOCKING_REASONS, BlockingError, Reason
from stress.contracts.inputs import (
    APPROVAL_FILE,
    DATASETS,
    ENGINE_NAMES,
    INPUT_MANIFEST,
    MATRIX_DIR,
    MODEL_SETTINGS,
    PARAMETER_SET_TOP_KEYS,
    SCENARIO_TOP_KEYS,
    TABLE_DATASETS,
    TTC_MATRIX,
    DatasetSpec,
    segments_of,
)
from stress.contracts.run import RunConfig
from stress.contracts.specification import validate_document
from stress.contracts.status import STATUS_SUFFIX
from stress.ingest.specification import SpecificationLoader
from stress.models import of_portfolio, resolve
from stress.projection.dynamic import validate_assumptions

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
SPEC_DIR = ROOT / "docs" / "spec"
MILLION = 1_000_000.0
SPECIFICATION_PHASE = "specification"
PHASES = (SPECIFICATION_PHASE, "R1", "R2", "R3", "R4")
# A segment's own settings, under the parameter set's names; its models hold their coefficients.
SEGMENT_FIELDS = ("asset_correlation", "sicr_k", "cpr_ttc", "ccf")
# What only a specification can carry. A setup with any of these runs from a file, not from flags.
SECTIONS = ("scenarios", "segments", "terminal_policies", "balance_sheet", "assignments",
            "reporting", "additional_values")
ENVELOPE = ("schema_version", "status", "source", "version", "input_set_hash")
INPUT_SET = re.compile(r"[0-9a-f]{16}")  # inputs/<hash>/, as nbtools names them
SAMPLE = 6
PREVIEW_ROWS = 12
TOP = 12  # a breakdown lists this many groups at most
FILE_GUIDE = {  # what each kind of file is called on the page, and what it holds
    "facilities": ("Facilities", "One row per loan: portfolio, stage, grade, balance, rate, maturity"),
    "obligors": ("Obligors", "One row per borrower: country, sector, SME flag, default flag"),
    "commitments": ("Commitments", "Undrawn amounts and conversion factors, per facility"),
    "opening_provisions": ("Opening provisions", "Provisions at the snapshot date, per facility"),
    "ttc_matrix": ("Rating transitions", "One-year transition probabilities between grades, one file per segment"),
    "scenarios": ("Scenarios", "Macro paths by scenario, country, variable and year"),
    "parameter_set": ("Parameters", "Horizon, master scale, segment parameters and run variants"),
}

_engine = threading.Lock()  # the stress logger is shared, so one dry run at a time


def plain(value):
    """A value the page can read: no numpy scalars, and missing is None, never a number."""
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or value is pd.NA or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return value


@lru_cache(maxsize=32)
def _parsed(path: Path, stamp: int):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def read_yaml(path: Path):
    return _parsed(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=16)
def _loaded_table(path: Path, stamp: int) -> pd.DataFrame:
    return pd.read_parquet(path)


def read_table(folder: Path, filename: str) -> pd.DataFrame:
    path = folder / filename
    return _loaded_table(path, path.stat().st_mtime_ns)


# --- what an input set offers -----------------------------------------------------------------------

def base_of(folder: Path) -> dict:
    """Everything the editor needs from one input set, as its files hold it."""
    manifest = json.loads((folder / INPUT_MANIFEST).read_text(encoding="utf-8"))
    approval_path = folder / APPROVAL_FILE
    approval = json.loads(approval_path.read_text(encoding="utf-8")) if approval_path.is_file() else None
    ps = read_yaml(folder / "parameter_set.yaml")
    paths = read_yaml(folder / "scenarios.yaml")
    fac = read_table(folder, "facilities.parquet")
    names = read_yaml(SPEC_DIR / "targets.yaml")["portfolios"]
    portfolios = [{"id": portfolio, "name": names.get(portfolio, {}).get("name"), "facilities": len(part),
                   "gca": float(part["gca"].sum()) / MILLION, "segments": sorted(part["segment"].unique())}
                  for portfolio, part in fac.groupby("portfolio")]
    values = pd.DataFrame(paths["values"])
    common = {}  # one value per scenario, variable and year when every country states the same; else None
    for (name, variable, year), part in values.groupby(["scenario", "variable", "year"]):
        same = part["value"].nunique() == 1
        common.setdefault(name, {}).setdefault(variable, {})[int(year)] = plain(part["value"].iloc[0]) if same else None
    held = fac.groupby("segment").agg(facilities=("facility_id", "size"), gca=("gca", "sum"))
    segments = {}
    for name, s in segments_of(ps).items():
        segments[name] = {"portfolio": s["portfolio"], **{f: s.get(ENGINE_NAMES.get(f, f)) for f in SEGMENT_FIELDS},
                          "ttc_matrix": s.get("ttc_matrix"),
                          **{setting: s.get(setting) for setting in MODEL_SETTINGS.values()},
                          "models": {role: model_view(s.get(setting), role, s["model_portfolio"])
                                     for role, setting in MODEL_SETTINGS.items()},
                          "facilities": int(held["facilities"].get(name, 0)),
                          "gca": float(held["gca"].get(name, 0.0)) / MILLION}
    choices = {p: {role: [model_view(m.name, role, p) for m in of_portfolio(p, role)] for role in MODEL_SETTINGS}
               for p in sorted({s["portfolio"] for s in segments.values()})}
    return {
        "hash": manifest["input_set_hash"], "folder": f"inputs/{folder.name}", "status": manifest.get("status"),
        "approval": approval, "generator": manifest.get("generator"),
        "parameter_set": {k: ps.get(k) for k in ("parameter_set_id", "version", "status")},
        "horizon": ps["horizon"], "terminal_rule": ps["terminal_rule"], "sicr_triggers": ps.get("sicr_triggers"),
        "variants": [{"id": name, "label": v["label"], "bullet": set(v["repayment_profile"].values()) == {"bullet"}}
                     for name, v in ps["variants"].items()],
        "segments": segments, "portfolios": portfolios, "model_choices": choices,
        "facilities": len(fac), "gca": float(fac["gca"].sum()) / MILLION,
        "scenarios": [{"id": s["id"], "label": s["label"]} for s in paths["scenarios"]],
        "variables": [{"id": v["id"], "label": v["label"], "unit": v["unit"], "value_type": v["value_type"]}
                      for v in paths["variables"]],
        "countries": sorted(values["country"].unique()), "years": sorted(int(y) for y in values["year"].unique()),
        "common": common,
    }


def model_view(name, role: str, portfolio: str) -> dict:
    """A model as the page shows it: its name, where its function lives, its sensitivity and its
    docstring as written. A name the registry does not hold says so, as R2 would."""
    try:
        model = resolve(name, role, portfolio)
    except BlockingError as exc:
        return {"name": name, "problem": exc.message}
    return {"name": model.name, "location": model.location, "sensitivity": model.sensitivity,
            "description": model.description}


def matrix_files(folder: Path) -> dict[str, str]:
    """Each segment's TTC matrix file, as the parameter set names it."""
    return {seg: s["ttc_matrix"] for seg, s in segments_of(read_yaml(folder / "parameter_set.yaml")).items()
            if s.get("ttc_matrix")}


def _table_shape(path: Path) -> tuple[int, list[str]]:
    meta = pq.read_metadata(path)
    return meta.num_rows, [c for c in pq.read_schema(path).names if not c.endswith(STATUS_SUFFIX)]


def files_of(folder: Path) -> list[dict]:
    """Each file an input set must hold, as it stands on disk: present, size, rows, hash against the
    manifest, columns against the contract. The datasets come first, then each segment's matrix file,
    then the manifest and the approval record."""
    manifest_path = folder / INPUT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    rows = []
    try:
        matrices = sorted(set(matrix_files(folder).values()))
    except (OSError, KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError):
        matrices = sorted(f for f in manifest.get("files", {}) if f.startswith(MATRIX_DIR + "/"))
    specs = (*DATASETS, *(DatasetSpec(TTC_MATRIX.name, f, TTC_MATRIX.key, TTC_MATRIX.columns) for f in matrices))
    for spec in specs:
        path = folder / spec.filename
        record = manifest.get("files", {}).get(spec.filename)
        row = {"name": spec.name, "file": spec.filename, "required": True, "present": path.is_file(), "bytes": None,
               "rows": None, "columns": None, "hash_ok": None, "missing_columns": [], "extra_columns": [],
               "problem": None}
        if row["present"]:
            row["bytes"] = path.stat().st_size
            row["hash_ok"] = (ingest._hash(path) == record.get("sha256")) if record else None
            if spec in TABLE_DATASETS or spec.name == TTC_MATRIX.name:
                try:
                    row["rows"], names = _table_shape(path)
                    row["columns"] = len(names)
                    row["missing_columns"] = [c for c in spec.column_names if c not in names]
                    row["extra_columns"] = [c for c in names if c not in spec.column_names]
                except (OSError, ValueError) as exc:
                    row["problem"] = f"not a readable Parquet file: {exc}"
            else:
                try:
                    read_yaml(path)
                except (OSError, yaml.YAMLError) as exc:
                    row["problem"] = f"not valid YAML: {exc}"
        rows.append(row)
    approval_path = folder / APPROVAL_FILE
    approval = json.loads(approval_path.read_text(encoding="utf-8")) if approval_path.is_file() else None
    rows.append({"name": "manifest", "file": INPUT_MANIFEST, "required": True, "present": manifest_path.is_file(),
                 "bytes": manifest_path.stat().st_size if manifest_path.is_file() else None, "rows": None,
                 "columns": None, "hash_ok": None, "missing_columns": [], "extra_columns": [], "problem": None,
                 "detail": f"input set {manifest['input_set_hash'][:16]}" if manifest.get("input_set_hash") else None})
    rows.append({"name": "approval", "file": APPROVAL_FILE, "required": False, "present": approval is not None,
                 "bytes": approval_path.stat().st_size if approval is not None else None, "rows": None, "columns": None,
                 "hash_ok": None, "missing_columns": [], "extra_columns": [], "problem": None,
                 "detail": (f"{approval.get('status')}" + (f" by {approval.get('approved_by')} on {approval.get('approved_on')}"
                                                           if approval.get("approved_by") else "")) if approval else None})
    return rows


def listed(names: list[str], limit: int = 4) -> str:
    """Names in a sentence: the first few, and how many more."""
    shown = ", ".join(names[:limit])
    return f"{shown} and {len(names) - limit} more" if len(names) > limit else shown


def file_roles() -> list[dict]:
    """The files a person can add, in the engine's order, with what each one holds in words. The matrix
    files come from the saved set, one per segment."""
    return [{"name": spec.name, "file": spec.filename, "label": FILE_GUIDE[spec.name][0],
             "holds": FILE_GUIDE[spec.name][1], "format": "Parquet" if spec in TABLE_DATASETS else "YAML"}
            for spec in DATASETS]


def inspected(spec: DatasetSpec, path: Path) -> dict:
    """One file against its place in the contract, before it joins a set: the checks R2 starts with,
    so that a wrong file is named at once. The engine still judges the values."""
    view = {"rows": None, "columns": None, "problem": None}
    if spec in TABLE_DATASETS:
        try:
            view["rows"], names = _table_shape(path)
        except (OSError, ValueError):
            return {**view, "problem": "This is not a readable Parquet file."}
        view["columns"] = len(names)
        missing = [c for c in spec.column_names if c not in names]
        unknown = [c for c in names if c not in spec.column_names]
        if missing:
            view["problem"] = f"Columns missing: {listed(missing)}."
        elif unknown:
            view["problem"] = f"Columns the engine does not know: {listed(unknown)}."
        return view
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {**view, "problem": "This is not a readable YAML file."}
    keys = SCENARIO_TOP_KEYS if spec.name == "scenarios" else PARAMETER_SET_TOP_KEYS
    missing = [k for k in keys if not isinstance(doc, dict) or k not in doc]
    if missing:
        view["problem"] = f"Sections missing: {listed(missing)}."
    return view


def prepared_status(folder: Path) -> dict:
    """A folder of files before it is packaged: which of the datasets it holds, and what is wrong with them."""
    rows = []
    for spec in DATASETS:
        path = folder / spec.filename
        row = {"name": spec.name, "file": spec.filename, "present": path.is_file(), "rows": None, "problem": None}
        if row["present"]:
            row.update(inspected(spec, path))
        rows.append(row)
    return {"folder": folder.as_posix(), "files": rows,
            "complete": all(r["present"] and not r["problem"] for r in rows)}


def approval_of(folder: Path) -> dict | None:
    """The owner's approval record of a set, as it stands beside the data."""
    path = folder / APPROVAL_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _top(series: pd.Series, limit: int = TOP) -> list[list]:
    return [[str(value), int(n)] for value, n in series.value_counts().head(limit).items()]


def table_summary(folder: Path) -> dict:
    """What each table holds, in the terms the run reports: portfolios, stages, countries, amounts."""
    fac = read_table(folder, "facilities.parquet")
    obligors = read_table(folder, "obligors.parquet")
    com = read_table(folder, "commitments.parquet")
    prov = read_table(folder, "opening_provisions.parquet")
    files = matrix_files(folder)
    matrix = pd.concat([read_table(folder, path).assign(segment=seg) for seg, path in files.items()],
                       ignore_index=True)
    names = read_yaml(SPEC_DIR / "targets.yaml")["portfolios"]
    by_portfolio = []
    for portfolio, part in fac.groupby("portfolio"):
        stage = part.groupby("ifrs_stage")["gca"].sum()
        count = part.groupby("ifrs_stage").size()
        by_portfolio.append({"portfolio": portfolio, "name": names.get(portfolio, {}).get("name"), "facilities": len(part),
                             "gca": float(part["gca"].sum()) / MILLION,
                             "stage_gca": {int(s): float(stage.get(s, 0.0)) / MILLION for s in (1, 2, 3)},
                             "stage_count": {int(s): int(count.get(s, 0)) for s in (1, 2, 3)},
                             "products": sorted(part["product"].unique())})
    linked = com.merge(fac[["facility_id", "portfolio"]], on="facility_id", how="left")
    allowances = prov.merge(fac[["facility_id", "portfolio"]], on="facility_id", how="left")
    return {
        "facilities": {"rows": len(fac), "columns": len([c for c in fac.columns if not c.endswith(STATUS_SUFFIX)]),
                       "by_portfolio": by_portfolio, "gca": float(fac["gca"].sum()) / MILLION,
                       "snapshot": str(fac["snapshot_date"].iloc[0]) if len(fac) else None,
                       "products": _top(fac["product"]), "stages": _top(fac["ifrs_stage"]),
                       "flagged": int(fac[["watchlist", "forborne"]].any(axis=1).sum()) if {"watchlist", "forborne"} <= set(fac.columns) else None},
        "obligors": {"rows": len(obligors), "columns": len([c for c in obligors.columns if not c.endswith(STATUS_SUFFIX)]),
                     "countries": _top(obligors["country"]), "sectors": _top(obligors["counterparty_sector"]),
                     "groups": int(obligors["group_id"].nunique()) if "group_id" in obligors else None},
        "commitments": {"rows": len(com), "columns": len([c for c in com.columns if not c.endswith(STATUS_SUFFIX)]),
                        "undrawn": float(com["nominal_undrawn"].sum()) / MILLION,
                        "by_portfolio": [{"portfolio": str(p), "commitments": len(g),
                                          "undrawn": float(g["nominal_undrawn"].sum()) / MILLION,
                                          "ccf": plain(g["accounting_ccf"].mean())}
                                         for p, g in linked.groupby("portfolio")]},
        "opening_provisions": {"rows": len(prov), "columns": len([c for c in prov.columns if not c.endswith(STATUS_SUFFIX)]),
                               "allowance_on": float(prov["allowance_on"].sum()) / MILLION,
                               "provision_off": float(prov["provision_off"].sum()) / MILLION,
                               "overlay": float(prov["overlay_amount"].sum()) / MILLION if "overlay_amount" in prov else None,
                               "by_portfolio": [{"portfolio": str(p), "allowance_on": float(g["allowance_on"].sum()) / MILLION,
                                                 "provision_off": float(g["provision_off"].sum()) / MILLION}
                                                for p, g in allowances.groupby("portfolio")]},
        "ttc_pd_matrix": {"rows": len(matrix), "segments": sorted(matrix["segment"].unique()),
                          "files": dict(sorted(files.items())),
                          "grades": list(matrix[["from_rank", "from_grade"]].drop_duplicates().sort_values("from_rank")["from_grade"])},
    }


def matrix_of(folder: Path, segment: str) -> dict | None:
    """One segment's TTC matrix as a grid, grades in rank order, from the file the segment names."""
    path = matrix_files(folder).get(segment)
    if path is None:
        return None
    cells = read_table(folder, path)
    if cells.empty:
        return None
    grid = cells.pivot(index="from_rank", columns="to_rank", values="probability").sort_index(axis=0).sort_index(axis=1)
    grades = list(cells[["from_rank", "from_grade"]].drop_duplicates().sort_values("from_rank")["from_grade"])
    return {"segment": segment, "file": path, "grades": grades,
            "grid": [[plain(v) for v in row] for row in grid.to_numpy()]}


def preview(folder: Path, name: str, offset: int = 0, query: str = "") -> dict | None:
    """One page of a table as filed, status columns aside. A search looks for the text in any column."""
    spec = next((s for s in TABLE_DATASETS if s.name == name), None)
    if spec is None:
        return None
    raw = read_table(folder, spec.filename)
    columns = [c for c in raw.columns if not c.endswith(STATUS_SUFFIX)]
    view = raw[columns]
    if query:
        hits = view.astype("string").apply(lambda c: c.str.contains(query, case=False, regex=False, na=False))
        view = view[hits.any(axis=1)]
    start = max(0, offset)
    page = view.iloc[start:start + PREVIEW_ROWS]
    return {"name": name, "columns": columns, "total": len(view), "offset": start, "page": PREVIEW_ROWS,
            "rows": [[plain(value) for value in row] for row in page.astype(object).to_numpy()]}


# --- the engine's own verdict -----------------------------------------------------------------------

class _Captured(logging.Handler):
    """What the engine says about itself while it checks."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append({"step": record.name.removeprefix("stress."), "level": record.levelname,
                           "text": record.getMessage()})


def _rejections(rejections: pd.DataFrame) -> list[dict]:
    """Each rule R3 applied to a record here, with what it rejected."""
    rows = []
    for reason in Reason:
        hits = rejections[rejections["reason_code"] == str(reason)]
        if len(hits):
            rows.append({"code": str(reason), "blocks_run": reason in RUN_BLOCKING_REASONS, "records": len(hits),
                         "details": sorted(set(hits["detail"]))[:4],
                         "sample": [str(i) for i in hits["record_id"].head(SAMPLE)]})
    return rows


def _z_view(loaded, drivers) -> list[dict]:
    """The Z each segment's PD, LGD and prepayment model gets in each scenario and year: R4's reading
    of the paths."""
    horizon = [int(y) for y in loaded.parameter_set["horizon"]["projection_years"]]
    part = drivers.z[drivers.z["year"].isin(horizon)]
    grouped = part.groupby(["segment", "model", "scenario", "year"])["z"].agg(["mean", "min", "max"]).reset_index()
    return [{"segment": r.segment, "model": r.model, "scenario": r.scenario, "year": int(r.year),
             "mean": plain(r.mean), "min": plain(r.min), "max": plain(r.max)}
            for r in grouped.itertuples(index=False)]


def _effective_book(routed) -> list[dict]:
    """The accepted book by portfolio, as the run would see it after a specification is applied."""
    rows = []
    for portfolio, part in routed.portfolio.groupby("portfolio"):
        rows.append({"id": portfolio, "segments": sorted(part["segment"].unique()), "facilities": len(part),
                     "gca": float(part["gca"].sum()) / MILLION})
    return rows


def dry_run(config: RunConfig) -> dict:
    """R1 to R4 of the run a setup describes. The order is ``cli.pipeline``'s, up to R5."""
    captured = _Captured()
    logger = logging.getLogger("stress")
    specification = bool(config.specification)
    reached = SPECIFICATION_PHASE if specification else "R1"
    blocked = ctx = loaded = routed = drivers = None
    fault = None
    with _engine, tempfile.TemporaryDirectory(prefix="stress-preflight-") as folder:
        before = logger.level
        logger.addHandler(captured)
        logger.setLevel(logging.INFO)
        try:
            config = ingest.specification.resolve(config)
            reached = "R1"
            ctx = lineage.open_run(config, Path(folder))
            reached = "R2"
            loaded = ingest.load_inputs(ctx)
            reached = "R3"
            routed = validate.validate_and_route(loaded, ctx)
            validate.raise_if_blocking(routed.rejections)
            years = [int(y) for y in loaded.parameter_set["horizon"]["projection_years"]]
            validate_assumptions(loaded.specification, ctx.config.balance_sheet, routed.portfolio,
                                 ctx.scenarios, years)
            reached = "R4"
            drivers = scenario.build_drivers(loaded, ctx)
        except BlockingError as exc:
            blocked = exc
        except Exception as exc:  # noqa: BLE001 - a fault in a check must read as a fault, not as a pass
            fault = {"message": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()}
        finally:
            logger.removeHandler(captured)
            logger.setLevel(before)
    rejections = routed.rejections if routed is not None else None
    verdict = "blocked" if blocked or fault else "rejected" if len(rejections) else "ready"
    return {
        "verdict": verdict, "reached": reached, "phases": list(PHASES[0 if specification else 1:]),
        "blocked": blocked and {"step": blocked.step, "code": str(blocked.code), "message": blocked.message},
        "fault": fault, "log": captured.lines,
        "rejected": None if rejections is None else len(rejections),
        "records": [] if rejections is None else _rejections(rejections),
        "accepted": None if routed is None else len(routed.portfolio),
        "book": None if routed is None else _effective_book(routed),
        "z": None if drivers is None else _z_view(loaded, drivers),
        "scenarios": None if loaded is None else [s["id"] for s in loaded.scenario_meta["scenarios"]],
    }


# --- the requirements -------------------------------------------------------------------------------

def _within(actual: float, expected: float, tolerance: dict) -> bool:
    """Section 12.3: the larger of the absolute and the relative limit."""
    return bool(abs(actual - expected) <= max(tolerance["abs"], tolerance["rel"] * abs(expected)))


class _Group:
    """One set of comparisons with the requirements."""

    def __init__(self, title: str, source: str):
        self.title, self.source, self.rows = title, source, []
        self.error = None  # could not be measured: never a match, never a difference

    def add(self, item: str, actual, expected, unit: str, ok: bool) -> None:
        self.rows.append({"item": item, "actual": plain(actual), "expected": plain(expected), "unit": unit,
                          "ok": bool(ok)})


def _measured(title: str, source: str, build) -> list[_Group]:
    """A defect in the data must not hide the rest of the comparison, and must not read as a pass."""
    try:
        return build()
    except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
        group = _Group(title, source)
        group.error = f"cannot be measured: {type(exc).__name__}: {exc}"
        return [group]


def _amount(group, item, actual, expected_m, tolerance):
    group.add(item, actual / MILLION, expected_m, "EUR m", _within(actual, expected_m * MILLION, tolerance))


def _share(group, item, part, whole, expected, tolerance):
    group.add(item, part / whole if whole else None, expected, "share",
              bool(whole) and _within(part, expected * whole, tolerance))


def _total_groups(fac, com, targets: dict, tolerance: dict) -> list[_Group]:
    totals = _Group("Book totals", "AT-01, section 5.1")
    want = targets["totals"]
    totals.add("Facilities", len(fac), want["facilities"], "count", len(fac) == want["facilities"])
    _amount(totals, "GCA", fac["gca"].sum(), want["gca"], tolerance)
    _amount(totals, "Undrawn", com["nominal_undrawn"].sum(), want["undrawn"], tolerance)
    converted = fac["gca"].sum() + (com["nominal_undrawn"] * com["accounting_ccf"]).sum()
    _amount(totals, "GCA plus converted undrawn", converted, want["converted_total"], tolerance)
    scope = _Group("Scope", "section 5.1")
    for column, value in (("currency", targets["currency"]), ("accounting_category", targets["accounting_category"])):
        outside = int((fac[column] != value).sum())
        scope.add(f"Facilities not {value}", outside, 0, "count", outside == 0)
    return [totals, scope]


def _portfolio_groups(fac, com, targets: dict, tolerance: dict) -> list[_Group]:
    undrawn = com.merge(fac[["facility_id", "portfolio"]], on="facility_id")
    portfolios = _Group("Portfolios", "AT-01, section 5.1")
    stages = _Group("Stages", "AT-01, section 5.2")
    for portfolio, target in targets["portfolios"].items():
        book = fac[fac["portfolio"] == portfolio]
        portfolios.add(f"{portfolio} facilities", len(book), target["facilities"], "count",
                       len(book) == target["facilities"])
        _amount(portfolios, f"{portfolio} GCA", book["gca"].sum(), target["gca"], tolerance)
        _amount(portfolios, f"{portfolio} undrawn",
                undrawn.loc[undrawn["portfolio"] == portfolio, "nominal_undrawn"].sum(), target["undrawn"], tolerance)
        for stage in (1, 2, 3):
            part = book[book["ifrs_stage"] == stage]
            expected = targets["stages"][portfolio]
            stages.add(f"{portfolio} S{stage} facilities", len(part), expected["count"][stage], "count",
                       len(part) == expected["count"][stage])
            _amount(stages, f"{portfolio} S{stage} GCA", part["gca"].sum(), expected["gca"][stage], tolerance)
    return [portfolios, stages]


def _mix_groups(joined: pd.DataFrame, targets: dict, tolerance: dict) -> list[_Group]:
    countries = _Group("Country mix", "AT-01, section 5.3")
    approach = _Group("IRB share", "AT-01, section 5.3")
    sectors = _Group("Sector mix", "AT-01, section 5.3")
    for portfolio in targets["portfolios"]:
        part = joined[joined["portfolio"] == portfolio]
        total = part["gca"].sum()
        for country, value in targets["countries"].items():
            _share(countries, f"{portfolio} {country}", part.loc[part["country"] == country, "gca"].sum(), total,
                   value, tolerance)
        _share(approach, portfolio, part.loc[part["regulatory_approach"] == "IRB", "gca"].sum(), total,
               targets["irb_share"][portfolio], tolerance)
        if len(targets["sectors"].get(portfolio, {})) > 1:
            for section, value in targets["sectors"][portfolio].items():
                _share(sectors, f"{portfolio} NACE {section}", part.loc[part["nace_code"] == section, "gca"].sum(),
                       total, value, tolerance)
    return [countries, approach, sectors]


def _concentration_group(joined: pd.DataFrame, targets: dict, tolerance: dict) -> list[_Group]:
    group = _Group("Counterparties and concentration", "AT-01, sections 5.3 and 5.5")
    p06 = joined[joined["portfolio"] == "P06"]
    for sector, value in targets["p06_counterparties"].items():
        _share(group, f"P06 {sector.replace('_', ' ')}",
               p06.loc[p06["counterparty_sector"] == sector, "gca"].sum(), p06["gca"].sum(), value, tolerance)
    top = targets["concentration_top_groups"]
    for portfolio, value in top["share_of_gca"].items():
        part = joined[joined["portfolio"] == portfolio]
        held = part.groupby("group_id")["gca"].sum().sort_values(ascending=False)
        _share(group, f"{portfolio} top {top['groups']} groups", held.head(top["groups"]).sum(), part["gca"].sum(),
               value, tolerance)
    return [group]


def _range_group(fac, grade_pd: dict, profiles: dict) -> list[_Group]:
    group = _Group("Risk ranges", "section 5.4")
    performing = fac[fac["ifrs_stage"].isin([1, 2])].assign(pd=lambda d: d["current_grade"].map(grade_pd))
    measures = (("Performing PD", "performing_pd", "pd", "rate"), ("TTC LGD", "lgd", "ttc_lgd", "rate"),
                ("Residual maturity", "residual_maturity_years", "residual_maturity", "years"),
                ("LTV", "ltv", "ltv", "rate"), ("DSCR", "dscr", "dscr", "number"))
    for portfolio, profile in profiles.items():
        book = performing[performing["portfolio"] == portfolio]
        for label, key, column, unit in measures:
            if key in profile:
                low, high = book[column].min(), book[column].max()
                group.add(f"{portfolio} {label}", [plain(low), plain(high)], profile[key], f"range {unit}",
                          bool(profile[key][0] <= low and high <= profile[key][1]))
    return [group]


def _calibration_group(fac, grade_pd: dict, segments: dict, tolerance: float) -> list[_Group]:
    """SYN-PAR-05 is an equality. The other section 8.7 values are reference observations the generator
    uses as distribution centres, so they are not compared."""
    group = _Group("Stage PD calibration", "SYN-PAR-05, section 8.7")
    for name, target in segments.items():
        book = fac[(fac["segment"] == name) & fac["ifrs_stage"].isin([1, 2])]
        for stage, key in ((1, "s1_pd"), (2, "s2_pd")):
            part = book[book["ifrs_stage"] == stage]
            average = float((part["gca"] * part["current_grade"].map(grade_pd)).sum() / part["gca"].sum()) if len(part) else None
            group.add(f"{name} S{stage}", average, target[key], "rate",
                      average is not None and abs(average - target[key]) <= tolerance)
    return [group]


def _scenario_groups(folder: Path, spec: dict) -> list[_Group]:
    doc = read_yaml(folder / "scenarios.yaml")
    values = pd.DataFrame(doc["values"])
    paths = _Group("Scenario paths", "section 6.2")
    for name, variables in spec["paths"].items():
        for variable, years in variables.items():
            for year, expected in years.items():
                rows = values[(values["scenario"] == name) & (values["variable"] == variable)
                              & (values["year"] == int(year))]
                same = len(rows) == len(spec["countries"]) and bool((rows["value"] == expected).all())
                paths.add(f"{name} {variable} {year}", rows["value"].iloc[0] if len(rows) else None, expected,
                          rows["unit"].iloc[0] if len(rows) else "", same)
    starting = _Group("Starting values", "section 6.2")
    start = pd.DataFrame(doc.get("starting_values", []))
    for variable, target in spec["starting_values"].items():
        rows = start[start["variable"] == variable] if len(start) else start
        same = len(rows) == len(spec["countries"]) and bool((rows["value"] == target["value"]).all())
        starting.add(variable, rows["value"].iloc[0] if len(rows) else None, target["value"], target["unit"], same)
    return [paths, starting]


def against_requirements(folder: Path) -> list[_Group]:
    """The input set against docs/spec/, group by group. Runs on any input set, whatever its contract."""
    targets = read_yaml(SPEC_DIR / "targets.yaml")
    tolerance = read_yaml(SPEC_DIR / "oracles" / "AT-01.yaml")["tolerance"]

    def facilities():
        return read_table(folder, "facilities.parquet")

    def joined():
        return facilities().merge(read_table(folder, "obligors.parquet"), on="obligor_id", suffixes=("", "_obligor"))

    def graded():
        scale = read_yaml(folder / "parameter_set.yaml")["master_scale"]
        return facilities(), dict(zip(scale["grades"], scale["ttc_pd"]))

    groups = []
    for title, source, build in (
            ("Book totals", "AT-01, section 5.1",
             lambda: _total_groups(facilities(), read_table(folder, "commitments.parquet"), targets, tolerance)),
            ("Portfolios and stages", "AT-01, sections 5.1 and 5.2",
             lambda: _portfolio_groups(facilities(), read_table(folder, "commitments.parquet"), targets, tolerance)),
            ("Mix", "AT-01, section 5.3", lambda: _mix_groups(joined(), targets, tolerance)),
            ("Counterparties and concentration", "AT-01, sections 5.3 and 5.5",
             lambda: _concentration_group(joined(), targets, tolerance)),
            ("Risk ranges", "section 5.4", lambda: _range_group(*graded(), targets["risk_profiles"])),
            ("Stage PD calibration", "SYN-PAR-05, section 8.7",
             lambda: _calibration_group(*graded(), read_yaml(SPEC_DIR / "calibration_targets.yaml")["segments"],
                                        targets["tolerances"]["probability_identity"]["abs"])),
            ("Scenario paths", "section 6.2", lambda: _scenario_groups(folder, read_yaml(SPEC_DIR / "scenarios.yaml")))):
        groups += _measured(title, source, build)
    return groups


@lru_cache(maxsize=8)
def _differences(folder: Path, stamp: int) -> dict:
    groups = against_requirements(folder)
    return {
        "compared": sum(len(g.rows) for g in groups),
        "differing": [{"group": g.title, "source": g.source, **row} for g in groups for row in g.rows if not row["ok"]],
        "unmeasured": [{"group": g.title, "error": g.error} for g in groups if g.error],
    }


def differences(folder: Path) -> dict:
    """Where the base input set departs from docs/spec/. The engine does not check this, so the page
    says so beside its verdict; a derived scenario is an intended departure and is not compared."""
    return _differences(folder, (folder / INPUT_MANIFEST).stat().st_mtime_ns)


# --- the setup as the engine reads it ------------------------------------------------------------------

def needs_specification(document: dict) -> bool:
    """Flags carry a plain run. Anything a flag cannot say goes through a specification file."""
    return any(document.get(name) for name in SECTIONS) or document["run"].get("balance_sheet") == "dynamic"


def specification_document(document: dict, inputs: str, analysis: str | None) -> dict:
    """The YAML the engine reads, from the page's setup: paths as the file needs them, empty settings and
    sections left out, and nothing added."""
    out = {name: document.get(name) for name in ENVELOPE}
    run = {k: v for k, v in document["run"].items() if v not in (None, "", [])}
    run["inputs"] = inputs
    run.pop("analysis", None)
    if analysis:
        run["analysis"] = analysis
    out["run"] = run
    for name in SECTIONS:
        if document.get(name):
            out[name] = document[name]
    return out


def yaml_text(spec: dict) -> str:
    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=110)


def parse_yaml(text: str, base: Path | None) -> dict:
    """A specification's text as the page's setup. The engine's own loader reads it, so a duplicate key
    or an unknown field is refused here as it would be at R2. Paths become repository-relative."""
    try:
        doc = yaml.load(text, Loader=SpecificationLoader)
    except yaml.YAMLError as exc:
        raise BlockingError("R2", "INVALID_SPECIFICATION", f"not valid YAML: {exc}") from exc
    validate_document(doc)
    run = doc["run"]
    for field in ("inputs", "analysis"):
        value = run.get(field)
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        if not path.is_absolute() and base is not None:
            path = (base / path).resolve()
        if field == "inputs" and path.parent.name == "inputs" and INPUT_SET.fullmatch(path.name):
            run[field] = f"inputs/{path.name}"  # an input set is known by its name, wherever the text was
        elif path.is_absolute() and path.is_relative_to(ROOT):
            run[field] = path.relative_to(ROOT).as_posix()
    return doc
