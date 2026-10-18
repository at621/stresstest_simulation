"""R8 year-end provisions: S1 12-month and S2 lifetime ECL, end-2029 interpolation,
S3 allowance floored per exposure, drawn/undrawn split, raw and constrained values.

ECL-01–ECL-11, EAD-08, REG-05, REG-06. Read CLAUDE.md in this folder before editing.
"""

import logging

import numpy as np
import pandas as pd

from stress.contracts.errors import Block, BlockingError
from stress.contracts.run import BASELINE
from stress.contracts.tables import (
    ECL_BUCKETS,
    METHOD_S1,
    METHOD_S1_TERMINAL,
    METHOD_S2,
    METHOD_S3_NEW_BOOKING,
    METHOD_S3_NEW_FLOOR,
    METHOD_S3_ORIGINAL,
    PROVISIONS,
    ROUTE_PERFORMING,
    SLICE_S3_ORIGINAL,
    SLICES,
    Parameters,
    YearProvisions,
)
from stress.ecl.kernels import floor_per_exposure, interpolated_loss_rate, part_year_pd

STEP = "R8"
LOG = logging.getLogger("stress.R8")
METHOD_OPENING_FROZEN = "s3_opening_frozen"
FLOOR_EPS = 1e-9  # EUR; a floor binds when it lifts the raw value by more than this


class PerformingEcl:
    """ECL per performing facility and grade for one scenario and valuation year-end.

    ``on12[f, g]``, ``off12[f, g]``: 12-month ECL (bucket y+1) of the whole facility were it
    entirely in grade g; ``on_life``/``off_life``: the lifetime sum to maturity. ``m[f, g, k]``
    and ``w_on[f, k]``/``w_off[f, k]`` keep the bucket terms for the ECL-09 breakdown.
    """

    def __init__(self, facility_ids, grades, m, w_on, w_off, on12, off12):
        self.facility_ids = facility_ids
        self.grades = grades
        self.m = m
        self.w_on = w_on
        self.w_off = w_off
        self.on12 = on12
        self.off12 = off12
        self.on_life = np.einsum("igk,ik->ig", m, w_on)
        self.off_life = np.einsum("igk,ik->ig", m, w_off)


def _dense(rows: pd.DataFrame, fac_ids: np.ndarray) -> dict:
    """Facility parameter rows of one scenario and valuation as facility x bucket arrays."""
    pos = pd.Series(np.arange(len(fac_ids)), index=fac_ids)
    mapped = rows["facility_id"].map(pos)
    if mapped.isna().any():
        raise BlockingError(STEP, Block.PARAMETER_ALIGNMENT, "parameters for an unknown facility")
    i = mapped.to_numpy(dtype=int)
    k = rows["default_bucket"].to_numpy() - 1
    size = int(k.max()) + 1
    out = {}
    for name in ("ead_drawn", "ead_undrawn", "lgd", "discount_factor"):
        arr = np.zeros((len(fac_ids), size))
        arr[i, k] = rows[name].to_numpy()
        out[name] = arr
    buckets = np.zeros(len(fac_ids), dtype=int)
    np.maximum.at(buckets, i, k + 1)
    last_fraction = np.ones(len(fac_ids))
    last = rows["default_bucket"].to_numpy() == buckets[i]
    last_fraction[i[last]] = rows["fraction"].to_numpy()[last]
    out["buckets"] = buckets
    out["last_fraction"] = last_fraction
    if (buckets == 0).any():
        raise BlockingError(STEP, Block.PARAMETER_ALIGNMENT, "a performing facility has no default bucket")
    return out


def _curve_arrays(curves: pd.DataFrame, grades: tuple[str, ...]) -> dict:
    """Whole-year marginal PDs per (segment, country) as grades x buckets. A curve with a missing
    grade or bucket blocks: a gap is never read as a zero PD."""
    n = len(grades)
    gindex = {g: j for j, g in enumerate(grades)}
    full = {}
    for (segment, country), cv in curves.groupby(["segment", "country"]):
        width = int(cv["default_bucket"].max())
        if len(cv) != n * width:
            raise BlockingError(STEP, Block.PARAMETER_ALIGNMENT, f"PD curve {segment}/{country} has gaps")
        arr = np.zeros((n, width))
        arr[cv["cohort"].map(gindex).to_numpy(), cv["default_bucket"].to_numpy() - 1] = cv["m"].to_numpy()
        full[(segment, country)] = arr
    return full


