"""Independent macro models retain one score and explicit data dependencies."""

import pytest

from stress.contracts.errors import BlockingError
from stress.scenario.models import evaluate_model


@pytest.mark.req("MOD-01", "SCN-03", "SCN-08")
def test_polynomial_model_uses_lagged_driver_and_records_terms():
    model = {"kind": "polynomial", "version": "test", "source": "synthetic", "intercept": 0.1,
             "terms": {"gdp_lag": {"variable": "gdp", "lag": 1, "power": 2,
                                   "mean": 0.0, "sd": 1.0, "beta": -0.5}}}
    index = {("crisis", "gdp", "DE", 2026): (-0.2, "supplied"),
             ("crisis", "gdp", "DE", 2027): (0.8, "supplied")}
    value, terms = evaluate_model(model, index, "crisis", "DE", 2027)
    assert value == pytest.approx(model["intercept"] + model["terms"]["gdp_lag"]["beta"] * (-0.2) ** 2)
    assert sum(t[-1] for t in terms) == pytest.approx(value)
    del index[("crisis", "gdp", "DE", 2026)]
    with pytest.raises(BlockingError, match="missing"):
        evaluate_model(model, index, "crisis", "DE", 2027)


@pytest.mark.req("MOD-01", "SCN-08")
def test_external_score_requires_exact_coverage_and_unique_keys():
    row = {"scenario": "crisis", "country": "DE", "year": 2027, "z": -1.5}
    model = {"kind": "supplied", "source": "external synthetic model", "version": "v1", "values": [row]}
    value, terms = evaluate_model(model, {}, "crisis", "DE", 2027)
    assert value == row["z"] and sum(t[-1] for t in terms) == value
    with pytest.raises(BlockingError, match="missing"):
        evaluate_model(model, {}, "crisis", "DE", 2028)
    model["values"].append(row.copy())
    with pytest.raises(BlockingError, match="duplicate"):
        evaluate_model(model, {}, "crisis", "DE", 2027)


@pytest.mark.req("MOD-01")
@pytest.mark.parametrize("kind", ["unknown", "polynomial", "supplied"])
def test_incomplete_model_blocks(kind):
    with pytest.raises(BlockingError):
        evaluate_model({"kind": kind}, {}, "baseline", "DE", 2027)


@pytest.mark.req("SCN-08", "MOD-01")
def test_linear_model_cannot_return_an_infinite_score():
    model = {"kind": "linear", "version": "test", "source": "synthetic",
             "drivers": {"driver": {"beta": 1e308, "mean": 0.0, "sd": 1.0}}}
    with pytest.raises(BlockingError, match="non-finite"):
        evaluate_model(model, {("baseline", "driver", "DE", 2027): (10.0, "supplied")},
                       "baseline", "DE", 2027)


@pytest.mark.req("MOD-01", "MOD-06", "SCN-03", "SCN-08")
def test_selected_model_changes_only_its_segment_in_a_sealed_run(mini, tmp_path):
    import pandas as pd

    from stress.cli import execute
    from stress.contracts.run import RunConfig
    from tests import builders
    from tests.unit.test_specification import specification, write_spec

    inputs = builders.write(mini, tmp_path / "inputs")
    reference, result = builders.run(inputs, tmp_path / "runs")
    assert result["status"] == "SYNTHETIC"
    driver = mini["parameter_set"]["segments"]["P02"]["z_drivers"]["gdp_growth"]
    doc = specification(inputs, models={"consumer_nonlinear": {
        "kind": "polynomial", "source": "synthetic test", "version": "v1",
        "terms": {"gdp_squared": {"variable": "gdp_growth", "power": 2, "lag": 1, **driver}},
    }}, segments={"P02": {"macro_model": "consumer_nonlinear"}})
    doc["additional_values"] = [{"scenario": "*", "country": "*", "variable": "gdp_growth",
                                 "year": 2026, "value": driver["mean"], "unit": "decimal", "value_type": "growth"}]
    doc["terminal_policies"] = {"adverse": {"method": "flat"}}
    config = RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc))
    current, result = execute(config, tmp_path / "runs")
    assert result["status"] == "SYNTHETIC", result.get("blocked")
    old = builders.result(reference, "pit_matrices.parquet")
    new = builders.result(current, "pit_matrices.parquet")
    within = old.year.isin(mini["parameter_set"]["horizon"]["projection_years"])
    mask = old.segment.ne("P02") & within
    pd.testing.assert_frame_equal(old.loc[mask].reset_index(drop=True), new.loc[mask].reset_index(drop=True))
    assert not old.loc[old.segment.eq("P02"), "probability"].equals(
        new.loc[new.segment.eq("P02"), "probability"])
    scores = builders.result(current, "drivers.parquet")
    tail = scores[(scores.scenario == "adverse") & (scores.year >= 2029)]
    assert tail.groupby(["segment", "country"]).z.nunique().eq(1).all()


@pytest.mark.req("SCN-03", "SCN-08", "SCP-01")
def test_sector_assignment_uses_supplied_sector_driver(mini, tmp_path):
    import pandas as pd

    from stress.cli import execute
    from stress.contracts.run import RunConfig
    from tests import builders
    from tests.unit.test_specification import specification, write_spec

    inputs = builders.write(mini, tmp_path / "inputs")
    borrower = mini["facilities"].loc[mini["facilities"].portfolio.eq("P03"), "obligor_id"].iloc[0]
    nace = mini["obligors"].set_index("obligor_id").loc[borrower, "nace_code"]
    doc = specification(inputs, models={"sector": {
        "kind": "linear", "source": "synthetic sector", "version": "v1",
        "drivers": {"sector_gva": {"mean": 0, "sd": 1, "beta": 1}},
    }}, segments={"P03_SECTOR": {"inherits": "P03", "macro_model": "sector", "template_class": "Sector loans"}},
        assignments=[{"where": {"portfolio": "P03", "nace_code": nace}, "segment": "P03_SECTOR"}],
        additional_values=[{"scenario": "*", "country": "*", "variable": "sector_gva", "year": year,
                            "value": -0.1, "unit": "decimal", "value_type": "growth"}
                           for year in (2027, 2028, 2029)])
    ctx, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                            tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    scores = builders.result(ctx, "drivers.parquet")
    sector = scores[(scores.segment == "P03_SECTOR") & scores.year.isin([2027, 2028, 2029])]
    assert len(sector) > 0 and sector.z.eq(-0.1).all()
    report = pd.read_csv(ctx.reports_dir / "analysis_template_replica.csv")
    assert "P03_SECTOR" in set(report.segment)
