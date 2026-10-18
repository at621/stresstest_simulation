"""AT-02: stage arithmetic, opening balances times transition rows (MIG-01, MIG-02)."""

import pytest

from stress.projection.kernels import stage_flows
from tests.support import assert_close, oracle, tolerance


@pytest.mark.at("AT-02")
def test_closing_stages_from_transition_rows():
    case = oracle("AT-02")
    closing, flows = stage_flows(case["input"]["opening"], case["input"]["transitions"],
                                 tolerance("probability_identity")["abs"])
    for stage, expected in case["expected"]["closing"].items():
        assert_close(closing[stage], expected, case["tolerance"], stage)
    assert_close(sum(closing.values()), case["expected"]["total"], case["tolerance"], "total")
    # Closing balances reconcile to all incoming flows (MIG-02).
    for dest in closing:
        assert_close(sum(flows[o][dest] for o in flows), closing[dest], case["tolerance"], dest)
