"""Unit tests of the one-off steps O1-O4."""

import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from foundation import matrices as o2
from foundation.synth import SCENARIO_LIBRARY, scenario_document
from foundation.transcribe import check
from foundation.transcribe.markdown import check_transcribed, numbers
from stress.ingest import check_hashes
from tests import builders
from tests.support import CURRENT_INPUT_SET, INPUTS_DIR, SPEC_DIR, spec_yaml


def _yaml(path):
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.mark.req("GOV-03")
def test_o1_files_are_current():
    """docs/spec/ is exactly what O1 writes from the current requirements version."""
    assert check(SPEC_DIR) == []


@pytest.mark.control("Repository rules")
def test_transcription_rejects_numbers_not_in_the_source():
    assert numbers("Closing S1/S2/S3 = 814/140/46; AT-25 End-2029 2.94%") == [814.0, 140.0, 46.0, 0.0294]
    check_transcribed({"a": 814.0, "b": 0.0294}, "814 and 2.94%", "ok")
    with pytest.raises(ValueError):
        check_transcribed({"a": 815.0}, "814 and 2.94%", "typed by hand")


@pytest.mark.req("SYN-PAR-05")
def test_calibration_hits_every_stage_target(full_tables):
    params = full_tables["parameter_set"]
    pds = np.array(params["master_scale"]["ttc_pd"])
    targets = spec_yaml("targets.yaml")
    plan = o2.calibration_plan(pds, spec_yaml("calibration_targets.yaml"), targets["risk_profiles"])
    cal = spec_yaml("calibration_targets.yaml")["segments"]
    for seg, stages in plan.items():
        for stage, mix in stages.items():
            target = cal[seg]["s1_pd" if stage == 1 else "s2_pd"]
            assert abs(sum(pds[g - 1] * w for g, w in mix.items()) - target) <= 1e-12
            lo, hi = targets["risk_profiles"][cal[seg]["portfolio"]]["performing_pd"]
            assert all(lo - 1e-12 <= pds[g - 1] <= hi + 1e-12 for g in mix)
    # The generated book realises the mix: GCA-weighted TTC PD per segment and stage.
    fac = full_tables["facilities"]
    grade_pd = dict(zip(params["master_scale"]["grades"], pds))
    for (seg, stage), part in fac[fac["ifrs_stage"] < 3].groupby(["segment", "ifrs_stage"]):
        avg = float((part["gca"] * part["current_grade"].map(grade_pd)).sum() / part["gca"].sum())
        target = cal[seg]["s1_pd" if stage == 1 else "s2_pd"]
        assert abs(avg - target) <= 1e-10, (seg, stage)


@pytest.mark.req("SYN-PAR-08")
def test_reported_stage_is_the_pd_test_or_a_flag(full_tables):
    # O3 after the owner decision of 18 October 2026 (A30): the reported stage of a performing
    # facility is S2 when the PD test or a qualitative trigger says so. S1 carries no trigger, and
    # a share of S2 is S2 by a flag alone, with a grade above the SICR line.
    from foundation.synth import config as cfg
    from stress.params import ttc_arrays
    from stress.validate.sicr import TtcLifetime, qualitative_trigger, sicr_rank

    ps = {**full_tables["parameter_set"], "segments": builders.segments(full_tables)}
    fac = full_tables["facilities"]
    perf = fac[fac["ifrs_stage"] < 3]
    matrices, grades = ttc_arrays(full_tables["ttc_pd_matrix"])
    rank = {g: i + 1 for i, g in enumerate(grades)}
    life = TtcLifetime(matrices)
    line = np.array([sicr_rank(life.pd(s, float(h)), rank[g0], float(ps["segments"][s]["sicr_k"]))[0]
                     for s, h, g0 in perf[["segment", "residual_maturity", "origination_grade"]].to_numpy()])
    pd_test = perf["current_grade"].map(rank).to_numpy() >= line
    flag = np.asarray(qualitative_trigger(perf["dpd"], perf["watchlist"], perf["forborne"], ps["sicr_triggers"]))
    assert (np.where(pd_test | flag, 2, 1) == perf["ifrs_stage"].to_numpy()).all()
    assert not flag[perf["ifrs_stage"].to_numpy() == 1].any(), "no S1 facility carries a trigger"
    flag_only = (perf["ifrs_stage"].to_numpy() == 2) & ~pd_test
    assert flag[flag_only].all()
    for seg, part in perf.assign(flag_only=flag_only).groupby("segment"):
        s2 = int((part["ifrs_stage"] == 2).sum())
        assert int(part["flag_only"].sum()) == round(cfg.FLAG_ONLY_S2_SHARE * s2), seg
    assert (fac["credit_status_date"] == fac["snapshot_date"]).all()


