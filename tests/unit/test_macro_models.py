"""Segment models: a closed registry of documented functions, one PD, LGD and prepayment model per
segment, each with its own score, named by the parameter set and by run specifications."""

import inspect

import pandas as pd
import pytest

from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import MODEL_SETTINGS
from stress.models import LGD, PD, PREPAYMENT, REGISTRY, Economy, resolve
from stress.models.forms import linear, polynomial, supplied
from tests import builders


def economy(values: dict, scenario="crisis", country="DE", year=2027) -> Economy:
    return Economy(scenario, country, year, {(scenario, v, country, y): (x, "supplied") for (v, y), x in values.items()})


@pytest.mark.req("MOD-01", "SCN-03", "SCN-08")
def test_polynomial_model_uses_lagged_driver_and_records_terms():
    terms = {"gdp_lag": {"variable": "gdp", "lag": 1, "power": 2, "mean": 0.0, "sd": 1.0, "beta": -0.5}}
    score = polynomial(economy({("gdp", 2026): -0.2, ("gdp", 2027): 0.8}), 0.1, terms)
    assert score.z == pytest.approx(0.1 + terms["gdp_lag"]["beta"] * (-0.2) ** 2)
    assert sum(t.contribution for t in score.terms) == pytest.approx(score.z)
    with pytest.raises(BlockingError, match="missing"):
        polynomial(economy({("gdp", 2027): 0.8}), 0.1, terms)


@pytest.mark.req("MOD-01", "SCN-08")
def test_supplied_scores_need_the_scenario_and_year():
    scores = {("crisis", 2027): -1.5}
    score = supplied(economy({}), scores)
    assert score.z == -1.5 and sum(t.contribution for t in score.terms) == score.z
    with pytest.raises(BlockingError, match="missing"):
        supplied(economy({}, year=2028), scores)


@pytest.mark.req("SCN-08", "MOD-01")
def test_linear_model_cannot_return_an_infinite_score():
    with pytest.raises(BlockingError, match="non-finite"):
        linear(economy({("driver", 2027): 10.0}), {"driver": {"beta": 1e308, "mean": 0.0, "sd": 1.0}})


@pytest.mark.req("MOD-01")
def test_every_segment_names_its_own_pd_lgd_and_prepayment_model(full_tables):
    """Each segment of the parameter set has three models of its own portfolio, each a documented
    function in src/stress/models/ that holds its coefficients, and no two segments share one."""
    used = []
    for portfolio, body in full_tables["parameter_set"]["portfolios"].items():
        for settings in body["segments"].values():
            for role, setting in MODEL_SETTINGS.items():
                model = resolve(settings[setting], role, portfolio)
                assert model.name.startswith(portfolio.lower() + ".") and model.role == role
                assert model.description and model.location.startswith(f"src/stress/models/{portfolio.lower()}.py")
                assert inspect.getsourcefile(model.function).replace("\\", "/").endswith(model.location.split(",")[0])
                assert (model.sensitivity is None) == (role == PD)
                used.append(model.name)
    assert len(used) == len(set(used)) == 3 * len(builders.segments(full_tables))


@pytest.mark.req("MOD-01")
@pytest.mark.parametrize("name, role, portfolio", [
    ("p01.nothing", PD, "P01"),          # not a registered model
    ("stress.models.p01.pd", PD, "P01"),  # an import path is not a model name
    ("p01.lgd", PD, "P01"),              # a model of another role
    ("p02.pd", PD, "P01"),               # a model of another portfolio
    (None, LGD, "P01"),
])
def test_a_model_the_registry_does_not_offer_blocks(name, role, portfolio):
    with pytest.raises(BlockingError) as caught:
        resolve(name, role, portfolio)
    assert caught.value.code == Block.UNKNOWN_MODEL


@pytest.mark.req("MOD-01", "DAT-02")
def test_a_parameter_set_naming_an_unknown_model_blocks_at_r2(mini, tmp_path):
    builders.settings(mini, "P02")["lgd_model"] = "p02.missing"
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "BLOCKED"
    assert (manifest["blocked"]["step"], manifest["blocked"]["code"]) == ("R2", Block.UNKNOWN_MODEL)


@pytest.mark.req("MOD-01", "DAT-02")
@pytest.mark.parametrize("setting", ["z_drivers", "lgd_w", "cpr_v", "rho"])
def test_a_coefficient_in_the_parameter_set_blocks(mini, tmp_path, setting):
    """The coefficients live in the model functions, so the old settings are no longer accepted."""
    builders.settings(mini, "P01")[setting] = 0.1
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "BLOCKED" and manifest["blocked"]["code"] == Block.MISSING_PARAMETER
    assert setting in manifest["blocked"]["message"]


