"""AT-47: one grade in one year: its one-year PD rises as Z falls, all else fixed (PD-10)."""

import numpy as np
import pytest

from stress.params import ttc_arrays
from stress.params.matrix import pit_matrix
from tests.support import oracle


@pytest.mark.at("AT-47")
def test_pd_rises_as_z_falls(full_tables):
    case = oracle("AT-47")
    assert case["expected"]["pd_rises_as_z_falls"]
    matrices, grades = ttc_arrays(full_tables["ttc_pd_matrix"])
    segments = full_tables["parameter_set"]["segments"]
    zs = np.linspace(3, -3, 13)  # falling
    for segment, ttc in matrices.items():
        rho = segments[segment]["rho"]
        for g in range(len(grades) - 1):
            pd = [pit_matrix(ttc, float(z), rho)[g, -1] for z in zs]
            assert np.all(np.diff(pd) > 0), (segment, grades[g])
