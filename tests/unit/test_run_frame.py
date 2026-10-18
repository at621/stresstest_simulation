"""Unit tests of the run frame: contracts, R1/R11 lineage, R2 ingestion."""

import json
import os
import re
import stat
from datetime import UTC, datetime

import pandas as pd
import pytest

from stress.contracts.errors import Block, BlockingError
from stress.contracts.run import RunConfig
from stress.contracts.status import USABLE_STATUSES, ValueStatus
from stress.contracts.tables import REJECTIONS
from stress.ingest import _infer_status
from stress.lineage import compare_outputs, open_run, read_manifest
from tests import builders


@pytest.mark.req("MOD-06")
def test_duplicate_or_missing_key_blocks():
    row = {"record_type": "facility", "record_id": "F1", "row": 0, "reason_code": "X", "detail": "", "step": "R3"}
    with pytest.raises(BlockingError) as err:
        REJECTIONS.check(pd.DataFrame([row, row]), "test")
    assert err.value.code == Block.DUPLICATE_KEY
    with pytest.raises(BlockingError) as err:
        REJECTIONS.check(pd.DataFrame([{**row, "record_id": None}]), "test")
    assert err.value.code == Block.MISSING_KEY


@pytest.mark.req("DAT-02")
def test_value_status_distinguishes_missing_zero_and_supplied():
    assert {s.value for s in ValueStatus} == {"supplied", "zero", "not_applicable", "estimated", "missing"}
    assert ValueStatus.MISSING not in USABLE_STATUSES and ValueStatus.NOT_APPLICABLE not in USABLE_STATUSES
    status = _infer_status(pd.Series([1.5, 0.0, None]), "float").tolist()
    assert status == ["supplied", "zero", "missing"], "missing is never zero"


@pytest.mark.req("OPS-01")
def test_run_id_and_write_once(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    config = RunConfig(inputs=inputs.as_posix(), scenarios=("baseline", "adverse"), variant="core")
    now = datetime(2026, 10, 17, 18, 30, tzinfo=UTC)
    first = open_run(config, tmp_path / "runs", now)
    second = open_run(config, tmp_path / "runs", now)
    assert re.fullmatch(r"20261017T1830Z-core-[0-9a-f]{8}", first.run_id)
    assert second.run_id != first.run_id, "a rerun is a new folder"
    assert first.input_set_hash.startswith(inputs.name)


@pytest.mark.req("OPS-04")
def test_sealed_run_is_labelled_and_read_only(mini_tables, tmp_path):
    ctx, manifest = builders.run(builders.write(builders.copy_tables(mini_tables), tmp_path / "in"),
                                 tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC" == read_manifest(ctx.run_dir)["status"]
    assert set(manifest["outputs"]) and all(name.startswith("results/") for name in manifest["outputs"])
    assert set(manifest["inputs"]) >= {"data/facilities.parquet", "data/manifest.json"}
    summary = (ctx.reports_dir / "summary.md").read_text(encoding="utf-8")
    assert "SYNTHETIC" in summary.splitlines()[0]
    assert not os.stat(ctx.results_dir / "slices.parquet").st_mode & stat.S_IWRITE
    assert compare_outputs(manifest, manifest) == []


@pytest.mark.req("OPS-01")
def test_tampered_input_blocks(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["facilities.parquet"]["sha256"] = "0" * 64
    (inputs / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _, sealed = builders.run(inputs, tmp_path / "runs")
    assert sealed["status"] == "BLOCKED" and sealed["blocked"]["code"] == Block.INPUT_HASH_MISMATCH


@pytest.mark.req("SCN-02")
def test_scenario_value_without_unit_blocks(mini, tmp_path):
    mini["scenarios"]["values"][0].pop("unit")
    _, sealed = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert sealed["status"] == "BLOCKED" and sealed["blocked"]["code"] == Block.SCENARIO_WITHOUT_UNIT


@pytest.mark.req("DAT-03")
def test_raw_files_kept_unchanged(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    ctx, _ = builders.run(inputs, tmp_path / "runs")
    for name in ("facilities.parquet", "scenarios.yaml", "parameter_set.yaml"):
        assert (ctx.data_dir / name).read_bytes() == (inputs / name).read_bytes()