@pytest.mark.req("MOD-01", "SCN-08", "LGD-12", "EAD-11")
def test_each_model_has_its_own_score(core_run, full_tables):
    """The run scores every segment's three models, and each parameter takes its own model's Z: the
    PiT matrices the PD model's, the LGD the LGD model's, prepayment the prepayment model's."""
    ctx, _ = core_run
    z = builders.result(ctx, "drivers.parquet")
    segments = builders.segments(full_tables)
    assert set(z["model"]) == {PD, LGD, PREPAYMENT}
    assert z.groupby(["segment", "country", "scenario", "year"])["model"].nunique().eq(3).all()
    assert set(z["segment"]) == set(segments)
    key = ["segment", "country", "scenario", "year"]
    pit = builders.result(ctx, "pit_matrices.parquet").drop_duplicates(key)[[*key, "z"]]
    joined = pit.merge(z[z["model"] == PD][[*key, "z"]], on=key, suffixes=("", "_pd"))
    assert len(joined) == len(pit) and (joined["z"] == joined["z_pd"]).all()
    lgd = builders.result(ctx, "lgd_of_year.parquet")
    facts = full_tables["facilities"][["facility_id", "obligor_id", "segment"]].merge(
        full_tables["obligors"][["obligor_id", "country"]], on="obligor_id")
    lgd = lgd.merge(facts, on="facility_id").merge(z[z["model"] == LGD][[*key, "z"]].rename(columns={"z": "z_model"}),
                                                    on=key)
    assert len(lgd) and (lgd["z"] == lgd["z_model"]).all()
    contributions = builders.result(ctx, "driver_contributions.parquet")
    assert set(contributions["model"]) == {PD, LGD, PREPAYMENT}


@pytest.mark.req("MOD-01", "LGD-12", "EAD-11", "PD-10")
def test_an_lgd_model_moves_lgd_alone(mini, tmp_path):
    """A segment's LGD model with other drivers changes its LGD and nothing of its PD or prepayment."""
    reference, result = builders.run(builders.write(builders.copy_tables(mini), tmp_path / "a"), tmp_path / "ra")
    assert result["status"] == "SYNTHETIC"
    own = REGISTRY[builders.settings(mini, "P02")["lgd_model"]]
    builders.settings(mini, "P02")["lgd_model"] = builders.model(
        "p02.test_lgd_on_rates", LGD, sensitivity=own.sensitivity,
        drivers={"reference_rate": {"beta": -1.0, "mean": 0.025, "sd": 0.015}})
    current, result = builders.run(builders.write(mini, tmp_path / "b"), tmp_path / "rb")
    assert result["status"] == "SYNTHETIC", result.get("blocked")
    pd.testing.assert_frame_equal(builders.result(reference, "pit_matrices.parquet"),
                                  builders.result(current, "pit_matrices.parquet"))
    before, after = (builders.result(c, "parameters.parquet") for c in (reference, current))
    other = before["facility_id"].isin(mini["facilities"].loc[mini["facilities"]["segment"] != "P02", "facility_id"])
    assert (before["prepayment_rate"] == after["prepayment_rate"]).all()
    assert (before.loc[other, "lgd"] == after.loc[other, "lgd"]).all()
    assert not before.loc[~other, "lgd"].equals(after.loc[~other, "lgd"])
    yearly = [builders.result(c, "lgd_of_year.parquet") for c in (reference, current)]
    p02 = yearly[0]["facility_id"].isin(mini["facilities"].loc[mini["facilities"]["segment"] == "P02", "facility_id"])
    assert (yearly[0].loc[~p02, "lgd"] == yearly[1].loc[~p02, "lgd"]).all()
    assert not yearly[0].loc[p02, "lgd"].equals(yearly[1].loc[p02, "lgd"])


