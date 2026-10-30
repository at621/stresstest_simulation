"""AT-28, kernel-only (R8 takes a part year pro rata, by owner decision A7): stub PD (PD-06)."""

import pytest

from stress.params.pd import stub_pd
from tests.support import assert_close, oracle


@pytest.mark.at("AT-28")
def test_half_year_stub():
    case = oracle("AT-28")
    value = float(stub_pd(case["input"]["annual_pd"], case["input"]["fraction"]))
    assert_close(value, case["expected"]["stub_pd"], case["tolerance"], "stub PD")
