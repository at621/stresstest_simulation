"""Synthetic preparation reporting with explicit, versioned export mappings."""

import numpy as np
import pandas as pd

from stress.contracts.checks import number, required
from stress.contracts.errors import BlockingError
from stress.contracts.inputs import SCENARIO_UNITS
from stress.contracts.preparation import COLLATERAL_INDEX, price_growth, require_ltv
from stress.contracts.run import ADVERSE


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
    in_book = facilities[facilities["facility_id"].isin(portfolio["facility_id"])]
    require_ltv(in_book)
    secured = in_book.loc[in_book["ltv"].notna(), ["facility_id", "ltv", "collateral_type"]].copy()
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


def _stage_share(by_stage: pd.DataFrame, scope: str, stage: int, year: int) -> float:
    book = by_stage[by_stage["year"] == year]
    book = book if scope == "Total" else book[book["portfolio"] == scope]
    return float(book.loc[book["stage"] == stage, "gca"].sum() / book["gca"].sum())


def plausibility_sheet(spec: dict, impairment: pd.DataFrame, by_stage: pd.DataFrame, loaded, indices: pd.DataFrame,
                       years: list[int]) -> pd.DataFrame:
    """The adverse result beside published figures (Basel principle 8, GL paragraph 62). The sheet
    shows the difference and judges nothing; ratios come from sums, never from averaged ratios."""
    required(spec, ("version", "source", "sources", "rows"), "plausibility")
    first, last = min(years), max(years)
    charges = impairment[impairment["scenario"] == ADVERSE]
    stages = by_stage[by_stage["scenario"] == ADVERSE]
    paths = loaded.scenario_values[loaded.scenario_values["scenario"] == ADVERSE]
    growth = price_growth(indices[indices["scenario"] == ADVERSE])

    def book(scope: str) -> pd.DataFrame:
        return charges[charges["portfolio"] == scope].set_index("year")

    def path(variable: str) -> pd.Series:
        values = paths[paths["variable"] == variable].groupby("year")["value"].mean()
        if values.empty:
            raise BlockingError("report", "MISSING_INPUT", f"no adverse path for {variable}")
        return values

    def price_fall(variable: str) -> float:
        return float(growth.loc[(growth["variable"] == variable) & (growth["year"] == last), "growth"].mean()) - 1.0

    def unemployment_start() -> float:
        rows = [s for s in loaded.scenario_meta["starting_values"] if s["variable"] == "unemployment"]
        return float(np.mean([s["value"] * SCENARIO_UNITS[s["unit"]] for s in rows]))

    def loss_rate(scope: str) -> float:
        gca = stages[stages["year"] == first - 1]
        gca = gca if scope == "Total" else gca[gca["portfolio"] == scope]
        return float(book(scope).loc[last, "cumulative_charge"] / gca["gca"].sum())

    measures = {
        "credit_loss_rate": loss_rate,
        "first_year_loss_share": lambda s: float(book(s).loc[first, "charge_total"] / book(s).loc[last, "cumulative_charge"]),
        "s2_share_start": lambda s: _stage_share(stages, s, 2, first - 1),
        "s2_share_end": lambda s: _stage_share(stages, s, 2, last),
        "s3_share_start": lambda s: _stage_share(stages, s, 3, first - 1),
        "s3_share_end": lambda s: _stage_share(stages, s, 3, last),
        "gdp_cumulative": lambda s: float((1.0 + path("gdp_growth")).prod() - 1.0),
        "unemployment_rise": lambda s: float(path("unemployment").loc[last] - unemployment_start()),
        "residential_price_cumulative": lambda s: price_fall("residential_price_index"),
        "cre_price_cumulative": lambda s: price_fall("cre_price_index"),
    }
    out = []
    for row in spec["rows"]:
        required(row, ("measure", "scope", "published", "source"), "plausibility row")
        if row["measure"] not in measures:
            raise BlockingError("report", "INVALID_INPUT", f"unknown plausibility measure {row['measure']}")
        if row["source"] not in spec["sources"]:
            raise BlockingError("report", "MISSING_INPUT", f"no source named {row['source']}")
        value = measures[row["measure"]](row["scope"])
        published = number(row["published"], "published")
        out.append({"measure": row["measure"], "scope": row["scope"], "engine": value, "published": published,
                    "multiple": value / published if published else np.nan, "source": spec["sources"][row["source"]],
                    "benchmark_version": spec["version"], "basis": "NOT_LIKE_FOR_LIKE"})
    return pd.DataFrame(out)


def readiness(loaded, config) -> pd.DataFrame:
    rows = [
        ("input_approval", loaded.approval.get("status", "MISSING"), "Owner attestation recorded, not inferred"),
        ("methodology", "DRAFT", "June 2026 draft; final package reconciliation required"),
        ("scenario", "SYNTHETIC", "Official scenario required for production"),
        ("parameters", str(loaded.parameter_set.get("status", "MISSING")), "Bank model validation required"),
        ("terminal_treatment", config.terminal_treatment, "Z default or parameter-linear sensitivity"),
        ("s2_treatment", config.s2_treatment, "Repriced default or held reading of paragraph 125 (C14)"),
        ("horizon_runoff", config.horizon_runoff, "Contractual default or replaced inside the horizon (C15)"),
        ("lgd_path", config.lgd_path, "Annual default or worst-Z reading for property-secured books (C16)"),
        ("numerical_oracles", "OPEN", "Owner AT-48, AT-51 and AT-52 sign-off remains open"),
        ("submission", "BLOCKED", "Synthetic analyses do not enable regulatory mode"),
    ]
    for name in ("benchmarks", "recoveries", "capital", "climate", "template_mapping", "challenge",
                 "npe_backstop", "plausibility"):
        rows.append((name, "SYNTHETIC_PROVIDED" if name in loaded.analysis else "NOT_PROVIDED",
                     "Independent validation and approved source package required"))
    return pd.DataFrame(rows, columns=["gate", "state", "evidence"])
