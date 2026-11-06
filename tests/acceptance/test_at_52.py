"""AT-52: the Z-score and its reversion after 2029 (SCN-08, ECL-10).

The Z values are OPEN in the spec until the owner approves them; the case proves the rule.
"""

import pytest

from stress.contracts.errors import Block, BlockingError
from stress.models.forms import z_score
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-52")
def test_z_score_and_reversion(core_run, full_tables, mini, tmp_path):
    case = oracle("AT-52")
    e = case["expected"]
    tol = case["tolerance"]
    ctx, _ = core_run
    # P01's PD model, as the run recorded its drivers: their beta, mean and sd.
    terms = builders.result(ctx, "driver_contributions.parquet")
    terms = terms[(terms["segment"] == "P01") & (terms["model"] == "pd")].drop_duplicates("driver")
    drivers = {t.driver: {"beta": t.beta, "mean": t.mean, "sd": t.sd} for t in terms.itertuples()}
    at_means = {name: coef["mean"] for name, coef in drivers.items()}
    assert_close(z_score(at_means, drivers)[0], e["z_at_means"], tol, "Z at the means")
    broken = {**drivers, next(iter(drivers)): {**next(iter(drivers.values())), "beta": None}}
    with pytest.raises(BlockingError) as err:
        z_score(at_means, broken)
    assert err.value.code == Block.MISSING_PARAMETER and e["missing_coefficient_blocks"]

    z = builders.result(ctx, "drivers.parquet")
    z = z[z["model"] == "pd"].set_index(["segment", "country", "scenario", "year"])["z"]
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

    # A run whose model lacks a Z coefficient blocks.
    broken_drivers = {"gdp_growth": {"beta": None, "mean": 0.015, "sd": 0.03}}
    builders.settings(mini, "P02")["pd_model"] = builders.model("p02.test_no_beta", "pd", drivers=broken_drivers)
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "BLOCKED" and manifest["blocked"]["code"] == Block.MISSING_PARAMETER
