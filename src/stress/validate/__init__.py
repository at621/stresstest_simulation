"""R3 validate and route: schema and referential integrity, EUR-only and AC-only scope,
TTC matrix checks, grade or qualitative trigger explains stage, section 12.2 input controls.
Sends each record down exactly one route; a rejected record goes to the log with a reason code.

DAT-01, DAT-04, SCP-02, SCP-06, MIG-01, MIG-05, MIG-07, section 12.2.
"""

import logging

import numpy as np
import pandas as pd

from stress.contracts.errors import RUN_BLOCKING_REASONS, Block, BlockingError, Reason
from stress.contracts.inputs import (
    CENTRAL_BANK_SECTOR,
    CURRENCY,
    DEFAULT_GRADE,
    OFF_BALANCE_CATEGORY,
    ON_BALANCE_CATEGORY,
    PRODUCTS,
    REPAYMENT_PROFILES,
    SEGMENT_PARAMETERS,
    STAGES,
    TERM_PRODUCTS,
    LoadedInputs,
)
from stress.contracts.run import RunContext
from stress.contracts.status import USABLE_STATUSES
from stress.contracts.tables import (
    PORTFOLIO,
    REJECTIONS,
    ROUTE_PERFORMING,
    ROUTE_S3_ORIGINAL,
    RoutedPortfolio,
)
from stress.validate.sicr import (
    HOLD_UNTIL_DEFAULT,
    TRIGGERS,
    TtcLifetime,
    qualitative_trigger,
    sicr_rank,
)

STEP = "R3"
LOG = logging.getLogger("stress.R3")
USABLE = [str(s) for s in USABLE_STATUSES]


# --- matrices -----------------------------------------------------------------------------------

def matrix_set(table: pd.DataFrame, tol: float) -> tuple[dict[str, np.ndarray], tuple[str, ...]]:
    """Every segment's TTC matrix as an array (grades in rank order, D last), checked against
    PD-09: rows sum to one, no negative cell, D absorbing, PD rising with the grade."""
    if table.duplicated(["segment", "from_grade", "to_grade"]).any():
        raise BlockingError(STEP, Block.INVALID_MATRIX, "duplicate matrix cell")
    labels = (
        table[["from_rank", "from_grade"]].drop_duplicates().sort_values("from_rank")
    )
    if labels["from_rank"].duplicated().any() or labels["from_grade"].duplicated().any():
        raise BlockingError(STEP, Block.INVALID_MATRIX, "grade labels differ between segments")
    grades = tuple(labels["from_grade"])
    if not grades or grades[-1] != DEFAULT_GRADE:
        raise BlockingError(STEP, Block.INVALID_MATRIX, "the master scale must end with D")
    size = len(grades)
    if list(labels["from_rank"]) != list(range(1, size + 1)):
        raise BlockingError(STEP, Block.INVALID_MATRIX, "grade ranks are not 1..N+1")
    matrices = {}
    for segment, cells in table.groupby("segment", sort=True):
        if len(cells) != size * size:
            raise BlockingError(STEP, Block.INVALID_MATRIX,
                                f"{segment}: {len(cells)} cells, expected {size * size}")
        m = np.zeros((size, size))
        m[cells["from_rank"].to_numpy() - 1, cells["to_rank"].to_numpy() - 1] = cells["probability"]
        _check_matrix(m, tol, f"TTC matrix {segment}")
        matrices[str(segment)] = m
    return matrices, grades[:-1]


def _check_matrix(m: np.ndarray, tol: float, name: str) -> None:
    problems = []
    if (np.abs(m.sum(axis=1) - 1.0) > tol).any():
        problems.append("a row does not sum to one")
    if (m < 0).any():
        problems.append("negative cell")
    if not (abs(m[-1, -1] - 1.0) <= tol and np.all(np.abs(m[-1, :-1]) <= tol)):
        problems.append("D is not absorbing")
    if not np.all(np.diff(m[:-1, -1]) > 0):
        problems.append("PD does not rise with the grade")
    if problems:
        raise BlockingError(STEP, Block.INVALID_MATRIX, f"{name}: " + "; ".join(problems))


