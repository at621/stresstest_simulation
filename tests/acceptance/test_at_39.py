"""AT-39: S1 one-year and S2 lifetime ECL from the AT-25 curve (ECL-01, ECL-02)."""

import numpy as np
import pytest

from stress.ecl.kernels import ecl
from stress.params.pd import curve_from_conditional
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-39")
def test_one_year_and_lifetime_ecl():
    case = oracle("AT-39")
    i, e = case["input"], case["expected"]
    curve = curve_from_conditional(oracle(i["pd_curve"])["input"]["conditional_pd"])
    years = int(i["remaining_life_years"])
    ead = np.full(years, i["ead"])
    lgd = np.full(years, i["lgd"])
    df = (1 + i["eir"]) ** -np.arange(1, years + 1)
    s1 = ecl(curve.m[:1], ead[:1], lgd[:1], df[:1])
    s2 = ecl(curve.m, ead, lgd, df)
    assert_close(s1, e["s1_ecl"], case["tolerance"], "S1")
    assert_close(s2, e["s2_ecl"], case["tolerance"], "S2")
    assert round(s2, 2) == e["s2_ecl_displayed"]
    summed = float(np.sum(curve.q * ead * lgd * df))
    assert within(summed, case["wrong_answers"][0]["value"], case["tolerance"])
    assert not within(s2, case["wrong_answers"][0]["value"], case["tolerance"])
