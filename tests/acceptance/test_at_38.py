"""AT-38: accounting and regulatory EAD with an explicit CCF bridge (EAD-07, MOD-02)."""

import pytest

from stress.params.ead import regulatory_bridge
from tests.support import assert_close, oracle


@pytest.mark.at("AT-38")
def test_ccf_bridge():
    case = oracle("AT-38")
    i, e = case["input"], case["expected"]
    result = regulatory_bridge(i["drawn"], i["undrawn"], i["accounting_ccf"], i["regulatory_ccf"],
                               i["other_adjustments"])
    assert_close(result["accounting_ead"], e["accounting_ead"], case["tolerance"])
    assert_close(result["regulatory_ead"], e["regulatory_ead"], case["tolerance"])
    assert_close(result["ccf_bridge"], e["ccf_bridge"], case["tolerance"])
    sequential = i["drawn"] + i["undrawn"] * i["accounting_ccf"] * i["regulatory_ccf"]
    assert abs(sequential - result["regulatory_ead"]) > case["tolerance"]["abs"], (
        case["wrong_answers"][0]["why"])
