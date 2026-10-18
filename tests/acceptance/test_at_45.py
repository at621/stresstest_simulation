"""AT-45: every TTC matrix is a valid transition matrix, and a broken one blocks (PD-09)."""

import numpy as np
import pytest

from stress.contracts.errors import Block
from stress.params import ttc_arrays
from stress.params.matrix import matrix_problems
from tests import builders
from tests.support import oracle


@pytest.mark.at("AT-45")
def test_ttc_matrices_valid_and_broken_blocks(full_tables, mini, tmp_path):
    case = oracle("AT-45")
    tol = case["expected"]["row_sum_tolerance"]
    matrices, grades = ttc_arrays(full_tables["ttc_pd_matrix"])
    assert grades[-1] == "D"
    for segment, m in matrices.items():
        assert np.all(np.abs(m.sum(axis=1) - 1.0) <= tol), segment
        assert (m < 0).sum() == case["expected"]["negative_cells"], segment
        assert m[-1, -1] == 1.0 and np.all(m[-1, :-1] == 0.0), f"{segment}: D not absorbing"
        assert matrix_problems(m, tol) == []
    # Break one row by more than the tolerance: the run blocks before any calculation.
    table = mini["ttc_pd_matrix"]
    cell = (table["segment"] == "P05") & (table["from_grade"] == grades[0]) & (table["to_grade"] == grades[0])
    table.loc[cell, "probability"] += 10 * tol
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "BLOCKED" and case["expected"]["invalid_matrix_blocked"]
    assert manifest["blocked"]["code"] == Block.INVALID_MATRIX
