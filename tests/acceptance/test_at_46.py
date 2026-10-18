"""AT-46: PiT shifts of every TTC matrix stay valid, and PD rises with the grade (PD-10)."""

import numpy as np
import pytest

from stress.params import ttc_arrays
from stress.params.matrix import pd_rises_with_grade, pit_matrix
from tests import builders
from tests.support import oracle


@pytest.mark.at("AT-46")
def test_pit_rows_sum_to_one_and_pd_rises(full_tables, core_run):
    case = oracle("AT-46")
    tol = case["expected"]["row_sum_tolerance"]
    matrices, _ = ttc_arrays(full_tables["ttc_pd_matrix"])
    segments = full_tables["parameter_set"]["segments"]
    ctx, _ = core_run
    run_z = builders.result(ctx, "drivers.parquet")["z"].unique()
    grid = np.concatenate([np.linspace(-4, 4, 17), run_z])
    for segment, ttc in matrices.items():
        assert pd_rises_with_grade(ttc), f"TTC {segment}"
        for z in grid:
            m = pit_matrix(ttc, float(z), segments[segment]["rho"])
            assert np.all(np.abs(m.sum(axis=1) - 1.0) <= tol), (segment, z)
            assert (m >= 0).all(), (segment, z)
            assert pd_rises_with_grade(m) is case["expected"]["pd_rises_with_grade"], (segment, z)
    # The matrices the run used, as written to pit_matrices.parquet.
    pit = builders.result(ctx, "pit_matrices.parquet")
    sums = pit.groupby(["segment", "country", "scenario", "year", "from_grade"])["probability"].sum()
    assert np.all(np.abs(sums - 1.0) <= tol)
