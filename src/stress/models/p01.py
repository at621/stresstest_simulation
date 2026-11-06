"""P01 Residential mortgages: the models of segment P01.

The parameter set names each one as ``p01.<function>``. Each docstring is the model's
description, shown as written in the control room.
"""

from stress.models.forms import linear
from stress.models.registry import Economy, Score, lgd_model, pd_model, prepayment_model


@pd_model
def pd(economy: Economy) -> Score:
    """Residential mortgages: PD model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the
    unemployment level and the annual change in residential property prices. Each driver is
    standardised by its long-run mean and standard deviation and weighted by its beta. Z > 0 is
    a better economy than average.

    The engine shifts the segment's TTC matrix with this Z and the segment's asset correlation,
    so Z = 0 gives back the TTC matrix.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.4, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.3, "mean": 0.065, "sd": 0.02},
        "residential_price_change": {"beta": 0.3, "mean": 0.025, "sd": 0.08},
    })


@lgd_model(sensitivity=0.2)
def lgd(economy: Economy) -> Score:
    """Residential mortgages: LGD model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the
    unemployment level and the annual change in residential property prices. Each driver is
    standardised by its long-run mean and standard deviation and weighted by its beta. Z > 0 is
    a better economy than average.

    Each facility's LGD moves from its TTC LGD with this Z and a sensitivity of 0.2:
    LGD = Phi(Phi^-1(TTC LGD) - 0.2 x Z), so Z = 0 gives back the TTC LGD.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.4, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.3, "mean": 0.065, "sd": 0.02},
        "residential_price_change": {"beta": 0.3, "mean": 0.025, "sd": 0.08},
    })


@prepayment_model(sensitivity=0.25)
def prepayment(economy: Economy) -> Score:
    """Residential mortgages: prepayment model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the
    unemployment level and the annual change in residential property prices. Each driver is
    standardised by its long-run mean and standard deviation and weighted by its beta. Z > 0 is
    a better economy than average.

    The prepayment rate moves from the segment's TTC rate with this Z and a sensitivity of
    0.25, so Z = 0 gives back the TTC rate.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.4, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.3, "mean": 0.065, "sd": 0.02},
        "residential_price_change": {"beta": 0.3, "mean": 0.025, "sd": 0.08},
    })
