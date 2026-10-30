"""Synthetic preparation reporting with explicit, versioned export mappings."""

import numpy as np
import pandas as pd

from stress.contracts.checks import number, required
from stress.contracts.errors import BlockingError
from stress.contracts.preparation import COLLATERAL_INDEX, price_growth


def mapped_cells(spec: dict, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    required(spec, ("version", "cells"), "template mapping")
    if not spec["version"] or not spec["cells"]:
        raise BlockingError("report", "MISSING_INPUT", "mapping requires version and cells")
    seen, out = set(), []
    for cell in spec["cells"]:
        required(cell, ("sheet", "row", "column", "table", "measure", "filters"), "mapped cell")
        key = (cell["sheet"], cell["row"], cell["column"])
        if key in seen:
            raise BlockingError("report", "DUPLICATE_KEY", "duplicate template destination")
        seen.add(key)
        if cell["table"] not in tables or not isinstance(cell["filters"], dict):
            raise BlockingError("report", "MISSING_INPUT", "unknown source table or invalid filters")
        rows = tables[cell["table"]]
        if cell["measure"] not in rows or set(cell["filters"]) - set(rows):
            raise BlockingError("report", "MISSING_INPUT", "unknown source measure or dimension")
        for column, value in cell["filters"].items():
            rows = rows.loc[rows[column].eq(value)]
        if rows.empty or rows[cell["measure"]].isna().any():
            raise BlockingError("report", "MISSING_INPUT", "empty selection or missing mapped values")
        if not pd.api.types.is_numeric_dtype(rows[cell["measure"]]):
            raise BlockingError("report", "INVALID_INPUT", "mapped measure must be numeric")
        value = number(float(rows[cell["measure"]].sum()), "mapped value")
        out.append(dict(zip(("sheet", "row", "column"), key)) | {
            "mapping_version": spec["version"], "source_table": cell["table"], "source_measure": cell["measure"],
            "matched_rows": len(rows), "value": value, "basis": "SYNTHETIC_MAPPING_NOT_OFFICIAL_TEMPLATE"})
    return pd.DataFrame(out)


def portfolio_diagnostics(portfolio: pd.DataFrame, obligors: pd.DataFrame,
                          facilities: pd.DataFrame, slices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    dims = ["country", "nace_code", "nace_version", "group_id"]
    obligors = obligors.loc[obligors.obligor_id.isin(portfolio.obligor_id)]
    facilities = facilities.loc[facilities.facility_id.isin(portfolio.facility_id)]
    info = portfolio[["facility_id", "obligor_id", "portfolio"]].merge(
        obligors[["obligor_id", *dims]], on="obligor_id", validate="many_to_one")
    # Missing classification is visible as a separate bucket; never silently dropped by groupby.
    info[dims] = info[dims].fillna("MISSING")
    joined = slices.merge(info, on="facility_id", validate="many_to_one")
    measures = ["gca", "undrawn", "allowance_on", "provision_off"]
    dimensions = joined.groupby(["scenario", "year", "portfolio", "country", "nace_code",
                                 "nace_version", "stage"], dropna=False)[measures].sum().reset_index()
    if not np.allclose(dimensions[measures].sum(), slices[measures].sum(), rtol=1e-10, atol=.01):
        raise BlockingError("report", "RECONCILIATION", "dimensional aggregation lost exposure")
    concentration = joined.groupby(["scenario", "year", "group_id"])[measures].sum().reset_index()
    total = concentration.groupby(["scenario", "year"])["gca"].transform("sum")
    concentration["gca_share"] = concentration.gca / total
    concentration["hhi_contribution"] = concentration.gca_share**2
    concentration["rank"] = concentration.groupby(["scenario", "year"])["gca"].rank(method="first", ascending=False)
    flags = portfolio[["facility_id", "qualitative_trigger", "sicr_rank"]].merge(
        facilities[["facility_id", "dpd", "watchlist", "forborne"]], on="facility_id", validate="one_to_one")
    attributed = slices.merge(flags, on="facility_id", validate="many_to_one")
    attributed = attributed.loc[attributed.stage.eq(2)].copy()
    attributed["trigger"] = np.where(attributed.qualitative_trigger, "qualitative_present", "grade_only")
    # Flag combinations remain visible without counting the same exposure several times.
    attributed["flags"] = ("dpd=" + attributed.dpd.astype(str) + ";watchlist="
                            + attributed.watchlist.astype(str) + ";forborne=" + attributed.forborne.astype(str))
    attribution = attributed.groupby(["scenario", "year", "trigger", "flags"])[measures].sum().reset_index()
    return {"dimensions": dimensions, "concentration": concentration, "sicr_attribution": attribution}


def _with_total(frame: pd.DataFrame, keys: list[str], measures: list[str]) -> pd.DataFrame:
    """Sums per stage plus one row per key labelled stage "all"; ratios come from these sums."""
    stages = frame.groupby([*keys, "stage"], dropna=False)[measures].sum().reset_index()
    total = frame.groupby(keys, dropna=False)[measures].sum().reset_index().assign(stage="all")
    out = pd.concat([stages.astype({"stage": object}), total], ignore_index=True)
    return out.sort_values(keys, kind="mergesort").reset_index(drop=True)


def stressed_ltv(portfolio: pd.DataFrame, facilities: pd.DataFrame, slices: pd.DataFrame,
                 indices: pd.DataFrame) -> pd.DataFrame:
    """Paragraph 69 and A31: GCA over collateral value, the value following the scenario's price
    index from the snapshot. GCA is static, so a loan's LTV is its opening LTV over that index."""
    secured = facilities.loc[facilities["ltv"].notna() & facilities["facility_id"].isin(portfolio["facility_id"]),
                             ["facility_id", "ltv", "collateral_type"]].copy()
    secured["variable"] = secured["collateral_type"].map(COLLATERAL_INDEX)
    if secured["variable"].isna().any():
        raise BlockingError("report", "MISSING_INPUT", "no price index for a collateral type")
    growth = price_growth(indices)
    book = slices[["scenario", "year", "facility_id", "stage", "gca"]].merge(
        secured, on="facility_id", validate="many_to_one").merge(
        portfolio[["facility_id", "portfolio", "country"]], on="facility_id", validate="many_to_one").merge(
        growth[["scenario", "country", "variable", "year", "growth"]],
        on=["scenario", "country", "variable", "year"], how="left", validate="many_to_one")
    book["growth"] = book["growth"].where(book["year"] >= indices["year"].min(), 1.0)  # the snapshot
    if book["growth"].isna().any():
        raise BlockingError("report", "MISSING_INPUT", "no price index for a projected year")
    level = book["ltv"] / book["growth"]
    book["ltv_numerator"] = book["gca"] * level
    book["gca_above_100"] = book["gca"].where(level > 1.0, 0.0)
    out = _with_total(book, ["scenario", "year", "portfolio"], ["gca", "ltv_numerator", "gca_above_100"])
    out["average_ltv"] = (out["ltv_numerator"] / out["gca"]).where(out["gca"] > 0)
    out["share_above_100"] = (out["gca_above_100"] / out["gca"]).where(out["gca"] > 0)
    return out


def average_maturity(portfolio: pd.DataFrame, slices: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    """Paragraph 70: performing exposure-weighted residual maturity, the maturity R5 gave R8."""
    rest = schedule.drop_duplicates(["facility_id", "valuation_year"])[
        ["facility_id", "valuation_year", "remaining_maturity"]]
    book = slices.loc[slices["stage"].lt(3), ["scenario", "year", "facility_id", "stage", "gca"]].merge(
        rest, left_on=["facility_id", "year"], right_on=["facility_id", "valuation_year"], how="left",
        validate="many_to_one").merge(portfolio[["facility_id", "portfolio"]], on="facility_id")
    if book["remaining_maturity"].isna().any():
        raise BlockingError("report", "MISSING_INPUT", "no residual maturity for a performing slice")
    book["maturity_numerator"] = book["gca"] * book["remaining_maturity"]
    out = _with_total(book, ["scenario", "year", "portfolio"], ["gca", "maturity_numerator"])
    out["average_maturity"] = (out["maturity_numerator"] / out["gca"]).where(out["gca"] > 0)
    return out


def readiness(loaded, terminal_treatment: str) -> pd.DataFrame:
    rows = [
        ("input_approval", loaded.approval.get("status", "MISSING"), "Owner attestation recorded, not inferred"),
        ("methodology", "DRAFT", "June 2026 draft; final package reconciliation required"),
        ("scenario", "SYNTHETIC", "Official scenario required for production"),
        ("parameters", str(loaded.parameter_set.get("status", "MISSING")), "Bank model validation required"),
        ("terminal_treatment", terminal_treatment, "Z default or parameter-linear sensitivity"),
        ("numerical_oracles", "OPEN", "Owner AT-48, AT-51 and AT-52 sign-off remains open"),
        ("submission", "BLOCKED", "Synthetic analyses do not enable regulatory mode"),
    ]
    for name in ("benchmarks", "recoveries", "capital", "climate", "template_mapping", "challenge",
                 "npe_backstop"):
        rows.append((name, "SYNTHETIC_PROVIDED" if name in loaded.analysis else "NOT_PROVIDED",
                     "Independent validation and approved source package required"))
    return pd.DataFrame(rows, columns=["gate", "state", "evidence"])
