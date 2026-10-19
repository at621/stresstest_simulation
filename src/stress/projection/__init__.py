"""R7 project the year: grade migration (closing = opening × M(y)), stage from the grade,
new S3 cohorts with entry year and origin stage, static balance and like-for-like
replacement.

EXP-01–EXP-03, EXP-05, MIG-01–MIG-08, PD-05, PD-06, REG-02, REG-04.
"""

import logging

import numpy as np
import pandas as pd

from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import DEFAULT_GRADE
from stress.contracts.tables import (
    GRADE_FLOWS,
    ROUTE_PERFORMING,
    SLICE_S3_ORIGINAL,
    SLICES,
    STAGE_FLOWS,
    YearProjection,
    new_s3_slice,
)
from stress.projection.kernels import stage_of_rank

STEP = "R7"
LOG = logging.getLogger("stress.R7")
STAGE_NAMES = {1: "S1", 2: "S2", 3: "S3"}


def opening_slices(portfolio: pd.DataFrame, grades: tuple[str, ...], snapshot_year: int,
                   scenario: str) -> pd.DataFrame:
    """End-2026 state: one slice per facility at its current grade (or S3_orig), carrying the
    frozen opening allowance and provision."""
    perf = portfolio["route"] == ROUTE_PERFORMING
    out = pd.DataFrame({
        "scenario": scenario,
        "year": snapshot_year,
        "facility_id": portfolio["facility_id"],
        "slice": np.where(perf, portfolio["current_grade"], SLICE_S3_ORIGINAL),
        "stage": portfolio["stage"].astype(int),
        "grade": portfolio["current_grade"],
        "origination_grade": portfolio["origination_grade"],
        "entry_year": np.where(perf, np.nan, snapshot_year).astype(float),
        "origin_stage": np.nan,
        "gca": portfolio["gca"].astype(float),
        "undrawn": portfolio["undrawn"].astype(float),
        "allowance_on": portfolio["opening_allowance_on"].astype(float),
        "provision_off": portfolio["opening_provision_off"].astype(float),
        "generation": 0,
        "replaced": False,
    })
    return SLICES.check(out, STEP)


def _matrix(pit: pd.DataFrame, grades: list[str]) -> dict[tuple[str, str], np.ndarray]:
    size = len(grades)
    rank = {g: i for i, g in enumerate(grades)}
    out = {}
    for (segment, country), cells in pit.groupby(["segment", "country"]):
        m = np.zeros((size, size))
        m[cells["from_grade"].map(rank).to_numpy(), cells["to_grade"].map(rank).to_numpy()] = cells["probability"]
        out[(segment, country)] = m
    return out


