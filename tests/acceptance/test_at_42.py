"""AT-42: the P03 opening-S1 reference traced through the R5, R6 and R8 kernels."""

import pytest

from stress.cashflows.kernels import contractual_schedule
from stress.ecl.kernels import ecl
from stress.params.ead import ead
from stress.params.prepay import not_prepaid_share, prepayment_rate
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-42")
def test_reference_ecl(reference_runs):
    case = oracle("AT-42")
    i, e = case["input"], case["expected"]
    schedule = contractual_schedule(i["drawn"], i["eir"], 1.0, i["profile"])  # R5
    cpr = prepayment_rate([i["prepayment_rate"]], 0.0, 0.0)  # R6, zero prepayment
    exposure = ead(schedule.balance, i["undrawn"], i["ccf"], not_prepaid_share(cpr))  # R6
    assert_close(exposure.total[0], e["ead_total"], case["tolerance"], "EAD")
    value = ecl([i["pd"]], exposure.total, [i["lgd"]], schedule.discount_factor)  # R8
    assert_close(value, e["ecl"], case["tolerance"], "ECL")
    assert round(value, 2) == e["ecl_displayed"]
    # The same case through the whole pipeline: R5 schedule, R6 parameters, R8 provision.
    ctx, _ = reference_runs["core"]
    fid = reference_runs["ids"]["AT-42"]
    params = builders.result(ctx, "parameters.parquet")
    start = int(params["valuation_year"].min())
    first = params[(params["facility_id"] == fid) & (params["valuation_year"] == start)
                   & (params["default_bucket"] == 1)]
    for row in first.itertuples(index=False):
        assert_close(row.ead_total, e["ead_total"], case["tolerance"], "run EAD")
        assert_close(row.lgd, i["lgd"], oracle("AT-49")["tolerance"], "run LGD")
        assert_close(row.discount_factor * (1 + i["eir"]), 1.0, oracle("AT-49")["tolerance"], "run DF")
    curves = builders.result(ctx, "pd_curves.parquet")
    prov = builders.result(ctx, "provisions.parquet")
    mine = prov[(prov["facility_id"] == fid) & (prov["year"] == start)]
    assert len(mine) == 2
    for row in mine.itertuples(index=False):
        assert_close(row.allowance_on + row.provision_off, e["ecl"], case["tolerance"], "run ECL")
        assert round(row.allowance_on + row.provision_off, 2) == e["ecl_displayed"]
    grade = mine["slice"].iloc[0]
    pd_run = curves[(curves["segment"] == i["segment"]) & (curves["valuation_year"] == start)
                    & (curves["cohort"] == grade) & (curves["default_bucket"] == 1)]
    for value in pd_run["m"]:
        assert_close(value, i["pd"], oracle("AT-49")["tolerance"], "run PD")
