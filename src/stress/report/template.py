"""Replica of the draft's CSV_CR_SCEN provisions from reported parameters (paragraphs 64, 133).

The template does not take provisions from a bank: it calculates them from the PD, TR, LGD and
LRLT the bank reports, through Boxes 3-9. This report derives those parameters from the run,
puts them through the same boxes per segment and sets the result beside the engine's own
on-balance stock, so a gap is visible before a submission rather than after one.

Not an official template. LRLT S2 is the engine's own S2 coverage, so S2 ties by construction,
and the draft's flow lines (Prov S1-S1, S2-S1, S1-S2, S2-S2, S1-S3, S2-S3) are the template's
arithmetic, because the engine does not track provisions by flow.
"""

import numpy as np
import pandas as pd

from stress.contracts.errors import BlockingError
from stress.contracts.run import BASELINE
from stress.contracts.tables import SLICE_S3_ORIGINAL

STEP = "report"
# Table 4 of the draft. P04 holds SME and other corporates together: R7's stage flows are per segment.
TEMPLATE_CLASS = {
    "P01": "Loans and advances - Households - Lending for house purchase",
    "P02": "Loans and advances - Households - Credit for consumption",
    "P03": "Loans and advances - NFC - SME - Other loans",
    "P04": "Loans and advances - NFC - Commercial real estate loans (SME and other)",
    "P05": "Loans and advances - NFC - Other than SME - Other loans",
    "P06_CI": "Debt securities - Credit institutions",
    "P06_GG": "Debt securities - General governments",
}


def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator).where(denominator > 0)


def _flow_amount(flow: pd.Series, rate: pd.Series) -> pd.Series:
    """A flow times its rate. No flow gives no provision, even where the rate does not exist."""
    return (flow * rate).where(flow != 0, 0.0)


def _weighted_lgd(book: pd.DataFrame, lgd: pd.DataFrame) -> pd.DataFrame:
    """GCA-weighted LGD of year y over each stage's stock at the end of y - 1 (paragraph 67)."""
    rows = book[book["stage"].isin([1, 2])].assign(year=lambda d: d["year"] + 1).merge(
        lgd[["scenario", "year", "facility_id", "lgd"]], on=["scenario", "year", "facility_id"], how="inner")
    rows["weighted"] = rows["gca"] * rows["lgd"]
    sums = rows.groupby(["scenario", "segment", "year", "stage"])[["weighted", "gca"]].sum()
    return _ratio(sums["weighted"], sums["gca"]).unstack("stage").reindex(columns=[1, 2]).rename(
        columns={1: "lgd_s1", 2: "lgd_s2"})


