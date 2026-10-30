"""AT-08: converted total exposure with an illustrative CCF (EAD-02)."""

import pytest

from stress.params.ead import ead
from tests import builders
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-08")
def test_converted_total_exposure(reference_runs):
    case = oracle("AT-08")
    i = case["input"]
    value = float(ead(i["drawn"], i["undrawn"], i["ccf"]).total)
    assert_close(value, case["expected"]["ead_total"], case["tolerance"], "EAD")
    for wrong in case["wrong_answers"]:
        assert not within(value, wrong["value"], case["tolerance"]), wrong["why"]
    # The same case through the whole pipeline: R6 converts the undrawn amount.
    ctx, _ = reference_runs["core"]
    params = builders.result(ctx, "parameters.parquet")
    first = params[(params["facility_id"] == reference_runs["ids"]["AT-08"])
                   & (params["valuation_year"] == params["valuation_year"].min()) & (params["default_bucket"] == 1)]
    assert len(first) == 2  # baseline and adverse
    for value in first["ead_total"]:
        assert_close(value, case["expected"]["ead_total"], case["tolerance"], "run EAD")
        for wrong in case["wrong_answers"]:
            assert not within(value, wrong["value"], case["tolerance"]), wrong["why"]
