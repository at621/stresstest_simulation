"""Prepayment rate by Z and the share not yet prepaid, SP[k] (EAD-11).

``CPR[t] = Phi(Phi^-1(CPR_TTC) + v * Z[t])`` and ``SP[k] = (1 - CPR[1]) x ... x (1 - CPR[k-1])``
with ``SP[1] = 1``. Prepayment is applied once, in EAD; never in the default survival.
"""

import numpy as np
from scipy.special import ndtr, ndtri


def prepayment_rate(cpr_ttc, v, z):
    cpr_ttc = np.asarray(cpr_ttc, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = ndtr(ndtri(cpr_ttc) + np.asarray(v, dtype=float) * np.asarray(z, dtype=float))
    return np.where(cpr_ttc <= 0.0, 0.0, np.where(cpr_ttc >= 1.0, 1.0, out))


def not_prepaid_share(cpr_by_bucket) -> np.ndarray:
    """SP[k] for buckets k = 1..K from the prepayment rate of each bucket's year."""
    cpr = np.asarray(cpr_by_bucket, dtype=float)
    sp = np.cumprod(1.0 - cpr)
    return np.concatenate(([1.0], sp[:-1])) if sp.size else sp
