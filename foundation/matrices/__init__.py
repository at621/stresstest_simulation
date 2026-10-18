"""O2: build the TTC PD matrices, one per reference segment.

Shared master scale of N performing grades plus default D. Rows sum to 1, D is absorbing
and PD rises with the grade. Calibrated to the section 8.7 S1 and S2 PDs.

PD-09, SYN-PAR-05.

The D column of every matrix is the master-scale PD of the grade. Calibration (SYN-PAR-05) is
the grade mix: for each segment and stage, weights over a window of grades whose
exposure-weighted average one-year TTC PD equals the section 8.7 target exactly. O3 assigns
facilities and GCA to grades with these weights.
"""

import numpy as np
import pandas as pd

DEFAULT = "D"
WINDOW_FACTOR = 3.0  # grades within a factor 3 of a stage target form its calibration window


def build_matrix(pd_by_grade: np.ndarray, stay: float, downgrade_share: float, decay: float) -> np.ndarray:
    """One TTC matrix: the D column is the master scale; the rest of each row stays in its
    grade with probability ``stay`` or moves, geometrically less likely the further it goes."""
    n = len(pd_by_grade)
    m = np.zeros((n + 1, n + 1))
    for i in range(n):
        alive = 1.0 - pd_by_grade[i]
        moving = alive * (1.0 - stay)
        down = np.array([decay ** (j - i - 1) for j in range(i + 1, n)])
        up = np.array([decay ** (i - 1 - j) for j in range(i)])
        down_mass = moving * downgrade_share if down.size else 0.0
        up_mass = moving * (1.0 - downgrade_share) if up.size else 0.0
        if down.size:
            m[i, i + 1:n] = down_mass * down / down.sum()
        if up.size:
            m[i, :i] = up_mass * up / up.sum()
        m[i, i] = alive - down_mass - up_mass
        m[i, n] = pd_by_grade[i]
    m[n, n] = 1.0
    return m


def matrix_problems(m: np.ndarray, tol: float) -> list[str]:
    """AT-45: rows sum to one, no negative cell, D absorbing; PD rises with the grade."""
    problems = []
    if (np.abs(m.sum(axis=1) - 1.0) > tol).any():
        problems.append("row sum")
    if (m < 0).any():
        problems.append("negative cell")
    if not (m[-1, -1] == 1.0 and np.all(m[-1, :-1] == 0.0)):
        problems.append("D not absorbing")
    if not np.all(np.diff(m[:-1, -1]) > 0):
        problems.append("PD does not rise with the grade")
    return problems


def lifetime_pd(m: np.ndarray, horizon: float) -> np.ndarray:
    """Lifetime TTC PD per performing grade; a stub year uses 1 - (1 - PD)^d per grade."""
    whole = int(np.floor(horizon + 1e-9))
    stub = horizon - whole
    power = np.linalg.matrix_power(m, whole)
    f = power[:-1, -1].copy()
    if stub > 1e-9:
        f = f + power[:-1, :-1] @ (1.0 - (1.0 - m[:-1, -1]) ** stub)
    return f


def lifetime_monotone(m: np.ndarray, max_years: int) -> bool:
    """Lifetime PD rises with the grade at every whole and half-year horizon up to max_years."""
    for half_years in range(1, 2 * max_years + 1):
        if not np.all(np.diff(lifetime_pd(m, half_years / 2)) > 0):
            return False
    return True


def tilt_weights(pds: np.ndarray, target: float) -> np.ndarray:
    """Weights w_g proportional to exp(theta * ln PD_g) with sum(w * PD) = target exactly."""
    if not pds.min() < target < pds.max():
        if len(pds) == 1 and abs(pds[0] - target) < 1e-15:
            return np.array([1.0])
        raise ValueError(f"target {target} is not inside the window {pds.tolist()}")
    logp = np.log(pds)

    def mean(theta: float) -> float:
        w = np.exp(theta * (logp - logp.mean()))
        w = w / w.sum()
        return float(w @ pds)

    lo, hi = -200.0, 200.0
    for _ in range(300):
        mid = (lo + hi) / 2
        if mean(mid) < target:
            lo = mid
        else:
            hi = mid
    w = np.exp(((lo + hi) / 2) * (logp - logp.mean()))
    w = w / w.sum()
    # Remove the last rounding residual on the two outer grades so the mean is exact.
    residual = target - float(w @ pds)
    w[-1] += residual / (pds[-1] - pds[0])
    w[0] -= residual / (pds[-1] - pds[0])
    return w


def calibration_window(pds: np.ndarray, target: float, pd_range: tuple[float, float],
                       min_rank: int = 1) -> np.ndarray:
    """Indices of the grades that may hold a stage: inside the portfolio's section 5.4 PD
    range, within a factor of the target, and at or after ``min_rank``."""
    lo, hi = pd_range
    idx = [
        g for g, p in enumerate(pds)
        if lo - 1e-12 <= p <= hi + 1e-12 and target / WINDOW_FACTOR <= p <= target * WINDOW_FACTOR
        and g + 1 >= min_rank
    ]
    window = np.array(idx)
    if window.size == 0 or not (pds[window].min() < target < pds[window].max()):
        raise ValueError(f"no calibration window brackets {target} in {pd_range}")
    return window


def calibration_plan(pds: np.ndarray, calibration: dict, profiles: dict) -> dict[str, dict]:
    """Grade weights per segment and stage (SYN-PAR-05). S2 grades start at G2, so a better
    origination grade exists for the SICR rule."""
    plan = {}
    for seg, cal in calibration["segments"].items():
        pd_range = tuple(profiles[cal["portfolio"]]["performing_pd"])
        plan[seg] = {}
        for stage, target, min_rank in ((1, cal["s1_pd"], 1), (2, cal["s2_pd"], 2)):
            window = calibration_window(pds, target, pd_range, min_rank)
            weights = tilt_weights(pds[window], target)
            plan[seg][stage] = {int(g) + 1: float(w) for g, w in zip(window, weights)}
    return plan


def build_matrices(params: dict) -> dict[str, np.ndarray]:
    pds = np.array(params["master_scale"]["ttc_pd"], dtype=float)
    return {
        seg: build_matrix(pds, **shape) for seg, shape in params["migration"].items()
    }


def matrix_table(matrices: dict[str, np.ndarray], grades: list[str]) -> pd.DataFrame:
    """The ttc_pd_matrix dataset: one row per segment, from grade and to grade."""
    labels = list(grades) + [DEFAULT]
    rows = []
    for seg in sorted(matrices):
        m = matrices[seg]
        for i, src in enumerate(labels):
            for j, dst in enumerate(labels):
                rows.append({
                    "segment": seg, "from_grade": src, "to_grade": dst,
                    "probability": float(m[i, j]), "from_rank": i + 1, "to_rank": j + 1,
                    "master_scale_pd": float(m[i, -1]),
                })
    return pd.DataFrame(rows)
