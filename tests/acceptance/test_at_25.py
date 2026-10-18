"""AT-25: PD-03 probability arithmetic from conditional PDs."""

import numpy as np
import pytest

from stress.params.pd import check_curve, curve_from_conditional
from tests.support import assert_close, oracle, tolerance


@pytest.mark.at("AT-25")
def test_marginal_cumulative_and_survival():
    case = oracle("AT-25")
    curve = curve_from_conditional(case["input"]["conditional_pd"])
    e = case["expected"]
    assert_close(curve.m, e["marginal_pd"], case["tolerance"], "marginal")
    assert_close(curve.f, e["cumulative_pd"], case["tolerance"], "cumulative")
    assert_close(curve.s[-1], e["terminal_survival"], case["tolerance"], "survival")
    check_curve(curve, tolerance("probability_identity")["abs"], "test", "AT-25")
    summed = np.cumsum(case["input"]["conditional_pd"])
    assert abs(summed[-1] - curve.f[-1]) > case["tolerance"]["abs"], case["wrong_answers"][0]["why"]
