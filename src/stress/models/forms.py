"""The arithmetic the portfolio modules build their models from (SCN-08, MOD-01).

A missing coefficient or scenario value blocks; nothing is carried forward or set to zero.
"""

from collections.abc import Mapping
from math import isfinite

from stress.contracts.errors import Block, BlockingError
from stress.models.registry import STEP, Economy, Score, Term


def z_score(values: Mapping[str, float], drivers: Mapping[str, Mapping[str, float]],
            where: str = "") -> tuple[float, dict[str, float]]:
    """``Z = sum_i(beta_i * (x_i - mu_i) / sigma_i)`` and each driver's contribution (SCN-08).

    ``drivers`` maps a driver to its ``beta``, ``mean`` and ``sd``.
    """
    if not drivers:
        raise BlockingError(STEP, Block.MISSING_PARAMETER, f"no Z-score drivers {where}")
    contributions = {}
    for name, coef in drivers.items():
        for field in ("beta", "mean", "sd"):
            if (coef is None or not isinstance(coef.get(field), (int, float))
                    or isinstance(coef[field], bool) or not isfinite(coef[field])):
                raise BlockingError(STEP, Block.MISSING_PARAMETER,
                                    f"Z coefficient {field} missing for driver {name} {where}")
        if coef["sd"] <= 0:
            raise BlockingError(STEP, Block.MISSING_PARAMETER,
                                f"standard deviation of driver {name} must be positive {where}")
        x = values.get(name)
        if x is None or not isfinite(x):
            raise BlockingError(STEP, Block.MISSING_SCENARIO_VALUE,
                                f"scenario value for driver {name} missing {where}")
        contributions[name] = coef["beta"] * (x - coef["mean"]) / coef["sd"]
    return sum(contributions.values()), contributions


def linear(economy: Economy, drivers: Mapping[str, Mapping[str, float]]) -> Score:
    """The linear score of the year's drivers, each standardised by its mean and sd."""
    x = {name: economy.value(name) for name in drivers}
    z, parts = z_score(x, drivers, f"for {economy.where}")
    if not isfinite(z):
        raise BlockingError(STEP, Block.MISSING_PARAMETER, f"non-finite linear score for {economy.where}")
    return Score(z, tuple(Term(name, x[name], drivers[name]["mean"], drivers[name]["sd"], drivers[name]["beta"], part)
                          for name, part in parts.items()))


def polynomial(economy: Economy, intercept: float, terms: Mapping[str, Mapping]) -> Score:
    """An intercept plus ``beta * ((x - mean) / sd) ** power`` per term, where x may be lagged."""
    out = [Term("__intercept__", 1.0, 0.0, 1.0, intercept, intercept)]
    for name, term in terms.items():
        lag, power = term.get("lag", 0), term.get("power", 1)
        if term["sd"] <= 0 or lag < 0 or power not in (1, 2, 3):
            raise BlockingError(STEP, Block.MISSING_PARAMETER, f"term {name} has an invalid sd, lag or power")
        value = economy.value(term["variable"], lag)
        if value is None:
            raise BlockingError(STEP, Block.MISSING_SCENARIO_VALUE,
                                f"missing model driver/history {term['variable']} lag {lag} for {economy.where}")
        try:
            contribution = term["beta"] * ((value - term["mean"]) / term["sd"]) ** power
        except OverflowError:
            contribution = float("inf")
        if not isfinite(contribution):
            raise BlockingError(STEP, Block.MISSING_PARAMETER, f"non-finite contribution in term {name}")
        out.append(Term(name, value, term["mean"], term["sd"], term["beta"], contribution))
    return Score(sum(t.contribution for t in out), tuple(out))


def supplied(economy: Economy, scores: Mapping[tuple[str, int], float]) -> Score:
    """A score taken as given by scenario and year, the same in every country."""
    key = (economy.scenario, economy.year)
    if key not in scores:
        raise BlockingError(STEP, Block.MISSING_SCENARIO_VALUE, f"missing supplied score {key}")
    value = float(scores[key])
    return Score(value, (Term("supplied_score", value, 0.0, 1.0, 1.0, value),))
