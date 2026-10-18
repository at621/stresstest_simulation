"""Unit tests of the one-off steps O1-O4."""

import numpy as np
import pytest
import yaml

from foundation import matrices as o2
from foundation.transcribe import check
from foundation.transcribe.markdown import check_transcribed, numbers
from tests import builders
from tests.support import INPUTS_DIR, SPEC_DIR, spec_yaml


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
def test_generator_is_deterministic_and_matches_the_committed_set(full_inputs, tmp_path):
    again = builders.full_input_set(tmp_path)
    assert again.name == full_inputs.name, "same seed and targets give the same input-set hash"
    # The committed input set is the one O2-O4 produce now, byte for byte.
    committed = INPUTS_DIR / full_inputs.name
    assert committed.exists(), f"inputs/ holds no set with the hash O2-O4 produce now ({full_inputs.name})"
    for name in ("facilities.parquet", "opening_provisions.parquet", "parameter_set.yaml"):
        assert (committed / name).read_bytes() == (full_inputs / name).read_bytes(), name


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


@pytest.mark.req("PD-09")
def test_parameter_set_documents_its_status(full_inputs):
    with (full_inputs / "parameter_set.yaml").open(encoding="utf-8") as fh:
        params = yaml.safe_load(fh)
    assert params["status"] == "PROPOSED"
    assert len(params["master_scale"]["grades"]) == len(params["master_scale"]["ttc_pd"])
    for seg in params["segments"].values():
        assert all(seg[k] is not None for k in ("rho", "sicr_k", "lgd_w", "cpr_ttc", "cpr_v"))
