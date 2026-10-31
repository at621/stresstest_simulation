"""R10: LTV under the scenario's prices, average maturity and default-loss-weighted LGD."""

import numpy as np
import pandas as pd
import pytest

from stress.contracts.errors import BlockingError
from stress.params.assessment import default_weighted_lgd
from stress.report.assessment import average_maturity, stressed_ltv
from tests import builders

PORTFOLIO = pd.DataFrame({"facility_id": ["A", "B", "C"], "portfolio": ["P01", "P01", "P02"],
                          "country": ["DE", "DE", "DE"], "segment": ["P01", "P01", "P02"],
                          "gca": [100.0, 300.0, 50.0], "undrawn": [0.0, 0.0, 10.0]})
FACILITIES = pd.DataFrame({"facility_id": ["A", "B", "C"], "ltv": [0.8, 0.96, np.nan],
                           "ltv_status": ["supplied", "supplied", "not_applicable"],
                           "collateral_type": ["residential_property", "residential_property", None]})
INDICES = pd.DataFrame({"scenario": ["adverse"] * 2, "country": ["DE"] * 2,
                        "variable": ["residential_price_index"] * 2, "year": [2027, 2028],
                        "annual_change": [-0.1, -0.1], "index": [90.0, 81.0]})


def slices(year: int, stage: int = 1) -> pd.DataFrame:
    return pd.DataFrame({"scenario": "adverse", "year": year, "facility_id": ["A", "B", "C"],
                         "stage": stage, "gca": [100.0, 300.0, 50.0]})


@pytest.mark.req("RPT-05")
def test_ltv_follows_the_price_index_and_keeps_its_numerator_and_denominator():
    book = pd.concat([slices(2026), slices(2027), slices(2028)], ignore_index=True)
    out = stressed_ltv(PORTFOLIO, FACILITIES, book, INDICES).set_index(["year", "stage"])
    assert "P02" not in set(out["portfolio"]), "a book without real-estate collateral is not reported"
    opening = out.loc[(2026, 1)]
    assert opening["gca"] == 400.0 and opening["average_ltv"] == pytest.approx((80 + 288) / 400)
    assert opening["gca_above_100"] == 0.0
    # 0.96 / 0.9 passes 100% in 2027 and 0.8 / 0.81 does not reach it in 2028.
    assert out.loc[(2027, 1), "share_above_100"] == pytest.approx(0.75)
    assert out.loc[(2028, 1), "ltv_numerator"] == pytest.approx((100 * 0.8 + 300 * 0.96) / 0.81)
    assert out.loc[(2028, 1), "share_above_100"] == pytest.approx(0.75)
    assert out.loc[(2028, "all"), "gca"] == 400.0


@pytest.mark.req("RPT-05")
def test_ltv_blocks_rather_than_guess_an_index():
    unknown = FACILITIES.assign(collateral_type=["ship", "ship", None])
    with pytest.raises(BlockingError, match="collateral type"):
        stressed_ltv(PORTFOLIO, unknown, slices(2027), INDICES)
    with pytest.raises(BlockingError, match="price index"):
        stressed_ltv(PORTFOLIO, FACILITIES, slices(2029), INDICES)


@pytest.mark.req("RPT-05")
@pytest.mark.parametrize("change", [{"ltv": [0.8, np.nan, np.nan]},
                                    {"ltv": [0.8, 0.96, np.nan], "ltv_status": ["supplied", "supplied", "missing"]}])
def test_a_missing_ltv_blocks_rather_than_reads_as_unsecured(change):
    with pytest.raises(BlockingError, match="no LTV"):
        stressed_ltv(PORTFOLIO, FACILITIES.assign(**change), slices(2027), INDICES)


