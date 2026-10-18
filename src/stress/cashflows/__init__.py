"""R5 generate cash flows: the contractual schedule per facility from drawn balance, rate,
residual maturity and repayment profile, giving B[k] and DF[k].

The only step that creates cash flows. Scenario-independent: prepayment, default and
drawdown belong to R6.

EAD-01, EAD-05, EAD-10, ECL-08.

At each valuation year-end the schedule restarts from the static stock balance (EAD-05,
EAD-11): D is the facility's opening GCA, accrued interest counted once. A facility that has
matured by then is replaced like for like with its starting residual maturity, which restarts
its schedule (EXP-05).
"""

import calendar
import logging
from functools import cache

import numpy as np
import pandas as pd

from stress.cashflows.kernels import EPS
from stress.contracts.errors import Block, BlockingError
from stress.contracts.tables import ROUTE_PERFORMING, SCHEDULE

STEP = "R5"
LOG = logging.getLogger("stress.R5")
PROFILE_CODES = {"bullet": 0, "annuity": 1, "linear": 2}


def variant_profiles(portfolio: pd.DataFrame, variant: dict) -> pd.Series:
    """Repayment profile per facility under the variant (core: bullet for every facility)."""
    rule = variant["repayment_profile"]
    default = rule.get("default")
    profiles = portfolio["product"].map(lambda p: rule.get(p, default))
    if profiles.isna().any():
        raise BlockingError(STEP, Block.UNKNOWN_VARIANT, "variant gives no repayment profile for a product")
    return profiles


def remaining(original: np.ndarray, elapsed: float) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised ``kernels.remaining_maturity``: residual maturity and replacement generation."""
    generation = np.where(elapsed < original - EPS, 0, np.floor((elapsed + EPS) / original))
    into = elapsed - generation * original
    into = np.where(into < EPS, 0.0, into)
    rest = np.where(generation == 0, original - elapsed, original - into)
    return rest, generation.astype(int)


def schedules(drawn: np.ndarray, rate: np.ndarray, maturity: np.ndarray, profile: np.ndarray):
    """All facilities' schedules at once; same arithmetic as ``kernels.contractual_schedule``.

    Returns arrays (facilities x periods): fraction, t, opening, interest, principal, closing,
    and the number of periods per facility.
    """
    if (maturity <= EPS).any():
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "non-positive maturity reached R5")
    if (rate <= -1.0).any():
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "rate of -100% or lower reached R5")
    whole = np.floor(maturity + EPS).astype(int)
    stub = maturity - whole
    has_stub = stub > EPS
    periods = whole + has_stub
    size = int(periods.max())
    k = np.arange(size)[None, :]
    fraction = np.where(k < whole[:, None], 1.0, np.where((k == whole[:, None]) & has_stub[:, None],
                                                          stub[:, None], 0.0))
    t = np.cumsum(fraction, axis=1)
    zero_rate = np.abs(rate) < 1e-15
    safe = np.where(zero_rate, 1.0, rate)  # the annuity formula is D / M when r = 0
    payment = np.where(zero_rate, drawn / maturity, drawn * safe / (1.0 - (1.0 + safe) ** (-maturity)))
    n = len(drawn)
    opening = np.zeros((n, size))
    interest = np.zeros((n, size))
    principal = np.zeros((n, size))
    closing = np.zeros((n, size))
    balance = drawn.astype(float).copy()
    for j in range(size):
        active = j < periods
        last = j == periods - 1
        frac = fraction[:, j]
        opening[:, j] = np.where(active, balance, 0.0)
        accrued = balance * ((1.0 + rate) ** frac - 1.0)
        regular = np.select(
            [profile == PROFILE_CODES["bullet"], profile == PROFILE_CODES["annuity"]],
            [np.zeros(n), payment - accrued],
            default=drawn * frac / maturity,
        )
        paid = np.where(last, balance, regular)
        paid = np.where(active, paid, 0.0)
        interest[:, j] = np.where(active, accrued, 0.0)
        principal[:, j] = paid
        balance = balance - paid
        closing[:, j] = np.where(active & ~last, balance, 0.0)
    return fraction, t, opening, interest, principal, closing, periods


@cache
def _month_end(year: int, month: int) -> str:
    return f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def _period_end(valuation_year: int, t: np.ndarray) -> list[str]:
    """Default date of each bucket: a calendar year-end, or the month-end of a stub maturity."""
    whole = np.floor(t + EPS).astype(int)
    rest = t - whole
    month = np.clip(np.round(rest * 12).astype(int), 1, 12)
    return [
        f"{valuation_year + w}-12-31" if r < EPS else _month_end(valuation_year + w + 1, int(m))
        for w, r, m in zip(whole, rest, month)
    ]


def build_schedules(portfolio: pd.DataFrame, parameter_set: dict, variant: str) -> pd.DataFrame:
    """R5: cf_schedule rows for every performing facility and valuation year-end."""
    perf = portfolio[portfolio["route"] == ROUTE_PERFORMING].reset_index(drop=True)
    horizon = parameter_set["horizon"]
    start = int(horizon["snapshot_year"])
    valuations = [start] + [int(y) for y in horizon["projection_years"]]
    profiles = variant_profiles(perf, parameter_set["variants"][variant])
    codes = profiles.map(PROFILE_CODES).to_numpy()
    # D: the drawn measure with accrued interest counted exactly once (EAD-02, AT-37).
    drawn = np.where(perf["accrued_in_gca"].eq(True), perf["gca"],
                     perf["principal"] + perf["accrued_interest"]).astype(float)
    rate = perf["interest_rate"].to_numpy(dtype=float)
    original = perf["residual_maturity"].to_numpy(dtype=float)
    frames = []
    for valuation in valuations:
        rest, generation = remaining(original, valuation - start)
        fraction, t, opening, interest, principal, closing, periods = schedules(drawn, rate, rest, codes)
        size = fraction.shape[1]
        rows, cols = np.nonzero(np.arange(size)[None, :] < periods[:, None])
        df = (1.0 + rate[rows]) ** (-t[rows, cols])
        frame = pd.DataFrame({
            "facility_id": perf["facility_id"].to_numpy()[rows],
            "valuation_year": valuation,
            "period": cols + 1,
            "bucket_year": valuation + cols + 1,
            "fraction": fraction[rows, cols],
            "t": t[rows, cols],
            "opening_balance": opening[rows, cols],
            "interest": interest[rows, cols],
            "principal": principal[rows, cols],
            "closing_balance": closing[rows, cols],
            "discount_factor": df,
            "profile": profiles.to_numpy()[rows],
            "generation": generation[rows],
            "remaining_maturity": rest[rows],
        })
        frame["period_end"] = _period_end(valuation, frame["t"].to_numpy())
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    mix = ", ".join(f"{p} {n:,}" for p, n in profiles.value_counts().sort_index().items())
    LOG.info("contractual schedules for %s performing facilities at %d valuation dates: %s periods",
             f"{len(perf):,}", len(valuations), f"{len(out):,}")
    LOG.info("variant %s repayment profiles: %s", variant, mix)
    final = out[out["valuation_year"] == valuations[-1]].drop_duplicates("facility_id")
    LOG.info("facilities replaced like for like by %d: %s", valuations[-1],
             f"{int((final['generation'] > 0).sum()):,}")
    return SCHEDULE.check(out, STEP).sort_values(list(SCHEDULE.key), kind="mergesort").reset_index(drop=True)
