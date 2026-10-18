"""R6 build parameters: every scenario-dependent value per facility, scenario and default
bucket, each stored as a ParameterRecord under the MOD-06 key.

PD-01–PD-07, PD-09–PD-11, LGD-08, LGD-10–LGD-12, EAD-02–EAD-04, EAD-06, EAD-07, EAD-11,
SYN-PAR-04, MOD-02, MOD-06. Read CLAUDE.md in this folder before editing.
"""

import logging

import numpy as np
import pandas  # not "pd": the submodule stress.params.pd would shadow it

from stress import __version__
from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import DEFAULT_GRADE, LoadedInputs
from stress.contracts.run import BASELINE, RunContext
from stress.contracts.tables import (
    BASIS_ACCOUNTING,
    COHORT_PERFORMING,
    LGD_OF_YEAR,
    PIT_MATRICES,
    ROUTE_PERFORMING,
    Drivers,
    Parameters,
    RoutedPortfolio,
)
from stress.params import store
from stress.params.ead import check_ccf, ead
from stress.params.lgd import lgd_from_z
from stress.params.matrix import check_matrix, pd_rises_with_grade, pit_matrix
from stress.params.pd import Curve, check_curve, grade_distributions
from stress.params.prepay import prepayment_rate
from stress.params.terminal import require_years, z_lookup

STEP = "R6"
LOG = logging.getLogger("stress.R6")


def ttc_arrays(table: pandas.DataFrame) -> tuple[dict[str, np.ndarray], list[str]]:
    """The TTC matrices as arrays in rank order (performing grades, then D)."""
    labels = table[["from_rank", "from_grade"]].drop_duplicates().sort_values("from_rank")
    grades = list(labels["from_grade"])
    size = len(grades)
    out = {}
    for segment, cells in table.groupby("segment", sort=True):
        m = np.zeros((size, size))
        m[cells["from_rank"].to_numpy() - 1, cells["to_rank"].to_numpy() - 1] = cells["probability"]
        out[str(segment)] = m
    return out, grades


def scenario_order(requested) -> list[str]:
    """Baseline first: adverse buckets after 2029 revert toward baseline 2029."""
    return sorted(requested, key=lambda s: (s != BASELINE, s))


class PitBook:
    """PiT matrices M(y) per segment, country, scenario and year, cached by (segment, Z)."""

    def __init__(self, ttc: dict[str, np.ndarray], segments: dict, z: dict, tol: float):
        self.ttc = ttc
        self.segments = segments
        self.z = z
        self.tol = tol
        self._cache: dict[tuple[str, float], np.ndarray] = {}

    def get(self, segment: str, country: str, scenario: str, year: int) -> np.ndarray:
        key = (segment, country, scenario, int(year))
        if key not in self.z:
            raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT,
                                f"no Z for {segment}/{country}/{scenario}/{year}")
        z = self.z[key]
        cache_key = (segment, z)
        if cache_key not in self._cache:
            m = pit_matrix(self.ttc[segment], z, float(self.segments[segment]["rho"]))
            check_matrix(m, self.tol, STEP, f"PiT matrix {segment} Z={z:.6f}", Block.INVALID_PIT_MATRIX)
            if not pd_rises_with_grade(m):
                raise BlockingError(STEP, Block.INVALID_PIT_MATRIX,
                                    f"PiT matrix {segment} Z={z:.6f}: PD does not rise with the grade")
            self._cache[cache_key] = m
        return self._cache[cache_key]


def pit_table(book: PitBook, keys: list[tuple[str, str, str]], years: range,
              grades: list[str]) -> pandas.DataFrame:
    labels = np.array(grades)
    size = len(grades)
    frames = []
    for segment, country, scenario in keys:
        for year in years:
            m = book.get(segment, country, scenario, year)
            frames.append(pandas.DataFrame({
                "segment": segment, "country": country, "scenario": scenario, "year": year,
                "from_grade": np.repeat(labels, size), "to_grade": np.tile(labels, size),
                "probability": m.ravel(), "z": book.z[(segment, country, scenario, year)],
            }))
    return PIT_MATRICES.check(pandas.concat(frames, ignore_index=True), STEP)


