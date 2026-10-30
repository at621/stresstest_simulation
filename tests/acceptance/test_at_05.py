"""AT-05: simplified S1 loss-rate provision (ECL-02)."""

import pytest

from stress.contracts.tables import METHOD_S1
from stress.ecl.kernels import s1_loss_rate_provision
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-05")
def test_s1_provision_from_next_year_pd_and_lgd(reference_runs):
    case = oracle("AT-05")
    i = case["input"]
    value = s1_loss_rate_provision(i["exposure"], i["pd"], i["lgd"], i["discount_factor"])
    assert_close(value, case["expected"]["provision"], case["tolerance"], "provision")
    # The same case through the whole pipeline: R8 provides for the whole S1 exposure.
    ctx, _ = reference_runs["core"]
    prov = builders.result(ctx, "provisions.parquet")
    mine = prov[(prov["facility_id"] == reference_runs["ids"]["AT-05"]) & (prov["year"] == prov["year"].min())]
    assert len(mine) == 2  # baseline and adverse
    for row in mine.itertuples(index=False):
        assert row.stage == 1 and row.method == METHOD_S1
        assert_close(row.allowance_on, case["expected"]["provision"], case["tolerance"], "run provision")
