"""AT-42: the P03 opening-S1 reference traced through the R5, R6 and R8 kernels."""

import pandas as pd
import pytest

from stress.cashflows.kernels import contractual_schedule
from stress.ecl.kernels import ecl
from stress.params.ead import ead
from stress.params.prepay import not_prepaid_share, prepayment_rate
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-42")
def test_reference_ecl(reference_runs, core_run, full_tables):
    case = oracle("AT-42")
    i, e = case["input"], case["expected"]
    schedule = contractual_schedule(i["drawn"], i["eir"], 1.0, i["profile"])  # R5
    cpr = prepayment_rate([i["prepayment_rate"]], 0.0, 0.0)  # R6, zero prepayment
    exposure = ead(schedule.balance, i["undrawn"], i["ccf"], not_prepaid_share(cpr))  # R6
    assert_close(exposure.total[0], e["ead_total"], case["tolerance"], "EAD")
    value = ecl([i["pd"]], exposure.total, [i["lgd"]], schedule.discount_factor)  # R8
    assert_close(value, e["ecl"], case["tolerance"], "ECL")
    assert round(value, 2) == e["ecl_displayed"]
    # The same case through the whole pipeline: R5 schedule, R6 parameters, R8 provision.
    ctx, _ = reference_runs["core"]
    fid = reference_runs["ids"]["AT-42"]
    params = builders.result(ctx, "parameters.parquet")
    start = int(params["valuation_year"].min())
    first = params[(params["facility_id"] == fid) & (params["valuation_year"] == start)
                   & (params["default_bucket"] == 1)]
    for row in first.itertuples(index=False):
        assert_close(row.ead_total, e["ead_total"], case["tolerance"], "run EAD")
        assert_close(row.lgd, i["lgd"], oracle("AT-49")["tolerance"], "run LGD")
        assert_close(row.discount_factor * (1 + i["eir"]), 1.0, oracle("AT-49")["tolerance"], "run DF")
    curves = builders.result(ctx, "pd_curves.parquet")
    prov = builders.result(ctx, "provisions.parquet")
    mine = prov[(prov["facility_id"] == fid) & (prov["year"] == start)]
    assert len(mine) == 2
    for row in mine.itertuples(index=False):
        assert_close(row.allowance_on + row.provision_off, e["ecl"], case["tolerance"], "run ECL")
        assert round(row.allowance_on + row.provision_off, 2) == e["ecl_displayed"]
    grade = mine["slice"].iloc[0]
    pd_run = curves[(curves["segment"] == i["segment"]) & (curves["valuation_year"] == start)
                    & (curves["cohort"] == grade) & (curves["default_bucket"] == 1)]
    for value in pd_run["m"]:
        assert_close(value, i["pd"], oracle("AT-49")["tolerance"], "run PD")
    real, _ = core_run
    prov = builders.result(real, "provisions.parquet")
    last = int(prov["year"].max())
    s1 = prov.loc[(prov["stage"] == 1) & (prov["year"] < last), ["scenario", "year", "facility_id", "slice", "raw_on"]]
    slices = builders.result(real, "slices.parquet")[["scenario", "year", "facility_id", "slice", "grade", "gca"]]
    facts = full_tables["facilities"][["facility_id", "obligor_id", "segment"]].merge(
        full_tables["obligors"][["obligor_id", "country"]], on="obligor_id")
    gca = builders.result(real, "slices.parquet").groupby(["scenario", "year", "facility_id"])["gca"].sum()
    params = builders.result(real, "parameters.parquet")
    first = params.loc[params["default_bucket"] == 1, ["scenario", "valuation_year", "facility_id", "fraction",
                                                       "ead_drawn", "lgd", "discount_factor"]]
    curves = builders.result(real, "pd_curves.parquet")
    curves = curves.loc[curves["default_bucket"] == 1, ["segment", "country", "scenario", "valuation_year", "cohort", "m"]]
    rows = s1.merge(slices, on=["scenario", "year", "facility_id", "slice"]).merge(facts, on="facility_id").merge(
        first, left_on=["scenario", "year", "facility_id"], right_on=["scenario", "valuation_year", "facility_id"]).merge(
        curves, left_on=["segment", "country", "scenario", "valuation_year", "grade"],
        right_on=["segment", "country", "scenario", "valuation_year", "cohort"])
    assert len(rows) == len(s1) and set(rows["scenario"]) == {"baseline", "adverse"}
    assert set(rows["year"]) == set(range(int(prov["year"].min()), last))
    share = rows["gca"] / gca.reindex(pd.MultiIndex.from_frame(rows[["scenario", "year", "facility_id"]])).to_numpy()
    value = share * rows["m"] * rows["fraction"] * rows["ead_drawn"] * rows["lgd"] * rows["discount_factor"]
    assert (rows["raw_on"] - value).abs().max() <= case["tolerance"]["abs"]
