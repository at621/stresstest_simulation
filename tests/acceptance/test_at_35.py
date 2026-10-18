"""AT-35: the utilisation sensitivity, as a separate labelled run (EAD-06, SYN-PAR-07)."""

import pytest

from stress.lineage import compare_outputs
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-35")
def test_utilisation_variant_run(reference_runs):
    case = oracle("AT-35")
    e = case["expected"]
    tol = case["tolerance"]
    base = oracle(case["input"]["base_case"])["input"]
    fid = reference_runs["ids"]["AT-34"]
    start = None
    for variant, ead_key, ecl_key in (("core", "ead_from", "ecl_from"), ("utilisation", "ead_to", "ecl_to")):
        ctx, manifest = reference_runs[variant]
        assert manifest["config"]["variant"] == variant and f"-{variant}-" in ctx.run_id
        params = builders.result(ctx, "parameters.parquet")
        start = int(params["valuation_year"].min())
        first = params[(params["facility_id"] == fid) & (params["valuation_year"] == start)
                       & (params["default_bucket"] == 1)]
        assert len(first) == 2  # baseline and adverse, the same EAD in both
        for value in first["ead_total"]:
            assert_close(value, e[ead_key], tol, f"{variant} EAD")
        prov = builders.result(ctx, "provisions.parquet")
        mine = prov[(prov["facility_id"] == fid) & (prov["year"] == start)]
        for row in mine.itertuples(index=False):
            assert_close(row.allowance_on + row.provision_off, e[ecl_key], tol, f"{variant} ECL")
        # Nominal balances do not move with the CCF (EAD-06).
        slices = builders.result(ctx, "slices.parquet")
        totals = slices[slices["facility_id"] == fid].groupby(["scenario", "year"])[["gca", "undrawn"]].sum()
        for gca, undrawn in totals.itertuples(index=False):
            assert_close(gca, base["drawn"], tol)
            assert_close(undrawn, base["undrawn"], tol)
    # The core run is unchanged by the variant: a second core run reproduces it exactly.
    assert e["in_core_run"] is False
    ctx, again = builders.run(reference_runs["inputs"], reference_runs["runs_dir"], variant="core")
    assert compare_outputs(reference_runs["core"][1], again) == []
