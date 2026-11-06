"""The closed list of segment models and how the parameter set names them.

A model is a Python function in one of the portfolio modules of this package. It takes the
economy of one scenario, country and year and returns one score Z with the terms that make it
up. Its docstring is its description: the control room shows it as written. The decorators
below register each function under ``<module>.<function>``, for example ``p01.pd``, and the
parameter set names models only by those names, never by an import path (MOD-01).
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from math import isfinite

from stress.contracts.errors import Block, BlockingError
from stress.contracts.tables import MODEL_LGD as LGD
from stress.contracts.tables import MODEL_PD as PD
from stress.contracts.tables import MODEL_PREPAYMENT as PREPAYMENT
from stress.contracts.tables import MODEL_ROLES as ROLES

STEP = "R4"
PACKAGE = "stress.models"


@dataclass(frozen=True)
class Term:
    """One part of a score: the driver's value, its mean, sd and beta, and its contribution."""

    driver: str
    value: float
    mean: float
    sd: float
    beta: float
    contribution: float


@dataclass(frozen=True)
class Score:
    z: float
    terms: tuple[Term, ...]


@dataclass(frozen=True)
class Economy:
    """The scenario values a model may read for one scenario, country and year."""

    scenario: str
    country: str
    year: int
    values: Mapping[tuple[str, str, str, int], tuple[float | None, str]] = field(repr=False)

    def value(self, variable: str, lag: int = 0) -> float | None:
        """The value of ``variable`` ``lag`` years before this year; None when it is missing."""
        value, status = self.values.get((self.scenario, variable, self.country, self.year - lag), (None, "missing"))
        return None if status == "missing" or value is None else float(value)

    @property
    def where(self) -> str:
        return f"{self.scenario}/{self.country}/{self.year}"


@dataclass(frozen=True)
class Model:
    """A registered model. ``sensitivity`` is the LGD's w or the prepayment's v; a PD model has
    none, because the PD shift takes the segment's asset correlation from the parameter set."""

    name: str
    role: str
    function: Callable[[Economy], Score] = field(repr=False)
    sensitivity: float | None = None

    @property
    def description(self) -> str:
        return inspect.getdoc(self.function) or ""

    @property
    def location(self) -> str:
        module, function = self.name.split(".", 1)
        return f"src/stress/models/{module}.py, function {function}"

    def score(self, economy: Economy) -> Score:
        score = self.function(economy)
        if not isinstance(score, Score) or not isfinite(score.z):
            raise BlockingError(STEP, Block.MISSING_PARAMETER,
                                f"model {self.name} gave no finite score for {economy.where}")
        return score


REGISTRY: dict[str, Model] = {}


def register(model: Model) -> Model:
    if model.role not in ROLES:
        raise ValueError(f"unknown model role {model.role}")
    if model.name in REGISTRY and REGISTRY[model.name] is not model:
        raise ValueError(f"model {model.name} is registered twice")
    if model.role != PD and not (isinstance(model.sensitivity, (int, float)) and isfinite(model.sensitivity)):
        raise ValueError(f"{model.role} model {model.name} needs a finite sensitivity")
    REGISTRY[model.name] = model
    return model


def _name(function: Callable) -> str:
    module = function.__module__
    if not module.startswith(PACKAGE + "."):
        raise ValueError(f"{function.__qualname__} is not in {PACKAGE}")
    return f"{module.removeprefix(PACKAGE + '.')}.{function.__name__}"


def pd_model(function: Callable[[Economy], Score]) -> Model:
    """Register a PD model. Its score shifts the TTC matrix by the asset correlation (PD-10)."""
    return register(Model(_name(function), PD, function))


def lgd_model(*, sensitivity: float) -> Callable[[Callable[[Economy], Score]], Model]:
    """Register an LGD model with its sensitivity w: ``LGD = Phi(Phi^-1(LGD_TTC) - w Z)`` (LGD-12)."""
    return lambda function: register(Model(_name(function), LGD, function, float(sensitivity)))


def prepayment_model(*, sensitivity: float) -> Callable[[Callable[[Economy], Score]], Model]:
    """Register a prepayment model with its sensitivity v to the score (EAD-11)."""
    return lambda function: register(Model(_name(function), PREPAYMENT, function, float(sensitivity)))


def resolve(name, role: str, portfolio: str, where: str = "") -> Model:
    """The model the parameter set names. It must be registered, have this role and belong to
    the segment's portfolio: models are portfolio-specific."""
    if not isinstance(name, str) or name not in REGISTRY:
        raise BlockingError("R2", Block.UNKNOWN_MODEL, f"{where}{role} model {name!r} is not a model in {PACKAGE}")
    model = REGISTRY[name]
    if model.role != role:
        raise BlockingError("R2", Block.UNKNOWN_MODEL, f"{where}{name} is a {model.role} model, not a {role} model")
    if name.split(".", 1)[0] != str(portfolio).lower():
        raise BlockingError("R2", Block.UNKNOWN_MODEL,
                            f"{where}{name} belongs to another portfolio than {portfolio}")
    return model


def of_portfolio(portfolio: str, role: str | None = None) -> list[Model]:
    """The registered models of a portfolio, optionally of one role, by name."""
    prefix = str(portfolio).lower() + "."
    return sorted((m for m in REGISTRY.values() if m.name.startswith(prefix) and role in (None, m.role)),
                  key=lambda m: m.name)