def performing_ecl(params: Parameters, portfolio: pd.DataFrame, scenario: str, valuation: int,
                   grades: tuple[str, ...]) -> tuple[PerformingEcl, dict]:
    """Every product m[k] x EAD[k] x LGD[k] x DF[k] shares scenario, valuation date, default
    bucket and basis: all terms come from rows selected by that one key (ECL-08)."""
    perf = portfolio[portfolio["route"] == ROUTE_PERFORMING].sort_values("facility_id")
    fac_ids = perf["facility_id"].to_numpy()
    fp = params.facility
    rows = fp[(fp["scenario"] == scenario) & (fp["valuation_year"] == valuation)]
    if rows["basis"].nunique() > 1:
        raise BlockingError(STEP, Block.PARAMETER_ALIGNMENT, "mixed parameter bases in one product")
    dense = _dense(rows, fac_ids)
    w_on = dense["ead_drawn"] * dense["lgd"] * dense["discount_factor"]
    w_off = dense["ead_undrawn"] * dense["lgd"] * dense["discount_factor"]
    n = len(grades)
    size = w_on.shape[1]
    curves = params.pd_curves
    curves = curves[(curves["scenario"] == scenario) & (curves["valuation_year"] == valuation)]
    full = _curve_arrays(curves, grades)
    seg = perf["segment"].to_numpy()
    cty = perf["country"].to_numpy()
    buckets = dense["buckets"]
    # Every bucket to maturity takes its whole-year marginal PD; a final bucket of d years takes
    # d of it, pro rata by the maturity (A7). Whole years have d = 1.
    cover = (np.arange(size)[None, :] < buckets[:, None]).astype(float)
    cover[np.arange(len(fac_ids)), buckets - 1] = dense["last_fraction"]
    m = np.zeros((len(fac_ids), n, size))
    for (segment, country) in sorted(set(zip(seg, cty))):
        idx = np.nonzero((seg == segment) & (cty == country))[0]
        if (segment, country) not in full:
            raise BlockingError(STEP, Block.PARAMETER_ALIGNMENT, f"no PD curve for {segment}/{country}")
        m_full = full[(segment, country)]
        if (buckets[idx] > m_full.shape[1]).any():
            raise BlockingError(STEP, Block.PARAMETER_ALIGNMENT, f"PD curve too short for {segment}/{country}")
        padded = np.zeros((n, size))
        width = min(size, m_full.shape[1])
        padded[:, :width] = m_full[:, :width]
        m[idx] = part_year_pd(padded[None, :, :], cover[idx][:, None, :])
    on12 = m[:, :, 0] * w_on[:, :1]
    off12 = m[:, :, 0] * w_off[:, :1]
    return PerformingEcl(fac_ids, grades, m, w_on, w_off, on12, off12), dense


def terminal_s1(params: Parameters, z: pd.DataFrame, portfolio: pd.DataFrame, scenario: str,
                valuation: int, grades: tuple[str, ...], dense: dict) -> tuple[np.ndarray, np.ndarray]:
    """End-of-horizon S1: the 2030 loss rate interpolated between this scenario's and baseline's
    2029 loss rates, ``a x PD x LGD + (1 - a) x PD_base x LGD_base`` (ECL-05, ECL-10, AT-06).
    Missing 2030 or baseline inputs block; nothing is set to zero (AT-41)."""
    perf = portfolio[portfolio["route"] == ROUTE_PERFORMING].sort_values("facility_id")
    fac_ids = perf["facility_id"].to_numpy()
    n = len(grades)
    weights = z[(z["scenario"] == scenario) & (z["year"] == valuation + 1)].set_index(["segment", "country"])["adverse_weight"]
    if weights.empty:
        raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT,
                            f"no {valuation + 1} terminal weight for {scenario}")
    keys = list(zip(perf["segment"], perf["country"]))
    try:
        a = np.array([weights.loc[k] for k in keys], dtype=float)
    except KeyError as exc:
        raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT, f"no terminal weight for {exc}") from exc

    def loss_rate(s: str) -> tuple[np.ndarray, np.ndarray]:
        curves = params.pd_curves
        one_year = curves[(curves["scenario"] == s) & (curves["valuation_year"] == valuation - 1)
                          & (curves["default_bucket"] == 1)]
        lgd = params.lgd_of_year
        lgd = lgd[(lgd["scenario"] == s) & (lgd["year"] == valuation)].set_index("facility_id")["lgd"]
        if one_year.empty or lgd.empty:
            raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT,
                                f"{s} {valuation} PD or LGD missing for the {valuation + 1} interpolation")
        pd_grid = np.zeros((len(fac_ids), n))
        table = {(r.segment, r.country, r.cohort): r.m for r in one_year.itertuples(index=False)}
        for i, (segment, country) in enumerate(keys):
            pd_grid[i] = [table.get((segment, country, g), np.nan) for g in grades]
        if np.isnan(pd_grid).any():
            raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT, f"{s} {valuation} PD missing")
        # A first bucket shorter than a year takes the part of each PD that the maturity covers,
        # as in every other bucket (A7, A27).
        frac = np.where(dense["buckets"] == 1, dense["last_fraction"], 1.0)
        pd_grid = part_year_pd(pd_grid, frac[:, None])
        lgd_vec = lgd.reindex(fac_ids).to_numpy()
        if np.isnan(lgd_vec).any():
            raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT, f"{s} {valuation} LGD missing")
        return pd_grid, lgd_vec

    if BASELINE not in set(params.pd_curves["scenario"]):
        raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT,
                            f"the {valuation + 1} S1 loss rate needs baseline {valuation} parameters")
    own_pd, own_lgd = loss_rate(scenario)
    base_pd, base_lgd = loss_rate(BASELINE)
    rate = interpolated_loss_rate(own_pd, own_lgd[:, None], base_pd, base_lgd[:, None], a[:, None])
    on = rate * (dense["ead_drawn"][:, 0] * dense["discount_factor"][:, 0])[:, None]
    off = rate * (dense["ead_undrawn"][:, 0] * dense["discount_factor"][:, 0])[:, None]
    return on, off


