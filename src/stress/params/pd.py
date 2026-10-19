"""PD curves from products of future PiT matrices; PD-03 identities (PD-11).

``F[k] = (e_g x M(y+1) x ... x M(y+k))[D]``, ``m[k] = F[k] - F[k-1]``, ``S[k] = 1 - F[k]``,
``q[k] = m[k] / S[k-1]``. Conditional PDs are never summed. The curves hold whole years; R8
takes a part-year bucket pro rata (A7). ``stub_pd`` keeps the constant-hazard convention
``1 - (1 - PD)^d`` (PD-06) for the uses outside the ECL.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from stress.contracts.errors import Block, BlockingError


@dataclass(frozen=True)
class Curve:
    q: np.ndarray  # conditional PD of each bucket
    m: np.ndarray  # marginal (unconditional) PD
    s: np.ndarray  # survival at the end of each bucket
    f: np.ndarray  # cumulative PD


def curve_from_conditional(q: Sequence[float]) -> Curve:
    """PD-03: ``m[k] = S[k-1] q[k]``, ``S[k] = S[k-1](1 - q[k])``, ``F[k] = 1 - S[k]``."""
    q = np.asarray(q, dtype=float)
    s = np.cumprod(1.0 - q)
    s_prev = np.concatenate(([1.0], s[:-1]))
    m = s_prev * q
    return Curve(q=q, m=m, s=s, f=1.0 - s)


def curve_from_cumulative(f: np.ndarray) -> Curve:
    """Marginal, survival and conditional PD from a cumulative curve F[1..K] (PD-11)."""
    f = np.asarray(f, dtype=float)
    f_prev = np.concatenate(([0.0], f[:-1]))
    m = f - f_prev
    s = 1.0 - f
    s_prev = 1.0 - f_prev
    with np.errstate(invalid="ignore", divide="ignore"):
        q = np.where(s_prev > 0, m / np.where(s_prev > 0, s_prev, 1.0), 0.0)
    return Curve(q=q, m=m, s=s, f=f)


def stub_pd(annual_pd, fraction):
    """PD for a stub interval of ``fraction`` years: ``1 - (1 - q)^d`` (PD-06)."""
    return 1.0 - (1.0 - np.asarray(annual_pd, dtype=float)) ** fraction


def curve_problems(curve: Curve, tol: float) -> list[str]:
    """PD-03 identity and bound checks on one curve."""
    problems = []
    for name in ("q", "m", "s", "f"):
        values = getattr(curve, name)
        if not np.all(np.isfinite(values)):
            problems.append(f"{name} not finite")
            continue
        if (values < -tol).any() or (values > 1 + tol).any():
            problems.append(f"{name} outside [0, 1]")
    if (np.diff(curve.f) < -tol).any():
        problems.append("cumulative PD decreases")
    if (np.diff(curve.s) > tol).any():
        problems.append("survival increases")
    if (np.abs(curve.f + curve.s - 1.0) > tol).any():
        problems.append("F + S differs from 1")
    if (np.abs(np.cumsum(curve.m) - curve.f) > tol).any():
        problems.append("F differs from the sum of marginal PDs")
    return problems


def check_curve(curve: Curve, tol: float, step: str, name: str) -> None:
    problems = curve_problems(curve, tol)
    if problems:
        raise BlockingError(step, Block.PD_IDENTITY, f"{name}: " + "; ".join(problems))


def grade_distributions(matrices: Sequence[np.ndarray]) -> np.ndarray:
    """``P[k] = M(y+1) x ... x M(y+k)`` for k = 0..K, stacked; P[0] is the identity."""
    size = matrices[0].shape[0] if matrices else 1
    out = np.empty((len(matrices) + 1, size, size))
    out[0] = np.eye(size)
    for k, m in enumerate(matrices, start=1):
        out[k] = out[k - 1] @ m
    return out


def cumulative_pd(matrices: Sequence[np.ndarray]) -> np.ndarray:
    """F[g, k] for every start grade g (rows) and bucket k = 1..K (columns)."""
    dist = grade_distributions(matrices)
    return dist[1:, :-1, -1].T


def stub_marginal(distribution: np.ndarray, next_matrix: np.ndarray, fraction: float) -> np.ndarray:
    """Marginal PD of a stub bucket per start grade.

    ``distribution`` is P[n] (grade distribution at the start of the stub, from each start
    grade); within the stub each performing grade defaults with ``1 - (1 - PD_j)^d``.
    """
    pd_next = stub_pd(next_matrix[:-1, -1], fraction)
    return distribution[:-1, :-1] @ pd_next


def lifetime_pd_ttc(ttc: np.ndarray, horizon: float) -> np.ndarray:
    """Lifetime PD of every performing grade over ``horizon`` years under the TTC matrix."""
    whole = int(np.floor(horizon + 1e-9))
    stub = horizon - whole
    power = np.linalg.matrix_power(ttc, whole)
    f = power[:-1, -1].copy()
    if stub > 1e-9:
        f = f + stub_marginal(power, ttc, stub)
    return f
