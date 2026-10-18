"""Contractual schedule arithmetic (EAD-10). Contractual only: no prepayment, default or
drawdown, and the same in every scenario.

A balance B[k] is the contractual drawn balance at default date k, before that date's payment.
DF[k] = (1 + r)^-t(k) discounts from default date k back to the valuation date.
"""

import math
from dataclasses import dataclass

import numpy as np

EPS = 1e-9


def drawn_measure(principal: float, accrued_interest: float, accrued_in_gca: bool,
                  gca: float | None = None) -> float:
    """The drawn exposure D with accrued interest counted exactly once (EAD-02, AT-37)."""
    if accrued_in_gca:
        if gca is None:
            return principal + accrued_interest
        return gca
    return principal + accrued_interest


def period_fractions(maturity: float) -> list[float]:
    """Yearly periods to maturity; a final stub of fraction d where M is not whole (PD-06)."""
    if not maturity > EPS:
        raise ValueError("maturity must be positive")
    whole = math.floor(maturity + EPS)
    stub = maturity - whole
    fractions = [1.0] * whole
    if stub > EPS:
        fractions.append(stub)
    return fractions


def remaining_maturity(original: float, elapsed: float) -> tuple[float, int]:
    """Residual maturity after ``elapsed`` years under like-for-like replacement (EXP-05).

    A facility that matures is replaced by one with the starting residual maturity, which
    restarts its schedule. Returns the remaining maturity and the replacement generation.
    """
    if elapsed < original - EPS:
        return original - elapsed, 0
    generation = math.floor((elapsed + EPS) / original)
    into = elapsed - generation * original
    if into < EPS:
        into = 0.0
    return original - into, generation


@dataclass(frozen=True)
class Schedule:
    fraction: np.ndarray
    t: np.ndarray
    opening_balance: np.ndarray
    interest: np.ndarray
    principal: np.ndarray
    closing_balance: np.ndarray
    discount_factor: np.ndarray

    @property
    def balance(self) -> np.ndarray:
        """B[k], the balance at default date k before that date's payment."""
        return self.opening_balance

    @property
    def payment(self) -> np.ndarray:
        return self.interest + self.principal


def annuity_payment(drawn: float, rate: float, maturity: float) -> float:
    """``A = D r / (1 - (1 + r)^-M)``, or ``D / M`` when r = 0."""
    if abs(rate) < 1e-15:
        return drawn / maturity
    return drawn * rate / (1.0 - (1.0 + rate) ** (-maturity))


def contractual_schedule(drawn: float, rate: float, maturity: float, profile: str) -> Schedule:
    """Yearly schedule from drawn balance D, rate r and residual maturity M (EAD-10).

    bullet: D repaid at M. annuity: constant payment A each full year; the stub pays off the
    rest. linear: D / M each full year, D * d / M in the stub. Interest for a stub of fraction
    d is ``B * ((1 + r)^d - 1)``, consistent with the discount factor.
    """
    if rate <= -1.0:
        raise ValueError("rate must be above -100%")
    fractions = np.array(period_fractions(maturity))
    n = len(fractions)
    t = np.cumsum(fractions)
    opening = np.zeros(n)
    interest = np.zeros(n)
    principal = np.zeros(n)
    closing = np.zeros(n)
    payment = annuity_payment(drawn, rate, maturity) if profile == "annuity" else 0.0
    balance = float(drawn)
    for k in range(n):
        frac = fractions[k]
        opening[k] = balance
        interest[k] = balance * ((1.0 + rate) ** frac - 1.0)
        last = k == n - 1
        if last:
            principal[k] = balance
        elif profile == "bullet":
            principal[k] = 0.0
        elif profile == "annuity":
            principal[k] = payment - interest[k]
        elif profile == "linear":
            principal[k] = drawn * frac / maturity
        else:
            raise ValueError(f"unknown repayment profile {profile!r}")
        balance = balance - principal[k]
        closing[k] = 0.0 if last else balance
    df = (1.0 + rate) ** (-t)
    return Schedule(fractions, t, opening, interest, principal, closing, df)
