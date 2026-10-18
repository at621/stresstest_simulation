"""AT-22: the accounting allocation of section 5.3, as the engine accepts it (SCP-02, SCP-06)."""

import pytest

from tests import builders
from tests.support import assert_close, eur, oracle, spec_yaml


@pytest.mark.at("AT-22")
def test_accounting_allocation(full_tables, core_run):
    case = oracle("AT-22")
    e = case["expected"]
    tol = case["tolerance"]
    fac = full_tables["facilities"]
    ac = fac[fac["accounting_category"] == "AC"]
    assert_close(ac["gca"].sum(), eur(e["ac_gca_m"]), tol, "AC GCA")
    assert_close(ac.loc[ac["portfolio"] == "P06", "gca"].sum(), eur(e["p06_ac_gca_m"]), tol, "P06 AC")
    assert_close(fac.loc[fac["accounting_category"].isin(["FVOCI", "FVPL"]), "gca"].sum(),
                 eur(e["fvoci_fvpl_gca_m"]), tol, "FVOCI/FVPL")
    assert set(full_tables["commitments"]["asset_category"]) == {"not_applicable"}
    targets = spec_yaml("targets.yaml")
    for approach, total in targets["approach_totals"].items():
        if approach in ("IRB", "STA"):
            assert_close(fac.loc[fac["regulatory_approach"] == approach, "gca"].sum(), eur(total), tol, approach)
    # The engine accepted the whole allocation: the starting point reconciles stage by stage.
    ctx, _ = core_run
    start = builders.report(ctx, "starting_point_reconciliation.csv")
    cells = start[start["stage"] != "all"]
    assert (cells["rejected_count"] == 0).all()
    for row in cells.itertuples(index=False):
        stage = int(row.stage)
        assert row.accepted_count == targets["stages"][row.portfolio]["count"][stage]
        assert_close(row.accepted_gca, eur(targets["stages"][row.portfolio]["gca"][stage]), tol)
    assert set(start["accounting_check"].dropna()) == {"AC only"}
