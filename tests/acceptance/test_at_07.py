"""AT-07: the impairment charge is the change in the allowance stock (ACC-01)."""

import pytest

from stress.accounting.kernels import charge
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-07")
def test_charge_is_closing_minus_opening():
    case = oracle("AT-07")
    value = float(charge(case["input"]["opening"], case["input"]["closing"]))
    assert_close(value, case["expected"]["charge"], case["tolerance"], "charge")
    for wrong in case["wrong_answers"]:
        assert not within(value, wrong["value"], case["tolerance"]), wrong["why"]
