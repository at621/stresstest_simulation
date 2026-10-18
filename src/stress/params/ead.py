"""EAD per default date: drawn, undrawn and total; regulatory EAD bridge kept apart
(EAD-02-EAD-04, EAD-07, EAD-11).

EAD is conditional on default: it is never multiplied by PD or survival here. The accounting
CCF is applied once in the accounting calculation and the regulatory CCF once in the regulatory
one, never in sequence.
"""

from dataclasses import dataclass

import numpy as np

from stress.contracts.errors import Block, BlockingError

STEP = "R6"


@dataclass(frozen=True)
class Ead:
    drawn: np.ndarray
    undrawn: np.ndarray
    total: np.ndarray


def check_ccf(ccf, undrawn) -> None:
    """EAD-04: 0 <= c <= 1; a missing CCF on a positive undrawn amount blocks."""
    ccf = np.asarray(ccf, dtype=float)
    undrawn = np.asarray(undrawn, dtype=float)
    if (np.isnan(ccf) & (undrawn > 0)).any():
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "missing CCF on a positive undrawn amount")
    valid = ccf[~np.isnan(ccf)]
    if ((valid < 0) | (valid > 1)).any():
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "CCF outside [0, 1]")
    if (undrawn < 0).any():
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "negative undrawn amount")


def ead(balance, undrawn, ccf, not_prepaid=1.0) -> Ead:
    """``EAD_drawn = B x SP``, ``EAD_undrawn = U x CCF`` (not prepaid), total = their sum."""
    balance = np.asarray(balance, dtype=float)
    undrawn = np.asarray(undrawn, dtype=float)
    ccf = np.nan_to_num(np.asarray(ccf, dtype=float), nan=0.0)
    drawn = balance * np.asarray(not_prepaid, dtype=float)
    undrawn_ead = undrawn * ccf
    return Ead(drawn=drawn, undrawn=undrawn_ead, total=drawn + undrawn_ead)


def utilisation_sensitivity(drawn: float, undrawn: float, ccf_from: float, ccf_to: float) -> dict:
    """EAD-06: change the accounting CCF only; nominal balances stay as they are."""
    before = ead(drawn, undrawn, ccf_from)
    after = ead(drawn, undrawn, ccf_to)
    return {
        "ead_from": float(before.total), "ead_to": float(after.total),
        "ead_change": float(after.total - before.total),
        "nominal_drawn": drawn, "nominal_undrawn": undrawn,
    }


def permitted_transfer(drawn: float, undrawn: float, transfer: float, ccf: float) -> dict:
    """EAD-06: a permitted drawdown moves ``transfer`` from undrawn to drawn before the CCF
    applies to the remainder; the limit is unchanged and the transfer is not counted twice."""
    if transfer < 0 or transfer > undrawn:
        raise ValueError("transfer must be between 0 and the undrawn amount")
    new_drawn = drawn + transfer
    new_undrawn = undrawn - transfer
    result = ead(new_drawn, new_undrawn, ccf)
    return {"drawn": new_drawn, "undrawn": new_undrawn, "limit": drawn + undrawn,
            "ead_total": float(result.total)}


def regulatory_bridge(drawn: float, undrawn: float, accounting_ccf: float,
                      regulatory_ccf: float, other_adjustments: float = 0.0) -> dict:
    """EAD-07: accounting EAD and regulatory EAD, each with its own CCF, and the bridge."""
    accounting = float(ead(drawn, undrawn, accounting_ccf).total)
    regulatory = float(ead(drawn, undrawn, regulatory_ccf).total) + other_adjustments
    return {
        "accounting_ead": accounting,
        "regulatory_ead": regulatory,
        "ccf_bridge": undrawn * (regulatory_ccf - accounting_ccf),
        "other_adjustments": other_adjustments,
    }
