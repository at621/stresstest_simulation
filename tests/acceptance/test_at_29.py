"""AT-29: aligned default flows by origin stage (PD-05)."""

import pytest

from stress.contracts.tables import new_s3_slice
from stress.projection.kernels import aligned_default_flows
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-29")
def test_new_defaults_from_origin_stage_pd(reference_runs):
    case = oracle("AT-29")
    result = aligned_default_flows(case["input"]["opening"], case["input"]["pd"])
    e = case["expected"]
    for stage, flow in e["new_default_flows"].items():
        assert_close(result["new_default_flows"][stage], flow, case["tolerance"], stage)
    assert_close(result["closing_s3"], e["closing_s3"], case["tolerance"], "closing S3")
    assert_close(result["closing_performing"], e["closing_performing"], case["tolerance"])
    assert_close(result["total"], e["total"], case["tolerance"], "total")
    # The same case through the whole pipeline: R7 takes each origin stage's defaults to a cohort.
    ctx, _ = reference_runs["core"]
    flows = builders.result(ctx, "stage_flows.parquet")
    year = int(flows["year"].min())
    mine = flows[(flows["segment"] == builders.REFERENCE_SEGMENTS["AT-29"]) & (flows["year"] == year)
                 & (flows["to_stage"] == 3)]
    assert set(mine["scenario"]) == {"baseline", "adverse"}
    for _, rows in mine.groupby("scenario"):
        origin = rows.set_index("from_stage")["gca"]
        for stage, flow in e["new_default_flows"].items():
            assert_close(origin[int(stage[1])], flow, case["tolerance"], f"run {stage}")
    ids = [reference_runs["ids"][f"AT-29/{stage}"] for stage in case["input"]["opening"]]
    slices = builders.result(ctx, "slices.parquet")
    book = slices[slices["facility_id"].isin(ids) & (slices["year"] == year)]
    for _, rows in book.groupby("scenario"):
        for stage, flow in e["new_default_flows"].items():
            cohort = rows[rows["slice"] == new_s3_slice(year, int(stage[1]))]
            assert_close(cohort["gca"].sum(), flow, case["tolerance"], f"run cohort {stage}")
        assert_close(rows.loc[rows["stage"] == 3, "gca"].sum(), e["closing_s3"], case["tolerance"], "run S3")
        assert_close(rows.loc[rows["stage"] < 3, "gca"].sum(), e["closing_performing"], case["tolerance"],
                     "run performing")
        assert_close(rows["gca"].sum(), e["total"], case["tolerance"], "run total")