def year_end_provisions(slices: pd.DataFrame, params: Parameters, z: pd.DataFrame,
                        portfolio: pd.DataFrame, scenario: str, year: int, grades: tuple[str, ...],
                        last_scenario_year: int, opening: bool = False) -> YearProvisions:
    """Provisions for every slice at the year-end ``year``. With ``opening`` the year is the
    snapshot and the result is a diagnostic: S3 keeps its frozen opening allowance."""
    facts = portfolio.set_index("facility_id")
    ecl, dense = performing_ecl(params, portfolio, scenario, year, grades)
    terminal = (not opening) and year == last_scenario_year
    if terminal:
        on12, off12 = terminal_s1(params, z, portfolio, scenario, year, grades, dense)
    else:
        on12, off12 = ecl.on12, ecl.off12
    pos = pd.Series(np.arange(len(ecl.facility_ids)), index=ecl.facility_ids)
    gindex = {g: j for j, g in enumerate(grades)}

    perf = slices[slices["stage"] < 3].copy()
    i = perf["facility_id"].map(pos).to_numpy()
    g = perf["grade"].map(gindex).to_numpy()
    gca_f = perf["facility_id"].map(facts["gca"]).to_numpy()
    und_f = perf["facility_id"].map(facts["undrawn"]).to_numpy()
    share_on = np.divide(perf["gca"].to_numpy(), gca_f, out=np.zeros(len(perf)), where=gca_f > 0)
    share_off = np.divide(perf["undrawn"].to_numpy(), und_f, out=np.zeros(len(perf)), where=und_f > 0)
    s1 = perf["stage"].to_numpy() == 1
    on = np.where(s1, on12[i, g], ecl.on_life[i, g]) * share_on
    off = np.where(s1, off12[i, g], ecl.off_life[i, g]) * share_off
    perf["raw_on"] = on
    perf["raw_off"] = off
    perf["allowance_on"] = on
    perf["provision_off"] = off
    perf["method"] = np.where(s1, METHOD_S1_TERMINAL if terminal else METHOD_S1, METHOD_S2)

    s3 = slices[slices["stage"] == 3].copy()
    if opening:
        s3["raw_on"] = s3["allowance_on"]
        s3["raw_off"] = s3["provision_off"]
        s3["method"] = METHOD_OPENING_FROZEN
    else:
        lgd = params.lgd_of_year
        lgd = lgd[(lgd["scenario"] == scenario) & (lgd["year"] == year)].set_index("facility_id")["lgd"]
        lgd_s = s3["facility_id"].map(lgd)
        if lgd_s.isna().any():
            raise BlockingError(STEP, Block.MISSING_PARAMETER, f"LGD of {year} missing for an S3 slice")
        ccf = params.lgd_of_year
        ccf = ccf[(ccf["scenario"] == scenario) & (ccf["year"] == year)].set_index("facility_id")["ccf"]
        # Without an undrawn amount the CCF is not applicable and the undrawn term is zero.
        ccf_s = s3["facility_id"].map(ccf).where(s3["undrawn"] > 0, 0.0)
        if ccf_s.isna().any():
            raise BlockingError(STEP, Block.MISSING_PARAMETER, "CCF missing for an S3 undrawn amount")
        raw_on = s3["gca"].to_numpy() * lgd_s.to_numpy()
        raw_off = s3["undrawn"].to_numpy() * ccf_s.to_numpy() * lgd_s.to_numpy()
        booked = (s3["entry_year"] == year) & (s3["slice"] != SLICE_S3_ORIGINAL)
        prior_on = s3["allowance_on"].to_numpy()
        prior_off = s3["provision_off"].to_numpy()
        if np.isnan(prior_on[~booked.to_numpy()]).any():
            raise BlockingError(STEP, Block.MISSING_PARAMETER, "an existing S3 slice has no prior allowance")
        floored_on, _ = floor_per_exposure(raw_on, np.nan_to_num(prior_on, nan=-np.inf))
        floored_off, _ = floor_per_exposure(raw_off, np.nan_to_num(prior_off, nan=-np.inf))
        s3["raw_on"] = raw_on
        s3["raw_off"] = raw_off
        s3["allowance_on"] = np.where(booked, raw_on, floored_on)
        s3["provision_off"] = np.where(booked, raw_off, floored_off)
        s3["method"] = np.where(booked, METHOD_S3_NEW_BOOKING,
                                np.where(s3["slice"] == SLICE_S3_ORIGINAL, METHOD_S3_ORIGINAL,
                                         METHOD_S3_NEW_FLOOR))
    out = pd.concat([perf, s3], ignore_index=True)
    out["masked_on"] = out["allowance_on"] - out["raw_on"]
    out["masked_off"] = out["provision_off"] - out["raw_off"]
    out["floor_binding"] = (out["masked_on"] > FLOOR_EPS) | (out["masked_off"] > FLOOR_EPS)
    provisions = PROVISIONS.check(out, STEP).sort_values(list(PROVISIONS.key), kind="mergesort")
    new_slices = SLICES.check(out, STEP).sort_values(list(SLICES.key), kind="mergesort")
    buckets = ecl_buckets(ecl, perf, i, g, share_on, share_off, s1, terminal, on12, off12,
                          facts, scenario, year)
    by_stage = out.groupby("stage")[["allowance_on", "provision_off"]].sum().sum(axis=1) / 1_000_000
    binding = out["floor_binding"].astype(bool)
    LOG.info("%s %d%s: provisions EUR %.1fm on-balance, %.1fm off-balance (S1 %.1fm, S2 %.1fm, S3 %.1fm)%s; "
             "S3 floors binding on %s slices (EUR %.1fm masked)",
             scenario, year, " opening diagnostic" if opening else "",
             out["allowance_on"].sum() / 1_000_000, out["provision_off"].sum() / 1_000_000,
             by_stage.get(1, 0.0), by_stage.get(2, 0.0), by_stage.get(3, 0.0),
             "; S1 uses the interpolated next-year loss rate" if terminal else "",
             f"{int(binding.sum()):,}", (out["masked_on"] + out["masked_off"]).sum() / 1_000_000)
    return YearProvisions(slices=new_slices.reset_index(drop=True),
                          provisions=provisions.reset_index(drop=True), ecl_buckets=buckets)


