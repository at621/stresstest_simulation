"""R10: the adverse result beside published figures. The sheet shows a difference and judges nothing."""

from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from foundation.synth.analysis import BENCHMARKS, build
from stress import cli
from stress.contracts.errors import BlockingError
from stress.contracts.run import RunConfig
from stress.report.assessment import plausibility_sheet
from tests import builders

YEARS = [2027, 2028]


def tables():
    impairment = pd.DataFrame({
        "scenario": "adverse", "portfolio": ["Total", "Total", "P04", "P04"], "year": [2027, 2028, 2027, 2028],
        "charge_total": [60.0, 40.0, 3.0, 7.0], "cumulative_charge": [60.0, 100.0, 3.0, 10.0]})
    stages = pd.DataFrame({
        "scenario": "adverse", "year": [2026, 2026, 2026, 2028, 2028, 2028], "portfolio": ["P04", "P04", "P01"] * 2,
        "stage": [1, 3, 2, 1, 3, 2], "gca": [90.0, 10.0, 900.0, 60.0, 40.0, 900.0]})
    values = pd.DataFrame({"scenario": "adverse", "variable": ["gdp_growth", "gdp_growth", "unemployment"],
                           "year": [2027, 2028, 2028], "value": [-0.1, -0.1, 0.09]})
    meta = {"starting_values": [{"variable": "unemployment", "value": 6.0, "unit": "percent"}]}
    indices = pd.DataFrame({"scenario": "adverse", "country": "DE", "variable": "cre_price_index", "year": YEARS,
                            "annual_change": [-0.2, -0.1], "index": [80.0, 72.0]})
    return impairment, stages, SimpleNamespace(scenario_values=values, scenario_meta=meta), indices


def sheet(*rows) -> pd.DataFrame:
    spec = {"version": "t", "source": "t", "sources": {"s": "a publication"}, "rows": list(rows)}
    impairment, stages, loaded, indices = tables()
    return plausibility_sheet(spec, impairment, stages, loaded, indices, YEARS).set_index(["measure", "scope"])


def row(measure, scope="Total", published=0.5):
    return {"measure": measure, "scope": scope, "published": published, "source": "s"}


@pytest.mark.req("RPT-05")
def test_measures_come_from_sums_and_the_multiple_is_shown():
    out = sheet(row("credit_loss_rate"), row("credit_loss_rate", "P04", 0.05), row("first_year_loss_share"),
                row("s3_share_start", "P04"), row("s3_share_end", "P04"), row("s2_share_end"),
                row("gdp_cumulative", "Scenario"), row("unemployment_rise", "Scenario"),
                row("cre_price_cumulative", "Scenario"))
    assert out.loc[("credit_loss_rate", "Total"), "engine"] == pytest.approx(100.0 / 1000.0)
    assert out.loc[("credit_loss_rate", "P04"), "engine"] == pytest.approx(10.0 / 100.0)
    assert out.loc[("credit_loss_rate", "P04"), "multiple"] == pytest.approx(2.0)
    assert out.loc[("first_year_loss_share", "Total"), "engine"] == pytest.approx(0.6)
    assert out.loc[("s3_share_start", "P04"), "engine"] == pytest.approx(0.1)
    assert out.loc[("s3_share_end", "P04"), "engine"] == pytest.approx(0.4)
    assert out.loc[("s2_share_end", "Total"), "engine"] == pytest.approx(0.9)
    assert out.loc[("gdp_cumulative", "Scenario"), "engine"] == pytest.approx(0.9 * 0.9 - 1)
    assert out.loc[("unemployment_rise", "Scenario"), "engine"] == pytest.approx(0.03)
    assert out.loc[("cre_price_cumulative", "Scenario"), "engine"] == pytest.approx(0.8 * 0.9 - 1)
    assert (out["basis"] == "NOT_LIKE_FOR_LIKE").all() and (out["source"] == "a publication").all()


@pytest.mark.req("RPT-05")
def test_an_unknown_measure_or_source_blocks():
    with pytest.raises(BlockingError, match="unknown plausibility measure"):
        sheet(row("happiness"))
    with pytest.raises(BlockingError, match="no source"):
        sheet({**row("credit_loss_rate"), "source": "unnamed"})


@pytest.mark.req("RPT-05")
def test_a_missing_path_blocks_rather_than_gives_a_zero_change():
    impairment, stages, loaded, indices = tables()
    empty = SimpleNamespace(scenario_values=loaded.scenario_values.iloc[:0], scenario_meta=loaded.scenario_meta)
    spec = {"version": "t", "source": "t", "sources": {"s": "a publication"}, "rows": [row("gdp_cumulative", "Scenario")]}
    with pytest.raises(BlockingError, match="no adverse path"):
        plausibility_sheet(spec, impairment, stages, empty, indices, YEARS)


@pytest.mark.req("RPT-05")
def test_every_published_row_has_a_named_source_and_a_value():
    doc = yaml.safe_load(BENCHMARKS.read_text(encoding="utf-8"))
    assert {r["source"] for r in doc["rows"]} <= set(doc["sources"])
    assert all(isinstance(r["published"], float) for r in doc["rows"])


@pytest.mark.req("RPT-05")
def test_the_example_package_writes_the_sheet(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    package = tmp_path / "analysis.yaml"
    package.write_text(yaml.safe_dump(build(inputs)), encoding="utf-8")
    ctx, manifest = cli.execute(RunConfig(str(inputs), ("baseline", "adverse"), "core", analysis=str(package)),
                                tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    out = builders.report(ctx, "analysis_plausibility.csv")
    assert out["engine"].notna().all() and len(out) == len(yaml.safe_load(BENCHMARKS.read_text(encoding="utf-8"))["rows"])
