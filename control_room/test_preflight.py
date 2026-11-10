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
import time
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
from stress.contracts.inputs import DATASETS, FACILITIES, SCENARIOS
from stress.models import Model, Score

nb = server.nb
SOURCE = server.ROOT / "inputs" / server.BOOKS["large"]
OLDER = server.ROOT / "inputs" / "514ed0e86e3dc760"
EXAMPLES = sorted(path for folder in (server.ROOT / "docs" / "examples", server.ROOT / "docs" / "run-workflow")
                  for path in folder.glob("*.yaml")
                  if "run:" in path.read_text(encoding="utf-8"))


def config_of(folder: Path) -> server.RunConfig:
    return server.RunConfig(inputs=str(folder), scenarios=("baseline", "adverse"), variant="core")


def reseal(work: Path, totals: bool = False) -> Path:
    """Re-hash a changed copy as the one-off steps would, so that it looks like a valid input set."""
    manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    hashes = {name: ingest._hash(work / name) for name in manifest["files"]}
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
    p01 = ps["portfolios"]["P01"]["segments"]["P01"]
    assert base["segments"]["P01"]["asset_correlation"] == p01["asset_correlation"] == 0.15
    assert base["segments"]["P01"]["ttc_matrix"] == p01["ttc_matrix"] == "matrices/P01.parquet"
    models = base["segments"]["P01"]["models"]
    assert [models[role]["name"] for role in ("pd", "lgd", "prepayment")] == [p01["pd_model"], p01["lgd_model"],
                                                                               p01["prepayment_model"]]
    assert models["pd"]["location"] == "src/stress/models/p01.py, function pd"
    assert models["pd"]["description"].startswith("Residential mortgages: PD model.")
    assert models["lgd"]["sensitivity"] == 0.2 and models["pd"]["sensitivity"] is None
    assert {m["name"] for m in base["model_choices"]["P02"]["pd"]} == {"p02.pd", "p02.pd_nonlinear"}
    assert sum(s["facilities"] for s in base["segments"].values()) == base["facilities"] == 10_000
    assert sum(p["facilities"] for p in base["portfolios"]) == 10_000 and len(base["portfolios"]) == 6
    assert base["common"]["adverse"]["gdp_growth"] == {2027: -3.0, 2028: -2.0, 2029: 0.5}
    assert [v["id"] for v in base["variables"]][:2] == ["gdp_growth", "unemployment"] and base["years"] == [2027, 2028, 2029]
    assert {v["id"]: v["bullet"] for v in base["variants"]} == {"core": True, "annuity": False, "linear": False, "utilisation": True}


def test_the_files_of_a_set_are_reported_as_they_stand(copy_of_set):
    rows = {row["file"]: row for row in preflight.files_of(SOURCE)}
    assert len(rows) == len(DATASETS) + 7 + 2  # the datasets, a matrix file per segment, manifest and approval
    assert rows["matrices/P06_CI.parquet"]["rows"] == 121 and rows["matrices/P06_CI.parquet"]["hash_ok"] is True
    assert rows["facilities.parquet"]["rows"] == 10_000 and rows["facilities.parquet"]["hash_ok"] is True
    assert rows["facilities.parquet"]["columns"] == 35 and rows["facilities.parquet"]["missing_columns"] == []
    assert rows["scenarios.yaml"]["hash_ok"] is True and rows["manifest.json"]["detail"].startswith(f"input set {SOURCE.name[:4]}")
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


def test_the_six_files_a_person_can_add_are_named_and_described():
    """Six rows: the rating transitions, one file per segment, come from the saved set and have no row."""
    roles = preflight.file_roles()
    assert len(roles) == 6 and "ttc_matrix" not in {r["name"] for r in roles}
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
    assert [s["id"] for s in base["scenarios"]][-3:] == ["mild", "severe", "stagflation"]
    config = server.RunConfig(inputs=str(folder), scenarios=tuple(s["id"] for s in base["scenarios"]), variant="core")
    result = preflight.dry_run(config)
    assert result["verdict"] == "ready", result["blocked"]
    assert {z["scenario"] for z in result["z"]} == set(config.scenarios)
    assert len(result["z"]) == 7 * 3 * len(config.scenarios) * 3


def test_each_scenario_carries_its_description_from_the_file():
    doc = yaml.safe_load((SOURCE / "scenarios.yaml").read_text(encoding="utf-8"))
    shown = [(s["id"], s["label"], s["description"]) for s in preflight.base_of(SOURCE)["scenarios"]]
    assert shown == [(s["id"], s["label"], s["description"]) for s in doc["scenarios"]]
    assert len(shown) > 2 and all(description for _, _, description in shown)


