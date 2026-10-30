"""AT-18: the no-release rule is checked per exposure, not on the total (ECL-07, REG-05)."""

import pytest

from stress.contracts.tables import SLICE_S3_ORIGINAL
from stress.ecl.kernels import floor_per_exposure
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-18")
def test_release_rejected_per_exposure(reference_runs, core_run):
    case = oracle("AT-18")
    i = case["input"]
    prior = [abs(i["A"]["change"]) * 4, abs(i["B"]["change"]) * 4]  # any positive allowances
    raw = [prior[0] + i["A"]["change"], prior[1] + i["B"]["change"]]
    constrained, released = floor_per_exposure(raw, prior)
    assert bool(released[0]) is case["expected"]["A_release_rejected"]
    assert not released[1]
    assert_close(sum(raw) - sum(prior), case["expected"]["aggregate_raw_change"], case["tolerance"])
    assert constrained[0] == prior[0], "A keeps its prior allowance"
    assert constrained[1] == raw[1]
    # The same case through the whole pipeline: R8 floors A and leaves B, whatever the total does.
    ctx, _ = reference_runs["core"]
    ids = reference_runs["ids"]
    prov = builders.result(ctx, "provisions.parquet")
    year = int(prov["year"].min()) + 1
    rows = prov[(prov["year"] == year) & (prov["slice"] == SLICE_S3_ORIGINAL)].set_index(["scenario", "facility_id"])
    slices = builders.result(ctx, "slices.parquet")
    before = slices[slices["year"] == year - 1].set_index(["scenario", "facility_id"])["allowance_on"]
    for scenario in ("baseline", "adverse"):
        a, prior_a = rows.loc[(scenario, ids["AT-18/A"])], before[(scenario, ids["AT-18/A"])]
        b, prior_b = rows.loc[(scenario, ids["AT-18/B"])], before[(scenario, ids["AT-18/B"])]
        assert_close(a["raw_on"] - prior_a, i["A"]["change"], case["tolerance"], "run A")
        assert_close(b["raw_on"] - prior_b, i["B"]["change"], case["tolerance"], "run B")
        assert_close(a["raw_on"] + b["raw_on"] - prior_a - prior_b, case["expected"]["aggregate_raw_change"],
                     case["tolerance"], "run aggregate")
        assert bool(a["floor_binding"]) is case["expected"]["A_release_rejected"]
        assert not b["floor_binding"]
        assert a["allowance_on"] == prior_a, "A keeps its prior allowance"
        assert b["allowance_on"] == b["raw_on"]
    # On the real book, many S3 slices would release, and none does.
    real, _ = core_run
    stock = builders.result(real, "slices.parquet")
    s3 = stock[stock["stage"] == 3]
    keys = ["scenario", "year", "facility_id", "slice"]
    pairs = builders.result(real, "provisions.parquet").merge(
        s3.assign(year=s3["year"] + 1)[[*keys, "allowance_on"]], on=keys, suffixes=("", "_prior"))
    assert (pairs["raw_on"] < pairs["allowance_on_prior"]).any()
    assert (pairs["allowance_on"] >= pairs["allowance_on_prior"]).all()
