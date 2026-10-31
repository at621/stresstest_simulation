"""NPE backstop (CAP-09): the insufficient coverage of paragraphs 562-564, calculated from the run.

The capital bridge takes npl_deduction_change as a supplied input and stays as it is. This
report calculates what that input should be, so the two can be compared. The calendar is a
supplied input: nothing here holds a factor of Article 47c.

Per S3 slice: minimum coverage = unsecured part x its factor + secured part x its factor, the
provision is capped at that minimum (footnote 77), and the shortfall is the difference, so one
exposure's excess never offsets another's gap. S3 is projected as default-weighted slices, so a
slice stands for the exposure (A33). On-balance only.
"""

import numpy as np
import pandas as pd

from stress.contracts.checks import number, required
from stress.contracts.errors import BlockingError
from stress.contracts.preparation import COLLATERAL_INDEX, price_growth, usable_ltv
from stress.contracts.tables import SLICE_S3_ORIGINAL

STEP = "capital"
FACTORS = ("unsecured", "secured")
MEASURES = ["gca_in_scope", "unsecured_part", "secured_part", "minimum_coverage", "provisions", "capped_provisions",
            "insufficient_coverage"]


def _calendar(spec: dict) -> pd.DataFrame:
    rows = []
    for row in spec["calendar"]:
        required(row, ("from_year", *FACTORS), "NPE calendar row")
        if not isinstance(row["from_year"], int) or row["from_year"] < 1:
            raise BlockingError(STEP, "INVALID_INPUT", "from_year must be a positive whole year")
        rows.append({"from_year": row["from_year"], **{f: number(row[f], f, 0, 1) for f in FACTORS}})
    table = pd.DataFrame(rows, columns=["from_year", *FACTORS]).sort_values("from_year")
    if table.empty or table["from_year"].duplicated().any() or table["from_year"].iloc[0] != 1:
        raise BlockingError(STEP, "INVALID_INPUT", "the calendar needs one row per period, starting at year 1")
    if (table[list(FACTORS)].diff().fillna(0.0) < 0).any().any():
        raise BlockingError(STEP, "INVALID_INPUT", "a calendar factor cannot fall with time as NPE")
    return table


def _exposures(spec: dict, slices: pd.DataFrame, portfolio: pd.DataFrame, facilities: pd.DataFrame) -> pd.DataFrame:
    """S3 slices in the scope of paragraph 563, with their years as NPE at each year-end."""
    wanted = ["facility_id", "origination_date", "default_date", "ltv", "collateral_type"]
    in_book = facilities[facilities["facility_id"].isin(portfolio["facility_id"])]
    usable_ltv(in_book)
    facts = portfolio[["facility_id", "portfolio", "country"]].merge(in_book[wanted], on="facility_id",
                                                                     validate="one_to_one")
    book = slices.loc[slices["stage"].eq(3), ["scenario", "year", "facility_id", "slice", "entry_year", "gca",
                                              "allowance_on", "generation"]].merge(
        facts, on="facility_id", validate="many_to_one")
    original = book["slice"].eq(SLICE_S3_ORIGINAL)
    entered = pd.to_datetime(book["default_date"].where(original), errors="coerce").dt.year
    if entered[original].isna().any():
        raise BlockingError(STEP, "MISSING_INPUT", "an original S3 exposure has no default date")
    book["npe_entry_year"] = entered.where(original, book["entry_year"])
    book["years_as_npe"] = (book["year"] - book["npe_entry_year"] + 1).astype(int)  # footnote 75: 2027-2029 is three
    if (book["years_as_npe"] < 1).any():
        raise BlockingError(STEP, "RECONCILIATION", "an exposure is NPE before its entry year")
    dates = pd.to_datetime(book["origination_date"], errors="coerce")
    if dates.isna().any():
        raise BlockingError(STEP, "MISSING_INPUT", "an S3 exposure has no origination date")
    in_window = dates.between(pd.Timestamp(spec["scope_from"]), pd.Timestamp(spec["scope_to"]))
    # Replaced first, then S3: a replacement counts only if it had happened when the slice defaulted.
    at_entry = book.sort_values("year", kind="mergesort").groupby(["scenario", "facility_id", "slice"])[
        "generation"].transform("first").reindex(book.index)
    return book[in_window | at_entry.gt(0)].copy()


def _split_by_collateral(book: pd.DataFrame, indices: pd.DataFrame) -> pd.DataFrame:
    """Secured part: the collateral value at the year-end, following the scenario's prices (A31, A33)."""
    secured = book["ltv"].notna()
    variable = book["collateral_type"].where(secured).map(COLLATERAL_INDEX)
    if variable[secured].isna().any():
        raise BlockingError(STEP, "MISSING_INPUT", "no price index for a collateral type")
    growth = price_growth(indices)[["scenario", "country", "variable", "year", "growth"]]
    out = book.assign(variable=variable).merge(growth, on=["scenario", "country", "variable", "year"], how="left",
                                               validate="many_to_one")
    secured = out["ltv"].notna()
    out["growth"] = out["growth"].where(out["year"] >= indices["year"].min(), 1.0)  # the snapshot
    if out.loc[secured, "growth"].isna().any():
        raise BlockingError(STEP, "MISSING_INPUT", "no price index for a projected year")
    collateral = (out["gca"] / out["ltv"] * out["growth"]).where(secured, 0.0)
    out["secured_part"] = np.minimum(out["gca"], collateral)
    out["unsecured_part"] = out["gca"] - out["secured_part"]
    return out


def npe_backstop(spec: dict, slices: pd.DataFrame, portfolio: pd.DataFrame, facilities: pd.DataFrame,
                 indices: pd.DataFrame) -> pd.DataFrame:
    """Insufficient coverage per scenario, year and book, with the change on the previous year."""
    required(spec, ("version", "source", "scope_from", "scope_to", "calendar"), "NPE backstop")
    calendar = _calendar(spec)
    book = _split_by_collateral(_exposures(spec, slices, portfolio, facilities), indices)
    factors = pd.merge_asof(book[["years_as_npe"]].reset_index().sort_values("years_as_npe"), calendar,
                            left_on="years_as_npe", right_on="from_year").set_index("index").reindex(book.index)
    book["minimum_coverage"] = (book["unsecured_part"] * factors["unsecured"]
                                + book["secured_part"] * factors["secured"])
    book = book.rename(columns={"gca": "gca_in_scope", "allowance_on": "provisions"})
    book["capped_provisions"] = np.minimum(book["provisions"], book["minimum_coverage"])
    book["insufficient_coverage"] = book["minimum_coverage"] - book["capped_provisions"]
    books = book.groupby(["scenario", "year", "portfolio"])[MEASURES].sum().reset_index()
    total = book.groupby(["scenario", "year"])[MEASURES].sum().reset_index().assign(portfolio="Total")
    out = pd.concat([books, total], ignore_index=True).sort_values(["scenario", "portfolio", "year"], kind="mergesort")
    out["insufficient_coverage_change"] = out.groupby(["scenario", "portfolio"])["insufficient_coverage"].diff()
    out["calendar_version"] = spec["version"]
    out["basis"] = "SUPPLIED_CALENDAR_NOT_APPROVED"
    return out.reset_index(drop=True)
