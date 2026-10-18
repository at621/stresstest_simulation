"""AT-36: a permitted drawdown transfer is not counted again as undrawn (EAD-06)."""

import pytest

from stress.params.ead import ead, permitted_transfer
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-36")
def test_transfer_moves_undrawn_to_drawn():
    case = oracle("AT-36")
    i, e = case["input"], case["expected"]
    result = permitted_transfer(i["drawn"], i["undrawn"], i["transfer"], i["ccf"])
    for field in ("drawn", "undrawn", "limit", "ead_total"):
        assert_close(result[field], e[field], case["tolerance"], field)
    counted_twice = float(ead(i["drawn"] + i["transfer"], i["undrawn"], i["ccf"]).total)
    assert not within(counted_twice, e["ead_total"], case["tolerance"]), case["wrong_answers"][0]["why"]
