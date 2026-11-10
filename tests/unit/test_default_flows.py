"""MIG-04: the PD curves and the stage-default flows are one calculation, so they cannot disagree.

The flow into Stage 3 over a year is what the PD curves give for that year: each performing slice
that opens the year, times the first-bucket default probability of its segment, country and grade.
"""

import numpy as np
import pytest

from tests import builders
from tests.support import tolerance


@pytest.mark.req("MIG-04")
def test_stage_default_flows_are_the_pd_curves_applied_to_the_opening_stock(core_run, full_tables):
    ctx, _ = core_run
    slices = builders.result(ctx, "slices.parquet")
    curves = builders.result(ctx, "pd_curves.parquet")
    flows = builders.result(ctx, "stage_flows.parquet")

    place = full_tables["facilities"][["facility_id", "segment", "obligor_id"]].merge(
        full_tables["obligors"][["obligor_id", "country"]], on="obligor_id", validate="many_to_one")
    last_year = int(flows["year"].max())
    opening = slices[(slices["stage"] < 3) & (slices["year"] < last_year)].merge(
        place, on="facility_id", validate="many_to_one")
    first = curves.loc[curves["default_bucket"] == 1,
                       ["segment", "country", "scenario", "valuation_year", "cohort", "m"]]
    priced = opening.merge(first, how="left", validate="many_to_one",
                           left_on=["segment", "country", "scenario", "year", "grade"],
                           right_on=["segment", "country", "scenario", "valuation_year", "cohort"])
    assert len(priced) and priced["m"].notna().all(), "every opening performing slice has its curve"

    priced["flow_year"] = priced["year"] + 1  # the stock at one year-end opens the next year
    from_curves = (priced["gca"] * priced["m"]).groupby(
        [priced["scenario"], priced["flow_year"], priced["segment"], priced["stage"]]).sum()
    defaults = flows[(flows["to_stage"] == 3) & (flows["from_stage"] < 3)]
    from_migration = defaults.groupby(["scenario", "year", "segment", "from_stage"])["gca"].sum()
    from_curves.index.names = from_migration.index.names

    assert set(from_curves.index) == set(from_migration.index)
    assert (from_migration > 0).any(), "the case needs defaults"
    rel = tolerance("aggregate")["rel"]
    assert np.allclose(from_curves.sort_index(), from_migration.sort_index(), rtol=rel, atol=0), (
        "a stage's default flow differs from its PD curves applied to the opening stock")