def project_year(previous: pd.DataFrame, pit: pd.DataFrame, portfolio: pd.DataFrame,
                 grades: tuple[str, ...], year: int, scenario: str, generation: pd.Series,
                 tol: dict) -> YearProjection:
    """Move every performing grade slice one year with the scenario's PiT matrix M(year).

    ``pit`` holds that scenario and year only. ``generation`` maps facility_id to its
    replacement generation at this year-end (from R5's schedule).
    """
    labels = list(grades) + [DEFAULT_GRADE]
    n = len(grades)
    rank = {g: i for i, g in enumerate(grades)}
    matrices = _matrix(pit, labels)
    facts = portfolio.set_index("facility_id")
    perf_prev = previous[previous["stage"] < 3]
    s3_prev = previous[previous["stage"] == 3]

    fac_ids = facts.index[facts["route"] == ROUTE_PERFORMING]
    pos = {f: i for i, f in enumerate(fac_ids)}
    rows = perf_prev["facility_id"].map(pos).to_numpy()
    cols = perf_prev["grade"].map(rank).to_numpy()
    gca = np.zeros((len(fac_ids), n))
    und = np.zeros((len(fac_ids), n))
    np.add.at(gca, (rows, cols), perf_prev["gca"].to_numpy())
    np.add.at(und, (rows, cols), perf_prev["undrawn"].to_numpy())
    sicr = facts.loc[fac_ids, "sicr_rank"].to_numpy()
    flagged = facts.loc[fac_ids, "qualitative_trigger"].to_numpy(dtype=bool)  # held until default
    grade_rank = np.arange(1, n + 1)[None, :]
    stage_grid = stage_of_rank(grade_rank, sicr[:, None], n + 1, flagged[:, None])  # facilities x grades
    s2 = stage_grid == 2

    seg = facts.loc[fac_ids, "segment"].to_numpy()
    cty = facts.loc[fac_ids, "country"].to_numpy()
    new_gca = np.zeros_like(gca)
    new_und = np.zeros_like(und)
    default_gca = np.zeros_like(gca)
    default_und = np.zeros_like(und)
    flows = []
    grade_flow_frames = []
    for key in sorted(set(zip(seg, cty))):
        idx = np.nonzero((seg == key[0]) & (cty == key[1]))[0]
        if key not in matrices:
            raise BlockingError(STEP, Block.MISSING_TERMINAL_INPUT, f"no PiT matrix for {key} in {year}")
        m = matrices[key]
        g, u = gca[idx], und[idx]
        new_gca[idx] = g @ m[:n, :n]
        new_und[idx] = u @ m[:n, :n]
        default_gca[idx] = g * m[:n, n]
        default_und[idx] = u * m[:n, n]
        # Stage flows: sums of matrix cells grouped by each facility's SICR line (MIG-08).
        to_s2 = s2[idx]
        for origin, mask in ((1, ~to_s2), (2, to_s2)):
            src_g = g * mask
            src_u = u * mask
            moved_g = src_g @ m[:n, :n]
            moved_u = src_u @ m[:n, :n]
            flows.append((key[0], origin, 1, (moved_g * ~to_s2).sum(), (moved_u * ~to_s2).sum()))
            flows.append((key[0], origin, 2, (moved_g * to_s2).sum(), (moved_u * to_s2).sum()))
            flows.append((key[0], origin, 3, (src_g * m[:n, n]).sum(), (src_u * m[:n, n]).sum()))
        totals = g.sum(axis=0)
        cells = totals[:, None] * m[:n, :]
        grade_flow_frames.append(pd.DataFrame({
            "segment": key[0], "country": key[1],
            "from_grade": np.repeat(list(grades), n + 1), "to_grade": np.tile(labels, n),
            "gca": cells.ravel(),
        }))

    # New S3 cohorts by origin stage keep their entry year (MIG-03).
    new_s3 = []
    for origin, mask in ((1, ~s2), (2, s2)):
        flow_g = (default_gca * mask).sum(axis=1)
        flow_u = (default_und * mask).sum(axis=1)
        keep = flow_g + flow_u > 0
        new_s3.append(pd.DataFrame({
            "facility_id": fac_ids[keep], "slice": new_s3_slice(year, origin), "stage": 3,
            "grade": DEFAULT_GRADE, "entry_year": float(year), "origin_stage": float(origin),
            "gca": flow_g[keep], "undrawn": flow_u[keep],
            "allowance_on": np.nan, "provision_off": np.nan,
        }))
    r_idx, c_idx = np.nonzero((new_gca > 0) | (new_und > 0))
    performing = pd.DataFrame({
        "facility_id": fac_ids[r_idx], "slice": np.array(grades)[c_idx],
        "stage": stage_grid[r_idx, c_idx], "grade": np.array(grades)[c_idx],
        "entry_year": np.nan, "origin_stage": np.nan,
        "gca": new_gca[r_idx, c_idx], "undrawn": new_und[r_idx, c_idx],
        "allowance_on": np.nan, "provision_off": np.nan,
    })
    # S3 slices bypass the matrix: no cure, sale or write-off removal (EXP-02). They carry their
    # prior allowance into R8, which floors it.
    carried = s3_prev[["facility_id", "slice", "stage", "grade", "entry_year", "origin_stage",
                       "gca", "undrawn", "allowance_on", "provision_off"]]
    slices = pd.concat([performing, *new_s3, carried], ignore_index=True)
    slices["origination_grade"] = slices["facility_id"].map(facts["origination_grade"])
    slices["scenario"] = scenario
    slices["year"] = year
    prev_gen = previous.groupby("facility_id")["generation"].max()
    slices["generation"] = slices["facility_id"].map(generation).fillna(
        slices["facility_id"].map(prev_gen)).fillna(0).astype(int)
    slices["replaced"] = slices["generation"] > slices["facility_id"].map(prev_gen).fillna(0)
    check_static(previous, slices, tol)

    stage_flows = pd.DataFrame(flows, columns=["segment", "from_stage", "to_stage", "gca", "undrawn"])
    stage_flows = stage_flows.groupby(["segment", "from_stage", "to_stage"], as_index=False).sum()
    s3_stock = s3_prev.groupby(s3_prev["facility_id"].map(facts["segment"]))[["gca", "undrawn"]].sum()
    for segment, row in s3_stock.iterrows():
        stage_flows.loc[len(stage_flows)] = [segment, 3, 3, row["gca"], row["undrawn"]]
    stage_flows = stage_flows.groupby(["segment", "from_stage", "to_stage"], as_index=False).sum()
    stage_flows["portfolio"] = stage_flows["segment"].map(
        portfolio.drop_duplicates("segment").set_index("segment")["portfolio"])
    stage_flows["scenario"] = scenario
    stage_flows["year"] = year
    stock = slices.groupby("stage")["gca"].sum() / 1_000_000
    new = [frame["gca"].sum() / 1_000_000 for frame in new_s3]
    LOG.info("%s %d: GCA S1 %.1fm, S2 %.1fm, S3 %.1fm; new S3 %.1fm (from S1 %.1fm, from S2 %.1fm); "
             "%s facilities replaced; static balance holds", scenario, year, stock.get(1, 0.0),
             stock.get(2, 0.0), stock.get(3, 0.0), sum(new), new[0], new[1],
             f"{int(slices.drop_duplicates('facility_id')['replaced'].sum()):,}")
    grade_flows = pd.concat(grade_flow_frames, ignore_index=True)
    grade_flows["scenario"] = scenario
    grade_flows["year"] = year
    return YearProjection(
        slices=SLICES.check(slices, STEP).sort_values(["facility_id", "slice"], kind="mergesort")
        .reset_index(drop=True),
        stage_flows=STAGE_FLOWS.check(stage_flows, STEP),
        grade_flows=GRADE_FLOWS.check(grade_flows, STEP),
    )


def check_static(previous: pd.DataFrame, current: pd.DataFrame, tol: dict) -> None:
    """GCA and undrawn stay at their end-2026 levels per facility (EXP-01, EAD-05, REG-02)."""
    for col in ("gca", "undrawn"):
        before = previous.groupby("facility_id")[col].sum()
        after = current.groupby("facility_id")[col].sum().reindex(before.index).fillna(0.0)
        gap = (after - before).abs()
        limit = np.maximum(tol["abs"], tol["rel"] * before.abs())
        if (gap > limit).any() or set(current["facility_id"]) - set(before.index):
            worst = gap.idxmax()
            raise BlockingError(STEP, Block.STATIC_BALANCE,
                                f"unexplained change in {col} of {worst}: {before[worst]} -> {after[worst]}")
