"""AT-04: a new S3 cohort is booked once as flow x LGD (ECL-11, PD-05)."""

import pytest

from stress.ecl.kernels import floor_per_exposure, s3_new_booking
from tests.support import assert_close, oracle


@pytest.mark.at("AT-04")
def test_new_cohort_booked_once():
    case = oracle("AT-04")
    i = case["input"]
    booked = s3_new_booking([i["flow"]], [i["lgd"]])
    assert_close(booked[0], case["expected"]["allowance"], case["tolerance"], "booking")
    # The next year re-measures the same cohort and floors it; it does not add a second booking.
    next_year, _ = floor_per_exposure(s3_new_booking([i["flow"]], [i["lgd"]]), booked)
    assert_close(next_year[0], case["expected"]["allowance"], case["tolerance"], "after a year")
