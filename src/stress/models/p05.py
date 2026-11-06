"""P05 Corporate lending: the models of segment P05.

The parameter set names each one as ``p05.<function>``. Each docstring is the model's
description, shown as written in the control room.
"""

from stress.models.forms import linear
from stress.models.registry import Economy, Score, lgd_model, pd_model, prepayment_model


@pd_model
def pd(economy: Economy) -> Score:
    """Corporate lending: PD model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the reference
    interest rate. Each driver is standardised by its long-run mean and standard deviation and
    weighted by its beta. Z > 0 is a better economy than average.

    The engine shifts the segment's TTC matrix with this Z and the segment's asset correlation,
    so Z = 0 gives back the TTC matrix.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.7, "mean": 0.015, "sd": 0.03},
        "reference_rate": {"beta": -0.3, "mean": 0.025, "sd": 0.015},
    })


@lgd_model(sensitivity=0.15)
def lgd(economy: Economy) -> Score:
    """Corporate lending: LGD model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the reference
    interest rate. Each driver is standardised by its long-run mean and standard deviation and
    weighted by its beta. Z > 0 is a better economy than average.

    Each facility's LGD moves from its TTC LGD with this Z and a sensitivity of 0.15:
    LGD = Phi(Phi^-1(TTC LGD) - 0.15 x Z), so Z = 0 gives back the TTC LGD.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.7, "mean": 0.015, "sd": 0.03},
        "reference_rate": {"beta": -0.3, "mean": 0.025, "sd": 0.015},
    })


@prepayment_model(sensitivity=0.15)
def prepayment(economy: Economy) -> Score:
    """Corporate lending: prepayment model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the reference
    interest rate. Each driver is standardised by its long-run mean and standard deviation and
    weighted by its beta. Z > 0 is a better economy than average.

    The prepayment rate moves from the segment's TTC rate with this Z and a sensitivity of
    0.15, so Z = 0 gives back the TTC rate.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.7, "mean": 0.015, "sd": 0.03},
        "reference_rate": {"beta": -0.3, "mean": 0.025, "sd": 0.015},
    })


# Illustrative models for the workflow walkthrough (docs/run-workflow/), for the energy firms it
# carves out of P05: the segment it creates inherits P05's models, so these belong to P05.
ENERGY = {
    "gdp_growth": {"beta": 0.5, "mean": 0.015, "sd": 0.03},
    "energy_price_change": {"beta": -0.5, "mean": 0.03, "sd": 0.15},
}


@pd_model
def pd_energy(economy: Economy) -> Score:
    """Corporate lending, energy firms: illustrative PD model, for the workflow walkthrough.

    Z is the linear score of real GDP growth and the annual change in energy prices, each
    standardised by its mean and standard deviation and weighted by its beta. Higher energy prices
    lower Z. The walkthrough supplies the energy price path; the base scenarios have none.

    Coefficients: illustrative; not estimates.
    """
    return linear(economy, ENERGY)


@lgd_model(sensitivity=0.15)
def lgd_energy(economy: Economy) -> Score:
    """Corporate lending, energy firms: illustrative LGD model, for the workflow walkthrough.

    The same score as the illustrative energy PD model, with the segment's own LGD sensitivity
    of 0.15.

    Coefficients: illustrative; not estimates.
    """
    return linear(economy, ENERGY)


@prepayment_model(sensitivity=0.15)
def prepayment_energy(economy: Economy) -> Score:
    """Corporate lending, energy firms: illustrative prepayment model, for the workflow walkthrough.

    The same score as the illustrative energy PD model, with the segment's own prepayment
    sensitivity of 0.15.

    Coefficients: illustrative; not estimates.
    """
    return linear(economy, ENERGY)
