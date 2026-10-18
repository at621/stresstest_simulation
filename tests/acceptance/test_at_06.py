"""AT-06: end-2029 S1 loss-rate interpolation for the 2030 bucket (ECL-05, ECL-10)."""

import pytest

from stress.ecl.kernels import interpolated_loss_rate
from stress.scenario.kernels import adverse_weight
from tests.support import assert_close, oracle


@pytest.mark.at("AT-06")
def test_loss_rate_is_interpolated_as_a_product():
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
