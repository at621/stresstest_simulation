"""AT-04: a new S3 cohort is booked once as flow x LGD (ECL-11, PD-05)."""

import pytest

from stress.contracts.tables import METHOD_S3_NEW_BOOKING, METHOD_S3_NEW_FLOOR, new_s3_slice
from stress.ecl.kernels import floor_per_exposure, s3_new_booking
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-04")
def test_new_cohort_booked_once(reference_runs, core_run):
    case = oracle("AT-04")
    i = case["input"]
    booked = s3_new_booking([i["flow"]], [i["lgd"]])
    assert_close(booked[0], case["expected"]["allowance"], case["tolerance"], "booking")
    # The next year re-measures the same cohort and floors it; it does not add a second booking.
    next_year, _ = floor_per_exposure(s3_new_booking([i["flow"]], [i["lgd"]]), booked)
    assert_close(next_year[0], case["expected"]["allowance"], case["tolerance"], "after a year")
    # The same case through the whole pipeline: R7 opens the cohort, R8 books it and re-measures it.
    ctx, _ = reference_runs["core"]
    fid = reference_runs["ids"]["AT-04"]
    prov = builders.result(ctx, "provisions.parquet")
    year = int(prov["year"].min()) + 1
    cohort = new_s3_slice(year, 1)
    slices = builders.result(ctx, "slices.parquet")
    flows = slices[(slices["facility_id"] == fid) & (slices["slice"] == cohort)]["gca"]
    assert len(flows)
    for value in flows:
        assert_close(value, i["flow"], case["tolerance"], "run flow")
    mine = prov[(prov["facility_id"] == fid) & (prov["slice"] == cohort)]
    assert set(mine["scenario"]) == {"baseline", "adverse"}
    for _, rows in mine.groupby("scenario"):
        assert (rows["method"] == METHOD_S3_NEW_BOOKING).sum() == case["expected"]["bookings"]
        assert rows.loc[rows["method"] == METHOD_S3_NEW_BOOKING, "year"].iloc[0] == year
        assert (rows["method"] == METHOD_S3_NEW_FLOOR).sum() == len(rows) - case["expected"]["bookings"] > 0
        for value in rows["allowance_on"]:
            assert_close(value, case["expected"]["allowance"], case["tolerance"], "run allowance")
    real, _ = core_run
    prov = builders.result(real, "provisions.parquet")
    booked = prov[prov["method"] == METHOD_S3_NEW_BOOKING]
    slices = builders.result(real, "slices.parquet")[["scenario", "year", "facility_id", "slice", "gca"]]
    lgd = builders.result(real, "lgd_of_year.parquet")[["scenario", "year", "facility_id", "lgd"]]
    rows = booked.merge(slices, on=["scenario", "year", "facility_id", "slice"]).merge(
        lgd, on=["scenario", "year", "facility_id"])
    assert len(rows) == len(booked) and set(rows["scenario"]) == {"baseline", "adverse"}
    worst = (rows["allowance_on"] - rows["gca"] * rows["lgd"]).abs().max()
    assert worst <= case["tolerance"]["abs"]