def ecl_buckets(ecl: PerformingEcl, perf: pd.DataFrame, i, g, share_on, share_off, s1, terminal,
                on12, off12, facts, scenario, year) -> pd.DataFrame:
    """Performing ECL split by default bucket, summed by segment and stage (ECL-09)."""
    n_fac, n_grades, _ = ecl.m.shape
    w2_on = np.zeros((n_fac, n_grades))
    w2_off = np.zeros((n_fac, n_grades))
    np.add.at(w2_on, (i[~s1], g[~s1]), share_on[~s1])
    np.add.at(w2_off, (i[~s1], g[~s1]), share_off[~s1])
    s2_on = np.einsum("ig,igk,ik->ik", w2_on, ecl.m, ecl.w_on)
    s2_off = np.einsum("ig,igk,ik->ik", w2_off, ecl.m, ecl.w_off)
    s1_on = np.zeros(n_fac)
    s1_off = np.zeros(n_fac)
    np.add.at(s1_on, i[s1], on12[i[s1], g[s1]] * share_on[s1])
    np.add.at(s1_off, i[s1], off12[i[s1], g[s1]] * share_off[s1])
    segment = facts.loc[ecl.facility_ids, "segment"].to_numpy()
    frames = []
    for stage, on_k, off_k in ((1, s1_on[:, None], s1_off[:, None]), (2, s2_on, s2_off)):
        df = pd.DataFrame(on_k, columns=range(1, on_k.shape[1] + 1))
        df["segment"] = segment
        on_sum = df.groupby("segment").sum()
        dfo = pd.DataFrame(off_k, columns=range(1, off_k.shape[1] + 1))
        dfo["segment"] = segment
        off_sum = dfo.groupby("segment").sum()
        long_on = on_sum.stack().rename("ecl_on")
        long_off = off_sum.stack().rename("ecl_off")
        part = pd.concat([long_on, long_off], axis=1).reset_index()
        part.columns = ["segment", "default_bucket", "ecl_on", "ecl_off"]
        part["stage"] = stage
        frames.append(part)
    out = pd.concat(frames, ignore_index=True)
    out = out[(out["ecl_on"] != 0) | (out["ecl_off"] != 0)]
    out["scenario"] = scenario
    out["valuation_year"] = year
    out["default_bucket"] = out["default_bucket"].astype(int)
    return ECL_BUCKETS.check(out, STEP).sort_values(list(ECL_BUCKETS.key)).reset_index(drop=True)