def pd_curves(book: PitBook, schedule: pandas.DataFrame, perf: pandas.DataFrame, scenarios: list[str],
              grades: list[str], tol: float) -> pandas.DataFrame:
    """Grade-level PD curves (PD-11) for every valuation date, full buckets to the longest
    maturity in each segment and country, plus the stub buckets the facilities need."""
    performing = np.array(grades[:-1])
    n = len(performing)
    sched = schedule.merge(perf[["facility_id", "segment", "country"]], on="facility_id")
    last_rows = sched.loc[sched.groupby(["facility_id", "valuation_year"])["period"].idxmax()]
    cols: dict[str, list] = {c: [] for c in ("segment", "country", "scenario", "valuation_year", "cohort",
                                             "default_bucket", "fraction", "q", "m", "s", "f")}

    def add(segment, country, scenario, valuation, cohort, bucket, fraction, q, m, s, f):
        size = len(q)
        for name, value in (("segment", segment), ("country", country), ("scenario", scenario),
                            ("valuation_year", valuation)):
            cols[name].append(np.full(size, value, dtype=object if isinstance(value, str) else int))
        for name, value in (("cohort", cohort), ("default_bucket", bucket), ("fraction", fraction),
                            ("q", q), ("m", m), ("s", s), ("f", f)):
            cols[name].append(np.asarray(value))

    for (segment, country, valuation), rows in last_rows.groupby(["segment", "country", "valuation_year"]):
        horizon = int(rows["period"].max())
        stubs = rows.loc[rows["fraction"] < 1.0, ["period", "fraction"]].drop_duplicates()
        stub_period = stubs["period"].to_numpy(dtype=int)
        stub_fraction = stubs["fraction"].to_numpy(dtype=float)
        for scenario in scenarios:
            matrices = [book.get(segment, country, scenario, valuation + k) for k in range(1, horizon + 1)]
            dist = grade_distributions(matrices)
            f = dist[1:, :n, -1].T  # grades x buckets
            f_prev = np.concatenate([np.zeros((n, 1)), f[:, :-1]], axis=1)
            m = f - f_prev
            s = 1.0 - f
            s_prev = 1.0 - f_prev
            q = np.divide(m, s_prev, out=np.zeros_like(m), where=s_prev > 0)
            for g in range(n):
                check_curve(Curve(q[g], m[g], s[g], f[g]), tol, STEP,
                            f"PD curve {segment}/{country}/{scenario}/{valuation}/{performing[g]}")
            buckets = np.arange(1, horizon + 1)
            add(segment, country, scenario, valuation, np.repeat(performing, horizon),
                np.tile(buckets, n), np.ones(n * horizon), q.ravel(), m.ravel(), s.ravel(), f.ravel())
            if stub_period.size == 0:
                continue
            # Stub buckets, all at once: each grade's distribution at the start of the stub times
            # the constant-hazard stub PD of every grade (PD-06).
            whole = stub_period - 1
            start = dist[whole][:, :n, :n]  # stubs x grades x grades
            year_pd = np.stack([matrices[w][:n, -1] for w in whole])  # stubs x grades
            stub_pd = 1.0 - (1.0 - year_pd) ** stub_fraction[:, None]
            stub_m = np.einsum("sij,sj->si", start, stub_pd)
            base_f = dist[whole][:, :n, -1]
            stub_f = base_f + stub_m
            base_s = 1.0 - base_f
            stub_q = np.divide(stub_m, base_s, out=np.zeros_like(stub_m), where=base_s > 0)
            # The stub extends each grade's curve by one step: bounds, F + S = 1 and a
            # non-decreasing F (PD-03), checked per grade.
            if ((stub_m < -tol) | (stub_f > 1 + tol) | (stub_q > 1 + tol)).any():
                raise BlockingError(STEP, Block.PD_IDENTITY,
                                    f"stub PD {segment}/{country}/{scenario}/{valuation} out of bounds")
            count = len(whole)
            add(segment, country, scenario, valuation, np.tile(performing, count),
                np.repeat(stub_period, n), np.repeat(stub_fraction, n), stub_q.ravel(),
                stub_m.ravel(), (1.0 - stub_f).ravel(), stub_f.ravel())
    out = pandas.DataFrame({name: np.concatenate(parts) for name, parts in cols.items()})
    out["bucket_year"] = out["valuation_year"] + out["default_bucket"]
    out["basis"] = BASIS_ACCOUNTING
    return out