@pytest.mark.req("MOD-01", "EAD-11", "PD-10", "LGD-12")
def test_a_prepayment_model_moves_prepayment_alone(mini, tmp_path):
    """A segment's prepayment model with other drivers changes its prepayment and nothing of its PD
    or LGD: prepayment takes the prepayment model's Z, not the PD model's."""
    reference, result = builders.run(builders.write(builders.copy_tables(mini), tmp_path / "a"), tmp_path / "ra")
    assert result["status"] == "SYNTHETIC"
    own = REGISTRY[builders.settings(mini, "P01")["prepayment_model"]]
    builders.settings(mini, "P01")["prepayment_model"] = builders.model(
        "p01.test_prepayment_on_rates", PREPAYMENT, sensitivity=own.sensitivity,
        drivers={"reference_rate": {"beta": -1.0, "mean": 0.025, "sd": 0.015}})
    current, result = builders.run(builders.write(mini, tmp_path / "b"), tmp_path / "rb")
    assert result["status"] == "SYNTHETIC", result.get("blocked")
    pd.testing.assert_frame_equal(builders.result(reference, "pit_matrices.parquet"),
                                  builders.result(current, "pit_matrices.parquet"))
    pd.testing.assert_frame_equal(builders.result(reference, "lgd_of_year.parquet"),
                                  builders.result(current, "lgd_of_year.parquet"))
    before, after = (builders.result(c, "parameters.parquet") for c in (reference, current))
    p01 = before["facility_id"].isin(mini["facilities"].loc[mini["facilities"]["segment"] == "P01", "facility_id"])
    assert (before["lgd"] == after["lgd"]).all()
    assert (before.loc[~p01, "prepayment_rate"] == after.loc[~p01, "prepayment_rate"]).all()
    assert not before.loc[p01, "prepayment_rate"].equals(after.loc[p01, "prepayment_rate"])


@pytest.mark.req("MOD-01", "MOD-06", "SCN-03", "SCN-08")
def test_a_specification_points_a_segment_at_another_model_of_its_portfolio(mini, tmp_path):
    from stress.cli import execute
    from stress.contracts.run import RunConfig
    from tests.unit.test_specification import specification, write_spec

    inputs = builders.write(mini, tmp_path / "inputs")
    reference, result = builders.run(inputs, tmp_path / "runs")
    assert result["status"] == "SYNTHETIC"
    doc = specification(inputs, segments={"P02": {"pd_model": "p02.pd_nonlinear"}})
    doc["additional_values"] = [{"scenario": "*", "country": "*", "variable": "gdp_growth", "year": 2026,
                                 "value": 0.02, "unit": "decimal", "value_type": "growth"}]
    config = RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc))
    current, result = execute(config, tmp_path / "runs")
    assert result["status"] == "SYNTHETIC", result.get("blocked")
    old = builders.result(reference, "pit_matrices.parquet")
    new = builders.result(current, "pit_matrices.parquet")
    within = old.year.isin(mini["parameter_set"]["horizon"]["projection_years"])
    mask = old.segment.ne("P02") & within
    pd.testing.assert_frame_equal(old.loc[mask].reset_index(drop=True), new.loc[mask].reset_index(drop=True))
    assert not old.loc[old.segment.eq("P02"), "probability"].equals(new.loc[new.segment.eq("P02"), "probability"])
    before, after = (builders.result(c, "parameters.parquet") for c in (reference, current))
    for column in ("lgd", "prepayment_rate"):  # the PD model's Z drives neither
        assert (before[column] == after[column]).all(), column
    pd.testing.assert_frame_equal(builders.result(reference, "lgd_of_year.parquet"),
                                  builders.result(current, "lgd_of_year.parquet"))
    models = pd.read_csv(current.reports_dir / "segment_models.csv").set_index(["segment", "model"])
    assert models.loc[("P02", PD), "name"] == "p02.pd_nonlinear" and models.loc[("P02", LGD), "name"] == "p02.lgd"
    assert models.loc[("P02", PD), "description"].startswith("Consumer credit: illustrative nonlinear PD model")
    # A model of another portfolio is refused, as is one of another role.
    for wrong in ({"pd_model": "p01.pd"}, {"lgd_model": "p02.pd_nonlinear"}):
        doc = specification(inputs, segments={"P02": wrong})
        _, result = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "bad.yaml", doc)),
                            tmp_path / "runs")
        assert result["status"] == "BLOCKED" and result["blocked"]["code"] == Block.UNKNOWN_MODEL