@pytest.mark.req("SYN-PAR-08")
def test_generator_is_deterministic(full_inputs, tmp_path):
    again = builders.full_input_set(tmp_path)
    assert again.name == full_inputs.name, "same seed and targets give the same input-set hash"


@pytest.mark.req("SYN-PAR-08")
@pytest.mark.skipif(sys.platform != "win32", reason="the hash depends on the system and the BLAS kernel (A36)")
def test_the_committed_set_is_what_the_generator_produces(full_inputs):
    # The committed input set is the one O2-O4 produce now, byte for byte, under the kernel that built it.
    committed = INPUTS_DIR / full_inputs.name
    assert committed.exists(), f"inputs/ holds no set with the hash O2-O4 produce now ({full_inputs.name})"
    assert full_inputs.name == CURRENT_INPUT_SET, "tests/support.py names another set as the current one"
    for name in ("facilities.parquet", "opening_provisions.parquet", "parameter_set.yaml", "scenarios.yaml"):
        assert (committed / name).read_bytes() == (full_inputs / name).read_bytes(), name


@pytest.mark.req("SCN-01")
def test_every_scenario_has_a_label_and_a_description(full_tables):
    doc = full_tables["scenarios"]
    library = _yaml(SCENARIO_LIBRARY)["scenarios"]
    section = list(spec_yaml("scenarios.yaml")["paths"])
    ids = [s["id"] for s in doc["scenarios"]]
    assert ids == section + [name for name in library if name not in section]
    assert len(ids) > len(section), "the library adds scenarios beyond section 6.2"
    for entry in doc["scenarios"]:
        assert entry["label"] == library[entry["id"]]["label"]
        assert entry["description"].strip() == library[entry["id"]]["description"].strip()
        assert entry["status"] == "SYNTHETIC" and entry["source_type"] == "synthetic"


@pytest.mark.req("SCN-01")
def test_the_section_6_2_paths_are_written_as_before(full_tables):
    """Adding scenarios leaves every section 6.2 value, its source and its release as they were."""
    spec = spec_yaml("scenarios.yaml")
    alone = scenario_document(spec, "1.3", _library(extra=None))
    values = full_tables["scenarios"]["values"]
    assert [v for v in values if v["scenario"] in spec["paths"]] == alone["values"]
    assert full_tables["scenarios"]["starting_values"] == alone["starting_values"]
    assert full_tables["scenarios"]["index_of"] == alone["index_of"]


@pytest.mark.req("SCN-02")
def test_an_added_scenario_states_every_variable_country_and_year(full_tables):
    spec = spec_yaml("scenarios.yaml")
    library = _yaml(SCENARIO_LIBRARY)
    added = [name for name in library["scenarios"] if name not in spec["paths"]]
    values = [v for v in full_tables["scenarios"]["values"] if v["scenario"] in added]
    keys = {(v["scenario"], v["variable"], v["country"], v["year"]) for v in values}
    assert len(keys) == len(values) == len(added) * len(spec["variables"]) * len(spec["countries"]) * len(spec["years"])
    for v in values:
        meta = spec["variables"][v["variable"]]
        entry = library["scenarios"][v["scenario"]]
        path = {**entry["paths"], **entry.get("by_country", {}).get(v["country"], {})}[v["variable"]]
        assert v["value"] == float(path[v["year"]])
        assert (v["unit"], v["value_type"]) == (meta["unit"], meta["value_type"])
        assert (v["source"], v["release"]) == (library["source"], library["release"])
        assert (v["status"], v["completeness"]) == ("SYNTHETIC", "complete")


def _library(**changes) -> dict:
    spec = spec_yaml("scenarios.yaml")
    paths = {var: {y: 1.0 for y in spec["years"]} for var in spec["variables"]}
    scenarios = {s: {"label": s.capitalize(), "description": s} for s in spec["paths"]}
    scenarios["extra"] = {"label": "Extra", "description": "An extra scenario.", "paths": paths}
    for name, body in changes.items():  # None drops a scenario, or one key of it
        if body is None:
            scenarios.pop(name)
        else:
            merged = {**scenarios.get(name, {}), **body}
            scenarios[name] = {key: value for key, value in merged.items() if value is not None}
    return {"source": "test library", "release": "2026-11-06", "scenarios": scenarios}


@pytest.mark.req("SCN-02")
def test_a_country_can_have_its_own_path():
    spec = spec_yaml("scenarios.yaml")
    library = _library()
    library["scenarios"]["extra"]["by_country"] = {"PL": {"gdp_growth": {y: -9.0 for y in spec["years"]}}}
    values = scenario_document(spec, "1.3", library)["values"]
    gdp = {(v["country"], v["year"]): v["value"] for v in values if v["scenario"] == "extra" and v["variable"] == "gdp_growth"}
    assert all(value == (-9.0 if country == "PL" else 1.0) for (country, _), value in gdp.items())
    assert len(gdp) == len(spec["countries"]) * len(spec["years"])


