"""AT-50: prepayment lowers the drawn EAD only, from the next bucket on, and never the default
survival (EAD-11)."""

import numpy as np
import pytest

from stress.params.prepay import not_prepaid_share
from tests import builders
from tests.support import oracle, tolerance


@pytest.mark.at("AT-50")
def test_prepayment_in_ead_only(core_run, mini_tables, tmp_path):
    case = oracle("AT-50")
    tol = tolerance("rate")["abs"]
    ctx, _ = core_run
    params = builders.result(ctx, "parameters.parquet")
    assert (params["prepayment_rate"] > 0).any(), "the case needs a positive prepayment rate"
    assert (params.loc[params["default_bucket"] == 1, "not_prepaid_share"] == case["expected"]["sp_first_bucket"]).all()
    # SP[k] = (1 - CPR[1]) x ... x (1 - CPR[k-1]) of the facility's own rates. R6 builds the share
    # itself and takes the EAD from it, so EAD = B x SP holds for any share: the share is held to
    # the kernel here, for every facility, scenario and valuation date.
    profile = ["facility_id", "scenario", "valuation_year"]
    params = params.sort_values([*profile, "default_bucket"], kind="mergesort").reset_index(drop=True)
    assert (params["default_bucket"] == params.groupby(profile).cumcount() + 1).all(), "buckets run 1..K"
    first = np.flatnonzero(params["default_bucket"].to_numpy() == 1)
    rates = np.split(params["prepayment_rate"].to_numpy(), first[1:])
    expected = np.concatenate([not_prepaid_share(of_profile) for of_profile in rates])
    assert np.all(np.abs(params["not_prepaid_share"].to_numpy() - expected) <= tol), (
        "SP[k] is the product of (1 - CPR) over the buckets before k")
    assert (params["not_prepaid_share"] < case["expected"]["sp_first_bucket"]).any(), (
        "prepayment must reach the buckets after the first")
    assert np.allclose(params["ead_drawn"], params["balance"] * params["not_prepaid_share"], rtol=1e-12, atol=0)
    committed = params[params["undrawn"] > 0]
    assert len(committed) and np.allclose(committed["ead_undrawn"], committed["undrawn"] * committed["ccf"],
                                          rtol=1e-12, atol=0), "the undrawn amount is not prepaid"
    # The same book with zero prepayment: EAD_drawn = B and the PD curves are identical.
    no_prepay = builders.copy_tables(mini_tables)
    for seg in builders.segments(no_prepay):
        builders.settings(no_prepay, seg)["cpr_ttc"] = 0.0
    with_prepay, _ = builders.run(builders.write(builders.copy_tables(mini_tables), tmp_path / "a"),
                                  tmp_path / "ra")
    without, _ = builders.run(builders.write(no_prepay, tmp_path / "b"), tmp_path / "rb")
    zero = builders.result(without, "parameters.parquet")
    assert (zero["prepayment_rate"] == 0).all()
    assert np.array_equal(zero["ead_drawn"].to_numpy(), zero["balance"].to_numpy())
    curves_a = builders.result(with_prepay, "pd_curves.parquet")
    curves_b = builders.result(without, "pd_curves.parquet")
    assert len(curves_a) == len(curves_b)
    assert np.all(np.abs(curves_a["s"].to_numpy() - curves_b["s"].to_numpy()) <= tol), (
        "default survival must not depend on prepayment")