@pytest.mark.req("SCN-03", "SCN-08", "SCP-01")
def test_a_carved_out_segment_keeps_its_parents_models_under_a_new_portfolio(mini, tmp_path):
    """A new segment inherits its parent's models and must use models of its parent's portfolio,
    even when it reports under a portfolio of its own."""
    from stress.cli import execute
    from stress.contracts.run import RunConfig
    from tests.unit.test_specification import specification, write_spec

    inputs = builders.write(mini, tmp_path / "inputs")
    borrower = mini["facilities"].loc[mini["facilities"].portfolio.eq("P03"), "obligor_id"].iloc[0]
    nace = mini["obligors"].set_index("obligor_id").loc[borrower, "nace_code"]
    sector = builders.model("p03.test_sector", PD, drivers={"sector_gva": {"mean": 0, "sd": 1, "beta": 1}})
    doc = specification(inputs, segments={"P03_SECTOR": {"inherits": "P03", "portfolio": "P07", "pd_model": sector,
                                                         "template_class": "Sector loans"}},
                        assignments=[{"where": {"portfolio": "P03", "nace_code": nace}, "segment": "P03_SECTOR",
                                      "portfolio": "P07"}],
                        additional_values=[{"scenario": "*", "country": "*", "variable": "sector_gva", "year": year,
                                            "value": -0.1, "unit": "decimal", "value_type": "growth"}
                                           for year in (2027, 2028, 2029)])
    ctx, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                            tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    scores = builders.result(ctx, "drivers.parquet")
    sector_z = scores[(scores.segment == "P03_SECTOR") & scores.year.isin([2027, 2028, 2029])]
    assert len(sector_z) and sector_z.loc[sector_z.model == PD, "z"].eq(-0.1).all()
    own = scores[(scores.segment == "P03") & scores.year.isin([2027, 2028, 2029])].set_index(
        ["model", "country", "scenario", "year"])["z"]
    carved = sector_z.set_index(["model", "country", "scenario", "year"])["z"]
    assert (carved.loc[[LGD, PREPAYMENT]] == own.loc[[LGD, PREPAYMENT]]).all(), "LGD and prepayment are P03's own"
    report = pd.read_csv(ctx.reports_dir / "analysis_template_replica.csv")
    assert "P03_SECTOR" in set(report.segment)
    assert "P07" in set(pd.read_csv(ctx.reports_dir / "impairment.csv").portfolio)
    elsewhere = builders.model("p07.test_pd", PD, drivers={"sector_gva": {"mean": 0, "sd": 1, "beta": 1}})
    doc["segments"]["P03_SECTOR"]["pd_model"] = elsewhere
    _, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "p07.yaml", doc)),
                          tmp_path / "runs")
    assert manifest["status"] == "BLOCKED" and manifest["blocked"]["code"] == Block.UNKNOWN_MODEL


@pytest.mark.req("DAT-02", "OPS-01")
@pytest.mark.parametrize("pointer", ["ttc_pd_matrix.parquet", "matrices/../facilities.parquet", "matrices/P99.parquet"])
def test_a_matrix_the_input_set_does_not_hold_blocks(mini, tmp_path, pointer):
    """A segment's ttc_matrix must name one of the set's own matrix files, listed in its manifest."""
    inputs = builders.write(mini, tmp_path / "in")
    import json

    import yaml
    doc = yaml.safe_load((inputs / "parameter_set.yaml").read_text(encoding="utf-8"))
    doc["portfolios"]["P01"]["segments"]["P01"]["ttc_matrix"] = pointer
    (inputs / "parameter_set.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    from stress import ingest
    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["parameter_set.yaml"]["sha256"] = ingest._hash(inputs / "parameter_set.yaml")
    manifest["input_set_hash"] = ingest.input_set_hash({k: v["sha256"] for k, v in manifest["files"].items()})
    (inputs / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (inputs / "approval.json").unlink()  # it names the old hash
    inputs = inputs.rename(inputs.with_name(manifest["input_set_hash"][:16]))  # R1 reads the name
    _, result = builders.run(inputs, tmp_path / "runs")
    assert result["status"] == "BLOCKED"
    assert (result["blocked"]["step"], result["blocked"]["code"]) == ("R2", Block.UNREADABLE_FILE)


@pytest.mark.req("DAT-02", "OPS-01")
@pytest.mark.parametrize("name", ["../outside.parquet", "C:/Windows/win.ini", "C:outside.parquet", "D:x",
                                  "/etc/hosts", "\\\\server\\share\\x", "matrices\\P01.parquet",
                                  "matrices/./P01.parquet", ""])
def test_a_manifest_naming_a_file_outside_the_set_blocks(mini, tmp_path, name):
    import json
    from types import SimpleNamespace

    from stress import ingest
    inputs = builders.write(mini, tmp_path / "in")
    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][name] = {"sha256": "x", "rows": 0}
    with pytest.raises(BlockingError) as caught:
        ingest.check_hashes(SimpleNamespace(input_dir=inputs, input_set_hash=manifest["input_set_hash"]), manifest)
    assert caught.value.code == Block.UNREADABLE_FILE


@pytest.mark.req("OPS-01", "DAT-03")
@pytest.mark.parametrize("pointer", ["../outside.parquet", "matrices/../facilities.parquet", "C:/x.parquet",
                                     "matrices/sub/P01.parquet"])
def test_packaging_refuses_a_matrix_outside_matrices(mini, tmp_path, pointer):
    builders.settings(mini, "P01")["ttc_matrix"] = pointer
    with pytest.raises(ValueError, match="directly under matrices/"):
        builders.write(mini, tmp_path / "in")