@pytest.mark.req("SCN-01")
@pytest.mark.parametrize("changes, wrong", [
    ({"baseline": None}, "baseline"),
    ({"baseline": {"paths": {}}}, "section 6.2"),
    ({"extra": {"paths": None}}, "paths"),
    ({"extra": {"description": " "}}, "description"),
    ({"extra": {"label": ""}}, "label"),
    ({"extra": {"paths": {"gdp_growth": {2027: 1.0, 2028: 1.0, 2029: 1.0}}}}, "unemployment"),
    ({"extra": {"paths": {"inflation": {2027: 1.0}}}}, "inflation"),
    ({"extra": {"by_country": {"XX": {}}}}, "XX"),
    ({"extra": {"colour": "red"}}, "colour"),
    ({"Bad name": {"label": "Bad", "description": "Bad.", "paths": {}}}, "Bad name"),
])
def test_the_scenario_library_is_checked(changes, wrong):
    with pytest.raises(ValueError, match=wrong):
        scenario_document(spec_yaml("scenarios.yaml"), "1.3", _library(**changes))


@pytest.mark.req("SCN-02")
def test_a_missing_year_is_refused():
    library = _library()
    del library["scenarios"]["extra"]["paths"]["gdp_growth"][2028]
    with pytest.raises(ValueError, match="2028"):
        scenario_document(spec_yaml("scenarios.yaml"), "1.3", library)


@pytest.mark.req("SCN-02")
@pytest.mark.parametrize("value", [None, True, "1.0", float("nan"), float("inf")])
def test_a_value_that_is_not_a_finite_number_is_refused(value):
    library = _library()
    library["scenarios"]["extra"]["paths"]["unemployment"][2028] = value
    with pytest.raises(ValueError, match="extra: unemployment in [A-Z]{2} 2028"):
        scenario_document(spec_yaml("scenarios.yaml"), "1.3", library)


@pytest.mark.req("SCN-01")
@pytest.mark.parametrize("where", ["scenarios", "entry", "paths", "path", "by_country"])
def test_a_library_that_is_not_built_of_mappings_is_refused(where):
    library = _library()
    extra = library["scenarios"]["extra"]
    if where == "scenarios":
        library["scenarios"] = ["extra"]
    elif where == "entry":
        library["scenarios"]["extra"] = "severe"
    elif where == "paths":
        extra["paths"] = [1.0, 2.0]
    elif where == "path":
        extra["paths"]["gdp_growth"] = [1.0, 1.0, 1.0]
    else:
        extra["by_country"] = {"PL": [1.0]}
    with pytest.raises(TypeError, match="mapping"):
        scenario_document(spec_yaml("scenarios.yaml"), "1.3", library)


@pytest.mark.req("OPS-01")
def test_the_committed_set_matches_its_manifest_hashes():
    # Runs on every system, unlike the byte-for-byte comparison above (A36). It checks the hashes
    # only: R2's reading of the files is proved by the runs other tests make.
    folder = INPUTS_DIR / CURRENT_INPUT_SET
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert folder.name == manifest["input_set_hash"][:16]
    check_hashes(SimpleNamespace(input_dir=folder, input_set_hash=manifest["input_set_hash"]), manifest)


@pytest.mark.req("SYN-PAR-09")
def test_opening_allowances_frozen_by_the_generator_formula(full_tables):
    fac = full_tables["facilities"].set_index("facility_id")
    prov = full_tables["opening_provisions"].set_index("facility_id")
    s3 = fac.index[fac["ifrs_stage"] == 3]
    assert np.allclose(prov.loc[s3, "allowance_on"], fac.loc[s3, "gca"] * fac.loc[s3, "ttc_lgd"], rtol=1e-12)
    assert (prov["allowance_on"] >= 0).all() and (prov["provision_off"] >= 0).all()
    assert prov["frozen"].all()
    off = prov.index[prov["provision_off"] > 0]
    assert set(off) <= set(full_tables["commitments"]["facility_id"])


@pytest.mark.req("SYN-PAR-06")
def test_parameter_set_documents_its_status(full_inputs):
    with (full_inputs / "parameter_set.yaml").open(encoding="utf-8") as fh:
        params = yaml.safe_load(fh)
    assert params["status"] == "PROPOSED"
    assert len(params["master_scale"]["grades"]) == len(params["master_scale"]["ttc_pd"])
    for body in params["portfolios"].values():
        for seg in body["segments"].values():
            assert all(seg[k] is not None for k in ("pd_model", "lgd_model", "prepayment_model", "ttc_matrix",
                                                    "asset_correlation", "sicr_k", "cpr_ttc"))
