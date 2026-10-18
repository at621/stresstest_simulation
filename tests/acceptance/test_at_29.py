"""AT-29: aligned default flows by origin stage (PD-05)."""

import pytest

from stress.projection.kernels import aligned_default_flows
from tests.support import assert_close, oracle


@pytest.mark.at("AT-29")
def test_new_defaults_from_origin_stage_pd():
    case = oracle("AT-29")
    result = aligned_default_flows(case["input"]["opening"], case["input"]["pd"])
    e = case["expected"]
    for stage, flow in e["new_default_flows"].items():
        assert_close(result["new_default_flows"][stage], flow, case["tolerance"], stage)
    assert_close(result["closing_s3"], e["closing_s3"], case["tolerance"], "closing S3")
    assert_close(result["closing_performing"], e["closing_performing"], case["tolerance"])
    assert_close(result["total"], e["total"], case["tolerance"], "total")
