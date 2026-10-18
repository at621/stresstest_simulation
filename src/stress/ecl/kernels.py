"""Provision arithmetic (ECL-01-ECL-11).

Performing: ``ECL = sum_k m[k] x EAD[k] x LGD[k] x DF[k]``; survival is applied once, through
the marginal PD, and DF discounts once from default date to valuation date. S3 allowances are
floored per exposure; a new S3 flow is already default-weighted, so no PD is applied to it.
"""

import numpy as np


def ecl(m, ead, lgd, df) -> float:
    """Sum of marginal PD x EAD x LGD x DF over the buckets given (ECL-08)."""
    m, ead, lgd, df = (np.asarray(x, dtype=float) for x in (m, ead, lgd, df))
    return float(np.sum(m * ead * lgd * df))


def ecl_split(m, ead_drawn, ead_undrawn, lgd, df) -> tuple[float, float]:
    """Drawn part to the on-balance allowance, undrawn part to the off-balance provision."""
    return ecl(m, ead_drawn, lgd, df), ecl(m, ead_undrawn, lgd, df)


def s1_loss_rate_provision(exposure: float, pd: float, lgd: float, df: float = 1.0) -> float:
    """12-month provision with a single bucket: exposure x PD x LGD x DF (AT-05)."""
    return exposure * pd * lgd * df


def interpolated_loss_rate(adverse_pd, adverse_lgd, baseline_pd, baseline_lgd, weight):
    """End-2029 S1 loss rate for the 2030 bucket: ``a x LR_adv + (1 - a) x LR_base``.

    The loss rate is interpolated as a product; PD and LGD are not interpolated separately
    (ECL-05, ECL-10, AT-06).
    """
    adverse = np.asarray(adverse_pd) * np.asarray(adverse_lgd)
    baseline = np.asarray(baseline_pd) * np.asarray(baseline_lgd)
    return weight * adverse + (1.0 - weight) * baseline


def floor_per_exposure(raw, prior) -> tuple[np.ndarray, np.ndarray]:
    """No-release rule applied to each exposure, never to the total (ECL-07, AT-18).

    Returns the constrained allowances and a mask of the exposures whose raw value would
    have released provision.
    """
    raw = np.asarray(raw, dtype=float)
    prior = np.asarray(prior, dtype=float)
    released = raw < prior
    return np.maximum(raw, prior), released


def s3_original_allowance(gca, lgd, prior) -> tuple[np.ndarray, np.ndarray]:
    """Original S3: ``max(GCA x LGD of the year, prior allowance)`` per exposure (ECL-11)."""
    raw = np.asarray(gca, dtype=float) * np.asarray(lgd, dtype=float)
    constrained, _ = floor_per_exposure(raw, prior)
    return raw, constrained


def s3_new_booking(flow, lgd):
    """New S3 cohort, booked once in its entry year: flow x LGD of the default year (ECL-11)."""
    return np.asarray(flow, dtype=float) * np.asarray(lgd, dtype=float)


def monetary_loss(ead: float, lgd: float | None) -> tuple[float, float | None]:
    """Zero EAD gives zero loss and an LGD that is not applicable (AT-33)."""
    if ead == 0:
        return 0.0, None
    return ead * lgd, lgd
