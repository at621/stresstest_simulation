"""Paragraphs 562-564: insufficient NPE coverage, calculated per exposure from a supplied calendar."""

import numpy as np
import pandas as pd
import pytest
import yaml

from foundation.synth.analysis import build
from stress import cli
from stress.capital.npe import npe_backstop
from stress.contracts.errors import BlockingError
from stress.contracts.run import RunConfig
from stress.contracts.tables import SLICE_S3_ORIGINAL
from tests import builders

CALENDAR = {"version": "test", "source": "test", "scope_from": "2019-04-26", "scope_to": "2026-12-31", "calendar": [
    {"from_year": 1, "unsecured": 0.0, "secured": 0.0}, {"from_year": 3, "unsecured": 0.35, "secured": 0.0},
    {"from_year": 4, "unsecured": 1.0, "secured": 0.25}]}
PORTFOLIO = pd.DataFrame({"facility_id": list("ABCDE"), "portfolio": ["P03", "P03", "P01", "P03", "P03"],
                          "country": "DE"})
FACILITIES = pd.DataFrame({
    "facility_id": list("ABCDE"),
    "origination_date": ["2022-01-01", "2022-01-01", "2020-01-01", "2018-01-01", "2018-01-01"],
    "default_date": [None, None, "2023-05-16", None, None],
    "ltv": [np.nan, np.nan, 0.5, np.nan, np.nan],
    "collateral_type": [None, None, "residential_property", None, None]})
INDICES = pd.DataFrame({"scenario": "adverse", "country": "DE", "variable": "residential_price_index",
                        "year": [2027, 2028, 2029], "annual_change": [-0.1, -0.1, 0.0], "index": [90.0, 81.0, 81.0]})


def s3(facility, allowance, generation=0, name="S3_2027_from_S1", entry=2027.0, gca=100.0):
    return {"scenario": "adverse", "year": 2029, "facility_id": facility, "slice": name, "stage": 3, "gca": gca,
            "entry_year": entry, "allowance_on": allowance, "generation": generation}


def book() -> pd.DataFrame:
    return pd.DataFrame([s3("A", 20.0), s3("B", 50.0), s3("C", 10.0, name=SLICE_S3_ORIGINAL, entry=2026.0),
                         s3("D", 0.0), s3("E", 0.0, generation=1)])


@pytest.mark.req("CAP-09")
def test_shortfall_is_measured_per_exposure_and_an_excess_never_offsets_it():
    out = npe_backstop(CALENDAR, book(), PORTFOLIO, FACILITIES, INDICES).set_index("portfolio")
    p03 = out.loc["P03"]
    # A and B are in their third year: 35 each. E is a replacement, so it is in scope; D is not.
    assert p03["gca_in_scope"] == 300.0 and p03["minimum_coverage"] == pytest.approx(3 * 35.0)
    assert p03["capped_provisions"] == pytest.approx(20.0 + 35.0 + 0.0)
    assert p03["insufficient_coverage"] == pytest.approx(15.0 + 0.0 + 35.0)
    p01 = out.loc["P01"]
    # C defaulted in 2023, so 2029 is its seventh year; the fall in prices leaves it fully secured.
    assert p01["secured_part"] == pytest.approx(100.0) and p01["unsecured_part"] == 0.0
    assert p01["minimum_coverage"] == pytest.approx(25.0) and p01["insufficient_coverage"] == pytest.approx(15.0)
    assert out.loc["Total", "insufficient_coverage"] == pytest.approx(65.0)


@pytest.mark.req("CAP-09")
def test_collateral_follows_the_scenario_and_the_rest_is_unsecured():
    thin = FACILITIES.assign(ltv=[np.nan, np.nan, 0.9, np.nan, np.nan])
    out = npe_backstop(CALENDAR, book(), PORTFOLIO, thin, INDICES).set_index("portfolio")
    collateral = 100.0 / 0.9 * 0.81
    assert out.loc["P01", "secured_part"] == pytest.approx(collateral)
    assert out.loc["P01", "minimum_coverage"] == pytest.approx(collateral * 0.25 + (100.0 - collateral))


@pytest.mark.req("CAP-09")
@pytest.mark.parametrize("calendar, message", [
    ([{"from_year": 3, "unsecured": 0.35, "secured": 0.0}], "starting at year 1"),
    ([{"from_year": 1, "unsecured": 0.5, "secured": 0.0}, {"from_year": 2, "unsecured": 0.1, "secured": 0.0}], "fall"),
    ([{"from_year": 1, "unsecured": 0.5}], "secured"),
])
def test_a_bad_calendar_blocks(calendar, message):
    with pytest.raises(BlockingError, match=message):
        npe_backstop({**CALENDAR, "calendar": calendar}, book(), PORTFOLIO, FACILITIES, INDICES)


@pytest.mark.req("CAP-09")
def test_missing_dates_block_rather_than_leave_scope():
    no_default = FACILITIES.assign(default_date=None)
    with pytest.raises(BlockingError, match="default date"):
        npe_backstop(CALENDAR, book(), PORTFOLIO, no_default, INDICES)
    no_origination = FACILITIES.assign(origination_date=None)
    with pytest.raises(BlockingError, match="origination date"):
        npe_backstop(CALENDAR, book(), PORTFOLIO, no_origination, INDICES)


@pytest.mark.req("CAP-09")
def test_the_example_package_reports_a_shortfall_beside_the_supplied_deduction(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    package = tmp_path / "analysis.yaml"
    doc = build(inputs)
    package.write_text(yaml.safe_dump(doc), encoding="utf-8")
    ctx, manifest = cli.execute(RunConfig(str(inputs), ("baseline", "adverse"), "core", analysis=str(package)),
                                tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    out = pd.read_parquet(ctx.results_dir / "analysis_npe_backstop.parquet")
    total = out[out["portfolio"] == "Total"]
    assert set(total["scenario"]) == {"baseline", "adverse"}
    assert (total["insufficient_coverage"] >= 0).all() and (total["basis"] == "SUPPLIED_CALENDAR_NOT_APPROVED").all()
    capital = pd.read_parquet(ctx.results_dir / "analysis_capital.parquet")
    assert capital["npl_deduction_change"].eq(0.0).all(), "the supplied input stays what it was"
    assert doc["npe_backstop"]["calendar"][0]["from_year"] == 1
