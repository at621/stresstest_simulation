"""P04 Commercial real estate: the models of segment P04.

The parameter set names each one as ``p04.<function>``. Each docstring is the model's
description, shown as written in the control room.
"""

from stress.models.forms import linear, supplied
from stress.models.registry import Economy, Score, lgd_model, pd_model, prepayment_model


@pd_model
def pd(economy: Economy) -> Score:
    """Commercial real estate: PD model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the annual
    change in commercial real estate prices and the reference interest rate. Each driver is
    standardised by its long-run mean and standard deviation and weighted by its beta. Z > 0 is
    a better economy than average.

    The engine shifts the segment's TTC matrix with this Z and the segment's asset correlation,
    so Z = 0 gives back the TTC matrix.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.3, "mean": 0.015, "sd": 0.03},
        "cre_price_change": {"beta": 0.5, "mean": 0.02, "sd": 0.1},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })


@lgd_model(sensitivity=0.25)
def lgd(economy: Economy) -> Score:
    """Commercial real estate: LGD model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the annual
    change in commercial real estate prices and the reference interest rate. Each driver is
    standardised by its long-run mean and standard deviation and weighted by its beta. Z > 0 is
    a better economy than average.

    Each facility's LGD moves from its TTC LGD with this Z and a sensitivity of 0.25:
    LGD = Phi(Phi^-1(TTC LGD) - 0.25 x Z), so Z = 0 gives back the TTC LGD.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.3, "mean": 0.015, "sd": 0.03},
        "cre_price_change": {"beta": 0.5, "mean": 0.02, "sd": 0.1},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })


@prepayment_model(sensitivity=0.15)
def prepayment(economy: Economy) -> Score:
    """Commercial real estate: prepayment model.

    Z is the linear score of three scenario drivers in the year: real GDP growth, the annual
    change in commercial real estate prices and the reference interest rate. Each driver is
    standardised by its long-run mean and standard deviation and weighted by its beta. Z > 0 is
    a better economy than average.

    The prepayment rate moves from the segment's TTC rate with this Z and a sensitivity of
    0.15, so Z = 0 gives back the TTC rate.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.3, "mean": 0.015, "sd": 0.03},
        "cre_price_change": {"beta": 0.5, "mean": 0.02, "sd": 0.1},
        "reference_rate": {"beta": -0.2, "mean": 0.025, "sd": 0.015},
    })


# Illustrative models for the workflow walkthrough (docs/run-workflow/): scores taken as given, as
# from an external CRE model, the same in every country.
EXTERNAL_SCORES = {
    ("baseline", 2027): 0.00, ("baseline", 2028): 0.07, ("baseline", 2029): 0.12,
    ("adverse", 2027): -1.80, ("adverse", 2028): -1.50, ("adverse", 2029): -0.70,
    ("energy_crisis", 2027): -2.40, ("energy_crisis", 2028): -1.90, ("energy_crisis", 2029): -0.90,
}


@pd_model
def pd_external(economy: Economy) -> Score:
    """Commercial real estate: illustrative scores standing in for an external CRE model.

    Z is not computed here: it is taken as given for each scenario and year, the same in every
    country, for the baseline, adverse and energy_crisis scenarios of the workflow walkthrough. Any
    other scenario or year has no score, and the run stops on it.

    Scores: illustrative; not the output of a real model.
    """
    return supplied(economy, EXTERNAL_SCORES)


@lgd_model(sensitivity=0.25)
def lgd_external(economy: Economy) -> Score:
    """Commercial real estate: illustrative external scores, used for LGD.

    The same given scores as the illustrative external PD model, with the segment's own LGD
    sensitivity of 0.25.

    Scores: illustrative; not the output of a real model.
    """
    return supplied(economy, EXTERNAL_SCORES)


@prepayment_model(sensitivity=0.15)
def prepayment_external(economy: Economy) -> Score:
    """Commercial real estate: illustrative external scores, used for prepayment.

    The same given scores as the illustrative external PD model, with the segment's own prepayment
    sensitivity of 0.15.

    Scores: illustrative; not the output of a real model.
    """
    return supplied(economy, EXTERNAL_SCORES)
