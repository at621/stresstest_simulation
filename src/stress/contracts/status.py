"""Value status carried by every input value (DAT-02, LGD-08, CAP-08).

Missing is never zero: a value with status ``missing`` blocks the calculation that needs it.
"""

from enum import StrEnum


class ValueStatus(StrEnum):
    SUPPLIED = "supplied"
    ZERO = "zero"
    NOT_APPLICABLE = "not_applicable"
    ESTIMATED = "estimated"
    MISSING = "missing"


ALL_STATUSES = frozenset(ValueStatus)

# Statuses whose value a calculation may use. not_applicable and missing are never usable.
USABLE_STATUSES = frozenset({ValueStatus.SUPPLIED, ValueStatus.ZERO, ValueStatus.ESTIMATED})

# Companion column holding a field's status, for example ``ltv__status``.
STATUS_SUFFIX = "__status"


def status_column(column: str) -> str:
    return column + STATUS_SUFFIX
