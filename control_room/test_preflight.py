"""Does the control room judge a setup as the engine would, and catch a bad input? These tests build
defective input sets the way a real one would arrive, properly re-hashed so that it looks valid, and
let the room judge them.

    uv run pytest control_room

A check that only ever saw good data proves nothing, so most tests here start from a broken set. The
two layers are tested apart on purpose: each catches what the other cannot.
"""

import ast
import inspect
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import preflight
import server

from stress import cli, ingest, validate
from stress.contracts.errors import BlockingError
from stress.contracts.inputs import DATASETS, FACILITIES

nb = server.nb
SOURCE = server.ROOT / "inputs" / "d62d0386f2c5256e"
OLDER = server.ROOT / "inputs" / "514ed0e86e3dc760"
EXAMPLES = sorted(path for folder in (server.ROOT / "docs" / "examples", server.ROOT / "docs" / "run-workflow")
                  for path in folder.glob("*.yaml")
                  if "run:" in path.read_text(encoding="utf-8"))


def config_of(folder: Path) -> server.RunConfig:
    return server.RunConfig(inputs=str(folder), scenarios=("baseline", "adverse"), variant="core")


def reseal(work: Path, totals: bool = False) -> Path:
    """Re-hash a changed copy as the one-off steps would, so that it looks like a valid input set."""
    manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    hashes = {spec.filename: ingest._hash(work / spec.filename) for spec in DATASETS}
    for name, digest in hashes.items():
        manifest["files"][name]["sha256"] = digest
    if totals:
        tables = (pd.read_parquet(work / f"{name}.parquet") for name in ("facilities", "commitments", "opening_provisions"))
        recount = ingest.control_totals(*tables)
        manifest["control_totals"].update({key: recount[key] for key in (
            "by_portfolio_stage", "gca_total", "undrawn_total", "allowance_on_total", "provision_off_total")})
    manifest["input_set_hash"] = ingest.input_set_hash(hashes)
    (work / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    approval = json.loads((work / "approval.json").read_text(encoding="utf-8"))
    approval["input_set_hash"] = manifest["input_set_hash"]
    (work / "approval.json").write_text(json.dumps(approval), encoding="utf-8")
    final = work.parent / manifest["input_set_hash"][:16]
    work.rename(final)
    return final


@pytest.fixture
def copy_of_set(tmp_path):
    work = tmp_path / "inputs" / SOURCE.name
    shutil.copytree(SOURCE, work)
    return work


def differing(folder: Path) -> list[str]:
    return [row["item"] for row in preflight.differences(folder)["differing"]]


def dry_run_of(doc: dict, folder: Path) -> dict:
    """A setup as the page sends it, judged through a specification file as the server writes one."""
    path = folder / "specification.yaml"
    path.write_text(server.specification_text(doc, folder), encoding="utf-8")
    return preflight.dry_run(server.RunConfig(inputs="", scenarios=("baseline",), variant="core", specification=str(path)))


# --- what an input set offers ---------------------------------------------------------------------------

def test_the_base_of_a_set_is_what_its_files_hold():
    base = preflight.base_of(SOURCE)
    ps = yaml.safe_load((SOURCE / "parameter_set.yaml").read_text(encoding="utf-8"))
    assert base["hash"].startswith(SOURCE.name) and base["folder"] == f"inputs/{SOURCE.name}"
    assert base["segments"]["P01"]["rho"] == ps["segments"]["P01"]["rho"] == 0.15
    assert base["segments"]["P01"]["z_drivers"] == ps["segments"]["P01"]["z_drivers"]
    assert sum(s["facilities"] for s in base["segments"].values()) == base["facilities"] == 10_000
    assert sum(p["facilities"] for p in base["portfolios"]) == 10_000 and len(base["portfolios"]) == 6
    assert base["common"]["adverse"]["gdp_growth"] == {2027: -3.0, 2028: -2.0, 2029: 0.5}
    assert [v["id"] for v in base["variables"]][:2] == ["gdp_growth", "unemployment"] and base["years"] == [2027, 2028, 2029]
    assert {v["id"]: v["bullet"] for v in base["variants"]} == {"core": True, "annuity": False, "linear": False, "utilisation": True}


def test_the_files_of_a_set_are_reported_as_they_stand(copy_of_set):
    rows = {row["file"]: row for row in preflight.files_of(SOURCE)}
    assert len(rows) == len(DATASETS) + 2
    assert rows["facilities.parquet"]["rows"] == 10_000 and rows["facilities.parquet"]["hash_ok"] is True
    assert rows["facilities.parquet"]["columns"] == 35 and rows["facilities.parquet"]["missing_columns"] == []
    assert rows["scenarios.yaml"]["hash_ok"] is True and rows["manifest.json"]["detail"].startswith("input set d62d")
    assert rows["approval.json"]["detail"].startswith("PENDING")
    older = {row["file"]: row for row in preflight.files_of(OLDER)}
    assert older["facilities.parquet"]["missing_columns"] == ["credit_status_date"]
    (copy_of_set / "obligors.parquet").unlink()
    (copy_of_set / "scenarios.yaml").write_text("- not: [a mapping", encoding="utf-8")
    broken = {row["file"]: row for row in preflight.files_of(copy_of_set)}
    assert not broken["obligors.parquet"]["present"] and broken["scenarios.yaml"]["problem"].startswith("not valid YAML")
    assert broken["scenarios.yaml"]["hash_ok"] is False


def test_the_summary_and_the_previews_are_the_tables_themselves():
    summary = preflight.table_summary(SOURCE)
    fac = pd.read_parquet(SOURCE / "facilities.parquet")
    assert summary["facilities"]["rows"] == len(fac) and summary["facilities"]["gca"] == pytest.approx(fac["gca"].sum() / 1e6)
    assert sum(p["facilities"] for p in summary["facilities"]["by_portfolio"]) == len(fac)
    assert sum(n for _, n in summary["obligors"]["countries"]) == summary["obligors"]["rows"]
    assert summary["ttc_pd_matrix"]["grades"][0] == "G1" and len(summary["ttc_pd_matrix"]["segments"]) == 7
    first = preflight.preview(SOURCE, "facilities")
    assert first["total"] == 10_000 and len(first["rows"]) == preflight.PREVIEW_ROWS
    assert not any(column.endswith("__status") for column in first["columns"])
    assert preflight.preview(SOURCE, "facilities", preflight.PREVIEW_ROWS)["rows"] != first["rows"]
    found = preflight.preview(SOURCE, "facilities", 0, "F07001")
    assert found["total"] == 1 and found["rows"][0][0] == "F07001"
    assert preflight.preview(SOURCE, "nothing") is None and preflight.matrix_of(SOURCE, "nothing") is None
    matrix = preflight.matrix_of(SOURCE, "P01")
    assert len(matrix["grid"]) == 11 and all(sum(row) == pytest.approx(1.0) for row in matrix["grid"])


def test_a_prepared_folder_is_judged_before_it_is_packaged(tmp_path):
    assert preflight.prepared_status(SOURCE)["complete"]
    status = preflight.prepared_status(tmp_path)
    assert not status["complete"] and not any(f["present"] for f in status["files"])


def test_the_seven_files_are_named_and_described():
    roles = preflight.file_roles()
    assert [r["file"] for r in roles] == [spec.filename for spec in DATASETS]
    assert all(r["label"] and r["holds"] for r in roles)
    assert {r["format"] for r in roles} == {"Parquet", "YAML"}


def test_an_older_file_is_named_by_what_it_lacks():
    view = preflight.inspected(FACILITIES, OLDER / FACILITIES.filename)
    assert view["rows"] == 10_000 and "credit_status_date" in view["problem"]
    assert preflight.inspected(FACILITIES, SOURCE / FACILITIES.filename)["problem"] is None


def test_a_column_the_engine_does_not_know_is_named(tmp_path):
    table = pd.read_parquet(SOURCE / FACILITIES.filename).head(3).assign(extra=1)
    table.to_parquet(tmp_path / "facilities.parquet", index=False)
    assert preflight.inspected(FACILITIES, tmp_path / "facilities.parquet")["problem"] == "Columns the engine does not know: extra."


def test_the_approval_record_is_read_as_it_stands(tmp_path):
    assert preflight.approval_of(SOURCE)["status"] == "PENDING_OWNER_APPROVAL"
    assert preflight.approval_of(tmp_path) is None


def test_a_scenarios_file_with_five_scenarios_is_read_as_it_stands(copy_of_set):
    """Nothing here assumes two scenarios: what the file holds is what the room offers and the engine reads."""
    doc = yaml.safe_load((copy_of_set / "scenarios.yaml").read_text(encoding="utf-8"))
    adverse = [dict(row) for row in doc["values"] if row["scenario"] == "adverse"]
    for number, name in enumerate(("mild", "severe", "stagflation"), start=1):
        doc["scenarios"].append({**doc["scenarios"][1], "id": name, "label": name.capitalize()})
        doc["values"] += [{**row, "scenario": name, "value": row["value"] - number if row["variable"] == "gdp_growth"
                           else row["value"]} for row in adverse]
    (copy_of_set / "scenarios.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    folder = reseal(copy_of_set)
    base = preflight.base_of(folder)
    assert [s["id"] for s in base["scenarios"]] == ["baseline", "adverse", "mild", "severe", "stagflation"]
    config = server.RunConfig(inputs=str(folder), scenarios=tuple(s["id"] for s in base["scenarios"]), variant="core")
    result = preflight.dry_run(config)
    assert result["verdict"] == "ready", result["blocked"]
    assert {z["scenario"] for z in result["z"]} == set(config.scenarios)
    assert len(result["z"]) == 7 * 5 * 3


# --- the engine's own verdict -----------------------------------------------------------------------------

def test_the_committed_set_is_ready_and_matches_every_requirement():
    result = preflight.dry_run(config_of(SOURCE))
    assert result["verdict"] == "ready" and result["reached"] == "R4" and result["blocked"] is None
    assert result["accepted"] == 10_000 and result["rejected"] == 0 and result["records"] == []
    assert len(result["z"]) == 7 * 2 * 3 and sum(p["facilities"] for p in result["book"]) == 10_000
    gap = preflight.differences(SOURCE)
    assert gap["differing"] == [] and gap["unmeasured"] == [] and gap["compared"] > 100


def test_a_dry_run_leaves_nothing_behind():
    before = sorted(p.name for p in nb.RUNS_DIR.iterdir())
    preflight.dry_run(config_of(SOURCE))
    assert sorted(p.name for p in nb.RUNS_DIR.iterdir()) == before
    assert not list(Path(tempfile.gettempdir()).glob("stress-preflight-*"))


def test_a_derived_scenario_changes_the_z_the_engine_computes(tmp_path):
    """The page's feedback on an override is R4's own number, not an estimate of it."""
    base = preflight.base_of(SOURCE)
    doc = {"schema_version": 1, "status": "SYNTHETIC", "source": "test", "version": "deeper", "input_set_hash": base["hash"],
           "run": {"inputs": base["folder"], "scenarios": ["baseline", "adverse", "deeper"], "variant": "core"},
           "scenarios": {"deeper": {"inherits": "adverse", "narrative": "deeper", "overrides": [
               {"variable": "gdp_growth", "country": "*", "year": 2027, "value": -6.0, "unit": "percent", "value_type": "growth"}]}}}
    result = dry_run_of(doc, tmp_path)
    assert result["verdict"] == "ready" and result["reached"] == "R4" and result["phases"][0] == "specification"
    z = {(r["scenario"], r["year"]): r["mean"] for r in result["z"] if r["segment"] == "P01"}
    assert z[("deeper", 2027)] < z[("adverse", 2027)] - 0.3
    assert z[("deeper", 2028)] == pytest.approx(z[("adverse", 2028)]), "only the overridden cell differs"


def test_a_bad_parameter_is_the_engines_own_message(tmp_path):
    base = preflight.base_of(SOURCE)
    doc = {"schema_version": 1, "status": "SYNTHETIC", "source": "test", "version": "bad", "input_set_hash": base["hash"],
           "run": {"inputs": base["folder"], "scenarios": ["baseline", "adverse"], "variant": "core"},
           "segments": {"P01": {"rho": 1.5}}}
    result = dry_run_of(doc, tmp_path)
    assert result["verdict"] == "blocked" and result["blocked"]["code"] == "INVALID_SPECIFICATION"
    assert "rho" in result["blocked"]["message"] and result["z"] is None


# --- the two layers catch different things ----------------------------------------------------------------

def test_a_softened_scenario_passes_the_engine_and_fails_the_requirements(copy_of_set):
    """The reason the requirement layer exists: a stress one third as deep breaks no engine rule."""
    doc = yaml.safe_load((copy_of_set / "scenarios.yaml").read_text(encoding="utf-8"))
    for row in doc["values"]:
        if row["scenario"] == "adverse" and row["variable"] == "gdp_growth" and row["year"] == 2027:
            row["value"] = -1.0
    (copy_of_set / "scenarios.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    folder = reseal(copy_of_set)
    assert preflight.dry_run(config_of(folder))["verdict"] == "ready"
    assert differing(folder) == ["adverse gdp_growth 2027"]


def test_a_defect_in_one_record_passes_the_requirements_and_blocks_the_engine(copy_of_set):
    """And the reverse: two commitments on one facility leave every total on target."""
    table = pd.read_parquet(copy_of_set / "commitments.parquet")
    table["facility_id"] = table["facility_id"].where(table.index != 1, table["facility_id"].iloc[0])
    table.to_parquet(copy_of_set / "commitments.parquet")
    folder = reseal(copy_of_set, totals=True)
    result = preflight.dry_run(config_of(folder))
    assert result["verdict"] == "blocked" and result["blocked"]["code"] == "DUPLICATE_COMMITMENT"
    assert result["reached"] == "R3" and result["z"] is None
    assert not differing(folder)


def test_a_wrong_amount_is_caught_by_both(copy_of_set):
    table = pd.read_parquet(copy_of_set / "facilities.parquet")
    table["gca"] = table["gca"].where(table.index != 100, table["gca"] + 5_000_000)
    table.to_parquet(copy_of_set / "facilities.parquet")
    folder = reseal(copy_of_set, totals=True)
    result = preflight.dry_run(config_of(folder))
    assert result["verdict"] == "rejected" and result["rejected"] == 2 and result["accepted"] == 9_999
    hit = {row["code"]: row for row in result["records"]}
    assert set(hit) == {"GCA_COMPONENTS_MISMATCH", "LINKED_RECORD_REJECTED"}
    assert hit["GCA_COMPONENTS_MISMATCH"]["sample"], "the page can name the record"
    assert "GCA" in differing(folder)


def test_a_file_edited_by_hand_stops_at_its_hash(copy_of_set):
    table = pd.read_parquet(copy_of_set / "facilities.parquet")
    table.loc[0, "gca"] *= 2
    table.to_parquet(copy_of_set / "facilities.parquet")
    result = preflight.dry_run(config_of(copy_of_set))
    assert result["blocked"]["code"] == "INPUT_HASH_MISMATCH" and result["reached"] == "R2"


def test_nothing_after_a_block_is_reported():
    result = preflight.dry_run(config_of(OLDER))
    assert result["blocked"]["code"] == "MISSING_COLUMN" and result["reached"] == "R2"
    assert result["accepted"] is None and result["z"] is None and result["book"] is None


def test_a_fault_in_a_check_reads_as_a_fault_not_a_pass(monkeypatch):
    def broken(*_):
        raise RuntimeError("a bug")

    monkeypatch.setattr(validate, "validate_and_route", broken)
    result = preflight.dry_run(config_of(SOURCE))
    assert result["verdict"] == "blocked" and "a bug" in result["fault"]["message"] and result["z"] is None


def test_the_dry_run_follows_the_pipeline():
    """preflight.dry_run repeats the opening of cli.pipeline. If that changes, this must fail first."""
    def calls(function, stop=None):
        names = []
        for node in ast.walk(ast.parse(inspect.getsource(function))):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                names.append((node.lineno, name.rsplit(".", 1)[-1]))
        ordered = [name for _, name in sorted(names)]
        return ordered[:ordered.index(stop) + 1] if stop else ordered

    steps = ["load_inputs", "validate_and_route", "raise_if_blocking", "validate_assumptions", "build_drivers"]
    pipeline = [name for name in calls(cli.pipeline, "build_drivers") if name in steps]
    dry = [name for name in calls(preflight.dry_run) if name in steps]
    assert pipeline == steps and dry == steps


# --- what could not be measured ---------------------------------------------------------------------------

def test_a_missing_column_costs_one_measurement_and_never_reads_as_a_match(copy_of_set):
    table = pd.read_parquet(copy_of_set / "obligors.parquet").drop(columns=["group_id"])
    table.to_parquet(copy_of_set / "obligors.parquet")
    folder = reseal(copy_of_set)
    gap = preflight.differences(folder)
    assert [u["group"] for u in gap["unmeasured"]] == ["Counterparties and concentration"]
    assert "group_id" in gap["unmeasured"][0]["error"] and gap["differing"] == []


def test_reference_observations_are_not_compared():
    """Section 8.7 calls them reference observations, and the generator uses them as distribution
    centres. A difference there is not a defect, so it is not measured at all."""
    groups = preflight.against_requirements(SOURCE)
    titles = [g.title for g in groups]
    assert "Reference values" not in titles
    assert not any("EIR" in row["item"] for g in groups for row in g.rows)
    calibration = next(g for g in groups if g.title == "Stage PD calibration")
    assert len(calibration.rows) == 14 and all(row["ok"] for row in calibration.rows)


def test_an_unreadable_set_does_not_hide_the_others(tmp_path, monkeypatch):
    (tmp_path / "inputs").mkdir()
    shutil.copytree(SOURCE, tmp_path / "inputs" / SOURCE.name)
    broken = tmp_path / "inputs" / OLDER.name
    shutil.copytree(OLDER, broken)
    (broken / "parameter_set.yaml").unlink()
    monkeypatch.setattr(nb, "INPUTS_DIR", tmp_path / "inputs")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    rows = {row["inputs"]: row for row in server.input_inventory()}
    assert rows[f"inputs/{SOURCE.name}"]["runnable"]
    assert not rows[f"inputs/{OLDER.name}"]["runnable"] and "unreadable" in rows[f"inputs/{OLDER.name}"]["gaps"][0]


# --- the setup as the engine reads it ----------------------------------------------------------------------

@pytest.mark.parametrize("doc, needed", [
    ({"run": {"balance_sheet": "static"}}, False),
    ({"run": {"balance_sheet": "dynamic"}}, True),
    ({"run": {}, "segments": {"P01": {"rho": 0.2}}}, True),
    ({"run": {}, "scenarios": {}, "models": {}, "assignments": []}, False),
])
def test_only_what_a_flag_cannot_say_needs_a_file(doc, needed):
    assert preflight.needs_specification(doc) is needed


def test_a_setup_round_trips_through_yaml(tmp_path):
    doc = {"schema_version": 1, "status": "SYNTHETIC", "source": "test", "version": "v", "input_set_hash": "h",
           "run": {"inputs": f"inputs/{SOURCE.name}", "scenarios": ["baseline", "adverse"], "variant": "core", "analysis": None},
           "segments": {"P01": {"rho": 0.2}}, "models": {}, "terminal_policies": {}}
    text = server.specification_text(doc, tmp_path)
    assert "models" not in text and "analysis" not in text and "terminal_policies" not in text, "empty is left out"
    back = preflight.parse_yaml(text, tmp_path)
    assert back["run"]["inputs"] == f"inputs/{SOURCE.name}" and back["segments"] == {"P01": {"rho": 0.2}}
    assert set(back) == {"schema_version", "status", "source", "version", "input_set_hash", "run", "segments"}


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_a_docs_example_round_trips_unchanged(path):
    """Loading an example and writing it back adds nothing and loses nothing, section for section."""
    doc = preflight.parse_yaml(path.read_text(encoding="utf-8"), path.parent)
    original = yaml.safe_load(path.read_text(encoding="utf-8"))
    again = preflight.parse_yaml(server.specification_text(doc, path.parent), path.parent)
    assert again == doc
    for name in preflight.SECTIONS:
        assert again.get(name) == original.get(name), name


@pytest.mark.parametrize("text, said", [
    ("run: {}\nrun: {}\n", "duplicate"),
    ("schema_version: 1\nstatus: SYNTHETIC\nsource: s\nversion: v\ninput_set_hash: h\nrun: {}\nnonsense: 1\n", "unknown"),
    ("- not\n- a mapping\n", "mapping"),
    ("run: [unclosed\n", "YAML"),
])
def test_yaml_the_engine_would_refuse_is_refused_here(text, said):
    with pytest.raises(BlockingError) as caught:
        preflight.parse_yaml(text, None)
    assert said in caught.value.message
