"""End-2029 S1 provisions in a full run use the interpolated 2030 loss rate (ECL-10, AT-06)."""

import numpy as np
import pytest

from tests import builders
from tests.support import oracle, tolerance


@pytest.mark.req("ECL-10")
def test_run_interpolates_the_2030_s1_loss_rate(core_run, full_tables):
    ctx, _ = core_run
    last = oracle("AT-06")["input"]["valuation_year"]
    prov = builders.result(ctx, "provisions.parquet")
    terminal = prov[(prov["year"] == last) & (prov["method"] == "s1_terminal_interpolated")]
    assert len(terminal) and set(terminal["scenario"]) == {"baseline", "adverse"}
    assert not ((prov["year"] < last) & (prov["method"] == "s1_terminal_interpolated")).any()

    fac = full_tables["facilities"].merge(full_tables["obligors"][["obligor_id", "country"]], on="obligor_id")
    fac = fac[["facility_id", "segment", "country", "gca"]].rename(columns={"gca": "facility_gca"})
    params = builders.result(ctx, "parameters.parquet")
    first = params[(params["valuation_year"] == last) & (params["default_bucket"] == 1)
                   & (params["fraction"] == 1.0)][["scenario", "facility_id", "ead_drawn", "discount_factor"]]
    curves = builders.result(ctx, "pd_curves.parquet")
    pd_last = curves[(curves["valuation_year"] == last - 1)
                     & (curves["default_bucket"] == 1)][["scenario", "segment", "country", "cohort", "m"]]
    lgd = builders.result(ctx, "lgd_of_year.parquet")
    lgd = lgd[lgd["year"] == last][["scenario", "facility_id", "lgd"]]
    z = builders.result(ctx, "drivers.parquet")
    weights = z[z["year"] == last + 1][["scenario", "segment", "country", "adverse_weight"]]
    slices = builders.result(ctx, "slices.parquet")[["scenario", "year", "facility_id", "slice", "gca"]]

    rows = (terminal[["scenario", "facility_id", "slice", "raw_on"]]
            .merge(first, on=["scenario", "facility_id"])  # whole-year first bucket only
            .merge(fac, on="facility_id")
            .merge(weights, on=["scenario", "segment", "country"])
            .merge(slices[slices["year"] == last].drop(columns="year"), on=["scenario", "facility_id", "slice"]))
    own = pd_last.rename(columns={"cohort": "slice", "m": "pd_own"})
    base = pd_last[pd_last["scenario"] == "baseline"].drop(columns="scenario").rename(
        columns={"cohort": "slice", "m": "pd_base"})
    rows = rows.merge(own, on=["scenario", "segment", "country", "slice"])
    rows = rows.merge(base, on=["segment", "country", "slice"])
    rows = rows.merge(lgd.rename(columns={"lgd": "lgd_own"}), on=["scenario", "facility_id"])
    rows = rows.merge(lgd[lgd["scenario"] == "baseline"].drop(columns="scenario")
                      .rename(columns={"lgd": "lgd_base"}), on="facility_id")
    assert len(rows) > 1000

    adverse = rows["scenario"] == "adverse"
    weight = oracle("AT-06")["expected"]["weights"]["adverse"]
    assert np.allclose(rows.loc[adverse, "adverse_weight"], weight, rtol=0, atol=tolerance("rate")["abs"]), "a(2030) = 5/6"
    # The loss rate is interpolated as a product of the 2029 PD and LGD (ECL-05).
    a = rows["adverse_weight"]
    rate = a * rows["pd_own"] * rows["lgd_own"] + (1 - a) * rows["pd_base"] * rows["lgd_base"]
    share = rows["gca"] / rows["facility_gca"]
    expected = share * rate * rows["ead_drawn"] * rows["discount_factor"]
    assert np.allclose(rows["raw_on"], expected, rtol=0, atol=tolerance("amount")["abs"])
