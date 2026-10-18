"""AT-40: discount once, from default date to valuation date (ECL-08)."""

import pytest

from stress.cashflows.kernels import contractual_schedule
from stress.ecl.kernels import ecl
from tests.support import assert_close, oracle


@pytest.mark.at("AT-40")
def test_single_discounting():
    case = oracle("AT-40")
    i, e = case["input"], case["expected"]
    schedule = contractual_schedule(i["ead"], i["eir"], float(i["buckets"]), "bullet")
    assert_close(1 / schedule.discount_factor[0], e["discount_divisor"], case["tolerance"])
    value = ecl([i["marginal_pd"]], [i["ead"]], [i["lgd"]], schedule.discount_factor)
    assert_close(value, e["ecl"], case["tolerance"], "ECL")
    twice = value * schedule.discount_factor[0]
    assert abs(twice - e["ecl"]) > case["tolerance"]["abs"], case["wrong_answers"][0]["why"]
