"""AT-37: accrued interest already in GCA is counted once (EAD-01, EAD-10)."""

import pytest

from stress.cashflows.kernels import contractual_schedule, drawn_measure
from tests import builders
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-37")
def test_accrued_interest_counted_once(reference_runs):
    case = oracle("AT-37")
    i = case["input"]
    d = drawn_measure(i["principal"], i["accrued_interest"], i["accrued_in_gca"], i["gca"])
    assert_close(d, case["expected"]["ead_drawn"], case["tolerance"], "drawn EAD")
    assert not within(d, case["wrong_answers"][0]["value"], case["tolerance"])
    # The schedule starts from D, so its first balance carries the interest once as well.
    rate = oracle("AT-42")["input"]["eir"]
    schedule = contractual_schedule(d, rate, 1.0, "bullet")
    assert_close(schedule.balance[0], case["expected"]["ead_drawn"], case["tolerance"])
    # The same case through the whole pipeline: R5's first balance and R6's drawn EAD, at each valuation.
    ctx, _ = reference_runs["core"]
    fid = reference_runs["ids"]["AT-37"]
    schedule = builders.result(ctx, "cf_schedule.parquet")
    params = builders.result(ctx, "parameters.parquet")
    balances = schedule[(schedule["facility_id"] == fid) & (schedule["period"] == 1)]["opening_balance"]
    drawn = params[(params["facility_id"] == fid) & (params["default_bucket"] == 1)]["ead_drawn"]
    assert len(balances) and len(drawn)
    for value in (*balances, *drawn):
        assert_close(value, case["expected"]["ead_drawn"], case["tolerance"], "run drawn EAD")
        assert not within(value, case["wrong_answers"][0]["value"], case["tolerance"])
