"""AT-08: converted total exposure with an illustrative CCF (EAD-02)."""

import pytest

from stress.params.ead import ead
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-08")
def test_converted_total_exposure():
    case = oracle("AT-08")
    i = case["input"]
    value = float(ead(i["drawn"], i["undrawn"], i["ccf"]).total)
    assert_close(value, case["expected"]["ead_total"], case["tolerance"], "EAD")
    for wrong in case["wrong_answers"]:
        assert not within(value, wrong["value"], case["tolerance"]), wrong["why"]
