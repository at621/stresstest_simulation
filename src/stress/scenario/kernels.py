"""Pure scenario arithmetic: compounded indices, the Z-score and its reversion after the
last scenario year (SCN-05, SCN-08, ECL-10)."""

from collections.abc import Mapping, Sequence

from stress.contracts.errors import Block, BlockingError

STEP = "R4"


def compound_index(changes: Sequence[float], initial: float) -> list[float]:
    """Index level after each annual change. Changes compound; they are never added (SCN-05)."""
    levels = []
    level = float(initial)
    for change in changes:
        level *= 1.0 + float(change)
        levels.append(level)
    return levels


def z_score(values: Mapping[str, float], drivers: Mapping[str, Mapping[str, float]],
            where: str = "") -> tuple[float, dict[str, float]]:
    """``Z = sum_i(beta_i * (x_i - mu_i) / sigma_i)`` and each driver's contribution (SCN-08).

    ``drivers`` maps a driver to its ``beta``, ``mean`` and ``sd``. A missing coefficient or
    scenario value blocks; nothing is carried forward or set to zero.
    """
    if not drivers:
        raise BlockingError(STEP, Block.MISSING_PARAMETER, f"no Z-score drivers {where}")
    contributions = {}
    for name, coef in drivers.items():
        for field in ("beta", "mean", "sd"):
            if coef is None or coef.get(field) is None:
                raise BlockingError(STEP, Block.MISSING_PARAMETER,
                                    f"Z coefficient {field} missing for driver {name} {where}")
        if coef["sd"] <= 0:
            raise BlockingError(STEP, Block.MISSING_PARAMETER,
                                f"standard deviation of driver {name} must be positive {where}")
        x = values.get(name)
        if x is None:
            raise BlockingError(STEP, Block.MISSING_SCENARIO_VALUE,
                                f"scenario value for driver {name} missing {where}")
        contributions[name] = coef["beta"] * (x - coef["mean"]) / coef["sd"]
    return sum(contributions.values()), contributions


def adverse_weight(year: int, last_scenario_year: int, reversion_years: int) -> float:
    """Weight a(t) on the adverse last-year Z: 1 inside the scenario, then (R - n)/R, then 0.

    With R = 6 and the last scenario year 2029: 5/6 in 2030 down to 0 in 2035 and after (ECL-10).
    """
    if year <= last_scenario_year:
        return 1.0
    steps = year - last_scenario_year
    return max(0.0, (reversion_years - steps) / reversion_years)


def reverted_z(year: int, z_adverse_last: float, z_baseline_last: float,
               last_scenario_year: int, reversion_years: int) -> float:
    """Adverse Z after the scenario: ``a(t) * Z_adv(last) + (1 - a(t)) * Z_base(last)``."""
    a = adverse_weight(year, last_scenario_year, reversion_years)
    return a * z_adverse_last + (1.0 - a) * z_baseline_last
