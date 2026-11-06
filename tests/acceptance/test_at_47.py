"""AT-47: one grade in one year: its one-year PD rises as Z falls, all else fixed (PD-10)."""

import numpy as np
import pytest

from stress.params import ttc_arrays
from stress.params.matrix import pit_matrix
from tests import builders
from tests.support import oracle


@pytest.mark.at("AT-47")
def test_pd_rises_as_z_falls(full_tables, core_run):
    case = oracle("AT-47")
    assert case["expected"]["pd_rises_as_z_falls"]
    matrices, grades = ttc_arrays(full_tables["ttc_pd_matrix"])
    segments = builders.segments(full_tables)
    zs = np.linspace(3, -3, 13)  # falling
    for segment, ttc in matrices.items():
        rho = segments[segment]["rho"]
        for g in range(len(grades) - 1):
            pd = [pit_matrix(ttc, float(z), rho)[g, -1] for z in zs]
            assert np.all(np.diff(pd) > 0), (segment, grades[g])
    # The matrices the run used: within one grade, the lower a year's Z, the higher its PD.
    ctx, _ = core_run
    pit = builders.result(ctx, "pit_matrices.parquet")
    one_year = pit[(pit["to_grade"] == grades[-1]) & (pit["from_grade"] != grades[-1])]
    one_year = one_year.drop_duplicates(["segment", "from_grade", "z"])
    assert not one_year.empty
    for (segment, grade), rows in one_year.groupby(["segment", "from_grade"]):
        by_falling_z = rows.sort_values("z", ascending=False)["probability"].to_numpy()
        assert len(by_falling_z) > 1 and np.all(np.diff(by_falling_z) > 0), (segment, grade)
