"""TTC matrix to PiT matrix M(y) by the year's Z (PD-10).

With ``C(i, j)`` the probability of ending in grade j or worse from grade i, and C = 0 beyond D:
``C_PiT = Phi((Phi^-1(C_TTC) - sqrt(rho) * Z) / sqrt(1 - rho))`` and
``M(i, j) = C_PiT(i, j) - C_PiT(i, j + 1)``. The D row stays absorbing.
"""

import numpy as np
from scipy.special import ndtr, ndtri

from stress.contracts.errors import Block, BlockingError


def cumulative(matrix: np.ndarray) -> np.ndarray:
    """C(i, j) = sum of M(i, j') for j' >= j; C(i, 1) = 1 exactly."""
    c = np.cumsum(matrix[:, ::-1], axis=1)[:, ::-1]
    c = np.clip(c, 0.0, 1.0)
    c[:, 0] = 1.0
    return c


def pit_matrix(ttc: np.ndarray, z: float, rho: float) -> np.ndarray:
    """Shift every performing row of a TTC matrix (grades plus D as last column) by Z."""
    if not 0.0 <= rho < 1.0:
        raise ValueError("rho must be in [0, 1)")
    n = ttc.shape[0] - 1
    c = cumulative(ttc[:n])
    with np.errstate(invalid="ignore", divide="ignore"):
        shifted = ndtr((ndtri(c) - np.sqrt(rho) * z) / np.sqrt(1.0 - rho))
    shifted[:, 0] = 1.0
    out = np.zeros_like(ttc, dtype=float)
    out[:n, :-1] = shifted[:, :-1] - shifted[:, 1:]
    out[:n, -1] = shifted[:, -1]
    out[n, -1] = 1.0
    return out


def matrix_problems(matrix: np.ndarray, tol: float) -> list[str]:
    """Why a transition matrix is invalid: row sums, negative cells, D not absorbing (PD-09)."""
    problems = []
    if not np.all(np.isfinite(matrix)):
        problems.append("non-finite cell")
        return problems
    sums = matrix.sum(axis=1)
    bad = np.nonzero(np.abs(sums - 1.0) > tol)[0]
    if bad.size:
        problems.append(f"rows {bad.tolist()} do not sum to one within {tol}")
    if (matrix < 0).any():
        problems.append("negative cell")
    d_row = matrix[-1]
    if not (abs(d_row[-1] - 1.0) <= tol and np.all(np.abs(d_row[:-1]) <= tol)):
        problems.append("D is not absorbing")
    return problems


def check_matrix(matrix: np.ndarray, tol: float, step: str, name: str,
                 code: str = Block.INVALID_MATRIX) -> None:
    problems = matrix_problems(matrix, tol)
    if problems:
        raise BlockingError(step, code, f"{name}: " + "; ".join(problems))


def pd_rises_with_grade(matrix: np.ndarray) -> bool:
    """The D column rises strictly with the grade over the performing rows."""
    pd = matrix[:-1, -1]
    return bool(np.all(np.diff(pd) > 0))
