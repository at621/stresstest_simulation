"""AT-03: the existing S3 allowance is floored at its opening value (ECL-07, ECL-11)."""

import pytest

from stress.contracts.tables import METHOD_S3_ORIGINAL, SLICE_S3_ORIGINAL
from stress.ecl.kernels import s3_original_allowance
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-03")
def test_existing_s3_allowance_keeps_its_floor(reference_runs):
    case = oracle("AT-03")
    i = case["input"]
    raw, constrained = s3_original_allowance(
        [i["exposure"]], [i["loss_rate"]], [i["opening_allowance"]]
    )
    assert_close(constrained[0], case["expected"]["allowance"], case["tolerance"], "allowance")
    assert raw[0] < constrained[0], "the raw year-one loss would have released provision"
    # The same case through the whole pipeline: R8 floors the opening S3 facility in year one.
    ctx, _ = reference_runs["core"]
    prov = builders.result(ctx, "provisions.parquet")
    mine = prov[(prov["facility_id"] == reference_runs["ids"]["AT-03"]) & (prov["year"] == prov["year"].min() + 1)]
    assert len(mine) == 2  # baseline and adverse
    for row in mine.itertuples(index=False):
        assert row.slice == SLICE_S3_ORIGINAL and row.method == METHOD_S3_ORIGINAL
        assert_close(row.raw_on, i["exposure"] * i["loss_rate"], case["tolerance"], "run raw loss")
        assert_close(row.allowance_on, case["expected"]["allowance"], case["tolerance"], "run allowance")
        assert row.floor_binding
