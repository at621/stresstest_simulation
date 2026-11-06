"""Segment models: every segment has its own PD, LGD and prepayment model (MOD-01, SCN-08).

Each model is a documented function in the module of its portfolio (``p01`` ... ``p06``), with
its coefficients inside it. The parameter set points each segment at its three models by name,
for example ``pd_model: p01.pd``. Only the functions registered here can be named, and only by
segments of their own portfolio. The engine never imports a model from anywhere else.
"""

from stress.models import p01, p02, p03, p04, p05, p06  # noqa: F401  (registers the models)
from stress.models.registry import (
    LGD,
    PD,
    PREPAYMENT,
    REGISTRY,
    ROLES,
    Economy,
    Model,
    Score,
    Term,
    of_portfolio,
    register,
    resolve,
)

__all__ = ["LGD", "PD", "PREPAYMENT", "REGISTRY", "ROLES", "Economy", "Model", "Score", "Term",
           "of_portfolio", "register", "resolve"]
