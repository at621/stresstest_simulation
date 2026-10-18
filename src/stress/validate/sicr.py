"""The SICR line of each facility under MIG-07.

A performing grade slice is S2 when its lifetime PD is at least k times the lifetime PD at the
origination grade. Both come from the segment's TTC matrix over the same horizon: the
facility's residual maturity at the opening date (assumption A6). The line is therefore fixed
per facility, and only rating moves change stage. A stub final year uses the constant-hazard
convention per grade (PD-06).
"""

import numpy as np

EPS = 1e-9


class TtcLifetime:
    """Lifetime TTC PD per performing grade for any horizon, cached per segment."""

    def __init__(self, matrices: dict[str, np.ndarray]):
        self.matrices = matrices
        self._cache: dict[tuple[str, float], np.ndarray] = {}
        self._powers: dict[tuple[str, int], np.ndarray] = {}

    def _power(self, segment: str, years: int) -> np.ndarray:
        key = (segment, years)
        if key not in self._powers:
            self._powers[key] = np.linalg.matrix_power(self.matrices[segment], years)
        return self._powers[key]

    def pd(self, segment: str, horizon: float) -> np.ndarray:
        key = (segment, round(horizon, 9))
        if key not in self._cache:
            whole = int(np.floor(horizon + EPS))
            stub = horizon - whole
            power = self._power(segment, whole)
            f = power[:-1, -1].copy()
            if stub > EPS:
                ttc = self.matrices[segment]
                stub_pd = 1.0 - (1.0 - ttc[:-1, -1]) ** stub
                f = f + power[:-1, :-1] @ stub_pd
            self._cache[key] = f
        return self._cache[key]


def sicr_rank(lifetime: np.ndarray, origination_rank: int, k: float) -> tuple[int, bool]:
    """Lowest grade rank that is S2 for this origination grade, and whether the S2 grades
    form one contiguous block at the bad end of the scale (they do when lifetime PD rises
    with the grade). Returns N + 1 when no performing grade is S2."""
    n = len(lifetime)
    threshold = k * lifetime[origination_rank - 1]
    s2 = lifetime >= threshold
    if not s2.any():
        return n + 1, True
    first = int(np.argmax(s2)) + 1
    contiguous = bool(s2[first - 1:].all())
    return first, contiguous
