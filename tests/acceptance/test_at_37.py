"""AT-37: accrued interest already in GCA is counted once (EAD-01, EAD-10)."""

import pytest

from stress.cashflows.kernels import contractual_schedule, drawn_measure
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-37")
def test_accrued_interest_counted_once():
    case = oracle("AT-37")
    i = case["input"]
    d = drawn_measure(i["principal"], i["accrued_interest"], i["accrued_in_gca"], i["gca"])
    assert_close(d, case["expected"]["ead_drawn"], case["tolerance"], "drawn EAD")
    assert not within(d, case["wrong_answers"][0]["value"], case["tolerance"])
    # The schedule starts from D, so its first balance carries the interest once as well.
    rate = oracle("AT-42")["input"]["eir"]
    schedule = contractual_schedule(d, rate, 1.0, "bullet")
    assert_close(schedule.balance[0], case["expected"]["ead_drawn"], case["tolerance"])