def _parameters(book: pd.DataFrame, flows: pd.DataFrame, lgd: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    stock = book.groupby(["scenario", "segment", "year", "stage"])["gca"].sum().unstack("stage", fill_value=0.0)
    stock = stock.reindex(columns=[1, 2, 3], fill_value=0.0)
    moved = flows.groupby(["scenario", "segment", "year", "from_stage", "to_stage"])["gca"].sum().unstack(
        ["from_stage", "to_stage"], fill_value=0.0)
    out = pd.DataFrame({
        "exp_s1_opening": stock[1].groupby(level=[0, 1]).shift(1),
        "exp_s2_opening": stock[2].groupby(level=[0, 1]).shift(1),
        "exp_s1": stock[1], "exp_s2": stock[2], "exp_s3": stock[3],
    })
    out = out[out.index.get_level_values("year").isin(years)]
    for (origin, target), name in (((1, 2), "flow_s1_s2"), ((2, 1), "flow_s2_s1"), ((1, 3), "flow_s1_s3"),
                                   ((2, 3), "flow_s2_s3")):
        out[name] = moved.get((origin, target), 0.0)
    out["tr12"] = _ratio(out["flow_s1_s2"], out["exp_s1_opening"])
    out["tr21"] = _ratio(out["flow_s2_s1"], out["exp_s2_opening"])
    out["pd12m_s1"] = _ratio(out["flow_s1_s3"], out["exp_s1_opening"])
    out["pd12m_s2"] = _ratio(out["flow_s2_s3"], out["exp_s2_opening"])
    out = out.join(_weighted_lgd(book, lgd))
    return out


def _next_loss_rate(p: pd.DataFrame, weight: pd.Series, last: int) -> pd.Series:
    """PD-12M S1(t+2) x LGD S1(t+2). After 2029 the baseline stays flat and the adverse blends the
    two 2029 products, a x adverse + (1 - a) x baseline, as Boxes 4 and 5 write it."""
    rate = p["pd12m_s1"] * p["lgd_s1"]
    out = {}
    for (scenario, segment, year) in p.index:
        if year < last:
            out[scenario, segment, year] = rate.get((scenario, segment, year + 1), np.nan)
        elif scenario == BASELINE:
            out[scenario, segment, year] = rate[scenario, segment, year]
        else:
            a = weight.loc[(scenario, segment)]
            out[scenario, segment, year] = a * rate[scenario, segment, year] + (1 - a) * rate[BASELINE, segment, year]
    return pd.Series(out).rename_axis(p.index.names)


def template_replica(slices: pd.DataFrame, flows: pd.DataFrame, lgd: pd.DataFrame, z: pd.DataFrame,
                     portfolio: pd.DataFrame, years: list[int], tol: dict,
                     template_classes: dict | None = None) -> pd.DataFrame:
    """Reported parameters, template provisions and the engine's on-balance stock per segment."""
    segment = portfolio.set_index("facility_id")["segment"]
    book = slices.assign(segment=slices["facility_id"].map(segment))
    last = max(years)
    p = _parameters(book, flows, lgd, years)
    terminal = z[(z["year"] == last + 1) & (z["scenario"] != BASELINE)].groupby(
        ["scenario", "segment"])["adverse_weight"].first()
    stressed = p[p.index.get_level_values("scenario") != BASELINE]
    missing = set(stressed.index.droplevel("year")) - set(terminal.index)
    if missing:
        raise BlockingError(STEP, "MISSING_INPUT", f"no terminal weight for {sorted(missing)}")
    p["loss_rate_s1_next"] = _next_loss_rate(p, terminal, last)
    engine = book.groupby(["scenario", "segment", "year", "stage"])["allowance_on"].sum().unstack(
        "stage", fill_value=0.0).reindex(columns=[1, 2, 3], fill_value=0.0)
    p["lrlt_s2"] = _ratio(engine[2].reindex(p.index), p["exp_s2"])

    stay_s1 = p["exp_s1_opening"] - p["flow_s1_s2"] - p["flow_s1_s3"]
    stay_s2 = p["exp_s2_opening"] - p["flow_s2_s1"] - p["flow_s2_s3"]
    p["prov_s1_s1"] = _flow_amount(stay_s1, p["loss_rate_s1_next"])  # Box 5
    p["prov_s2_s1"] = _flow_amount(p["flow_s2_s1"], p["loss_rate_s1_next"])  # Box 4
    p["prov_s1_s2"] = _flow_amount(p["flow_s1_s2"], p["lrlt_s2"])  # Box 6
    p["prov_s2_s2"] = _flow_amount(stay_s2, p["lrlt_s2"])  # Box 7
    p["prov_s1_s3"] = _flow_amount(p["flow_s1_s3"], p["lgd_s1"])  # Box 8
    p["prov_s2_s3"] = _flow_amount(p["flow_s2_s3"], p["lgd_s2"])  # Box 8
    new = (p["prov_s1_s3"] + p["prov_s2_s3"]).groupby(level=[0, 1]).cumsum(skipna=False)
    p["template_s1"] = p["prov_s1_s1"] + p["prov_s2_s1"]
    p["template_s2"] = p["prov_s1_s2"] + p["prov_s2_s2"]
    p["template_s3_new"] = new

    original = book["slice"] == SLICE_S3_ORIGINAL
    s3 = book[book["stage"] == 3]
    p["engine_s1"] = engine[1].reindex(p.index)
    p["engine_s2"] = engine[2].reindex(p.index)
    p["engine_s3_new"] = s3[~original.loc[s3.index]].groupby(["scenario", "segment", "year"])[
        "allowance_on"].sum().reindex(p.index, fill_value=0.0)
    if not np.all(np.abs(p["exp_s2"] - p["flow_s1_s2"] - stay_s2) <= np.maximum(tol["abs"], tol["rel"] * p["exp_s2"])):
        raise BlockingError(STEP, "RECONCILIATION", "template S2 flows do not rebuild the S2 stock")
    p["old_s3_box_9"] = _old_s3(book, lgd, years).reindex(p.index, fill_value=0.0)
    p["engine_s3_old"] = s3[original.loc[s3.index]].groupby(["scenario", "segment", "year"])[
        "allowance_on"].sum().reindex(p.index, fill_value=0.0)
    for name in ("s1", "s2", "s3_new"):
        p[f"gap_{name}"] = _ratio(p[f"template_{name}"], p[f"engine_{name}"]) - 1.0
    p["gap_s3_old"] = _ratio(p["old_s3_box_9"], p["engine_s3_old"]) - 1.0
    out = p.reset_index()
    out["template_class"] = out["segment"].map({**TEMPLATE_CLASS, **(template_classes or {})})
    if out["template_class"].isna().any():
        raise BlockingError(STEP, "MISSING_INPUT", "a segment has no Table 4 class")
    return out


def _old_s3(book: pd.DataFrame, lgd: pd.DataFrame, years: list[int]) -> pd.Series:
    """Box 9: MAX{Exp S3(t=0) x LGD S3(t=1); Prov S3(t=0)}, per segment as the template holds it."""
    first = min(years)
    opening = book[(book["slice"] == SLICE_S3_ORIGINAL) & (book["year"] == first - 1)]
    rows = opening.merge(lgd.loc[lgd["year"] == first, ["scenario", "facility_id", "lgd"]],
                         on=["scenario", "facility_id"], how="inner")
    rows["raw"] = rows["gca"] * rows["lgd"]
    sums = rows.groupby(["scenario", "segment"])[["raw", "allowance_on"]].sum()
    value = sums.max(axis=1)
    return pd.concat({year: value for year in years}, names=["year"]).reorder_levels(
        ["scenario", "segment", "year"]).sort_index()
