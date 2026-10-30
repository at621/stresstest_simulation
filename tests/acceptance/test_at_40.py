"""AT-40: discount once, from default date to valuation date (ECL-08)."""

import pytest

from stress.cashflows.kernels import contractual_schedule
from stress.ecl.kernels import ecl
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-40")
def test_single_discounting(reference_runs):
    case = oracle("AT-40")
    i, e = case["input"], case["expected"]
    schedule = contractual_schedule(i["ead"], i["eir"], float(i["buckets"]), "bullet")
    assert_close(1 / schedule.discount_factor[0], e["discount_divisor"], case["tolerance"])
    value = ecl([i["marginal_pd"]], [i["ead"]], [i["lgd"]], schedule.discount_factor)
    assert_close(value, e["ecl"], case["tolerance"], "ECL")
    twice = value * schedule.discount_factor[0]
    assert abs(twice - e["ecl"]) > case["tolerance"]["abs"], case["wrong_answers"][0]["why"]
    # The same case through the whole pipeline: R5's discount factor, applied once in R8.
    ctx, _ = reference_runs["core"]
    fid = reference_runs["ids"]["AT-40"]
    params = builders.result(ctx, "parameters.parquet")
    start = int(params["valuation_year"].min())
    first = params[(params["facility_id"] == fid) & (params["valuation_year"] == start)
                   & (params["default_bucket"] == 1)]
    assert len(first) == 2  # baseline and adverse
    for row in first.itertuples(index=False):
        assert_close(1 / row.discount_factor, e["discount_divisor"], case["tolerance"], "run divisor")
        assert_close(row.ead_total, i["ead"], case["tolerance"], "run EAD")
    prov = builders.result(ctx, "provisions.parquet")
    mine = prov[(prov["facility_id"] == fid) & (prov["year"] == start)]
    assert len(mine) == 2
    for row in mine.itertuples(index=False):
        assert_close(row.allowance_on, e["ecl"], case["tolerance"], "run ECL")
        assert abs(row.allowance_on * first["discount_factor"].iloc[0] - e["ecl"]) > case["tolerance"]["abs"]
