"""Strict scalar checks shared by preparation analysis contracts."""

from math import isfinite

from stress.contracts.errors import BlockingError


def number(value, name: str, minimum=None, maximum=None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise BlockingError("analysis", "INVALID_INPUT", f"{name} must be a finite number")
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise BlockingError("analysis", "INVALID_INPUT", f"{name} outside its domain")
    return float(value)


def required(row: dict, names, context: str) -> None:
    if not isinstance(row, dict):
        raise BlockingError("analysis", "INVALID_INPUT", f"{context} must be a mapping")
    missing = [n for n in names if n not in row or row[n] is None]
    if missing:
        raise BlockingError("analysis", "MISSING_INPUT", f"{context} lacks {missing}")
