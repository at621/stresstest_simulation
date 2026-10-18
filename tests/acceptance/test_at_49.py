"""AT-49: LGD from TTC LGD and Z (LGD-12)."""

import numpy as np
import pytest

from stress.params.lgd import lgd_from_z
from tests.support import oracle, spec_yaml


@pytest.mark.at("AT-49")
def test_lgd_shift(full_tables):
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
