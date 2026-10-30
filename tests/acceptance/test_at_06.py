"""AT-06: end-2029 S1 loss-rate interpolation for the 2030 bucket (ECL-05, ECL-10)."""

import pytest

from stress.contracts.tables import METHOD_S1_TERMINAL
from stress.ecl.kernels import interpolated_loss_rate
from stress.scenario.kernels import adverse_weight
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-06")
def test_loss_rate_is_interpolated_as_a_product(reference_runs):
    case = oracle("AT-06")
    i, e = case["input"], case["expected"]
    reversion_years = len(oracle("AT-52")["expected"]["adverse_weights"])
    weight = adverse_weight(e["bucket_year"], i["valuation_year"], reversion_years)
    assert_close(weight, e["weights"]["adverse"], case["tolerance"], "weight")
    value = interpolated_loss_rate(i["adverse"]["pd"], i["adverse"]["lgd"],
                                   i["baseline"]["pd"], i["baseline"]["lgd"], weight)
    assert_close(i["adverse"]["pd"] * i["adverse"]["lgd"], e["adverse_loss_rate"], case["tolerance"])
    assert_close(i["baseline"]["pd"] * i["baseline"]["lgd"], e["baseline_loss_rate"],
                 case["tolerance"])
    assert_close(value, e["interpolated_loss_rate"], case["tolerance"], "interpolated loss rate")
    # The same case through the whole pipeline: R4 gives the weight, R6 each scenario's end-2029
    # PD and LGD, and R8 the S1 provision of the facility's slice.
    ctx, _ = reference_runs["core"]
    fid = reference_runs["ids"]["AT-06"]
    segment = builders.REFERENCE_SEGMENTS["AT-06"]
    year = i["valuation_year"]
    z = builders.result(ctx, "drivers.parquet")
    z = z[(z["segment"] == segment) & (z["scenario"] == "adverse") & (z["year"] == e["bucket_year"])]
    assert len(z) > 0
    for value in z["adverse_weight"]:
        assert_close(value, e["weights"]["adverse"], case["tolerance"], "run weight")
    prov = builders.result(ctx, "provisions.parquet")
    mine = prov[(prov["facility_id"] == fid) & (prov["year"] == year) & (prov["method"] == METHOD_S1_TERMINAL)]
    keys = ["scenario", "year", "facility_id", "slice"]
    rows = mine.merge(builders.result(ctx, "slices.parquet")[[*keys, "gca"]], on=keys)
    assert sorted(rows["scenario"]) == ["adverse", "baseline"]
    curves = builders.result(ctx, "pd_curves.parquet")
    lgd = builders.result(ctx, "lgd_of_year.parquet")
    for scenario in ("adverse", "baseline"):
        pd_run = curves[(curves["segment"] == segment) & (curves["scenario"] == scenario)
                        & (curves["valuation_year"] == year - 1) & (curves["cohort"] == rows["slice"].iloc[0])
                        & (curves["default_bucket"] == 1)]
        lgd_run = lgd[(lgd["facility_id"] == fid) & (lgd["scenario"] == scenario) & (lgd["year"] == year)]
        assert_close(pd_run["m"].iloc[0], i[scenario]["pd"], case["tolerance"], f"run {scenario} PD")
        assert_close(lgd_run["lgd"].iloc[0], i[scenario]["lgd"], case["tolerance"], f"run {scenario} LGD")
    rates = (rows["raw_on"] / rows["gca"]).set_axis(rows["scenario"])
    assert_close(rates["adverse"], e["interpolated_loss_rate"], case["tolerance"], "run interpolated rate")
    assert_close(rates["baseline"], e["baseline_loss_rate"], case["tolerance"], "run baseline rate")
