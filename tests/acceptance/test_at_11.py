"""AT-11: bank-wide output-floor comparison (CAP-04)."""

import pytest

from stress.capital import output_floor
from tests.support import assert_close, oracle


@pytest.mark.at("AT-11")
def test_output_floor_comparison():
    case = oracle("AT-11")
    i = case["input"]
    result = output_floor(i["utrea"], i["strea"], i["factor"])
    assert_close(result["floored_strea"], case["expected"]["floored_strea"], case["tolerance"])
    assert_close(result["result"], case["expected"]["result"], case["tolerance"])
