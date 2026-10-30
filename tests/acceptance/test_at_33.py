"""AT-33: zero EAD gives zero loss and a not-applicable LGD, also in the RPT-06 report (LGD-12)."""

import pandas as pd
import pytest

from stress.ecl.kernels import monetary_loss
from stress.params.assessment import default_weighted_lgd
from stress.params.lgd import loss_weighted_lgd
from tests.support import oracle


@pytest.mark.at("AT-33")
def test_zero_ead():
    case = oracle("AT-33")
    any_lgd = oracle("AT-34")["input"]["lgd"]
    any_pd = oracle("AT-34")["input"]["pd"]
    loss, lgd = monetary_loss(case["input"]["ead"], any_lgd)
    assert loss == case["expected"]["loss"]
    assert lgd is None and case["expected"]["lgd"] == "not_applicable"
    _, den, value = loss_weighted_lgd([any_pd], [case["input"]["ead"]], [any_lgd])
    assert den == 0 and value is None
    # The report R10 writes keeps a zero-EAD book as not applicable, never as a zero LGD.
    keys = {"scenario": "adverse", "facility_id": "F"}
    slices = pd.DataFrame([{**keys, "year": 2026, "stage": 1, "grade": "G1", "gca": 0.0, "undrawn": 0.0}])
    facility = pd.DataFrame([{**keys, "valuation_year": 2026, "default_bucket": 1, "fraction": 1.0,
                              "ead_drawn": float(case["input"]["ead"]), "ead_undrawn": 0.0, "lgd": any_lgd}])
    curves = pd.DataFrame([{"segment": "P03", "country": "DE", "scenario": "adverse", "valuation_year": 2026,
                            "default_bucket": 1, "cohort": "G1", "m": any_pd}])
    portfolio = pd.DataFrame([{"facility_id": "F", "portfolio": "P03", "segment": "P03", "country": "DE",
                               "gca": 0.0, "undrawn": 0.0}])
    row = default_weighted_lgd(slices, facility, curves, portfolio).iloc[0]
    assert row["numerator"] == case["expected"]["loss"] and pd.isna(row["loss_weighted_lgd"])