def test_a_file_without_descriptions_is_still_read(copy_of_set):
    """The engine does not need a description, so an older Scenarios file stays usable."""
    doc = yaml.safe_load((copy_of_set / "scenarios.yaml").read_text(encoding="utf-8"))
    for entry in doc["scenarios"]:
        entry.pop("description")
    (copy_of_set / "scenarios.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    folder = reseal(copy_of_set)
    assert all(s["description"] is None for s in preflight.base_of(folder)["scenarios"])
    assert preflight.dry_run(config_of(folder))["verdict"] == "ready"


def test_each_model_says_which_scenario_variables_it_reads():
    """The link from a scenario to the models: read from the model functions themselves."""
    base = preflight.base_of(SOURCE)
    assert base["segments"]["P01"]["models"]["pd"]["reads"] == ["gdp_growth", "unemployment", "residential_price_change"]
    variables = {v["id"] for v in base["variables"]}
    used = [m for segment in base["segments"].values() for m in segment["models"].values()]
    assert used and all(m["reads"] and set(m["reads"]) <= variables for m in used)
    choices = {m["name"]: m["reads"] for p in base["model_choices"].values() for models in p.values() for m in models}
    assert choices["p04.pd_external"] == [], "a supplied score reads no variable"


def test_a_model_is_said_to_read_a_lagged_variable_once():
    def lagged(economy):
        economy.value("gdp_growth", 1)
        economy.value("unemployment")
        economy.value("gdp_growth")
        return Score(0.0, ())
    assert preflight.reads_of(Model("p01.lagged", "pd", lagged)) == ["gdp_growth", "unemployment"]


def test_a_model_that_reads_no_variable_reads_nothing():
    def supplied(economy):
        raise BlockingError("R4", "MISSING_SCENARIO_VALUE", "missing supplied score")
    assert preflight.reads_of(Model("p01.supplied", "pd", supplied)) == []


def test_a_model_that_fails_on_the_probe_is_not_known_and_the_set_still_opens():
    def fragile(economy):
        return Score(1 / economy.value("gdp_growth"), ())
    model = Model("p01.fragile", "pd", fragile)
    assert preflight.reads_of(model) is None
    assert preflight.model_view("p01.pd", "pd", "P01")["reads"], "a registered model still reads"


# --- the engine's own verdict -----------------------------------------------------------------------------

def test_the_committed_set_is_ready_and_matches_every_requirement():
    result = preflight.dry_run(config_of(SOURCE))
    assert result["verdict"] == "ready" and result["blocked"] is None and result["fault"] is None
    assert result["accepted"] == 10_000 and result["rejected"] == 0 and result["records"] == []
    assert len(result["z"]) == 7 * 3 * 2 * 3
    gap = preflight.differences(SOURCE)
    assert gap["differing"] == [] and gap["unmeasured"] == [] and gap["compared"] > 100


def test_the_answer_of_a_dry_run_holds_what_the_page_reads_and_no_more():
    """The page reads these and nothing else. The engine's log and a traceback name folders of the
    machine, so neither is in the answer."""
    assert set(preflight.dry_run(config_of(SOURCE))) == {"verdict", "blocked", "fault", "rejected", "records",
                                                         "accepted", "z"}


def test_a_dry_run_leaves_nothing_behind(tmp_path, monkeypatch):
    """Its run folder is made in a temporary folder of its own, here one only this test uses, so that
    another room checking at the same moment cannot be taken for a leftover."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    seen = []
    opened = preflight.lineage.open_run

    def watched(config, runs_dir, *rest):
        seen.append(Path(runs_dir))
        return opened(config, runs_dir, *rest)

    monkeypatch.setattr(preflight.lineage, "open_run", watched)
    before = sorted(p.name for p in nb.RUNS_DIR.iterdir())
    assert preflight.dry_run(config_of(SOURCE))["verdict"] == "ready"
    assert len(seen) == 1 and seen[0].parent == tmp_path and seen[0].name.startswith("stress-preflight-")
    assert list(tmp_path.iterdir()) == [], "the temporary folder went with the check"
    assert sorted(p.name for p in nb.RUNS_DIR.iterdir()) == before


def test_a_derived_scenario_changes_the_z_the_engine_computes(tmp_path):
    """The page's feedback on an override is R4's own number, not an estimate of it."""
    base = preflight.base_of(SOURCE)
    doc = {"schema_version": 1, "status": "SYNTHETIC", "source": "test", "version": "deeper", "input_set_hash": base["hash"],
           "run": {"inputs": base["folder"], "scenarios": ["baseline", "adverse", "deeper"], "variant": "core"},
           "scenarios": {"deeper": {"inherits": "adverse", "narrative": "deeper", "overrides": [
               {"variable": "gdp_growth", "country": "*", "year": 2027, "value": -6.0, "unit": "percent", "value_type": "growth"}]}}}
    result = dry_run_of(doc, tmp_path)
    assert result["verdict"] == "ready", result["blocked"]
    z ={(r["scenario"], r["year"]): r["mean"] for r in result["z"] if r["segment"] == "P01"}
    assert z[("deeper", 2027)] < z[("adverse", 2027)] - 0.3
    assert z[("deeper", 2028)] == pytest.approx(z[("adverse", 2028)]), "only the overridden cell differs"


def test_a_bad_parameter_is_the_engines_own_message(tmp_path):
    base = preflight.base_of(SOURCE)
    doc = {"schema_version": 1, "status": "SYNTHETIC", "source": "test", "version": "bad", "input_set_hash": base["hash"],
           "run": {"inputs": base["folder"], "scenarios": ["baseline", "adverse"], "variant": "core"},
           "segments": {"P01": {"asset_correlation": 1.5}}}
    result = dry_run_of(doc, tmp_path)
    assert result["verdict"] == "blocked" and result["blocked"]["code"] == "INVALID_SPECIFICATION"
    assert "asset_correlation" in result["blocked"]["message"] and result["z"] is None


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
    assert result["blocked"]["step"] == "R3" and result["z"] is None
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
    assert sum(row["records"] for row in result["records"]) == result["rejected"]
    assert "GCA" in differing(folder)


def test_rejected_records_are_counted_for_each_reason_and_detail():
    """One reason covers several rules. Each rule's detail is a line of its own with its own count and
    its own records, so no detail is shown with the count of the whole reason."""
    rows = pd.DataFrame({
        "record_type": "facility", "record_id": ["F1", "F2", "F3", "F4"], "row": [1, 2, 3, 4], "step": "R3",
        "reason_code": ["MISSING_FLAG", "MISSING_FLAG", "MISSING_FLAG", "INVALID_DPD"],
        "detail": ["watchlist missing", "watchlist missing", "dpd missing", "dpd is negative"]})
    lines = {(line["code"], line["detail"]): line for line in preflight._rejections(rows)}
    assert set(lines) == {("MISSING_FLAG", "watchlist missing"), ("MISSING_FLAG", "dpd missing"),
                          ("INVALID_DPD", "dpd is negative")}
    assert lines["MISSING_FLAG", "watchlist missing"]["records"] == 2
    assert lines["MISSING_FLAG", "watchlist missing"]["sample"] == ["F1", "F2"]
    assert lines["MISSING_FLAG", "dpd missing"]["records"] == 1 and lines["MISSING_FLAG", "dpd missing"]["sample"] == ["F3"]
    assert sum(line["records"] for line in lines.values()) == len(rows)


def test_the_page_words_a_rejection_by_its_own_detail():
    page = server.PAGE.read_text(encoding="utf-8")
    listed = page[page.index("function verdictBox"):page.index("function renderVerdict")]
    assert "r.detail ??" in listed and "details[0]" not in page


def test_a_file_edited_by_hand_stops_at_its_hash(copy_of_set):
    table = pd.read_parquet(copy_of_set / "facilities.parquet")
    table.loc[0, "gca"] *= 2
    table.to_parquet(copy_of_set / "facilities.parquet")
    result = preflight.dry_run(config_of(copy_of_set))
    assert result["blocked"]["code"] == "INPUT_HASH_MISMATCH" and result["blocked"]["step"] == "R2"


def test_nothing_after_a_block_is_reported():
    result = preflight.dry_run(config_of(OLDER))
    assert result["blocked"]["code"] == "MISSING_COLUMN" and result["blocked"]["step"] == "R2"
    assert result["accepted"] is None and result["z"] is None and result["rejected"] is None


def test_a_fault_in_a_check_reads_as_a_fault_not_a_pass(monkeypatch, capsys):
    def broken(*_):
        raise RuntimeError("a bug")

    monkeypatch.setattr(validate, "validate_and_route", broken)
    result = preflight.dry_run(config_of(SOURCE))
    assert result["verdict"] == "blocked" and result["z"] is None
    assert result["fault"] == {"message": "RuntimeError: a bug"}, "one line for the page, and no traceback"
    assert "Traceback" in capsys.readouterr().err, "the traceback is for whoever runs the server"


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
    ({"run": {}, "segments": {"P01": {"asset_correlation": 0.2}}}, True),
    ({"run": {}, "scenarios": {}, "assignments": []}, False),
])
def test_only_what_a_flag_cannot_say_needs_a_file(doc, needed):
    assert preflight.needs_specification(doc) is needed


def test_a_setup_round_trips_through_yaml(tmp_path):
    doc = {"schema_version": 1, "status": "SYNTHETIC", "source": "test", "version": "v", "input_set_hash": "h",
           "run": {"inputs": f"inputs/{SOURCE.name}", "scenarios": ["baseline", "adverse"], "variant": "core", "analysis": None},
           "segments": {"P01": {"asset_correlation": 0.2}}, "terminal_policies": {}}
    text = server.specification_text(doc, tmp_path)
    assert "analysis" not in text and "terminal_policies" not in text, "empty is left out"
    back = preflight.parse_yaml(text, tmp_path)
    assert back["run"]["inputs"] == f"inputs/{SOURCE.name}" and back["segments"] == {"P01": {"asset_correlation": 0.2}}
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


# --- YAML from outside: aliases are read, and none may stand for more than a file could hold -----------------

def nested_aliases(levels: int, width: int = 10) -> str:
    """A list of `width` aliases to a list of `width` aliases, and so on: width ** levels values."""
    lines = ["a0: &a0 [" + ", ".join(["x"] * width) + "]"]
    lines += [f"a{n}: &a{n} [" + ", ".join([f"*a{n - 1}"] * width) + "]" for n in range(1, levels)]
    return "\n".join(lines) + "\n"


def merged_aliases(levels: int, width: int = 10) -> str:
    """The same through merge keys, which the parser itself writes out while it reads."""
    lines = ["a0: &a0 {k0: v}"]
    lines += [f"a{n}: &a{n} {{<<: [" + ", ".join([f"*a{n - 1}"] * width) + f"], k{n}: v}}" for n in range(1, levels)]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("text", [nested_aliases(12), merged_aliases(7), "a: &a [*a, *a]\n", "[" * 5000 + "]" * 5000],
                         ids=["nested aliases", "merge keys", "an alias to itself", "five thousand levels deep"])
def test_a_yaml_that_expands_beyond_what_it_could_hold_is_refused_before_it_is_built(text):
    """Twelve levels of ten are a million million values from six hundred bytes. The answer must come
    at once: the count stops at the limit, long before the document is built or written out. The
    merge keys stop at seven levels, because the parser itself writes those out: if this check were
    ever lost, twelve would take the machine's memory with the test."""
    assert len(text) < 20_000
    began = time.perf_counter()
    with pytest.raises(preflight.TooLarge):
        preflight.load_yaml(text)
    assert time.perf_counter() - began < 5


def test_a_yaml_within_the_limit_is_read_as_yaml_reads_it_aliases_and_all():
    text = "base: &base {a: 1, b: [1, 2]}\ncopy: *base\nmerged: {<<: *base, c: 3}\n"
    assert preflight.load_yaml(text) == yaml.safe_load(text)
    assert preflight.load_yaml(nested_aliases(4)) == yaml.safe_load(nested_aliases(4)), "ten thousand values pass"
    assert preflight.load_yaml("") is None
    for name in ("scenarios.yaml", "parameter_set.yaml"):
        text = (SOURCE / name).read_text(encoding="utf-8")
        assert preflight.load_yaml(text) == yaml.safe_load(text)


def test_a_long_yaml_without_aliases_is_never_refused_for_its_length(monkeypatch):
    """The limit grows with the text, so only what aliases add can pass it."""
    monkeypatch.setattr(preflight, "YAML_VALUES", 10)
    text = yaml.safe_dump({"values": [{"scenario": "baseline", "year": year, "value": 1.5} for year in range(200)]})
    assert preflight.load_yaml(text) == yaml.safe_load(text)
    with pytest.raises(preflight.TooLarge):
        preflight.load_yaml(nested_aliases(3))


def test_a_pasted_setup_with_runaway_aliases_is_refused_as_the_engine_words_a_refusal():
    text = ("schema_version: 1\nstatus: SYNTHETIC\nsource: s\nversion: v\ninput_set_hash: h\n"
            f"run: {{inputs: inputs/{SOURCE.name}}}\nreporting:\n"
            + "".join(f"  {line}\n" for line in nested_aliases(12).splitlines()) + "additional_values: *a11\n")
    with pytest.raises(BlockingError) as caught:
        preflight.parse_yaml(text, None)
    assert caught.value.code == "INVALID_SPECIFICATION" and "aliases expand" in caught.value.message


def test_an_added_yaml_file_with_runaway_aliases_is_named_as_not_read(tmp_path):
    doc = (SOURCE / "scenarios.yaml").read_text(encoding="utf-8")
    path = tmp_path / "scenarios.yaml"
    path.write_text(doc + nested_aliases(12), encoding="utf-8")
    view = preflight.inspected(SCENARIOS, path)
    assert "aliases expand" in view["problem"] and view["rows"] is None
    path.write_text(doc + nested_aliases(2), encoding="utf-8")
    assert preflight.inspected(SCENARIOS, path)["problem"] is None, "an alias as such is no fault"
