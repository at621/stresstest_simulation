"""P02 Consumer credit: the models of segment P02.

The parameter set names each one as ``p02.<function>``. Each docstring is the model's
description, shown as written in the control room.
"""

from stress.models.forms import linear, polynomial
from stress.models.registry import Economy, Score, lgd_model, pd_model, prepayment_model


@pd_model
def pd(economy: Economy) -> Score:
    """Consumer credit: PD model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the
    unemployment level. Each driver is standardised by its long-run mean and standard deviation
    and weighted by its beta. Z > 0 is a better economy than average.

    The engine shifts the segment's TTC matrix with this Z and the segment's asset correlation,
    so Z = 0 gives back the TTC matrix.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.5, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.5, "mean": 0.065, "sd": 0.02},
    })


@lgd_model(sensitivity=0.1)
def lgd(economy: Economy) -> Score:
    """Consumer credit: LGD model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the
    unemployment level. Each driver is standardised by its long-run mean and standard deviation
    and weighted by its beta. Z > 0 is a better economy than average.

    Each facility's LGD moves from its TTC LGD with this Z and a sensitivity of 0.1:
    LGD = Phi(Phi^-1(TTC LGD) - 0.1 x Z), so Z = 0 gives back the TTC LGD.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.5, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.5, "mean": 0.065, "sd": 0.02},
    })


@prepayment_model(sensitivity=0.2)
def prepayment(economy: Economy) -> Score:
    """Consumer credit: prepayment model.

    Z is the linear score of two scenario drivers in the year: real GDP growth and the
    unemployment level. Each driver is standardised by its long-run mean and standard deviation
    and weighted by its beta. Z > 0 is a better economy than average.

    The prepayment rate moves from the segment's TTC rate with this Z and a sensitivity of
    0.2, so Z = 0 gives back the TTC rate.

    Coefficients: proposed synthetic values (SYN-PAR-06), not estimated and not owner-approved.
    """
    return linear(economy, {
        "gdp_growth": {"beta": 0.5, "mean": 0.015, "sd": 0.03},
        "unemployment": {"beta": -0.5, "mean": 0.065, "sd": 0.02},
    })


# Illustrative models for docs/examples/configurable-projection.yaml and the workflow walkthrough
# (docs/run-workflow/): a run specification points P02 at them in place of the three above.
NONLINEAR = {
    "activity": {"variable": "gdp_growth", "mean": 0.02, "sd": 0.03, "beta": 0.6},
    "activity_squared": {"variable": "gdp_growth", "mean": 0.02, "sd": 0.03, "beta": -0.08, "power": 2},
    "unemployment": {"variable": "unemployment", "mean": 0.07, "sd": 0.025, "beta": -0.3},
}


@pd_model
def pd_nonlinear(economy: Economy) -> Score:
    """Consumer credit: illustrative nonlinear PD model, for the docs examples.

    Z is the sum of three terms in the year: GDP growth and its square, both standardised by a mean
    of 2% and a standard deviation of 3%, and the unemployment level, standardised by 7% and 2.5%.
    The squared term makes a deep fall in GDP weigh more than a mild one.

    Coefficients: illustrative, chosen to show a nonlinear model; not estimates.
    """
    return polynomial(economy, 0.0, NONLINEAR)


@lgd_model(sensitivity=0.1)
def lgd_nonlinear(economy: Economy) -> Score:
    """Consumer credit: illustrative nonlinear LGD model, for the docs examples.

    The same score as the illustrative nonlinear PD model. Each facility's LGD moves from its TTC
    LGD with this Z and a sensitivity of 0.1, as in the segment's own LGD model.

    Coefficients: illustrative, chosen to show a nonlinear model; not estimates.
    """
    return polynomial(economy, 0.0, NONLINEAR)


@prepayment_model(sensitivity=0.2)
def prepayment_nonlinear(economy: Economy) -> Score:
    """Consumer credit: illustrative nonlinear prepayment model, for the docs examples.

    The same score as the illustrative nonlinear PD model, with the segment's own prepayment
    sensitivity of 0.2.

    Coefficients: illustrative, chosen to show a nonlinear model; not estimates.
    """
    return polynomial(economy, 0.0, NONLINEAR)
