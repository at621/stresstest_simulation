"""AT-39: S1 one-year and S2 lifetime ECL from the AT-25 curve (ECL-01, ECL-02)."""

import numpy as np
import pytest

from stress.contracts.tables import METHOD_S1, METHOD_S2
from stress.ecl.kernels import ecl
from stress.params.pd import curve_from_conditional
from tests import builders
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-39")
def test_one_year_and_lifetime_ecl(reference_runs):
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
    # The same case through the whole pipeline: R8 takes one bucket for S1 and the life for S2.
    ctx, _ = reference_runs["core"]
    prov = builders.result(ctx, "provisions.parquet")
    opening = prov[prov["year"] == prov["year"].min()]
    for name, method, expected in (("AT-39/S1", METHOD_S1, e["s1_ecl"]), ("AT-39/S2", METHOD_S2, e["s2_ecl"])):
        mine = opening[opening["facility_id"] == reference_runs["ids"][name]]
        assert len(mine) == 2  # baseline and adverse
        for row in mine.itertuples(index=False):
            assert row.method == method
            assert_close(row.allowance_on + row.provision_off, expected, case["tolerance"], f"run {name}")
    for value in opening.loc[opening["facility_id"] == reference_runs["ids"]["AT-39/S2"], "allowance_on"]:
        assert round(value, 2) == e["s2_ecl_displayed"]
        assert not within(value, case["wrong_answers"][0]["value"], case["tolerance"])
