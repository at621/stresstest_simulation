"""Versioned run specifications and data-only portfolio/scenario onboarding."""

import json

import pandas as pd
import pytest
import yaml

from stress.cli import cmd_rerun, execute
from stress.contracts.inputs import MODEL_SETTINGS
from stress.contracts.run import RunConfig
from stress.models import REGISTRY
from tests import builders


def specification(inputs, **sections):
    manifest = json.loads((inputs / "manifest.json").read_text())
    return {
        "schema_version": 1, "status": "SYNTHETIC", "source": "capability test",
        "version": "test-v1", "input_set_hash": manifest["input_set_hash"],
        "run": {"inputs": str(inputs), "scenarios": ["baseline", "adverse"]},
        **sections,
    }


def write_spec(path, doc):
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


@pytest.mark.req("OPS-01", "OPS-04", "SCN-01")
def test_specification_adds_a_crisis_and_replays_without_original(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    doc = specification(inputs, scenarios={"energy_crisis": {
        "inherits": "adverse", "narrative": "Energy disruption with weaker activity",
        "overrides": [{"variable": "gdp_growth", "country": "*", "year": 2027,
                       "value": -0.08, "unit": "decimal", "value_type": "growth"}],
    }})
    doc["run"]["scenarios"].append("energy_crisis")
    doc["terminal_policies"] = {"energy_crisis": {"method": "flat"}}
    source = tmp_path / "job.yaml"
    config = RunConfig("", (), "core", specification=write_spec(source, doc))
    ctx, manifest = execute(config, tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    result = builders.result(ctx, "slices.parquet")
    assert set(result.scenario) == set(doc["run"]["scenarios"])
    assert (ctx.data_dir / "specification.yaml").exists()
    replica = pd.read_csv(ctx.reports_dir / "analysis_template_replica.csv")
    final = replica[(replica.scenario == "energy_crisis") & (replica.year == 2029)]
    assert final.loss_rate_s1_next.to_numpy() == pytest.approx(
        (final.pd12m_s1 * final.lgd_s1).to_numpy(), abs=1e-9)
    source.unlink()
    from types import SimpleNamespace
    assert cmd_rerun(SimpleNamespace(run=str(ctx.run_dir), runs_dir=None, quiet=True)) == 0


@pytest.mark.control("Repository rules")
@pytest.mark.parametrize("change", ["unknown", "wrong_hash", "nonfinite"])
def test_specification_rejects_invalid_input(mini, tmp_path, change):
    from stress.contracts.errors import BlockingError
    inputs = builders.write(mini, tmp_path / "inputs")
    doc = specification(inputs)
    if change == "unknown":
        doc["silently_ignored"] = True
    elif change == "wrong_hash":
        doc["input_set_hash"] = "wrong"
    else:
        doc["scenarios"] = {"bad": {"inherits": "adverse", "narrative": "bad input", "overrides": [
            {"variable": "gdp_growth", "country": "*", "year": 2027,
             "value": float("inf"), "unit": "decimal", "value_type": "growth"}]}}
    config = RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc))
    try:
        _, manifest = execute(config, tmp_path / "runs")
    except BlockingError:
        return
    assert manifest["status"] == "BLOCKED"
    assert manifest["blocked"]["code"] != "INTERNAL_ERROR"


@pytest.mark.req("SCP-01", "RPT-05")
def test_new_segment_uses_configured_reporting_class(mini, tmp_path):
    mini["facilities"].loc[mini["facilities"].segment == "P03", ["portfolio", "segment"]] = ["P07", "P07_SME"]
    mini["ttc_pd_matrix"].loc[mini["ttc_pd_matrix"].segment == "P03", "segment"] = "P07_SME"
    portfolios = mini["parameter_set"]["portfolios"]
    sme = portfolios.pop("P03")["segments"]["P03"]
    for role, setting in MODEL_SETTINGS.items():  # a new portfolio has models of its own
        own = REGISTRY[sme[setting]]
        sme[setting] = builders.model(f"p07.sme_{role}", role, own.function, own.sensitivity)
    portfolios["P07"] = {"segments": {"P07_SME": sme}}
    inputs = builders.write(mini, tmp_path / "inputs")
    template_class = "Loans and advances - NFC - SME - Other loans"
    doc = specification(inputs, reporting={"template_classes": {"P07_SME": template_class}})
    ctx, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                            tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    report = pd.read_csv(ctx.reports_dir / "analysis_template_replica.csv")
    assert report.loc[report.segment == "P07_SME", "template_class"].eq(template_class).all()
    assert "P07" in set(pd.read_csv(ctx.reports_dir / "impairment.csv").portfolio)


@pytest.mark.req("OPS-01", "DAT-03", "SCP-01")
def test_packaging_preserves_supplied_exposure_and_frozen_provisions(mini, tmp_path):
    from foundation.synth.inputset import package
    inputs = builders.write(mini, tmp_path / "inputs")
    packaged = package(inputs, tmp_path / "packaged")
    for name in builders.TABLES:
        if name != "ttc_pd_matrix":
            pd.testing.assert_frame_equal(pd.read_parquet(inputs / f"{name}.parquet"),
                                          pd.read_parquet(packaged / f"{name}.parquet"))
    for path in sorted((inputs / "matrices").iterdir()):
        assert (packaged / "matrices" / path.name).read_bytes() == path.read_bytes()
    assert json.loads((packaged / "approval.json").read_text())["status"] == "PENDING_OWNER_APPROVAL"


