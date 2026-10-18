"""AT-03: the existing S3 allowance is floored at its opening value (ECL-07, ECL-11)."""

import pytest

from stress.ecl.kernels import s3_original_allowance
from tests.support import assert_close, oracle


@pytest.mark.at("AT-03")
def test_existing_s3_allowance_keeps_its_floor():
    case = oracle("AT-03")
    i = case["input"]
    raw, constrained = s3_original_allowance(
        [i["exposure"]], [i["loss_rate"]], [i["opening_allowance"]]
    )
    assert_close(constrained[0], case["expected"]["allowance"], case["tolerance"], "allowance")
    assert raw[0] < constrained[0], "the raw year-one loss would have released provision"
