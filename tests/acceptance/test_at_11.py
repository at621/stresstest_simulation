"""AT-11: bank-wide output-floor comparison, also through the capital bridge (CAP-04)."""

import pytest

from stress.capital import output_floor
from stress.capital.assessment import capital_bridge
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-11")
def test_output_floor_comparison():
    case = oracle("AT-11")
    i = case["input"]
    result = output_floor(i["utrea"], i["strea"], i["factor"])
    assert_close(result["floored_strea"], case["expected"]["floored_strea"], case["tolerance"])
    assert_close(result["result"], case["expected"]["result"], case["tolerance"])
    # The same case through the step: UTREA and STREA come from one unit of exposure.
    weight = {"STA": i["utrea"]}
    spec, slices, portfolio, charges = builders.capital_case(weight, weight, i["strea"], i["factor"])
    bridge, _ = capital_bridge(spec, slices, portfolio, charges)
    assert_close(bridge["strea"].iloc[0], i["strea"], case["tolerance"], "bridge STREA")
    assert_close(bridge["total_rea"].iloc[0], case["expected"]["result"], case["tolerance"], "bridge result")
