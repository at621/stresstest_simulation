"""Pure scenario arithmetic: compounded indices and the reversion of Z after the last scenario
year (SCN-05, ECL-10). The Z-score itself is the models' (stress.models.forms)."""

from collections.abc import Sequence

STEP = "R4"


def compound_index(changes: Sequence[float], initial: float) -> list[float]:
    """Index level after each annual change. Changes compound; they are never added (SCN-05)."""
    levels = []
    level = float(initial)
    for change in changes:
        level *= 1.0 + float(change)
        levels.append(level)
    return levels


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
