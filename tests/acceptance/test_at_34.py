"""AT-34: drawn/undrawn EAD and the on/off-balance ECL split (EAD-02, EAD-08)."""

import pytest

from stress.ecl.kernels import ecl_split
from stress.params.ead import ead
from tests.support import assert_close, oracle


@pytest.mark.at("AT-34")
def test_ead_and_ecl_split():
    case = oracle("AT-34")
    i, e = case["input"], case["expected"]
    result = ead(i["drawn"], i["undrawn"], i["ccf"])
    assert_close(result.drawn, e["ead_drawn"], case["tolerance"], "drawn")
    assert_close(result.undrawn, e["ead_undrawn"], case["tolerance"], "undrawn")
    assert_close(result.total, e["ead_total"], case["tolerance"], "total")
    on, off = ecl_split([i["pd"]], [result.drawn], [result.undrawn], [i["lgd"]],
                        [i["discount_factor"]])
    assert_close(on, e["ecl_on"], case["tolerance"], "on-balance")
    assert_close(off, e["ecl_off"], case["tolerance"], "off-balance")
    assert_close(on + off, e["ecl_total"], case["tolerance"], "total ECL")
