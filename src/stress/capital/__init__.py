"""R10 REA floor arithmetic as functions. Nothing in v1 feeds them portfolio REA.

CAP-03, CAP-04.
"""

from collections.abc import Mapping


def methodological_floor(starting: Mapping[str, float], raw: Mapping[str, float]) -> dict:
    """CAP-03: the starting-point floor applies separately to the aggregate IRB and STA REA
    contributions; the credit contribution is the sum of the floored parts (AT-10)."""
    floored = {approach: max(raw[approach], starting[approach]) for approach in raw}
    return {"floored": floored, "credit_contribution": sum(floored.values())}


def output_floor(utrea: float, strea: float, factor: float) -> dict:
    """CAP-04: the bank-wide output-floor comparison max(UTREA, factor x STREA) (AT-11).

    Bank-wide only; it is never applied loan by loan. The transitional factor is not set here.
    """
    floored_strea = factor * strea
    return {"floored_strea": floored_strea, "result": max(utrea, floored_strea)}
