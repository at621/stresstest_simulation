"""AT-10: separate methodological REA floors for IRB and STA, also through the capital bridge (CAP-03)."""

import pytest

from stress.capital import methodological_floor
from stress.capital.assessment import capital_bridge
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-10")
def test_floors_apply_per_approach():
    case = oracle("AT-10")
    i = case["input"]
    result = methodological_floor(i["starting"], i["raw"])
    assert_close(result["credit_contribution"], case["expected"]["credit_contribution"],
                 case["tolerance"], "credit contribution")
    # The same case through the step: one unit of exposure per approach, weighted to the oracle's REA.
    spec, slices, portfolio, charges = builders.capital_case(i["starting"], i["raw"])
    bridge, _ = capital_bridge(spec, slices, portfolio, charges)
    assert_close(bridge["floored_credit_rea"].iloc[0], case["expected"]["credit_contribution"],
                 case["tolerance"], "bridge credit contribution")
