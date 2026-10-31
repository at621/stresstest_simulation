"""R2 load inputs: check each file's hash against R1, parse into typed tables (EUR amounts,
decimal rates, a status on every value), keep the raw files unchanged, record row counts
and control totals.

Section 4.2, DAT-02, DAT-03, OPS-01.
"""

import hashlib
import json
import logging
import re
import shutil
from datetime import date

import numpy as np
import pandas as pd
import yaml

from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import (
    APPROVAL_FILE,
    COMMITMENTS,
    DATASETS,
    FACILITIES,
    INPUT_MANIFEST,
    OBLIGORS,
    OPENING_PROVISIONS,
    PARAMETER_SET,
    PARAMETER_SET_TOP_KEYS,
    SCENARIO_TOP_KEYS,
    SCENARIO_UNITS,
    SCENARIO_VALUE_FIELDS,
    SCENARIO_VALUE_TYPES,
    SCENARIOS,
    TTC_PD_MATRIX,
    DatasetSpec,
    LoadedInputs,
    TypedTable,
)
from stress.contracts.run import RunContext
from stress.contracts.status import ALL_STATUSES, STATUS_SUFFIX, ValueStatus
from stress.ingest import specification

STEP = "R2"
LOG = logging.getLogger("stress.R2")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _hash(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def input_set_hash(file_hashes: dict[str, str]) -> str:
    """The content hash of an input set: SHA-256 over the sorted (file, hash) pairs."""
    text = json.dumps(dict(sorted(file_hashes.items())), separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_hashes(ctx: RunContext, manifest: dict) -> dict[str, str]:
    files = manifest.get("files", {})
    hashes = {}
    for spec in DATASETS:
        path = ctx.input_dir / spec.filename
        if not path.is_file():
            raise BlockingError(STEP, Block.UNREADABLE_FILE, f"{spec.filename} is missing")
        expected = files.get(spec.filename, {}).get("sha256")
        actual = _hash(path)
        if actual != expected:
            raise BlockingError(STEP, Block.INPUT_HASH_MISMATCH,
                                f"{spec.filename} hash {actual[:12]} differs from the manifest")
        hashes[spec.filename] = actual
    if input_set_hash(hashes) != ctx.input_set_hash:
        raise BlockingError(STEP, Block.INPUT_HASH_MISMATCH, "input-set hash differs from R1")
    return hashes


def copy_raw(ctx: RunContext) -> None:
    """Keep the raw files unchanged in runs/<run_id>/data/ (DAT-03)."""
    ctx.data_dir.mkdir(parents=True, exist_ok=False)
    for spec in DATASETS:
        shutil.copy2(ctx.input_dir / spec.filename, ctx.data_dir / spec.filename)
    shutil.copy2(ctx.input_dir / INPUT_MANIFEST, ctx.data_dir / INPUT_MANIFEST)


# --- tables -------------------------------------------------------------------------------------

def _infer_status(series: pd.Series, kind: str) -> pd.Series:
    missing = series.isna()
    if kind == "str":
        missing = missing | (series.astype("string").str.strip() == "")
    status = pd.Series(str(ValueStatus.SUPPLIED), index=series.index, dtype=object)
    if kind in ("float", "int"):
        numeric = pd.to_numeric(series, errors="coerce")
        status[numeric == 0] = str(ValueStatus.ZERO)
    status[missing] = str(ValueStatus.MISSING)
    return status


def _cast(series: pd.Series, kind: str, name: str, dataset: str) -> pd.Series:
    try:
        if kind == "float":
            values = pd.to_numeric(series, errors="raise").astype(float)
            if np.isinf(values).any():
                raise ValueError("infinite numeric value")
            return values
        if kind == "int":
            values = pd.to_numeric(series, errors="raise")
            return values.astype("Int64")
        if kind == "bool":
            def boolean(value):
                if pd.isna(value):
                    return None
                if isinstance(value, (bool, np.bool_)):
                    return bool(value)
                if isinstance(value, (int, float, np.number)) and value in (0, 1):
                    return bool(value)
                if isinstance(value, str) and value.strip().lower() in ("true", "false", "0", "1"):
                    return value.strip().lower() in ("true", "1")
                raise ValueError(f"not a boolean: {value!r}")
            return pd.Series([boolean(v) for v in series], index=series.index, dtype=object)
        if kind == "date":
            text = series.astype(object)
            bad = text.notna() & ~text.astype(str).str.match(DATE)
            if bad.any():
                raise ValueError(f"not an ISO date: {text[bad].iloc[0]!r}")
            for value in text.dropna().unique():
                date.fromisoformat(str(value))
            return text
        return series.astype(object).where(series.notna(), None)
    except (TypeError, ValueError) as exc:
        raise BlockingError(STEP, Block.BAD_VALUE_TYPE, f"{dataset}.{name}: {exc}") from exc


def read_table(ctx: RunContext, spec: DatasetSpec) -> TypedTable:
    path = ctx.input_dir / spec.filename
    try:
        raw = pd.read_parquet(path)
    except Exception as exc:  # any reader failure means the file is unreadable
        raise BlockingError(STEP, Block.UNREADABLE_FILE, f"{spec.filename}: {exc}") from exc
    known = set(spec.column_names)
    status_cols = {c for c in raw.columns if c.endswith(STATUS_SUFFIX)}
    unknown = [c for c in raw.columns if c not in known and c not in status_cols]
    unknown += [c for c in status_cols if c[: -len(STATUS_SUFFIX)] not in known]
    if unknown:
        raise BlockingError(STEP, Block.UNKNOWN_COLUMN, f"{spec.filename}: unknown columns {unknown}")
    missing = [c for c in spec.column_names if c not in raw.columns]
    if missing:
        raise BlockingError(STEP, Block.MISSING_COLUMN, f"{spec.filename}: missing columns {missing}")
    data = {}
    status = {}
    for col in spec.columns:
        series = raw[col.name]
        inferred = _infer_status(series, col.kind)
        companion = col.name + STATUS_SUFFIX
        if companion in raw.columns:
            given = raw[companion].astype(object)
            bad = ~given.isin([str(s) for s in ALL_STATUSES])
            if bad.any():
                raise BlockingError(STEP, Block.BAD_VALUE_TYPE,
                                    f"{spec.filename}.{companion}: unknown status {given[bad].iloc[0]!r}")
            # A stated status wins, but an absent value can never be usable: it stays missing
            # unless the status says not applicable.
            absent = inferred == str(ValueStatus.MISSING)
            unusable = given.isin([str(ValueStatus.NOT_APPLICABLE), str(ValueStatus.MISSING)])
            inferred = given.where(~absent | unusable, str(ValueStatus.MISSING))
        data[col.name] = _cast(series, col.kind, col.name, spec.filename)
        status[col.name] = inferred
    return TypedTable(spec.name, pd.DataFrame(data), pd.DataFrame(status))


# --- YAML datasets ------------------------------------------------------------------------------

def _read_yaml(ctx: RunContext, spec: DatasetSpec) -> dict:
    path = ctx.input_dir / spec.filename
    try:
        with path.open(encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise BlockingError(STEP, Block.UNREADABLE_FILE, f"{spec.filename}: {exc}") from exc
    if not isinstance(doc, dict):
        raise BlockingError(STEP, Block.UNREADABLE_FILE, f"{spec.filename} is not a mapping")
    return doc


def read_scenarios(ctx: RunContext) -> tuple[pd.DataFrame, dict]:
    doc = _read_yaml(ctx, SCENARIOS)
    missing = [k for k in SCENARIO_TOP_KEYS if k not in doc]
    if missing:
        raise BlockingError(STEP, Block.MISSING_COLUMN, f"scenarios.yaml lacks {missing}")
    rows = []
    for n, value in enumerate(doc["values"]):
        absent = [f for f in SCENARIO_VALUE_FIELDS if f not in value]
        if "unit" in absent or not value.get("unit"):
            raise BlockingError(STEP, Block.SCENARIO_WITHOUT_UNIT,
                                f"scenario value {n} ({value.get('variable')}) has no unit")
        if absent:
            raise BlockingError(STEP, Block.MISSING_COLUMN, f"scenario value {n} lacks {absent}")
        if value["unit"] not in SCENARIO_UNITS:
            raise BlockingError(STEP, Block.SCENARIO_WITHOUT_UNIT,
                                f"scenario value {n} has an unknown unit {value['unit']!r}")
        if value["value_type"] not in SCENARIO_VALUE_TYPES:
            raise BlockingError(STEP, Block.BAD_VALUE_TYPE,
                                f"scenario value {n} has an unknown value type {value['value_type']!r}")
        raw = value["value"]
        number = np.nan if raw is None else float(raw)
        if raw is not None and not np.isfinite(number):
            raise BlockingError(STEP, Block.BAD_VALUE_TYPE, f"scenario value {n} is not finite")
        rows.append({
            "scenario": value["scenario"], "variable": value["variable"],
            "country": value["country"], "year": int(value["year"]),
            "value": number * SCENARIO_UNITS[value["unit"]],
            "raw_value": number, "unit": value["unit"], "value_type": value["value_type"],
            "status": value["status"], "completeness": value["completeness"],
            "value_status": str(ValueStatus.MISSING if np.isnan(number) else ValueStatus.SUPPLIED),
        })
    values = pd.DataFrame(rows)
    if len(values) and values.duplicated(["scenario", "variable", "country", "year"]).any():
        raise BlockingError(STEP, Block.DUPLICATE_KEY, "scenarios.yaml has a duplicate value")
    meta = {k: doc[k] for k in doc if k != "values"}
    return values, meta


def read_parameter_set(ctx: RunContext) -> dict:
    doc = _read_yaml(ctx, PARAMETER_SET)
    missing = [k for k in PARAMETER_SET_TOP_KEYS if k not in doc]
    if missing:
        raise BlockingError(STEP, Block.MISSING_PARAMETER, f"parameter_set.yaml lacks {missing}")
    return doc


def read_matrix(ctx: RunContext) -> pd.DataFrame:
    table = read_table(ctx, TTC_PD_MATRIX)
    if (table.status["probability"] == str(ValueStatus.MISSING)).any():
        raise BlockingError(STEP, Block.INVALID_MATRIX, "ttc_pd_matrix has a missing probability")
    return table.data


# --- control totals -------------------------------------------------------------------------------

def control_totals(fac: pd.DataFrame, com: pd.DataFrame, prov: pd.DataFrame) -> dict:
    """Row counts and amount totals as loaded, in the same shape as the input manifest."""
    gca = fac.assign(gca=fac["gca"].fillna(0.0))
    by = gca.groupby(["portfolio", "ifrs_stage"])
    stage = {
        f"{p}|{int(s)}": {"count": len(g), "gca": float(g["gca"].sum())}
        for (p, s), g in by
    }
    linked = com.merge(fac[["facility_id", "portfolio"]], on="facility_id", how="left")
    undrawn = {
        str(p): float(g["nominal_undrawn"].fillna(0.0).sum())
        for p, g in linked.groupby(linked["portfolio"].fillna("unlinked"))
    }
    return {
        "rows": {"facilities": len(fac), "commitments": len(com), "opening_provisions": len(prov)},
        "by_portfolio_stage": stage,
        "undrawn_by_portfolio": undrawn,
        "gca_total": float(fac["gca"].fillna(0.0).sum()),
        "undrawn_total": float(com["nominal_undrawn"].fillna(0.0).sum()),
        "allowance_on_total": float(prov["allowance_on"].fillna(0.0).sum()),
        "provision_off_total": float(prov["provision_off"].fillna(0.0).sum()),
    }


def _close(a: float, b: float, tol: dict) -> bool:
    return abs(a - b) <= max(tol["abs"], tol["rel"] * abs(b))


def compare_controls(loaded: dict, expected: dict, tol: dict) -> list[str]:
    problems = []
    for name, count in expected.get("rows", {}).items():
        if loaded["rows"].get(name) != count:
            problems.append(f"{name}: {loaded['rows'].get(name)} rows, manifest {count}")
    for key, cell in expected.get("by_portfolio_stage", {}).items():
        got = loaded["by_portfolio_stage"].get(key, {"count": 0, "gca": 0.0})
        if got["count"] != cell["count"] or not _close(got["gca"], cell["gca"], tol):
            problems.append(f"{key}: loaded {got}, manifest {cell}")
    for name in ("gca_total", "undrawn_total", "allowance_on_total", "provision_off_total"):
        if name in expected and not _close(loaded[name], expected[name], tol):
            problems.append(f"{name}: loaded {loaded[name]}, manifest {expected[name]}")
    return problems


def load_inputs(ctx: RunContext) -> LoadedInputs:
    """R2: hash-check, copy raw files, parse typed tables with a status on every value."""
    manifest = json.loads((ctx.input_dir / INPUT_MANIFEST).read_text(encoding="utf-8"))
    check_hashes(ctx, manifest)
    copy_raw(ctx)
    approval_path = ctx.input_dir / APPROVAL_FILE
    approval = {"status": "MISSING", "input_set_hash": ctx.input_set_hash}
    if approval_path.is_file():
        try:
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            if not isinstance(approval, dict) or approval.get("status") not in ("APPROVED", "PENDING_OWNER_APPROVAL"):
                raise ValueError("unknown approval status")
            if approval.get("status") == "APPROVED":
                if not approval.get("approved_by") or not approval.get("approved_on"):
                    raise ValueError("approval lacks approver or date")
                date.fromisoformat(approval["approved_on"])
        except (ValueError, TypeError) as exc:
            raise BlockingError(STEP, Block.BAD_VALUE_TYPE, f"invalid approval evidence: {exc}") from exc
        if approval.get("input_set_hash") != ctx.input_set_hash:
            raise BlockingError(STEP, Block.INPUT_HASH_MISMATCH, "approval belongs to another input set")
        shutil.copy2(approval_path, ctx.data_dir / APPROVAL_FILE)
    analysis = read_analysis(ctx)
    ctx.lineage["approval"] = approval
    facilities = read_table(ctx, FACILITIES)
    obligors = read_table(ctx, OBLIGORS)
    commitments = read_table(ctx, COMMITMENTS)
    provisions = read_table(ctx, OPENING_PROVISIONS)
    matrix = read_matrix(ctx)
    scenario_values, scenario_meta = read_scenarios(ctx)
    parameter_set = read_parameter_set(ctx)
    loaded_controls = control_totals(facilities.data, commitments.data, provisions.data)
    tol = parameter_set["tolerances"]["aggregate"]
    problems = compare_controls(loaded_controls, manifest.get("control_totals", {}), tol)
    if problems:
        raise BlockingError(STEP, Block.CONTROL_TOTAL_MISMATCH, "; ".join(problems[:5]))
    LOG.info("all %d files match their manifest hashes (input set %s)", len(DATASETS),
             ctx.input_set_hash[:16])
    LOG.info("raw files kept unchanged in %s/", ctx.data_dir.name)
    for name, table in (("facilities", facilities), ("obligors", obligors),
                        ("commitments", commitments), ("opening_provisions", provisions)):
        missing = int((table.status == "missing").sum().sum())
        LOG.info("loaded %-18s %8s rows, %s missing value(s)", name, f"{len(table.data):,}", missing)
    LOG.info("loaded %-18s %8s rows", "ttc_pd_matrix", f"{len(matrix):,}")
    LOG.info("loaded %-18s %8s values, converted to decimal fractions", "scenarios",
             f"{len(scenario_values):,}")
    LOG.info("parameter set %s (%s)", parameter_set["parameter_set_id"], parameter_set["status"])
    LOG.info("control totals match the manifest: GCA EUR %.1fm, undrawn EUR %.1fm, "
             "opening allowances EUR %.1fm", loaded_controls["gca_total"] / 1_000_000,
             loaded_controls["undrawn_total"] / 1_000_000,
             (loaded_controls["allowance_on_total"] + loaded_controls["provision_off_total"]) / 1_000_000)
    controls = {
        "loaded": loaded_controls,
        "manifest": manifest.get("control_totals", {}),
        "rows": {
            "facilities": len(facilities.data), "obligors": len(obligors.data),
            "commitments": len(commitments.data), "opening_provisions": len(provisions.data),
            "ttc_pd_matrix": len(matrix), "scenario_values": len(scenario_values),
        },
    }
    loaded = LoadedInputs(
        input_set_hash=ctx.input_set_hash, manifest=manifest, facilities=facilities,
        obligors=obligors, commitments=commitments, opening_provisions=provisions,
        ttc_pd_matrix=matrix, scenario_values=scenario_values, scenario_meta=scenario_meta,
        parameter_set=parameter_set, load_controls=controls, analysis=analysis, approval=approval,
    )
    specification.apply(loaded, ctx)
    return loaded


def read_analysis(ctx: RunContext) -> dict:
    """Optional versioned preparation inputs, captured once at R2 and sealed with the run."""
    if not ctx.config.analysis:
        return {}
    from pathlib import Path
    path = Path(ctx.config.analysis)
    try:
        raw = path.read_bytes()
        doc = yaml.safe_load(raw)
        allowed = {"schema_version", "input_set_hash", "status", "source", "version", "benchmarks", "recoveries",
                   "capital", "climate", "template_mapping", "challenge", "npe_backstop",
                   "plausibility"}
        if not isinstance(doc, dict) or doc.get("schema_version") != 1 or set(doc) - allowed:
            raise ValueError("analysis must use schema_version 1 and known sections")
        if doc.get("status") != "SYNTHETIC" or not doc.get("source") or not doc.get("version"):
            raise ValueError("preparation analysis requires SYNTHETIC status, source and version")
        if doc.get("input_set_hash") != ctx.input_set_hash:
            raise ValueError("analysis belongs to another input set")
        for section in ("benchmarks", "recoveries", "climate"):
            if section in doc and (not isinstance(doc[section], list) or not doc[section]
                                   or not all(isinstance(row, dict) for row in doc[section])):
                raise ValueError(f"{section} must be a nonempty list of mappings")
        for section in ("capital", "template_mapping", "challenge", "npe_backstop", "plausibility"):
            if section in doc and (not isinstance(doc[section], dict) or not doc[section]):
                raise ValueError(f"{section} must be a nonempty mapping")
        (ctx.data_dir / "analysis.yaml").write_bytes(raw)
        ctx.lineage["analysis"] = {"sha256": hashlib.sha256(raw).hexdigest(),
                                   "version": doc["version"], "source": doc["source"],
                                   "status": doc["status"]}
        return doc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise BlockingError(STEP, Block.BAD_VALUE_TYPE, f"analysis: {exc}") from exc
