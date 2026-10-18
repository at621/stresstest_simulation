"""Part-year buckets in the ECL (R8). The PD curves hold whole years only (R6). A final bucket of
d years uses d x the marginal PD of that bucket's whole year, pro rata by the maturity, owner
decision of 18 October 2026 (assumptions A7, A27 and C10)."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from stress.ecl.kernels import part_year_pd
from stress.params.pd import stub_pd
from tests import builders
from tests.support import tolerance


@pytest.mark.req("ECL-08")
@given(st.floats(0.0, 1.0), st.floats(1e-6, 1.0))
def test_part_year_pd_is_pro_rata(marginal, fraction):
    value = float(part_year_pd(marginal, fraction))
    assert 0.0 <= value <= marginal + 1e-15
    # Never above the constant-hazard rule it replaced: 1 - (1 - x)^d >= d x for d in (0, 1].
    assert value <= float(stub_pd(marginal, fraction)) + 1e-15
    assert float(part_year_pd(marginal, 1.0)) == marginal  # a whole year is unchanged


@pytest.mark.req("PD-11")
def test_curves_hold_whole_years_only(core_run):
    ctx, _ = core_run
    curves = builders.result(ctx, "pd_curves.parquet")
    assert "fraction" not in curves.columns
    span = curves.groupby(["segment", "country", "scenario", "valuation_year", "cohort"])["default_bucket"]
    span = span.agg(["min", "max", "count"])
    assert (span["min"] == 1).all() and (span["count"] == span["max"]).all()


def _facts(tables):
    fac = tables["facilities"].merge(tables["obligors"][["obligor_id", "country"]], on="obligor_id")
    undrawn = tables["commitments"].groupby("facility_id")["nominal_undrawn"].sum()
    fac = fac.assign(facility_undrawn=fac["facility_id"].map(undrawn).fillna(0.0))
    return fac[["facility_id", "segment", "country", "gca", "facility_undrawn"]].rename(
        columns={"gca": "facility_gca"})


def _shares(rows):
    on = rows["gca"] / rows["facility_gca"]
    off = np.where(rows["facility_undrawn"] > 0,
                   rows["undrawn"] / rows["facility_undrawn"].where(rows["facility_undrawn"] > 0, 1.0), 0.0)
    return on, off


@pytest.mark.req("ECL-08")
def test_s2_part_year_bucket_is_pro_rata(core_run, full_tables):
    ctx, _ = core_run
    params = builders.result(ctx, "parameters.parquet")
    curves = builders.result(ctx, "pd_curves.parquet")
    prov = builders.result(ctx, "provisions.parquet")
    slices = builders.result(ctx, "slices.parquet")
    with_stub = params.loc[params["fraction"] < 1.0, ["scenario", "valuation_year", "facility_id"]]
    s2 = prov[prov["stage"] == 2].rename(columns={"year": "valuation_year"})
    s2 = s2.merge(with_stub.drop_duplicates(), on=["scenario", "valuation_year", "facility_id"])
    s2 = s2.merge(slices.rename(columns={"year": "valuation_year"})[
        ["scenario", "valuation_year", "facility_id", "slice", "grade", "gca", "undrawn"]],
        on=["scenario", "valuation_year", "facility_id", "slice"])
    s2 = s2.merge(_facts(full_tables), on="facility_id")
    assert len(s2) > 100
    rows = s2.merge(params[["scenario", "valuation_year", "facility_id", "default_bucket", "fraction",
                            "ead_drawn", "ead_undrawn", "lgd", "discount_factor"]],
                    on=["scenario", "valuation_year", "facility_id"])
    rows = rows.merge(curves.rename(columns={"cohort": "grade"})[
        ["segment", "country", "scenario", "valuation_year", "grade", "default_bucket", "m"]],
        on=["segment", "country", "scenario", "valuation_year", "grade", "default_bucket"],
        how="left", validate="many_to_one")
    assert rows["m"].notna().all(), "every bucket, the part-year one included, has a whole-year PD"
    m = rows["m"] * rows["fraction"]  # whole years have fraction 1
    on, off = _shares(rows)
    rows["term_on"] = m * rows["ead_drawn"] * rows["lgd"] * rows["discount_factor"] * on
    rows["term_off"] = m * rows["ead_undrawn"] * rows["lgd"] * rows["discount_factor"] * off
    key = ["scenario", "valuation_year", "facility_id", "slice"]
    got = rows.groupby(key)[["term_on", "term_off", "raw_on", "raw_off"]].agg(
        {"term_on": "sum", "term_off": "sum", "raw_on": "first", "raw_off": "first"})
    limit = tolerance("amount")["abs"]
    assert np.allclose(got["raw_on"], got["term_on"], rtol=0, atol=limit)
    assert np.allclose(got["raw_off"], got["term_off"], rtol=0, atol=limit)


@pytest.mark.req("ECL-10")
def test_terminal_s1_part_year_first_bucket_is_pro_rata(core_run, full_tables):
    ctx, _ = core_run
    last = int(full_tables["parameter_set"]["terminal_rule"]["last_scenario_year"])
    prov = builders.result(ctx, "provisions.parquet")
    terminal = prov[(prov["year"] == last) & (prov["method"] == "s1_terminal_interpolated")]
    params = builders.result(ctx, "parameters.parquet")
    first = params[(params["valuation_year"] == last) & (params["default_bucket"] == 1)
                   & (params["fraction"] < 1.0)][["scenario", "facility_id", "fraction", "ead_drawn",
                                                  "ead_undrawn", "discount_factor"]]
    curves = builders.result(ctx, "pd_curves.parquet")
    one_year = curves[(curves["valuation_year"] == last - 1) & (curves["default_bucket"] == 1)]
    one_year = one_year[["scenario", "segment", "country", "cohort", "m"]].rename(columns={"cohort": "slice"})
    lgd = builders.result(ctx, "lgd_of_year.parquet")
    lgd = lgd[lgd["year"] == last][["scenario", "facility_id", "lgd"]]
    weights = builders.result(ctx, "drivers.parquet")
    weights = weights[weights["year"] == last + 1][["scenario", "segment", "country", "adverse_weight"]]
    slices = builders.result(ctx, "slices.parquet")
    slices = slices[slices["year"] == last][["scenario", "facility_id", "slice", "gca", "undrawn"]]
    rows = (terminal[["scenario", "facility_id", "slice", "raw_on", "raw_off"]]
            .merge(first, on=["scenario", "facility_id"])
            .merge(_facts(full_tables), on="facility_id")
            .merge(weights, on=["scenario", "segment", "country"])
            .merge(slices, on=["scenario", "facility_id", "slice"])
            .merge(one_year.rename(columns={"m": "pd_own"}), on=["scenario", "segment", "country", "slice"])
            .merge(one_year[one_year["scenario"] == "baseline"].drop(columns="scenario")
                   .rename(columns={"m": "pd_base"}), on=["segment", "country", "slice"])
            .merge(lgd.rename(columns={"lgd": "lgd_own"}), on=["scenario", "facility_id"])
            .merge(lgd[lgd["scenario"] == "baseline"].drop(columns="scenario")
                   .rename(columns={"lgd": "lgd_base"}), on="facility_id"))
    assert len(rows) > 100, "the run has end-of-horizon S1 slices whose first bucket is a part-year"
    a, d = rows["adverse_weight"], rows["fraction"]
    rate = a * rows["pd_own"] * d * rows["lgd_own"] + (1 - a) * rows["pd_base"] * d * rows["lgd_base"]
    on, off = _shares(rows)
    limit = tolerance("amount")["abs"]
    assert np.allclose(rows["raw_on"], rate * rows["ead_drawn"] * rows["discount_factor"] * on,
                       rtol=0, atol=limit)
    assert np.allclose(rows["raw_off"], rate * rows["ead_undrawn"] * rows["discount_factor"] * off,
                       rtol=0, atol=limit)


@pytest.mark.req("ECL-08")
def test_s1_part_year_first_bucket_is_pro_rata(core_run, full_tables):
    # Before the end of the horizon, an S1 slice whose only bucket is a part-year takes d x m[1].
    ctx, _ = core_run
    params = builders.result(ctx, "parameters.parquet")
    first = params[(params["default_bucket"] == 1) & (params["fraction"] < 1.0)]
    prov = builders.result(ctx, "provisions.parquet")
    s1 = prov[prov["method"] == "s1_12m"].rename(columns={"year": "valuation_year"})
    rows = s1.merge(first[["scenario", "valuation_year", "facility_id", "fraction", "ead_drawn",
                           "ead_undrawn", "lgd", "discount_factor"]],
                    on=["scenario", "valuation_year", "facility_id"])
    slices = builders.result(ctx, "slices.parquet").rename(columns={"year": "valuation_year"})
    rows = rows.merge(slices[["scenario", "valuation_year", "facility_id", "slice", "grade", "gca", "undrawn"]],
                      on=["scenario", "valuation_year", "facility_id", "slice"])
    rows = rows.merge(_facts(full_tables), on="facility_id")
    curves = builders.result(ctx, "pd_curves.parquet")
    one = curves[curves["default_bucket"] == 1].rename(columns={"cohort": "grade"})
    rows = rows.merge(one[["segment", "country", "scenario", "valuation_year", "grade", "m"]],
                      on=["segment", "country", "scenario", "valuation_year", "grade"], validate="many_to_one")
    assert len(rows) > 100, "the run has S1 slices whose first bucket is a part-year"
    m = rows["m"] * rows["fraction"]
    on, off = _shares(rows)
    limit = tolerance("amount")["abs"]
    assert np.allclose(rows["raw_on"], m * rows["ead_drawn"] * rows["lgd"] * rows["discount_factor"] * on,
                       rtol=0, atol=limit)
    assert np.allclose(rows["raw_off"], m * rows["ead_undrawn"] * rows["lgd"] * rows["discount_factor"] * off,
                       rtol=0, atol=limit)