@pytest.mark.req("RPT-05")
def test_average_maturity_weights_performing_exposure_only():
    book = pd.concat([slices(2027), slices(2027, 3).iloc[:1].assign(gca=1000.0)], ignore_index=True)
    schedule = pd.DataFrame({"facility_id": ["A", "A", "B", "C"], "valuation_year": [2027] * 4,
                             "period": [1, 2, 1, 1], "remaining_maturity": [2.0, 2.0, 4.0, 1.0]})
    out = average_maturity(PORTFOLIO, book, schedule).set_index(["portfolio", "stage"])
    assert out.loc[("P01", 1), "maturity_numerator"] == pytest.approx(100 * 2 + 300 * 4)
    assert out.loc[("P01", 1), "average_maturity"] == pytest.approx(3.5)
    assert out.loc[("P01", "all"), "gca"] == 400.0, "S3 has no maturity in this measure"
    with pytest.raises(BlockingError, match="maturity"):
        average_maturity(PORTFOLIO, book, schedule[schedule["facility_id"] != "B"])


def weighted_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    book = pd.DataFrame({"scenario": "adverse", "year": 2026, "facility_id": ["A", "A", "B", "C"],
                         "stage": [1, 2, 1, 3], "grade": ["G1", "G2", "G1", "D"],
                         "gca": [60.0, 40.0, 300.0, 50.0], "undrawn": [0.0, 0.0, 0.0, 10.0]})
    facility = pd.DataFrame({"facility_id": ["A", "B"], "scenario": "adverse", "valuation_year": 2026,
                             "default_bucket": 1, "fraction": [1.0, 0.5], "ead_drawn": [100.0, 300.0],
                             "ead_undrawn": [0.0, 0.0], "lgd": [0.2, 0.4]})
    curves = pd.DataFrame({"segment": "P01", "country": "DE", "scenario": "adverse", "valuation_year": 2026,
                           "default_bucket": 1, "cohort": ["G1", "G2"], "m": [0.01, 0.1]})
    return book, facility, curves


@pytest.mark.req("RPT-06")
def test_default_loss_weighted_lgd_uses_the_part_of_the_year_the_maturity_covers():
    out = default_weighted_lgd(*weighted_inputs(), PORTFOLIO).set_index("stage")
    weights = (0.01 * 60, 0.01 * 0.5 * 300)  # facility A's S1 share, facility B's half-year stub
    assert out.loc[1, "numerator"] == pytest.approx(weights[0] * 0.2 + weights[1] * 0.4)
    assert out.loc[1, "denominator"] == pytest.approx(sum(weights))
    assert out.loc[1, "loss_weighted_lgd"] == pytest.approx(out.loc[1, "numerator"] / out.loc[1, "denominator"])
    assert 3 not in out.index, "S3 is already in default"


@pytest.mark.req("RPT-06")
def test_default_loss_weighted_lgd_is_not_applicable_without_exposure():
    book, facility, curves = weighted_inputs()
    out = default_weighted_lgd(book, facility.assign(ead_drawn=0.0), curves, PORTFOLIO)
    assert out["denominator"].eq(0).all() and out["loss_weighted_lgd"].isna().all()


@pytest.mark.req("RPT-05", "RPT-06")
def test_reports_reach_a_full_run(core_run):
    ctx, _ = core_run
    ltv = builders.report(ctx, "analysis_ltv.csv")
    assert set(ltv["portfolio"]) == {"P01", "P04"}
    whole = ltv[(ltv["stage"].astype(str) == "all") & (ltv["portfolio"] == "P04")]
    path = whole[whole["scenario"] == "adverse"].sort_values("year")["average_ltv"].to_numpy()
    assert (np.diff(path) > 0).all(), "falling prices raise LTV every year"
    risen = whole[whole["scenario"] == "baseline"].sort_values("year")["average_ltv"].to_numpy()
    assert (np.diff(risen) < 0).all(), "rising prices lower LTV every year"
    maturity = builders.report(ctx, "analysis_maturity.csv")
    assert set(maturity["portfolio"]) >= {"P01", "P02", "P03", "P04", "P05", "P06"}
    assert maturity["average_maturity"].gt(0).all()
    lgd = builders.report(ctx, "analysis_loss_weighted_lgd.csv")
    assert lgd["loss_weighted_lgd"].between(0, 1).all() and lgd["denominator"].gt(0).all()
    one_year = builders.report(ctx, "portfolio_pd.csv")
    assert len(one_year) and one_year["denominator"].gt(0).all()
    assert np.allclose(one_year["one_year_pd"], one_year["numerator"] / one_year["denominator"], rtol=1e-6)