def facility_parameters(schedule: pandas.DataFrame, perf: pandas.DataFrame, z: pandas.DataFrame,
                        ps: dict, variant: dict, scenarios: list[str]) -> pandas.DataFrame:
    """LGD, prepayment and EAD per facility, scenario, valuation date and default bucket."""
    segments = ps["segments"]
    attrs = perf[["facility_id", "segment", "country", "ttc_lgd", "undrawn"]].copy()
    attrs["ccf"] = effective_ccf(perf, variant)
    check_ccf(attrs["ccf"].astype(float).to_numpy(), attrs["undrawn"].to_numpy())
    base = schedule[["facility_id", "valuation_year", "period", "fraction", "bucket_year", "t",
                     "opening_balance", "discount_factor"]].merge(attrs, on="facility_id")
    frames = []
    for scenario in scenarios:
        zs = z.loc[z["scenario"] == scenario, ["segment", "country", "year", "z"]]
        rows = base.merge(zs, left_on=["segment", "country", "bucket_year"],
                          right_on=["segment", "country", "year"], how="left")
        if rows["z"].isna().any():
            gap = rows.loc[rows["z"].isna()].iloc[0]
            raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT,
                                f"no Z for {gap['segment']}/{gap['country']}/{scenario}/{gap['bucket_year']}")
        w = rows["segment"].map(lambda s: segments[s]["lgd_w"]).astype(float)
        cpr_ttc = rows["segment"].map(lambda s: segments[s]["cpr_ttc"]).astype(float)
        cpr_v = rows["segment"].map(lambda s: segments[s]["cpr_v"]).astype(float)
        rows["lgd"] = lgd_from_z(rows["ttc_lgd"].to_numpy(), w.to_numpy(), rows["z"].to_numpy())
        rows["prepayment_rate"] = prepayment_rate(cpr_ttc.to_numpy(), cpr_v.to_numpy(), rows["z"].to_numpy())
        rows = rows.sort_values(["facility_id", "valuation_year", "period"], kind="mergesort")
        keys = [rows["facility_id"], rows["valuation_year"]]
        kept = (1.0 - rows["prepayment_rate"]).groupby(keys).cumprod()
        rows["not_prepaid_share"] = kept.groupby(keys).shift(1).fillna(1.0)
        exposure = ead(rows["opening_balance"].to_numpy(), rows["undrawn"].to_numpy(),
                       rows["ccf"].astype(float).to_numpy(), rows["not_prepaid_share"].to_numpy())
        rows["ead_drawn"] = exposure.drawn
        rows["ead_undrawn"] = exposure.undrawn
        rows["ead_total"] = exposure.total
        # CCF is not applicable without an undrawn amount (EAD-03): kept as NaN, never 0.
        rows["ccf"] = rows["ccf"].astype(float).where(rows["undrawn"] > 0)
        rows["scenario"] = scenario
        frames.append(rows)
    out = pandas.concat(frames, ignore_index=True)
    if ((out["lgd"] < 0) | (out["lgd"] > 1)).any() or out["lgd"].isna().any():
        raise BlockingError(STEP, Block.LGD_OUT_OF_RANGE, "a final LGD is outside [0, 1]")
    out = out.rename(columns={"period": "default_bucket", "opening_balance": "balance"})
    out["cohort"] = COHORT_PERFORMING
    out["basis"] = BASIS_ACCOUNTING
    return out


def effective_ccf(portfolio: pandas.DataFrame, variant: dict) -> pandas.Series:
    """The accounting CCF the run applies: the variant's override for the segment, else the
    commitment's own CCF; NaN (not applicable) without an undrawn amount (EAD-03)."""
    overrides = variant.get("ccf", {})
    ccf = pandas.Series([overrides.get(seg, c) for seg, c in zip(portfolio["segment"], portfolio["ccf"])],
                        index=portfolio.index, dtype=float)
    return ccf.where(portfolio["undrawn"] > 0)