# --- rejection log ------------------------------------------------------------------------------

class Log:
    def __init__(self):
        self.frames: list[pd.DataFrame] = []

    def add(self, table: pd.DataFrame, mask: pd.Series, record_type: str, id_col: str,
            reason: Reason, detail: str) -> None:
        mask = mask.fillna(False).astype(bool)
        if not mask.any():
            return
        sel = table.loc[mask]
        self.frames.append(pd.DataFrame({
            "record_type": record_type,
            "record_id": sel[id_col].astype(str).to_numpy(),
            "row": sel["_row"].to_numpy(),
            "reason_code": str(reason),
            "detail": detail,
            "step": STEP,
        }))

    def ids(self, record_type: str) -> set[int]:
        rows = set()
        for frame in self.frames:
            rows.update(frame.loc[frame["record_type"] == record_type, "row"].tolist())
        return rows

    def table(self) -> pd.DataFrame:
        if not self.frames:
            return pd.DataFrame({c: pd.Series(dtype=object) for c in REJECTIONS.all_columns})
        out = pd.concat(self.frames, ignore_index=True)
        out = out.drop_duplicates(["record_type", "record_id", "row", "reason_code"])
        out["row"] = out["row"].astype(int)
        return REJECTIONS.check(out, STEP).sort_values(
            ["record_type", "row", "reason_code"], kind="mergesort").reset_index(drop=True)


def _usable(status: pd.DataFrame, col: str) -> pd.Series:
    return status[col].isin(USABLE)


# --- checks -------------------------------------------------------------------------------------

def _check_parameters(ps: dict, segments: set[str], variant: str) -> None:
    if variant not in ps["variants"]:
        raise BlockingError(STEP, Block.UNKNOWN_VARIANT,
                            f"variant {variant!r} is not in the parameter set ({sorted(ps['variants'])})")
    for seg in sorted(segments):
        params = ps["segments"].get(seg)
        if params is None:
            raise BlockingError(STEP, Block.MISSING_PARAMETER, f"no parameters for segment {seg}")
        missing = [p for p in SEGMENT_PARAMETERS if p not in params]
        if missing:
            raise BlockingError(STEP, Block.MISSING_PARAMETER, f"segment {seg} lacks {missing}")
        for name in ("rho", "sicr_k", "lgd_w", "cpr_ttc", "cpr_v"):
            if params[name] is None:
                raise BlockingError(STEP, Block.MISSING_PARAMETER, f"segment {seg}: {name} is OPEN")
        if not params["z_drivers"]:
            raise BlockingError(STEP, Block.MISSING_PARAMETER, f"segment {seg}: no Z drivers")
    _check_triggers(ps["sicr_triggers"])


def _check_triggers(settings) -> None:
    """The qualitative SICR triggers (MIG-05, A30): which are switched on, the days-past-due
    threshold, and a source definition for each switched-on trigger (section 4.2)."""
    if not isinstance(settings, dict):
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "sicr_triggers is not a mapping")
    missing = [k for k in ("enabled", "dpd_days", "hold", "definitions", "source") if settings.get(k) is None]
    if missing:
        raise BlockingError(STEP, Block.MISSING_PARAMETER, f"sicr_triggers lacks {missing}")
    if not isinstance(settings["definitions"], dict):
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "sicr_triggers: definitions is not a mapping")
    if not str(settings["source"]).strip():
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "sicr_triggers: source is empty")
    if settings["hold"] != HOLD_UNTIL_DEFAULT:
        raise BlockingError(STEP, Block.MISSING_PARAMETER,
                            f"sicr_triggers: hold {settings['hold']!r} is not supported; v1 holds a flag until "
                            f"default ({HOLD_UNTIL_DEFAULT!r}, A30)")
    if not isinstance(settings["enabled"], list):
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "sicr_triggers: enabled is not a list of triggers")
    unknown = sorted(set(settings["enabled"]) - set(TRIGGERS))
    if unknown:
        raise BlockingError(STEP, Block.MISSING_PARAMETER, f"sicr_triggers: unknown triggers {unknown}")
    days = settings["dpd_days"]
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise BlockingError(STEP, Block.MISSING_PARAMETER, "sicr_triggers: dpd_days must be a positive integer")
    undefined = [t for t in settings["enabled"] if not settings["definitions"].get(t)]
    if undefined:
        raise BlockingError(STEP, Block.MISSING_PARAMETER, f"sicr_triggers: no source definition for {undefined}")


