"""AT-49: LGD from TTC LGD and Z (LGD-12)."""

import numpy as np
import pytest

from stress.params.lgd import lgd_from_z
from tests import builders
from tests.support import oracle, spec_yaml


@pytest.mark.at("AT-49")
def test_lgd_shift(full_tables, core_run, reference_runs):
    case = oracle("AT-49")
    e = case["expected"]
    tol = e["z_zero_returns_ttc_within"]
    interior = [s["reference_lgd"] for s in spec_yaml("calibration_targets.yaml")["segments"].values()]
    ws = [p["lgd_w"] for p in full_tables["parameter_set"]["segments"].values()]
    for w in ws:
        assert np.all(np.abs(lgd_from_z(interior, w, case["input"]["z"]["zero"]) - interior) <= tol)
        for edge in case["input"]["lgd_ttc_boundaries"]:
            for z in (-3.0, 0.0, 3.0):
                assert lgd_from_z(edge, w, z) == edge, "0 and 1 pass through unchanged"
        if w > 0:
            zs = np.linspace(2, -4, 13)  # falling
            values = np.array([lgd_from_z(interior, w, z) for z in zs])
            assert np.all(np.diff(values, axis=0) > 0), "LGD rises as Z falls"
            assert np.all(values < 1.0) and np.all(values > 0.0)
    # The LGDs the run used: each from its TTC LGD and that year's Z, rising as Z falls.
    ctx, _ = core_run
    fac = full_tables["facilities"][["facility_id", "segment", "ttc_lgd"]]
    run = builders.result(ctx, "lgd_of_year.parquet").merge(fac, on="facility_id")
    weights = run["segment"].map(lambda s: full_tables["parameter_set"]["segments"][s]["lgd_w"])
    assert np.allclose(run["lgd"], lgd_from_z(run["ttc_lgd"], weights, run["z"]), rtol=0, atol=tol)
    assert run["lgd"].between(0, 1, inclusive="neither").all()
    by_rising_z = run.drop_duplicates(["facility_id", "z"]).sort_values(["facility_id", "z"])
    falls = by_rising_z.groupby("facility_id")["lgd"].diff().dropna()
    assert len(falls) and (falls < 0).all()
    # A facility with w > 0 whose baseline Z is zero keeps its TTC LGD in a run.
    reference, _ = reference_runs["core"]
    i = oracle("AT-06")["input"]
    lgd = builders.result(reference, "lgd_of_year.parquet")
    row = lgd[(lgd["facility_id"] == reference_runs["ids"]["AT-06"]) & (lgd["scenario"] == "baseline")
              & (lgd["year"] == i["valuation_year"])].iloc[0]
    assert abs(row["z"]) <= tol and abs(row["lgd"] - i["baseline"]["lgd"]) <= tol
