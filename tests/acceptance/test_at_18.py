"""AT-18: the no-release rule is checked per exposure, not on the total (ECL-07, REG-05)."""

import pytest

from stress.ecl.kernels import floor_per_exposure
from tests.support import assert_close, oracle


@pytest.mark.at("AT-18")
def test_release_rejected_per_exposure():
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