def validate_and_route(loaded: LoadedInputs, ctx: RunContext) -> RoutedPortfolio:
    ps = loaded.parameter_set
    tol_prob = ps["tolerances"]["probability_identity"]["abs"]
    tol_amount = ps["tolerances"]["amount"]["abs"]
    tol_agg = ps["tolerances"]["aggregate"]
    matrices, grades = matrix_set(loaded.ttc_pd_matrix, tol_prob)
    _check_parameters(ps, set(matrices), ctx.variant)
    scale = ps["master_scale"]["grades"]
    if list(scale) != list(grades):
        raise BlockingError(STEP, Block.INVALID_MATRIX,
                            "matrix grades differ from the parameter-set master scale")
    rank = {g: i + 1 for i, g in enumerate(grades)}
    default_rank = len(grades) + 1
    rank_d = {**rank, DEFAULT_GRADE: default_rank}
    countries = set(loaded.scenario_values["country"])
    snapshot = str(ps["horizon"]["snapshot_date"])
    for table in (loaded.facilities, loaded.obligors, loaded.commitments, loaded.opening_provisions):
        dates = set(table.data["snapshot_date"].astype(str))
        if dates and dates != {snapshot}:
            raise BlockingError(STEP, Block.HORIZON_MISMATCH,
                                f"{table.name} snapshot dates {sorted(dates)} differ from {snapshot} (REG-01)")

    log = Log()
    fac = loaded.facilities.data.copy()
    fst = loaded.facilities.status
    fac["_row"] = np.arange(len(fac))
    obl = loaded.obligors.data.copy()
    ost = loaded.obligors.status
    obl["_row"] = np.arange(len(obl))
    com = loaded.commitments.data.copy()
    cst = loaded.commitments.status
    com["_row"] = np.arange(len(com))
    prov = loaded.opening_provisions.data.copy()
    pst = loaded.opening_provisions.status
    prov["_row"] = np.arange(len(prov))

    # Obligors.
    log.add(obl, obl["obligor_id"].duplicated(keep=False), "obligor", "obligor_id",
            Reason.DUPLICATE_OBLIGOR, "obligor_id appears more than once")
    good_obl = obl.loc[~obl["_row"].isin(log.ids("obligor"))]
    good_ost = ost.loc[good_obl.index]
    obligor_cols = ["obligor_id", "group_id", "country", "counterparty_sector", "nace_code",
                    "regulatory_default"]
    f = fac.merge(good_obl[obligor_cols], on="obligor_id", how="left", indicator=True)
    f.index = fac.index
    country_ok = good_ost.set_index(good_obl["obligor_id"])["country"].isin(USABLE)
    f["_country_usable"] = f["obligor_id"].map(country_ok).fillna(False).astype(bool)
    default_ok = good_ost.set_index(good_obl["obligor_id"])["regulatory_default"].isin(USABLE)
    f["_default_usable"] = f["obligor_id"].map(default_ok).fillna(False).astype(bool)

    # Facilities: identity, scope and classification.
    def add(mask, reason, detail):
        log.add(f, mask, "facility", "facility_id", reason, detail)

    add(f["facility_id"].duplicated(keep=False), Reason.DUPLICATE_FACILITY,
        "facility_id appears more than once")
    add(f["_merge"] != "both", Reason.ORPHAN_FACILITY, "obligor not found or rejected")
    add(~_usable(fst, "currency"), Reason.MISSING_CURRENCY, "currency missing")
    add(_usable(fst, "currency") & (f["currency"] != CURRENCY), Reason.NON_EUR_CURRENCY,
        "currency is not EUR")
    add(~_usable(fst, "accounting_category"), Reason.MISSING_ACCOUNTING_CATEGORY,
        "accounting category missing")
    add(_usable(fst, "accounting_category") & (f["accounting_category"] != ON_BALANCE_CATEGORY),
        Reason.NON_AC_ON_BALANCE, "on-balance asset is not at amortised cost")
    # A missing flag is never read as True or False (missing is never a default).
    for col in ("poci", "accrued_in_gca", "dpd", "watchlist", "forborne"):
        add(~_usable(fst, col), Reason.MISSING_FLAG, f"{col} missing")
    add(_usable(fst, "dpd") & (pd.to_numeric(f["dpd"], errors="coerce") < 0), Reason.INVALID_DPD,
        "days past due is negative")
    observed = pd.to_datetime(f["credit_status_date"], errors="coerce")
    add(~_usable(fst, "credit_status_date") | observed.isna(), Reason.INVALID_CREDIT_STATUS_DATE,
        "credit status observation date missing (section 4.2)")
    add(observed > pd.Timestamp(snapshot), Reason.INVALID_CREDIT_STATUS_DATE,
        "credit status observed after the snapshot date")
    add((f["_merge"] == "both") & ~f["_default_usable"], Reason.MISSING_FLAG,
        "obligor regulatory default flag missing")
    add(f["poci"].eq(True), Reason.POCI_NOT_IN_V1, "POCI has its own treatment, not in v1")
    add(f["counterparty_sector"] == CENTRAL_BANK_SECTOR, Reason.CENTRAL_BANK_NOT_IN_V1,
        "central-bank exposures take the prescribed zero-loss route, not in v1")
    known_segments = set(matrices) & set(ps["segments"])
    add(~f["segment"].isin(known_segments), Reason.UNKNOWN_SEGMENT,
        "segment has no TTC matrix or parameters")
    add(~f["_country_usable"] | ~f["country"].isin(countries), Reason.UNMAPPED_COUNTRY,
        "country missing or without scenario values")
    add(~f["product"].isin(PRODUCTS), Reason.UNKNOWN_PRODUCT, "unknown product")
    stage = pd.to_numeric(f["ifrs_stage"], errors="coerce")
    add(~stage.isin(STAGES), Reason.INVALID_STAGE, "IFRS stage is not 1, 2 or 3")
    for col in ("gca", "principal", "accrued_interest", "contractual_limit"):
        add(~_usable(fst, col), Reason.MISSING_AMOUNT, f"{col} missing")
        add(f[col] < 0, Reason.NEGATIVE_AMOUNT, f"{col} is negative")
    components = np.where(f["accrued_in_gca"].eq(True), f["principal"] + f["accrued_interest"],
                          f["principal"])
    add((f["gca"] - components).abs() > tol_amount, Reason.GCA_COMPONENTS_MISMATCH,
        "GCA does not equal principal plus accrued interest counted once")
    performing = stage.isin([1, 2])
    add(performing & ~_usable(fst, "interest_rate"), Reason.MISSING_RATE, "interest rate missing")
    add(performing & _usable(fst, "interest_rate") & (f["interest_rate"] <= -1.0),
        Reason.INVALID_RATE, "interest rate of -100% or lower")
    add(performing & (~_usable(fst, "residual_maturity") | ~(f["residual_maturity"] > 0)),
        Reason.INVALID_MATURITY, "residual maturity missing or not positive")
    add(performing & ~f["repayment_profile"].isin(REPAYMENT_PROFILES),
        Reason.UNKNOWN_REPAYMENT_PROFILE, "unknown repayment profile")
    for col in ("current_grade", "origination_grade"):
        add(~_usable(fst, col), Reason.MISSING_GRADE, f"{col} missing")
    add(_usable(fst, "current_grade") & ~f["current_grade"].isin(rank_d), Reason.UNKNOWN_GRADE,
        "current grade is not on the master scale")
    add(_usable(fst, "origination_grade") & ~f["origination_grade"].isin(rank), Reason.UNKNOWN_GRADE,
        "origination grade is not a performing master-scale grade")
    add((stage == 3) & _usable(fst, "current_grade") & (f["current_grade"] != DEFAULT_GRADE),
        Reason.STAGE_GRADE_CONFLICT, "S3 facility not in grade D")
    add(performing & (f["current_grade"] == DEFAULT_GRADE), Reason.STAGE_GRADE_CONFLICT,
        "performing facility in grade D")
    add(~_usable(fst, "ttc_lgd"), Reason.MISSING_TTC_LGD, "TTC LGD missing")
    add(_usable(fst, "ttc_lgd") & ((f["ttc_lgd"] < 0) | (f["ttc_lgd"] > 1)),
        Reason.TTC_LGD_OUT_OF_RANGE, "TTC LGD outside [0, 1]")
    defaulted = f["regulatory_default"].eq(True)
    add((f["_merge"] == "both") & f["_default_usable"] & (defaulted != (stage == 3)),
        Reason.DEFAULT_STAGE_CONFLICT,
        "regulatory default and S3 disagree without an explanation (DAT-04)")

    # Commitments.
    def cadd(mask, reason, detail):
        log.add(com, mask, "commitment", "commitment_id", reason, detail)

    cadd(com["commitment_id"].duplicated(keep=False), Reason.DUPLICATE_COMMITMENT,
         "commitment_id appears more than once")
    cadd(com["facility_id"].duplicated(keep=False), Reason.DUPLICATE_COMMITMENT,
         "facility has more than one commitment: its conversion would be counted twice")
    fac_ids = set(f["facility_id"])
    cadd(~com["facility_id"].isin(fac_ids), Reason.ORPHAN_COMMITMENT, "linked facility not found")
    cadd(~_usable(cst, "currency"), Reason.MISSING_CURRENCY, "currency missing")
    cadd(_usable(cst, "currency") & (com["currency"] != CURRENCY), Reason.NON_EUR_CURRENCY,
         "currency is not EUR")
    cadd(com["asset_category"] != OFF_BALANCE_CATEGORY, Reason.OFF_BALANCE_CATEGORY,
         'off-balance commitment must have asset category "not_applicable"')
    cadd(~_usable(cst, "nominal_undrawn"), Reason.MISSING_AMOUNT, "nominal undrawn missing")
    cadd(com["nominal_undrawn"] < 0, Reason.NEGATIVE_AMOUNT, "nominal undrawn is negative")
    cadd(~_usable(cst, "accounting_ccf") & (com["nominal_undrawn"] > 0), Reason.MISSING_CCF,
         "missing CCF on a positive undrawn amount (EAD-04)")
    cadd(_usable(cst, "accounting_ccf") & ((com["accounting_ccf"] < 0) | (com["accounting_ccf"] > 1)),
         Reason.CCF_OUT_OF_RANGE, "CCF outside [0, 1]")
    seg_of = dict(zip(f["facility_id"], f["segment"]))
    product_of = dict(zip(f["facility_id"], f["product"]))
    ref_ccf = com["facility_id"].map(lambda fid: (ps["segments"].get(seg_of.get(fid)) or {}).get("ccf"))
    mismatch = (_usable(cst, "accounting_ccf") & ref_ccf.notna()
                & ((com["accounting_ccf"] - ref_ccf.astype(float)).abs() > tol_prob))
    cadd(mismatch, Reason.CCF_MISMATCH, "CCF differs from the parameter set without explanation")
    cadd(com["facility_id"].map(product_of).isin(TERM_PRODUCTS) & (com["nominal_undrawn"] > 0),
         Reason.UNDRAWN_ON_TERM_PRODUCT, "fully drawn product with an undrawn commitment (EAD-03)")

    # Opening provisions.
    def padd(mask, reason, detail):
        log.add(prov, mask, "opening_provision", "facility_id", reason, detail)

    padd(prov["facility_id"].duplicated(keep=False), Reason.DUPLICATE_OPENING_PROVISION,
         "facility has more than one opening provision")
    padd(~prov["facility_id"].isin(fac_ids), Reason.ORPHAN_OPENING_PROVISION, "facility not found")
    padd(~_usable(pst, "currency"), Reason.MISSING_CURRENCY, "currency missing")
    padd(_usable(pst, "currency") & (prov["currency"] != CURRENCY), Reason.NON_EUR_CURRENCY,
         "currency is not EUR")
    for col in ("allowance_on", "provision_off", "overlay_amount"):
        padd(~_usable(pst, col), Reason.MISSING_AMOUNT, f"{col} missing")
        padd(prov[col] < 0, Reason.NEGATIVE_AMOUNT, f"{col} is negative")
    add(~f["facility_id"].isin(set(prov["facility_id"])), Reason.MISSING_OPENING_PROVISION,
        "no frozen opening provision")

    # Limit check needs the commitment amount.
    good_com = com.loc[~com["_row"].isin(log.ids("commitment"))]
    undrawn_of = dict(zip(good_com["facility_id"], good_com["nominal_undrawn"]))
    undrawn = f["facility_id"].map(undrawn_of).fillna(0.0)
    add(f["principal"] + undrawn > f["contractual_limit"] + tol_amount, Reason.LIMIT_BREACH,
        "drawn principal plus undrawn exceeds the contractual limit")

    # Linked records: a rejected commitment or provision rejects its facility, and back.
    bad_com_fac = set(com.loc[com["_row"].isin(log.ids("commitment")), "facility_id"])
    bad_prov_fac = set(prov.loc[prov["_row"].isin(log.ids("opening_provision")), "facility_id"])
    add(f["facility_id"].isin(bad_com_fac | bad_prov_fac), Reason.LINKED_RECORD_REJECTED,
        "its commitment or opening provision was rejected")
    bad_rows = log.ids("facility")

    # Grade or qualitative trigger explains stage (MIG-07, MIG-05, A30), for performing
    # facilities that passed so far.
    cand = f.loc[~f["_row"].isin(bad_rows) & performing].copy()
    lifetime = TtcLifetime(matrices)
    sicr = np.full(len(cand), default_rank, dtype=int)
    for pos, (seg, horizon, g0) in enumerate(zip(cand["segment"], cand["residual_maturity"],
                                                  cand["origination_grade"])):
        pd_life = lifetime.pd(seg, float(horizon))
        line, contiguous = sicr_rank(pd_life, rank[g0], float(ps["segments"][seg]["sicr_k"]))
        if not contiguous:
            raise BlockingError(STEP, Block.MATRIX_NOT_MONOTONE,
                                f"{seg}: lifetime TTC PD does not rise with the grade over {horizon} years")
        sicr[pos] = line
    cand["sicr_rank"] = sicr
    cand["current_rank"] = cand["current_grade"].map(rank)
    cand["qualitative_trigger"] = qualitative_trigger(cand["dpd"], cand["watchlist"], cand["forborne"],
                                                      ps["sicr_triggers"])
    derived = np.where((cand["current_rank"] >= cand["sicr_rank"]) | cand["qualitative_trigger"], 2, 1)
    conflict = pd.Series(derived != cand["ifrs_stage"].astype(int).to_numpy(), index=cand.index)
    log.add(cand, conflict, "facility", "facility_id", Reason.STAGE_GRADE_CONFLICT,
            "neither the SICR line nor a qualitative trigger gives back the reported stage")
    bad_rows = log.ids("facility")
    good_fac_ids = set(f.loc[~f["_row"].isin(bad_rows), "facility_id"])
    log.add(com, com["facility_id"].isin(set(f["facility_id"]) - good_fac_ids)
            & ~com["_row"].isin(log.ids("commitment")), "commitment", "commitment_id",
            Reason.LINKED_RECORD_REJECTED, "linked facility was rejected")
    log.add(prov, prov["facility_id"].isin(set(f["facility_id"]) - good_fac_ids)
            & ~prov["_row"].isin(log.ids("opening_provision")), "opening_provision", "facility_id",
            Reason.LINKED_RECORD_REJECTED, "linked facility was rejected")

    # Route and build the portfolio table.
    ok = f.loc[~f["_row"].isin(bad_rows)].copy()
    if ok.empty:
        raise BlockingError(STEP, Block.EMPTY_PORTFOLIO, "no facility passed validation")
    ok["stage"] = ok["ifrs_stage"].astype(int)
    ok["accrued_in_gca"] = ok["accrued_in_gca"].eq(True)
    ok["route"] = np.where(ok["stage"] == 3, ROUTE_S3_ORIGINAL, ROUTE_PERFORMING)
    ok["sicr_rank"] = ok["facility_id"].map(dict(zip(cand["facility_id"], cand["sicr_rank"])))
    ok.loc[ok["route"] == ROUTE_S3_ORIGINAL, "sicr_rank"] = default_rank
    ok["sicr_rank"] = ok["sicr_rank"].astype(int)
    ok["qualitative_trigger"] = qualitative_trigger(ok["dpd"], ok["watchlist"], ok["forborne"], ps["sicr_triggers"])
    ok["current_rank"] = ok["current_grade"].map(rank_d).astype(int)
    ok["origination_rank"] = ok["origination_grade"].map(rank).astype(int)
    good_com = com.loc[~com["_row"].isin(log.ids("commitment"))]
    cmap = good_com.set_index("facility_id")
    ok["undrawn"] = ok["facility_id"].map(cmap["nominal_undrawn"]).fillna(0.0).astype(float)
    ok["ccf"] = ok["facility_id"].map(cmap["accounting_ccf"]).astype(float)
    ok["commitment_id"] = ok["facility_id"].map(cmap["commitment_id"])
    good_prov = prov.loc[~prov["_row"].isin(log.ids("opening_provision"))].set_index("facility_id")
    ok["opening_allowance_on"] = ok["facility_id"].map(good_prov["allowance_on"]).astype(float)
    ok["opening_provision_off"] = ok["facility_id"].map(good_prov["provision_off"]).astype(float)
    ok["overlay_amount"] = ok["facility_id"].map(good_prov["overlay_amount"]).astype(float)
    portfolio = PORTFOLIO.check(ok, STEP).sort_values("facility_id", kind="mergesort").reset_index(drop=True)

    rejections = log.table()
    perf_count = int((portfolio["route"] == ROUTE_PERFORMING).sum())
    LOG.info("TTC matrices valid for %d segments on a %d-grade master scale plus D",
             len(matrices), len(grades))
    LOG.info("accepted %s facilities (EUR %.1fm GCA): %s performing, %s original S3",
             f"{len(portfolio):,}", portfolio["gca"].sum() / 1_000_000, f"{perf_count:,}",
             f"{len(portfolio) - perf_count:,}")
    LOG.info("SICR line computed for %s performing facilities; every accepted grade explains its stage",
             f"{perf_count:,}")
    held = int(portfolio.loc[portfolio["route"] == ROUTE_PERFORMING, "qualitative_trigger"].sum())
    LOG.info("qualitative SICR triggers (%s; %s+ days past due): %s performing facilities flagged, "
             "held in S2 until default", ", ".join(ps["sicr_triggers"]["enabled"]),
             ps["sicr_triggers"]["dpd_days"], f"{held:,}")
    if rejections.empty:
        LOG.info("no record rejected")
    else:
        for (kind, code), n in rejections.groupby(["record_type", "reason_code"]).size().items():
            LOG.warning("rejected %s %s record(s): %s", f"{n:,}", kind, code)
    reconciliation = reconcile(fac, f.loc[f["_row"].isin(bad_rows)], portfolio, com, good_com, tol_agg)
    return RoutedPortfolio(portfolio=portfolio, rejections=rejections, grades=grades,
                           reconciliation=reconciliation)


