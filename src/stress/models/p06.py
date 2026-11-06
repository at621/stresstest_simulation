"""P06 Sovereigns and credit institutions: the models of segments P06_GG, P06_CI.

The parameter set names each one as ``p06.<function>``. Each docstring is the model's
description, shown as written in the control room.
"""

from stress.models.forms import linear
from stress.models.registry import Economy, Score, lgd_model, pd_model, prepayment_model


@pd_model
def gg_pd(economy: Economy) -> Score:
    """Sovereigns and credit institutions, general governments (P06_GG): PD model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the reference
    interest rate. Each driver is standardised by its long-run mean and standard deviation and
    weighted by its beta. Z > 0 is a better economy than average.

    The engine shifts the segment's TTC matrix with this Z and the segment's asset correlation,
    so Z = 0 gives back the TTC matrix.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.8, "mean": 0.015, "sd": 0.03},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })


@lgd_model(sensitivity=0.1)
def gg_lgd(economy: Economy) -> Score:
    """Sovereigns and credit institutions, general governments (P06_GG): LGD model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the reference
    interest rate. Each driver is standardised by its long-run mean and standard deviation and
    weighted by its beta. Z > 0 is a better economy than average.

    Each facility's LGD moves from its TTC LGD with this Z and a sensitivity of 0.1:
    LGD = Phi(Phi^-1(TTC LGD) - 0.1 x Z), so Z = 0 gives back the TTC LGD.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.8, "mean": 0.015, "sd": 0.03},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })


@prepayment_model(sensitivity=0.0)
def gg_prepayment(economy: Economy) -> Score:
    """Sovereigns and credit institutions, general governments (P06_GG): prepayment model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the reference
    interest rate. Each driver is standardised by its long-run mean and standard deviation and
    weighted by its beta. Z > 0 is a better economy than average.

    The sensitivity is 0, so the prepayment rate stays at the segment's TTC rate in every
    year; the score is still recorded.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.8, "mean": 0.015, "sd": 0.03},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })


@pd_model
def ci_pd(economy: Economy) -> Score:
    """Sovereigns and credit institutions, credit institutions (P06_CI): PD model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the
    unemployment level and the reference interest rate. Each driver is standardised by its
    long-run mean and standard deviation and weighted by its beta. Z > 0 is a better economy
    than average.

    The engine shifts the segment's TTC matrix with this Z and the segment's asset correlation,
    so Z = 0 gives back the TTC matrix.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.6, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.2, "mean": 0.065, "sd": 0.02},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })


@lgd_model(sensitivity=0.1)
def ci_lgd(economy: Economy) -> Score:
    """Sovereigns and credit institutions, credit institutions (P06_CI): LGD model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the
    unemployment level and the reference interest rate. Each driver is standardised by its
    long-run mean and standard deviation and weighted by its beta. Z > 0 is a better economy
    than average.

    Each facility's LGD moves from its TTC LGD with this Z and a sensitivity of 0.1:
    LGD = Phi(Phi^-1(TTC LGD) - 0.1 x Z), so Z = 0 gives back the TTC LGD.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.6, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.2, "mean": 0.065, "sd": 0.02},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })


@prepayment_model(sensitivity=0.0)
def ci_prepayment(economy: Economy) -> Score:
    """Sovereigns and credit institutions, credit institutions (P06_CI): prepayment model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the
    unemployment level and the reference interest rate. Each driver is standardised by its
    long-run mean and standard deviation and weighted by its beta. Z > 0 is a better economy
    than average.

    The sensitivity is 0, so the prepayment rate stays at the segment's TTC rate in every
    year; the score is still recorded.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.6, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.2, "mean": 0.065, "sd": 0.02},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })
