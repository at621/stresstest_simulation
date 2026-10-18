"""AT-10: separate methodological REA floors for IRB and STA (CAP-03)."""

import pytest

from stress.capital import methodological_floor
from tests.support import assert_close, oracle


@pytest.mark.at("AT-10")
def test_floors_apply_per_approach():
    case = oracle("AT-10")
    result = methodological_floor(case["input"]["starting"], case["input"]["raw"])
    assert_close(result["credit_contribution"], case["expected"]["credit_contribution"],
                 case["tolerance"], "credit contribution")