def reconcile(loaded: pd.DataFrame, rejected: pd.DataFrame, accepted: pd.DataFrame,
              commitments: pd.DataFrame, accepted_commitments: pd.DataFrame, tol: dict) -> pd.DataFrame:
    """Starting point by portfolio and stage: loaded = accepted + rejected, counts exact and
    amounts within the aggregate tolerance. A rejected record never reaches a total."""
    def cells(df: pd.DataFrame, stage_col: str) -> pd.DataFrame:
        g = df.assign(_stage=pd.to_numeric(df[stage_col], errors="coerce").fillna(0).astype(int))
        return g.groupby(["portfolio", "_stage"]).agg(count=("facility_id", "size"), gca=("gca", "sum"))

    a = cells(loaded, "ifrs_stage").add_prefix("loaded_")
    b = cells(rejected, "ifrs_stage").add_prefix("rejected_")
    c = cells(accepted, "stage").add_prefix("accepted_")
    out = a.join(b, how="outer").join(c, how="outer").fillna(0.0)
    out.index.names = ["portfolio", "stage"]
    out = out.reset_index()
    for col in ("loaded_count", "rejected_count", "accepted_count"):
        out[col] = out[col].astype(int)
    count_gap = out["loaded_count"] - out["rejected_count"] - out["accepted_count"]
    gca_gap = out["loaded_gca"] - out["rejected_gca"] - out["accepted_gca"]
    limit = np.maximum(tol["abs"], tol["rel"] * out["loaded_gca"].abs())
    if (count_gap != 0).any() or (gca_gap.abs() > limit).any():
        raise BlockingError(STEP, Block.RECONCILIATION, "loaded facilities do not equal accepted plus rejected")
    linked = commitments.merge(loaded[["facility_id", "portfolio"]].drop_duplicates("facility_id"),
                               on="facility_id", how="left")
    und_loaded = linked.groupby(linked["portfolio"].fillna("unlinked"))["nominal_undrawn"].sum()
    und_accepted = accepted.groupby("portfolio")["undrawn"].sum()
    out["loaded_undrawn"] = out["portfolio"].map(und_loaded).fillna(0.0)
    out["accepted_undrawn"] = out["portfolio"].map(und_accepted).fillna(0.0)
    # Undrawn sits on the portfolio, not on a stage: show it once, on the S1 row.
    out.loc[out["stage"] != 1, ["loaded_undrawn", "accepted_undrawn"]] = 0.0
    return out.sort_values(["portfolio", "stage"]).reset_index(drop=True)


def raise_if_blocking(rejections: pd.DataFrame) -> None:
    """Block the run when a rejection is one the requirements treat as blocking the run
    (EAD-04, EAD-09). The caller has written rejections.parquet before this, so the log is kept."""
    hits = rejections[rejections["reason_code"].isin([str(r) for r in RUN_BLOCKING_REASONS])]
    if len(hits):
        counts = hits["reason_code"].value_counts().sort_index()
        summary = ", ".join(f"{code} x{n}" for code, n in counts.items())
        LOG.error("blocking defects (EAD-04, EAD-09): %s", summary)
        raise BlockingError(STEP, str(counts.index[0]),
                            f"blocking defects in the input set ({summary}); see rejections.parquet")