@pytest.mark.req("SCP-01", "DAT-02")
def test_assignments_cannot_hide_overlap_by_changing_portfolio(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    doc = specification(inputs, segments={"NEW": {"inherits": "P03", "portfolio": "P07"}},
                        assignments=[
                            {"where": {"portfolio": "P03"}, "segment": "NEW", "portfolio": "P07"},
                            {"where": {"portfolio": "P03"}, "segment": "P03"},
                        ])
    # A partially overlapping second selector must also block, independently of order.
    first_id = mini["facilities"].loc[mini["facilities"].portfolio.eq("P03"), "facility_id"].iloc[0]
    doc["assignments"][0]["where"] = {"facility_id": first_id}
    _, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                          tmp_path / "runs")
    assert manifest["status"] == "BLOCKED"
    assert manifest["blocked"]["code"] == "INVALID_SPECIFICATION"


@pytest.mark.req("RPT-01", "SCN-01")
def test_scenario_names_are_literal_workbook_labels(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    name = "energy.v2"
    doc = specification(inputs, scenarios={name: {"inherits": "adverse", "narrative": "Label test"}})
    doc["run"]["scenarios"] = ["baseline", name]
    ctx, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                            tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    from openpyxl import load_workbook
    workbook = load_workbook(ctx.reports_dir / "stress_report.xlsx")
    labels = [c.value for row in workbook["Results by portfolio"] for c in row]
    assert f"{name} - baseline" in labels


@pytest.mark.control("Repository rules")
def test_duplicate_yaml_setting_is_rejected(tmp_path):
    from stress.contracts.errors import BlockingError
    from stress.ingest.specification import resolve

    path = tmp_path / "duplicate.yaml"
    path.write_text("schema_version: 1\nschema_version: 1\n", encoding="utf-8")
    with pytest.raises(BlockingError, match="duplicate"):
        resolve(RunConfig("", (), "core", specification=str(path)))


@pytest.mark.req("SCN-08", "EAD-04", "DAT-02")
@pytest.mark.parametrize("override", [
    {"z_drivers": {"gdp_growth": {"beta": 1, "mean": 0, "sd": 1}}},  # coefficients live in the models
    {"lgd_w": 0.1}, {"cpr_v": 0.1}, {"rho": 0.1}, {"macro_model": "p03.pd"},
    {"pd_model": 3}, {"lgd_model": ""},
    {"asset_correlation": 1.0}, {"asset_correlation": True}, {"sicr_k": 0}, {"cpr_ttc": 1.5},
    {"ccf": "invalid"}, {"ccf": 1.5},
])
def test_segment_override_is_strict_data(mini, override):
    from types import SimpleNamespace

    from stress.contracts.errors import BlockingError
    from stress.ingest.specification import apply_segments

    loaded = SimpleNamespace(parameter_set={**mini["parameter_set"], "segments": builders.segments(mini)},
                             ttc_pd_matrix=mini["ttc_pd_matrix"],
                             facilities=SimpleNamespace(data=mini["facilities"]),
                             obligors=SimpleNamespace(data=mini["obligors"]),
                             commitments=SimpleNamespace(data=mini["commitments"]))
    with pytest.raises(BlockingError) as caught:
        apply_segments(loaded, {"P03": override}, [])
    assert caught.value.code == "INVALID_SPECIFICATION"


@pytest.mark.req("EAD-04", "DAT-02")
def test_specification_ccf_mismatch_blocks_instead_of_dropping_commitments(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    commitment = mini["commitments"].iloc[0]
    segment = mini["facilities"].set_index("facility_id").loc[commitment.facility_id, "segment"]
    different = 0.0 if commitment.accounting_ccf != 0 else 1.0
    doc = specification(inputs, segments={segment: {"ccf": different}})
    _, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                          tmp_path / "runs")
    assert manifest["status"] == "BLOCKED"
    assert manifest["blocked"]["code"] == "INVALID_SPECIFICATION"


@pytest.mark.req("DAT-02", "OPS-01")
def test_effective_specification_preserves_unused_missing_as_json_null(mini, tmp_path):
    row = mini["scenarios"]["values"][0].copy()
    row.update(variable="unused_driver", value=None, completeness="missing")
    mini["scenarios"]["values"].append(row)
    inputs = builders.write(mini, tmp_path / "inputs")
    ctx, manifest = builders.run(inputs, tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    def no_constant(value):
        raise ValueError(f"non-standard JSON constant {value}")
    doc = json.loads((ctx.reports_dir / "effective_specification.json").read_text(), parse_constant=no_constant)
    value = next(r for r in doc["scenario_values"] if r["variable"] == "unused_driver")
    assert value["value"] is None and value["value_status"] == "missing"
