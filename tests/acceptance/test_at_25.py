"""AT-25: PD-03 probability arithmetic from conditional PDs."""

import numpy as np
import pytest

from stress.params.pd import check_curve, curve_from_conditional
from tests import builders
from tests.support import assert_close, oracle, tolerance


@pytest.mark.at("AT-25")
def test_marginal_cumulative_and_survival(reference_runs, core_run):
    case = oracle("AT-25")
    curve = curve_from_conditional(case["input"]["conditional_pd"])
    e = case["expected"]
    assert_close(curve.m, e["marginal_pd"], case["tolerance"], "marginal")
    assert_close(curve.f, e["cumulative_pd"], case["tolerance"], "cumulative")
    assert_close(curve.s[-1], e["terminal_survival"], case["tolerance"], "survival")
    check_curve(curve, tolerance("probability_identity")["abs"], "test", "AT-25")
    summed = np.cumsum(case["input"]["conditional_pd"])
    assert abs(summed[-1] - curve.f[-1]) > case["tolerance"]["abs"], case["wrong_answers"][0]["why"]
    # The same curve through the whole pipeline: R6 builds it from a chain of matrix rows.
    ctx, _ = reference_runs["core"]
    prov = builders.result(ctx, "provisions.parquet")
    start = int(prov["year"].min())
    opening = prov[(prov["facility_id"] == reference_runs["ids"]["AT-39/S1"]) & (prov["year"] == start)]
    grade = opening["slice"].iloc[0]
    curves = builders.result(ctx, "pd_curves.parquet")
    mine = curves[(curves["segment"] == builders.REFERENCE_SEGMENTS["AT-25"]) & (curves["valuation_year"] == start)
                  & (curves["cohort"] == grade)]
    assert set(mine["scenario"]) == {"baseline", "adverse"}
    for _, rows in mine.groupby(["scenario", "country"]):
        rows = rows.sort_values("default_bucket")
        assert_close(list(rows["q"]), case["input"]["conditional_pd"], case["tolerance"], "run conditional")
        assert_close(list(rows["m"]), e["marginal_pd"], case["tolerance"], "run marginal")
        assert_close(list(rows["f"]), e["cumulative_pd"], case["tolerance"], "run cumulative")
        assert_close(rows["s"].iloc[-1], e["terminal_survival"], case["tolerance"], "run survival")
    # The PD-03 identities hold on every curve of the real book.
    real, _ = core_run
    keys = ["segment", "country", "scenario", "valuation_year", "cohort"]
    run = builders.result(real, "pd_curves.parquet").sort_values([*keys, "default_bucket"])
    tol = tolerance("probability_identity")["abs"]
    assert np.allclose(run["m"], run.groupby(keys)["s"].shift(1).fillna(1.0) * run["q"], rtol=0, atol=tol)
    assert np.allclose(run["s"], 1.0 - run["f"], rtol=0, atol=tol)
    assert np.allclose(run.groupby(keys)["m"].cumsum(), run["f"], rtol=0, atol=tol)
