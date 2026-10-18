"""AT-28: stub PD under the constant-hazard convention (PD-06)."""

import pytest

from stress.params.pd import stub_pd
from tests.support import assert_close, oracle


@pytest.mark.at("AT-28")
def test_half_year_stub():
    case = oracle("AT-28")
    value = float(stub_pd(case["input"]["annual_pd"], case["input"]["fraction"]))
    assert_close(value, case["expected"]["stub_pd"], case["tolerance"], "stub PD")
