"""Preparation-model contracts and independent arithmetic checks."""

import numpy as np
import pytest

from stress.contracts.errors import BlockingError
from stress.params.assessment import benchmark_selection, recovery_lgd, reverse_threshold
from tests.support import oracle


@pytest.mark.req("MOD-03")
def test_benchmark_whole_pivot_fallback_and_stable_choices():
    p = oracle("AT-34")["input"]["pd"]
    common = {"country": "DE", "pivot": "corporate", "family": "lgd_lr", "scenario": "adverse",
              "year": 2027, "benchmark_version": "test", "model_version": "test",
              "route": "ordinary", "model_parameters": {"lr11": p, "lr12": p, "lr13": p,
                                                            "lr21": p, "lr22": p, "lr23": p},
              "benchmark_parameters": {"lr11": 2*p, "lr12": 2*p, "lr13": 2*p,
                                         "lr21": 2*p, "lr22": 2*p, "lr23": 2*p}}
    a = {**common, "exposure_id": "a", "gca": p, "model_available": True}
    b = {**common, "exposure_id": "b", "gca": 1-p, "model_available": False}
    result = benchmark_selection([a, b])
    assert result["source"].eq("benchmark").all()
    assert result["value"].eq(2*p).all()
    with pytest.raises(BlockingError):
        benchmark_selection([a, {**a, "year": 2028, "model_available": False}])
    with pytest.raises(BlockingError):
        benchmark_selection([a, b, {**a, "year": 2028}])


@pytest.mark.req("LGD-01", "LGD-04")
def test_recovery_discounting_and_shared_collateral_allocation():
    amount = oracle("AT-34")["input"]["drawn"]
    row = {"facility_id": "F", "ead": amount, "eir": 0., "collateral_id": "C",
           "collateral_value": amount, "allocation": .5, "haircut": 0., "cost": 0.,
           "recovery_years": 1., "unsecured_recovery": 0., "model_version": "test"}
    result = recovery_lgd([row])
    assert np.isclose(result.iloc[0].lgd, 1 - row["allocation"])
    with pytest.raises(BlockingError):
        recovery_lgd([{**row, "allocation": 1.}, {**row, "facility_id": "G", "allocation": 1.}])


@pytest.mark.req("VAL-02")
def test_reverse_search_returns_bracketed_breach_and_reports_unreachable():
    result = reverse_threshold(lambda x: x*x, 1., 0., 2.)
    assert result["status"] == "BREACHED" and result["loss"] >= 1.
    assert abs(result["severity"] - 1.) < 1e-5
    assert reverse_threshold(lambda x: x, 3., 0., 2.)["status"] == "NOT_REACHED"