def lgd_of_year(portfolio: pandas.DataFrame, z: pandas.DataFrame, ps: dict, scenarios: list[str],
                variant: dict) -> pandas.DataFrame:
    """LGD of each projection year per facility (ECL-11), from the Z of that year, with the
    facility's effective CCF for the off-balance part of its S3 slices."""
    years = [int(y) for y in ps["horizon"]["projection_years"]]
    rows = portfolio[["facility_id", "segment", "country", "ttc_lgd"]].assign(
        ccf=effective_ccf(portfolio, variant))
    frames = []
    for scenario in scenarios:
        zs = z[(z["scenario"] == scenario) & z["year"].isin(years)][["segment", "country", "year", "z"]]
        part = rows.merge(zs, on=["segment", "country"], how="left")
        if part["z"].isna().any():
            raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT, "Z missing for an LGD year")
        w = part["segment"].map(lambda s: ps["segments"][s]["lgd_w"]).astype(float)
        part["lgd"] = lgd_from_z(part["ttc_lgd"].to_numpy(), w.to_numpy(), part["z"].to_numpy())
        part["scenario"] = scenario
        frames.append(part)
    out = pandas.concat(frames, ignore_index=True)
    return LGD_OF_YEAR.check(out, STEP).sort_values(list(LGD_OF_YEAR.key)).reset_index(drop=True)


def build_parameters(routed: RoutedPortfolio, schedule: pandas.DataFrame, drivers: Drivers,
                     loaded: LoadedInputs, ctx: RunContext) -> Parameters:
    ps = loaded.parameter_set
    tol = ps["tolerances"]["probability_identity"]["abs"]
    ttc, grades = ttc_arrays(loaded.ttc_pd_matrix)
    if grades[-1] != DEFAULT_GRADE:
        raise BlockingError(STEP, Block.INVALID_MATRIX, "the master scale must end with D")
    scenarios = scenario_order(ctx.scenarios)
    perf = routed.portfolio[routed.portfolio["route"] == ROUTE_PERFORMING]
    lookup = z_lookup(drivers.z)
    book = PitBook(ttc, ps["segments"], lookup, tol)
    keys = sorted({(s, c) for s, c in zip(routed.portfolio["segment"], routed.portfolio["country"])})
    first = int(ps["horizon"]["projection_years"][0])
    last_reported = int(ps["terminal_rule"]["last_scenario_year"]) + int(ps["terminal_rule"]["reversion_years"]) + 1
    for segment, country in keys:
        for scenario in scenarios:
            require_years(lookup, segment, country, scenario, range(first, int(schedule["bucket_year"].max()) + 1))
    version = store.source_version(ps, __version__)
    pit = pit_table(book, [(s, c, sc) for s, c in keys for sc in scenarios],
                    range(first, last_reported + 1), grades)
    curves = store.finalise_pd_curves(pd_curves(book, schedule, perf, scenarios, grades, tol), version)
    facility = store.finalise_parameters(
        facility_parameters(schedule, perf, drivers.z, ps, ps["variants"][ctx.variant], scenarios), version)
    lgd = lgd_of_year(routed.portfolio, drivers.z, ps, scenarios, ps["variants"][ctx.variant])
    LOG.info("PiT matrices: %d distinct shifts; every row sums to 1 within %g and PD rises with the grade",
             len(book._cache), tol)
    LOG.info("PD curves: %s records; PD-03 identities hold on every curve", f"{len(curves):,}")
    LOG.info("facility ParameterRecords (LGD, prepayment, EAD per bucket): %s", f"{len(facility):,}")
    for scenario in scenarios:
        part = facility[facility["scenario"] == scenario]
        LOG.info("%s: LGD %.1f%%-%.1f%%, prepayment rate %.1f%%-%.1f%%, EAD bucket 1 EUR %.1fm",
                 scenario, 100 * part["lgd"].min(), 100 * part["lgd"].max(),
                 100 * part["prepayment_rate"].min(), 100 * part["prepayment_rate"].max(),
                 part.loc[(part["default_bucket"] == 1)
                          & (part["valuation_year"] == part["valuation_year"].min()), "ead_total"].sum()
                 / 1_000_000)
    return Parameters(
        pit=pit.sort_values(list(PIT_MATRICES.key), kind="mergesort").reset_index(drop=True),
        pd_curves=curves, facility=facility, lgd_of_year=lgd,
    )
