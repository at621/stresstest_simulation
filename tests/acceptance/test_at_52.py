"""AT-52: the Z-score and its reversion after 2029 (SCN-08, ECL-10).

The Z values are OPEN in the spec until the owner approves them; the case proves the rule.
"""

import pytest

from stress.contracts.errors import Block, BlockingError
from stress.scenario.kernels import z_score
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-52")
def test_z_score_and_reversion(core_run, full_tables, mini, tmp_path):
    case = oracle("AT-52")
    e = case["expected"]
    tol = case["tolerance"]
    drivers = full_tables["parameter_set"]["segments"]["P01"]["z_drivers"]
    at_means = {name: coef["mean"] for name, coef in drivers.items()}
    assert_close(z_score(at_means, drivers)[0], e["z_at_means"], tol, "Z at the means")
    broken = {**drivers, next(iter(drivers)): {**next(iter(drivers.values())), "beta": None}}
    with pytest.raises(BlockingError) as err:
        z_score(at_means, broken)
    assert err.value.code == Block.MISSING_PARAMETER and e["missing_coefficient_blocks"]

    ctx, _ = core_run
    z = builders.result(ctx, "drivers.parquet").set_index(["segment", "country", "scenario", "year"])["z"]
    last = min(e["adverse_weights"]) - 1
    for (segment, country) in {(s, c) for s, c, _, _ in z.index}:
        z_adv, z_base = z[(segment, country, "adverse", last)], z[(segment, country, "baseline", last)]
        for year, weight in e["adverse_weights"].items():
            assert_close(z[(segment, country, "adverse", year)], weight * z_adv + (1 - weight) * z_base, tol)
            assert_close(z[(segment, country, "baseline", year)], z_base, tol, "baseline flat")
        flat = e["weight_from"]
        later = [y for (s, c, sc, y) in z.index if (s, c, sc) == (segment, country, "adverse") and y >= flat["year"]]
        for year in later:
            assert_close(z[(segment, country, "adverse", year)], flat["weight"] * z_adv + (1 - flat["weight"]) * z_base, tol)

    # A run whose parameter set lacks a Z coefficient blocks.
    seg = mini["parameter_set"]["segments"]["P02"]["z_drivers"]
    seg[next(iter(seg))]["beta"] = None
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "BLOCKED" and manifest["blocked"]["code"] == Block.MISSING_PARAMETER
