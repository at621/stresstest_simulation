"""LGD of the year from TTC LGD and Z (LGD-12).

``LGD[k] = Phi(Phi^-1(LGD_TTC) - w * Z[k])``: Z = 0 returns LGD_TTC, a worse economy raises
LGD, the result stays in [0, 1] without a cap, and an LGD_TTC of 0 or 1 passes through.
"""

import numpy as np
from scipy.special import ndtr, ndtri


def lgd_from_z(lgd_ttc, w, z):
    lgd_ttc = np.asarray(lgd_ttc, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = ndtr(ndtri(lgd_ttc) - np.asarray(w, dtype=float) * np.asarray(z, dtype=float))
    # Phi(Phi^-1(x)) is not exactly x in floating point; 0 and 1 pass through exactly.
    return np.where(lgd_ttc <= 0.0, 0.0, np.where(lgd_ttc >= 1.0, 1.0, out))


def loss_weighted_lgd(m, ead, lgd) -> tuple[float, float, float | None]:
    """``sum(m EAD LGD) / sum(m EAD)`` with its numerator and denominator (RPT-06).

    Returns None as the value when the denominator is zero: LGD is not applicable.
    """
    m, ead, lgd = (np.asarray(x, dtype=float) for x in (m, ead, lgd))
    num = float(np.sum(m * ead * lgd))
    den = float(np.sum(m * ead))
    return num, den, (num / den if den > 0 else None)
