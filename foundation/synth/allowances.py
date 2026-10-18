"""O4: end-2026 allowances from the generator's own formula, frozen as opening_provisions.

SYN-PAR-09 and D8, with assumption A8: PD curves from the TTC matrix itself (no Z shift),
TTC LGD, the TTC prepayment rate, and a bullet schedule at the facility's rate and residual
maturity. S1 takes the first bucket, S2 the lifetime. S3 is GCA x TTC LGD. The drawn part is
the on-balance allowance, the undrawn part the off-balance provision.

This code is independent of the engine: the run never recomputes these values, and any
difference from the engine's own formula shows as a first-year charge in R9.
"""

import numpy as np
import pandas as pd

EPS = 1e-9


def _fractions(maturity: float) -> np.ndarray:
    whole = int(np.floor(maturity + EPS))
    stub = maturity - whole
    return np.array([1.0] * whole + ([stub] if stub > EPS else []))


def marginal_pd(matrix: np.ndarray, rank: int, fractions: np.ndarray) -> np.ndarray:
    """Marginal TTC PD per bucket for a start grade; a stub uses 1 - (1 - PD)^d per grade."""
    n = matrix.shape[0] - 1
    state = np.zeros(n + 1)
    state[rank - 1] = 1.0
    out = np.empty(len(fractions))
    for k, frac in enumerate(fractions):
        if frac >= 1.0 - EPS:
            nxt = state @ matrix
            out[k] = nxt[-1] - state[-1]
            state = nxt
        else:
            out[k] = state[:n] @ (1.0 - (1.0 - matrix[:n, -1]) ** frac)
    return out


def opening_allowances(facilities: pd.DataFrame, commitments: pd.DataFrame,
                       matrices: dict[str, np.ndarray], params: dict, grades: list[str],
                       snapshot: str) -> pd.DataFrame:
    rank = {g: i + 1 for i, g in enumerate(grades)}
    undrawn = commitments.set_index("facility_id")["nominal_undrawn"]
    ccf = commitments.set_index("facility_id")["accounting_ccf"]
    rows = []
    for f in facilities.itertuples(index=False):
        u = float(undrawn.get(f.facility_id, 0.0))
        c = float(ccf.get(f.facility_id, 0.0)) if u > 0 else 0.0
        if f.ifrs_stage == 3:
            on, off = f.gca * f.ttc_lgd, u * c * f.ttc_lgd
        else:
            seg = params["segments"][f.segment]
            fractions = _fractions(f.residual_maturity)
            if f.ifrs_stage == 1:
                fractions = fractions[:1]
            m = marginal_pd(matrices[f.segment], rank[f.current_grade], fractions)
            t = np.cumsum(fractions)
            df = (1.0 + f.interest_rate) ** (-t)
            survival_prepay = (1.0 - seg["cpr_ttc"]) ** np.arange(len(fractions))
            on = float(np.sum(m * f.gca * survival_prepay * f.ttc_lgd * df))
            off = float(np.sum(m * u * c * f.ttc_lgd * df))
        rows.append({
            "facility_id": f.facility_id, "currency": "EUR", "allowance_on": on,
            "provision_off": off, "overlay_amount": 0.0,
            "overlay_risk": None, "overlay_risk__status": "not_applicable",
            "overlay_owner": None, "overlay_owner__status": "not_applicable",
            "overlay_reason": None, "overlay_reason__status": "not_applicable",
            "method": "O4 TTC formula v1 (SYN-PAR-09)", "frozen": True, "snapshot_date": snapshot,
        })
    return pd.DataFrame(rows)
