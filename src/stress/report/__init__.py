"""R10 aggregate and report: money summed from facility and bucket results, ratios with
numerator and denominator, the four v1 reports. The only place that rounds.

RPT-01, RPT-05, RPT-06, section 11.3.

Reports (results/reports/): starting-point reconciliation, stage migration (with S3 cohorts
and the grade-level detail), parameters (Z, PiT matrices, PD curves, LGD by Z, EAD profile,
ECL by bucket) and impairment, plus summary.md. Every report carries the run's status label.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import CURRENCY, ON_BALANCE_CATEGORY, LoadedInputs
from stress.contracts.preparation import ANALYSIS_RATES
from stress.contracts.run import (
    ADVERSE,
    LGD_TROUGH,
    RUNOFF_REPLACED,
    S2_HELD,
    TERMINAL_Z,
    RunContext,
)
from stress.contracts.tables import METHOD_S2_HELD, Drivers, Parameters, RoutedPortfolio
from stress.report import comparison
from stress.report.assessment import (
    average_maturity,
    mapped_cells,
    plausibility_sheet,
    portfolio_diagnostics,
    readiness,
    stressed_ltv,
)
from stress.report.excel import write_workbook
from stress.report.template import template_replica

STEP = "R10"
LOG = logging.getLogger("stress.R10")
SUMMARY_FILE = "summary.md"
WORKBOOK_FILE = "stress_report.xlsx"
AMOUNT_DP = 2  # EUR cents, the output boundary (section 12.3)
RATE_DP = 10
MILLION = 1_000_000.0


# --- rounding at the output boundary ------------------------------------------------------------

def _round(df: pd.DataFrame, rates: tuple[str, ...] = ()) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(RATE_DP if col in rates or col.endswith(("_rate", "_pd", "_lgd"))
                                      else AMOUNT_DP)
    return out


def _write(ctx: RunContext, name: str, df: pd.DataFrame, rates: tuple[str, ...] = ()) -> None:
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    table = _round(df, rates)
    table.insert(0, "status", ctx.status_label)
    table.to_csv(ctx.reports_dir / name, index=False, lineterminator="\n")


def _close(a, b, tol: dict) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return np.abs(a - b) <= np.maximum(tol["abs"], tol["rel"] * np.abs(b))


def _require(ok, what: str) -> None:
    if not np.all(ok):
        raise BlockingError(STEP, Block.RECONCILIATION, f"{what} is outside the section 12.3 tolerance")


def _json_values(value):
    """Retain missing data as null; never emit the non-standard JSON NaN token."""
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_values(item) for item in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value


# --- the four reports ---------------------------------------------------------------------------

def starting_point(loaded: LoadedInputs, routed: RoutedPortfolio, results: dict,
                   tol: dict) -> pd.DataFrame:
    """Accounting exposure, provisions, stage and scope bridges with EUR-only and AC-only
    checks, and the frozen opening allowance next to the engine's own end-2026 view."""
    port = routed.portfolio
    rec = routed.reconciliation.copy()
    conv = port.assign(converted=port["undrawn"] * port["ccf"].fillna(0.0))
    by = conv.groupby(["portfolio", "stage"]).agg(
        undrawn=("undrawn", "sum"), converted_commitments=("converted", "sum"),
        opening_allowance_on=("opening_allowance_on", "sum"),
        opening_provision_off=("opening_provision_off", "sum")).reset_index()
    rec = rec.merge(by, on=["portfolio", "stage"], how="left").fillna(0.0)
    prov = results["provisions"]
    diag = prov[prov["year"] == int(loaded.parameter_set["horizon"]["snapshot_year"])]
    diag = diag.merge(port[["facility_id", "portfolio"]], on="facility_id")
    for scen, part in diag.groupby("scenario"):
        engine = part.groupby(["portfolio", "stage"])[["allowance_on", "provision_off"]].sum()
        engine.columns = [f"engine_2026_{scen}_on", f"engine_2026_{scen}_off"]
        rec = rec.merge(engine.reset_index(), on=["portfolio", "stage"], how="left")
    if not port["currency"].eq(CURRENCY).all():
        raise BlockingError(STEP, Block.RECONCILIATION, "a non-EUR facility reached the reports")
    rec["currency_check"] = "EUR only"
    rec["accounting_check"] = "AC only"
    rejected_scope = routed.rejections["reason_code"].isin(
        ["NON_EUR_CURRENCY", "MISSING_CURRENCY", "NON_AC_ON_BALANCE", "MISSING_ACCOUNTING_CATEGORY"]).sum()
    rec["scope_rejections"] = int(rejected_scope)
    totals = rec.drop(columns=["stage", "currency_check", "accounting_check", "scope_rejections"]) \
        .groupby("portfolio").sum(numeric_only=True).reset_index()
    totals["stage"] = "all"
    _require(_close(rec["loaded_gca"], rec["accepted_gca"] + rec["rejected_gca"], tol),
             "starting-point GCA bridge")
    return pd.concat([rec, totals], ignore_index=True)


def stage_migration(results: dict, portfolio: pd.DataFrame, tol: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    slices = results["slices"].merge(portfolio[["facility_id", "portfolio"]], on="facility_id")
    stock = slices.groupby(["scenario", "year", "portfolio", "stage"])["gca"].sum().unstack("stage", fill_value=0.0)
    stock.columns = [f"S{c}" for c in stock.columns]
    stock = stock.reset_index()
    flows = results["stage_flows"].groupby(["scenario", "year", "portfolio", "from_stage", "to_stage"])["gca"].sum()
    flows = flows.unstack(["from_stage", "to_stage"], fill_value=0.0)
    flows.columns = [f"flow_S{a}_S{b}" for a, b in flows.columns]
    flows = flows.reset_index()
    rows = []
    for (scen, year, port), f in flows.groupby(["scenario", "year", "portfolio"]):
        prev = stock[(stock["scenario"] == scen) & (stock["year"] == year - 1) & (stock["portfolio"] == port)]
        curr = stock[(stock["scenario"] == scen) & (stock["year"] == year) & (stock["portfolio"] == port)]
        rec = {"scenario": scen, "year": year, "portfolio": port}
        for s in ("S1", "S2", "S3"):
            rec[f"opening_{s}"] = float(prev[s].sum()) if s in prev else 0.0
        for col in f.columns[3:]:
            rec[col] = float(f[col].iloc[0])
        for s in ("S1", "S2", "S3"):
            rec[f"closing_{s}"] = float(curr[s].sum()) if s in curr else 0.0
            inflow = sum(v for k, v in rec.items() if k.startswith("flow_") and k.endswith(f"_{s}"))
            _require(_close(inflow, rec[f"closing_{s}"], tol), f"stage migration {scen} {year} {port} {s}")
        for s in ("S1", "S2"):
            out = sum(v for k, v in rec.items() if k.startswith(f"flow_{s}_"))
            movement = 0.0
            if "exposure_movements" in results:
                moves = results["exposure_movements"]
                movement = moves.loc[(moves.scenario == scen) & (moves.year == year)
                                     & (moves.portfolio == port) & (moves.stage == int(s[1])), "gca_change"].sum()
                rec[f"volume_change_{s}"] = movement
            _require(_close(out, rec[f"opening_{s}"] + movement, tol),
                     f"stage outflows {scen} {year} {port} {s}")
        rows.append(rec)
    migration = pd.DataFrame(rows)
    s3 = slices[slices["stage"] == 3].copy()
    s3["cohort"] = np.where(s3["slice"] == "S3_orig", "original_2026",
                            "new_" + s3["entry_year"].fillna(0).astype(int).astype(str)
                            + "_from_S" + s3["origin_stage"].fillna(0).astype(int).astype(str))
    cohorts = s3.groupby(["scenario", "year", "portfolio", "cohort"])[
        ["gca", "undrawn", "allowance_on", "provision_off"]].sum().reset_index()
    grades = results["grade_flows"].groupby(["scenario", "year", "segment", "from_grade", "to_grade"])["gca"].sum().reset_index()
    return migration, cohorts, grades


def parameter_reports(ctx: RunContext, drivers: Drivers, params: Parameters, results: dict,
                      portfolio: pd.DataFrame, loaded: LoadedInputs) -> dict[str, pd.DataFrame]:
    out = {}
    out["z_scores.csv"] = drivers.z
    out["driver_contributions.csv"] = drivers.contributions
    out["property_indices.csv"] = drivers.indices
    out["ttc_matrices.csv"] = loaded.ttc_pd_matrix[["segment", "from_grade", "to_grade", "probability"]]
    out["pit_matrices.csv"] = params.pit
    full = params.pd_curves  # whole years only (A7)
    out["pd_curves.csv"] = full[["segment", "country", "scenario", "valuation_year", "cohort",
                                 "default_bucket", "bucket_year", "q", "m", "s", "f"]].rename(
        columns={"cohort": "grade", "q": "conditional_pd", "m": "marginal_pd", "s": "survival",
                 "f": "cumulative_pd"})
    # RPT-06: one-year portfolio PD = sum(D q) / sum(D) over performing slices, with both parts.
    slices = results["slices"]
    perf = slices[slices["stage"] < 3].merge(portfolio[["facility_id", "portfolio", "segment", "country"]],
                                             on="facility_id")
    one = full[full["default_bucket"] == 1][["segment", "country", "scenario", "valuation_year", "cohort", "q"]]
    joined = perf.merge(one, left_on=["segment", "country", "scenario", "year", "grade"],
                        right_on=["segment", "country", "scenario", "valuation_year", "cohort"], how="left")
    joined["dq"] = joined["gca"] * joined["q"]
    pd_tab = joined.groupby(["scenario", "year", "portfolio", "stage"]).agg(
        numerator=("dq", "sum"), denominator=("gca", "sum")).reset_index()
    pd_tab["one_year_pd"] = pd_tab["numerator"] / pd_tab["denominator"]
    out["portfolio_pd.csv"] = pd_tab
    lgd = params.lgd_of_year.merge(portfolio[["facility_id", "segment", "gca"]], on="facility_id")
    lgd["num"] = lgd["gca"] * lgd["lgd"]
    lgd_tab = lgd.groupby(["scenario", "year", "segment"]).agg(
        z=("z", "mean"), numerator=("num", "sum"), denominator=("gca", "sum")).reset_index()
    lgd_tab["exposure_weighted_lgd"] = lgd_tab["numerator"] / lgd_tab["denominator"]
    out["lgd_by_z.csv"] = lgd_tab
    fp = params.facility.merge(portfolio[["facility_id", "portfolio"]], on="facility_id")
    if "exposure_movements" in results:
        actual = results["slices"].loc[results["slices"].stage.lt(3)].groupby(
            ["scenario", "year", "facility_id"])[["gca", "undrawn"]].sum().rename(
                columns={"gca": "actual_gca", "undrawn": "actual_undrawn"}).reset_index()
        fp = fp.merge(actual, left_on=["scenario", "valuation_year", "facility_id"],
                      right_on=["scenario", "year", "facility_id"], how="left", validate="many_to_one")
        facts = portfolio.set_index("facility_id")
        for actual_name, reference, columns in (("actual_gca", "gca", ("balance", "ead_drawn")),
                                                ("actual_undrawn", "undrawn", ("ead_undrawn",))):
            denominator = fp.facility_id.map(facts[reference]).to_numpy()
            factor = np.divide(fp[actual_name].fillna(0).to_numpy(), denominator,
                               out=np.zeros(len(fp)), where=denominator > 0)
            fp[list(columns)] = fp[list(columns)].mul(factor, axis=0)
        fp["ead_total"] = fp.ead_drawn + fp.ead_undrawn
    ead = fp.groupby(["scenario", "valuation_year", "portfolio", "default_bucket"]).agg(
        balance=("balance", "sum"), ead_drawn=("ead_drawn", "sum"), ead_undrawn=("ead_undrawn", "sum"),
        ead_total=("ead_total", "sum"), facilities=("facility_id", "size")).reset_index()
    out["ead_profile.csv"] = ead
    out["ecl_by_bucket.csv"] = results["ecl_buckets"]
    return out


def impairment(results: dict, portfolio: pd.DataFrame, tol: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    charges = results["charges"].merge(portfolio[["facility_id", "portfolio"]], on="facility_id")
    cols = ["opening_on", "closing_on", "charge_on", "opening_off", "closing_off", "charge_off",
            "fx_movement", "overlay_closing"]
    tab = charges.groupby(["scenario", "year", "portfolio"])[cols].sum().reset_index()
    total = charges.groupby(["scenario", "year"])[cols].sum().reset_index()
    total["portfolio"] = "Total"
    tab = pd.concat([tab, total], ignore_index=True)
    tab["charge_total"] = tab["charge_on"] + tab["charge_off"]
    tab = tab.sort_values(["scenario", "portfolio", "year"])
    tab["cumulative_charge"] = tab.groupby(["scenario", "portfolio"])["charge_total"].cumsum()
    _require(_close(tab["closing_on"] - tab["opening_on"], tab["charge_on"], tol), "on-balance charge bridge")
    _require(_close(tab["closing_off"] - tab["opening_off"], tab["charge_off"], tol), "off-balance charge bridge")
    slices = results["slices"]
    prov = slices.groupby(["scenario", "year"])[["allowance_on", "provision_off"]].sum()
    closing = charges.groupby(["scenario", "year"])[["closing_on", "closing_off"]].sum()
    joined = prov.reindex(closing.index, fill_value=0.0).join(closing)
    _require(_close(joined["allowance_on"], joined["closing_on"], tol), "allowance stock against charges")
    _require(_close(joined["provision_off"], joined["closing_off"], tol), "off-balance stock against charges")
    by_stage = slices.merge(portfolio[["facility_id", "portfolio"]], on="facility_id").groupby(
        ["scenario", "year", "portfolio", "stage"]).agg(
        gca=("gca", "sum"), undrawn=("undrawn", "sum"), allowance_on=("allowance_on", "sum"),
        provision_off=("provision_off", "sum")).reset_index()
    if "exposure_movements" in results:
        grid = _book_grid(results, portfolio, stages=True)
        by_stage = by_stage.set_index(list(grid.names)).reindex(grid, fill_value=0.0).reset_index()
    by_stage["coverage_numerator"] = by_stage["allowance_on"]
    by_stage["coverage_denominator"] = by_stage["gca"]
    by_stage["coverage_rate"] = by_stage["allowance_on"] / by_stage["gca"]
    return tab.reset_index(drop=True), by_stage


def ecl_bridge(results: dict, tol: dict, amount: dict) -> pd.DataFrame:
    """ECL-09: ECL by default bucket, plus what the held reading of S2 keeps (C14), equals the
    booked performing provisions in every scenario and year. Only a held slice may differ from
    its raw value, and that check is per slice, so it takes the amount tolerance."""
    perf = results["provisions"][results["provisions"]["stage"] < 3]
    held = perf["method"] == METHOD_S2_HELD
    gap = perf.loc[~held, ["allowance_on", "provision_off"]].to_numpy() - perf.loc[~held, ["raw_on", "raw_off"]].to_numpy()
    _require(np.abs(gap) <= amount["abs"], "performing provisions against their raw value")
    rows = perf.assign(held_on=(perf["allowance_on"] - perf["raw_on"]).where(held, 0.0),
                       held_off=(perf["provision_off"] - perf["raw_off"]).where(held, 0.0))
    keys = ["scenario", "year"]
    booked = rows.groupby(keys)[["held_on", "held_off", "allowance_on", "provision_off"]].sum()
    buckets = results["ecl_buckets"].rename(columns={"valuation_year": "year"}).groupby(keys)[
        ["ecl_on", "ecl_off"]].sum()
    if not buckets.index.sort_values().equals(booked.index.sort_values()):
        raise BlockingError(STEP, Block.RECONCILIATION, "ECL buckets do not cover every scenario and year of the provisions")
    out = buckets.join(booked).reset_index()
    _require(_close(out["ecl_on"] + out["held_on"], out["allowance_on"], tol), "ECL by bucket against provisions")
    _require(_close(out["ecl_off"] + out["held_off"], out["provision_off"], tol), "off-balance ECL by bucket")
    return out


def _book_grid(results, portfolio, stages=False):
    """The expected reporting population includes fully extinguished dynamic books."""
    dimensions = [sorted(results["charges"].scenario.unique()),
                  sorted(set(results["slices"].year) | set(results["charges"].year)),
                  sorted(portfolio.portfolio.unique())]
    names = ["scenario", "year", "portfolio"]
    if stages:
        dimensions.append([1, 2, 3])
        names.append("stage")
    return pd.MultiIndex.from_product(dimensions, names=names)


def check_static_books(results: dict, portfolio: pd.DataFrame, params: Parameters,
                       tol: dict) -> pd.DataFrame:
    """AT-44 per projected year: GCA, nominal undrawn and converted commitments per book, the
    commitments converted at the CCF the run applied (a variant's CCF included)."""
    ccf = params.lgd_of_year.drop_duplicates("facility_id").set_index("facility_id")["ccf"]
    slices = results["slices"].merge(portfolio[["facility_id", "portfolio"]], on="facility_id")
    slices["converted"] = slices["undrawn"] * slices["facility_id"].map(ccf).fillna(0.0)
    books = slices.groupby(["scenario", "year", "portfolio"])[["gca", "undrawn", "converted"]].sum().reset_index()
    if "exposure_movements" in results:
        grid = _book_grid(results, portfolio)
        books = books.set_index(list(grid.names)).reindex(grid, fill_value=0.0).reset_index()
    books["gca_plus_converted"] = books["gca"] + books["converted"]
    opening = portfolio.groupby("portfolio")[["gca", "undrawn"]].sum()
    for col in ("gca", "undrawn"):
        expected = books["portfolio"].map(opening[col]).to_numpy()
        if "exposure_movements" in results:
            change = results["exposure_movements"].groupby(["scenario", "year", "portfolio"])[f"{col}_change"].sum()
            index = pd.MultiIndex.from_frame(books[["scenario", "year", "portfolio"]])
            cumulative = change.reindex(index, fill_value=0.0).groupby(level=[0, 2]).cumsum()
            expected = expected + cumulative.to_numpy()
        _require(_close(books[col], expected, tol), f"exposure stock bridge {col}")
    return books


def data_gaps(routed: RoutedPortfolio, start: pd.DataFrame) -> list[str]:
    """OPS-07: rejected records stay visible in the headline and the manifest."""
    rej = routed.rejections
    if rej.empty:
        return []
    cells = start[start["stage"] != "all"]
    facilities = rej.loc[rej["record_type"] == "facility", "record_id"].nunique()
    return [(f"DATA GAP: {len(rej):,} rejection(s) on {facilities:,} facilities; EUR "
            f"{cells['rejected_gca'].sum() / MILLION:,.1f}m of loaded GCA is not in these results "
            "(rejections.parquet)")]


def summary_lines(ctx: RunContext, impairment_tab: pd.DataFrame, books: pd.DataFrame,
                  migration: pd.DataFrame, years: list[int]) -> list[str]:
    lines = []
    last = max(years)
    for scen in sorted(impairment_tab["scenario"].unique(), key=lambda s: (s != "baseline", s)):
        tot = impairment_tab[(impairment_tab["scenario"] == scen) & (impairment_tab["portfolio"] == "Total")]
        cum = tot.loc[tot["year"] == last, "cumulative_charge"].iloc[0] / MILLION
        alloc = (tot.loc[tot["year"] == last, "closing_on"].iloc[0]
                 + tot.loc[tot["year"] == last, "closing_off"].iloc[0]) / MILLION
        first = tot.loc[tot["year"] == min(years), "charge_total"].iloc[0] / MILLION
        mig = migration[(migration["scenario"] == scen) & (migration["year"] == last)]
        s3 = mig["closing_S3"].sum() / MILLION
        lines.append(f"{scen}: cumulative charge {min(years)}-{last} EUR {cum:,.1f}m "
                     f"(first year {first:,.1f}m); closing provisions {last} EUR {alloc:,.1f}m; "
                     f"S3 GCA {last} EUR {s3:,.1f}m")
    return lines


def _selected(ctx: RunContext) -> str:
    return "; ".join(f"{label} {value}" for label, value in ctx.config.selected_methods().items())


def write_summary(ctx: RunContext, lines: list[str], impairment_tab: pd.DataFrame, books: pd.DataFrame,
                  migration: pd.DataFrame, start: pd.DataFrame, rejections: pd.DataFrame,
                  loaded: LoadedInputs) -> None:
    ps = loaded.parameter_set
    md = [
        f"# Stress run summary · {ctx.status_label}",
        "",
        ("Synthetic preparation run: not an EBA submission and not a bank forecast. "
         f"Parameter set {ps['parameter_set_id']} ({ps['status']}); input set "
         f"{ctx.input_set_hash[:16]}; variant {ctx.variant}; code {ctx.code_version}. "
         "Amounts in EUR millions, rounded here only."),
        "",
        "## Headline",
        "",
        *[f"- {line}" for line in lines],
        "",
        "## Impairment (total book, EUR m)",
        "",
        "| Scenario | Year | Opening | Charge | Closing | Cumulative charge |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    tot = impairment_tab[impairment_tab["portfolio"] == "Total"].sort_values(["scenario", "year"])
    for r in tot.itertuples(index=False):
        md.append(f"| {r.scenario} | {r.year} | {(r.opening_on + r.opening_off) / MILLION:,.1f} | "
                  f"{r.charge_total / MILLION:,.1f} | {(r.closing_on + r.closing_off) / MILLION:,.1f} | "
                  f"{r.cumulative_charge / MILLION:,.1f} |")
    md += ["", "## Stage mix of GCA (EUR m)", "",
           "| Scenario | Year | S1 | S2 | S3 | Total |", "|---|---:|---:|---:|---:|---:|"]
    mig = migration.groupby(["scenario", "year"])[["closing_S1", "closing_S2", "closing_S3"]].sum().reset_index()
    for r in mig.itertuples(index=False):
        total = r.closing_S1 + r.closing_S2 + r.closing_S3
        md.append(f"| {r.scenario} | {r.year} | {r.closing_S1 / MILLION:,.1f} | {r.closing_S2 / MILLION:,.1f} | "
                  f"{r.closing_S3 / MILLION:,.1f} | {total / MILLION:,.1f} |")
    book_heading = ("Dynamic books per projected year (EUR m)" if ctx.config.balance_sheet == "dynamic"
                    else "Static books per projected year (AT-44, EUR m)")
    md += ["", f"## {book_heading}", "",
           "| Scenario | Year | GCA | Undrawn | Converted | GCA + converted |", "|---|---:|---:|---:|---:|---:|"]
    agg = books.groupby(["scenario", "year"])[["gca", "undrawn", "converted", "gca_plus_converted"]].sum().reset_index()
    for r in agg.itertuples(index=False):
        md.append(f"| {r.scenario} | {r.year} | {r.gca / MILLION:,.1f} | {r.undrawn / MILLION:,.1f} | "
                  f"{r.converted / MILLION:,.1f} | {r.gca_plus_converted / MILLION:,.1f} |")
    whole = start[start["stage"] == "all"]
    accepted = int(start.loc[start["stage"] != "all", "accepted_count"].sum())
    opening = (whole["opening_allowance_on"].sum() + whole["opening_provision_off"].sum()) / MILLION
    md += [
        "", "## Starting point", "",
        f"- Facilities accepted: {accepted:,}; rejected records: {len(rejections):,}.",
        f"- Opening allowance (frozen, O4): EUR {opening:,.1f}m.",
        "- Currency EUR only; on-balance assets at amortised cost only.",
        "",
        ("Reports in this folder: starting_point_reconciliation.csv, stage_migration.csv, "
         "s3_cohorts.csv, grade_migration.csv, impairment.csv, impairment_by_stage.csv, "
         f"{ctx.config.balance_sheet}_books.csv and the parameter reports (z_scores.csv, pit_matrices.csv, "
         "pd_curves.csv, portfolio_pd.csv, lgd_by_z.csv, ead_profile.csv, ecl_by_bucket.csv)."),
        "",
    ]
    (ctx.reports_dir / SUMMARY_FILE).write_text("\n".join(md), encoding="utf-8", newline="\n")


def build_reports(ctx: RunContext, loaded: LoadedInputs, routed: RoutedPortfolio, drivers: Drivers,
                  schedule: pd.DataFrame, params: Parameters, results: dict) -> dict:
    ps = loaded.parameter_set
    tol = ps["tolerances"]["aggregate"]
    port = routed.portfolio
    if not port["accounting_category"].eq(ON_BALANCE_CATEGORY).all():
        raise BlockingError(STEP, Block.RECONCILIATION, "a non-AC asset reached the reports")
    years = [int(y) for y in ps["horizon"]["projection_years"]]
    books = check_static_books(results, port, params, tol)
    start = starting_point(loaded, routed, results, tol)
    migration, cohorts, grades = stage_migration(results, port, tol)
    imp, by_stage = impairment(results, port, tol)
    bridge = ecl_bridge(results, tol, ps["tolerances"]["amount"])

    _write(ctx, "starting_point_reconciliation.csv", start)
    _write(ctx, "stage_migration.csv", migration)
    _write(ctx, "s3_cohorts.csv", cohorts)
    _write(ctx, "grade_migration.csv", grades)
    _write(ctx, "impairment.csv", imp)
    _write(ctx, "impairment_by_stage.csv", by_stage, rates=("coverage_rate",))
    _write(ctx, "dynamic_books.csv" if ctx.config.balance_sheet == "dynamic" else "static_books.csv", books)
    if "exposure_movements" in results:
        _write(ctx, "exposure_movements.csv", results["exposure_movements"])
    rates = ("z", "probability", "conditional_pd", "marginal_pd", "survival", "cumulative_pd",
             "one_year_pd", "exposure_weighted_lgd", "value", "mean", "sd", "beta", "contribution",
             "adverse_weight", "annual_change", "index")
    param_tables = parameter_reports(ctx, drivers, params, results, port, loaded)
    for name, table in param_tables.items():
        _write(ctx, name, table, rates=rates)
    LOG.info("reconciliations within the section 12.3 tolerances: starting point, exposure stocks, "
             "stage flows, charge bridge, ECL by bucket")
    lines = summary_lines(ctx, imp, books, migration, years)
    lines += data_gaps(routed, start)
    if _selected(ctx):  # the headline reaches the console, the manifest and the summary
        lines.append(f"Selected method, not the design's default: {_selected(ctx)}")
    write_summary(ctx, lines, imp, books, migration, start, routed.rejections, loaded)
    effective = {
        "schema_version": 1, "input_set_hash": ctx.input_set_hash,
        "run": {k: v for k, v in ctx.config.as_dict().items() if k not in ("inputs", "analysis", "specification")},
        "parameter_set": ps, "scenarios": loaded.scenario_meta,
        "scenario_values": loaded.scenario_values.to_dict(orient="records"),
        "specification": {k: v for k, v in loaded.specification.items() if k != "run"},
        "preparation_analysis": loaded.analysis,
        "known_methodology_conflicts": ["C9", "C10", "C11", "C13", "C14", "C15", "C16"],
        "parameter_exposure_basis": "opening facility reference; R8 scales each grade slice to its current drawn/undrawn stock",
    }
    (ctx.reports_dir / "effective_specification.json").write_text(
        json.dumps(_json_values(effective), indent=2, sort_keys=True, default=str, allow_nan=False),
        encoding="utf-8", newline="\n")
    models = []
    for segment, settings in ps["segments"].items():
        model_id = settings.get("macro_model", "legacy_linear_z")
        model = ps.get("macro_models", {}).get(model_id, {})
        models.append({"segment": segment, "model_id": model_id,
                       "kind": model.get("kind", "linear"), "version": model.get("version", ps["version"]),
                       "source": model.get("source", ps["parameter_set_id"])})
    _write(ctx, "macro_models.csv", pd.DataFrame(models))
    meta = workbook_meta(ctx, loaded, routed, results, years)
    write_workbook(ctx.reports_dir / WORKBOOK_FILE, meta, {
        "impairment": imp, "by_stage": by_stage, "migration": migration, "cohorts": cohorts,
        "start": start, "portfolio": port, "z": drivers.z,
        "portfolio_pd": param_tables["portfolio_pd.csv"], "lgd": param_tables["lgd_by_z.csv"],
        "rejections": routed.rejections,
    })
    extra = portfolio_diagnostics(port, loaded.obligors.data, loaded.facilities.data, results["slices"])
    extra["ecl_bridge"] = bridge
    extra["ltv"] = stressed_ltv(port, loaded.facilities.data.assign(ltv_status=loaded.facilities.status["ltv"]),
                                results["slices"], drivers.indices, ctx.config.balance_sheet == "dynamic")
    extra["maturity"] = average_maturity(port, results["slices"], schedule)
    if ctx.config.balance_sheet == "static":
        extra["template_replica"] = template_replica(results["slices"], results["stage_flows"], params.lgd_of_year,
                                                     drivers.z, port, years, tol,
                                                     {s: p["template_class"] for s, p in ps["segments"].items()
                                                      if "template_class" in p})
    if "plausibility" in loaded.analysis and ADVERSE in ctx.scenarios:
        extra["plausibility"] = plausibility_sheet(loaded.analysis["plausibility"], imp, by_stage, loaded,
                                                   drivers.indices, years)
    extra.update(results.get("analyses", {}))
    extra["readiness"] = readiness(loaded, ctx.config)
    if "template_mapping" in loaded.analysis:
        extra["mapped_cells"] = mapped_cells(loaded.analysis["template_mapping"], extra)
    for name, table in extra.items():
        # Retain rate/diagnostic precision; amounts round only at this reporting boundary.
        rate_columns = ANALYSIS_RATES.get(name, ())
        # reverse_stress has its own solver status; preserve it beside the run label.
        table = table.rename(columns={"status": "analysis_status"})
        _write(ctx, f"analysis_{name}.csv", table, rate_columns)
    written = sorted(p.name for p in ctx.reports_dir.iterdir())
    LOG.info("wrote %d reports to %s: %s", len(written), ctx.reports_dir.relative_to(ctx.run_dir).as_posix(),
             ", ".join(written))
    return {"headline": lines}


def _portfolio_names(port: pd.DataFrame) -> dict[str, str]:
    """A plain label per portfolio from its data: products and counterparty sectors."""
    names = {}
    for p, part in port.groupby("portfolio"):
        products = ", ".join(sorted(part["product"].unique())).replace("_", " ")
        sectors = ", ".join(sorted(part["counterparty_sector"].unique())).replace("_", " ")
        names[p] = f"{products} ({sectors})"
    return names


def workbook_meta(ctx: RunContext, loaded: LoadedInputs, routed: RoutedPortfolio, results: dict,
                  years: list[int]) -> dict:
    ps = loaded.parameter_set
    rej = routed.rejections
    prov = results["provisions"]
    binding = int(prov.loc[prov["year"] == max(years), "floor_binding"].astype(bool).sum())
    n_fac = len(routed.portfolio)
    rows = loaded.load_controls["rows"]
    config = ctx.config
    schedules = ("Contractual schedules from balance, rate and maturity; each ends at zero"
                 + ("; no run-off inside the horizon (C15)" if config.horizon_runoff == RUNOFF_REPLACED else ""))
    z_note = (("; adverse property-secured LGD takes the path's worst Z (C16)" if config.lgd_path == LGD_TROUGH else "")
              + (f"; after {ps['terminal_rule']['last_scenario_year']} PD and LGD revert linearly, and Z still "
                 "drives prepayment (C8)" if config.terminal_treatment != TERMINAL_Z else ""))
    buckets = ("ECL by default bucket plus the held S2 amount equals the performing provisions (C14)"
               if config.s2_treatment == S2_HELD else "ECL by default bucket equals the performing provisions")
    rejected = "passed: no record rejected" if rej.empty else (
        f"{len(rej):,} rejection(s) on {rej.loc[rej['record_type'] == 'facility', 'record_id'].nunique():,} "
        "facilities; see the table below")
    checks = [
        ("R1", "Synthetic mode; the input set is fixed by its content hash", "OPS-01, OPS-04, GOV-04", "passed"),
        ("R2", "Every input file matches its manifest hash; raw files kept unchanged in data/",
         "OPS-01, DAT-03", f"passed: {len(rows)} tables and documents"),
        ("R2", "Row counts and control totals equal the input-set manifest; every value has a status",
         "DAT-02", f"passed: {rows['facilities']:,} facilities loaded"),
        ("R3", ("Duplicates, referential integrity, EUR-only and AC-only scope, CCF contract, grades, "
         "rates, maturities and TTC LGD (section 12.2 input controls)"), "SCP-06, EAD-04, EAD-10, LGD-12",
         rejected),
        ("R3", "TTC matrices: rows sum to one, no negative cell, D absorbing, PD rising with the grade",
         "PD-09, AT-45", "passed"),
        ("R3", "Every accepted facility's grade explains its reported stage under the SICR rule",
         "MIG-07, SYN-PAR-08", f"passed: {n_fac:,} facilities accepted"),
        ("R4", ("Scenarios labelled SYNTHETIC; every driver value and Z coefficient present; "
         f"adverse reverts toward baseline{z_note}"), "SCN-04, SCN-08, ECL-10", "passed"),
        ("R5", schedules, "EAD-10", "passed"),
        ("R6", ("Every PiT row sums to one; PD-03 identities on every curve; every LGD in [0, 1]; "
         f"prepayment in EAD only{z_note}"), "PD-10, PD-03, LGD-12, EAD-11", "passed"),
        ("R7", "Static balance: GCA and undrawn stay at end-2026 levels for every facility and year",
         "EXP-01, EAD-05, REG-02", "passed"),
        ("R8", "S3 allowances floored per exposure, never on the total",
         "ECL-07, ECL-11, AT-18", f"passed: floors bind on {binding:,} S3 slices at end-{max(years)}"),
        ("R9", "No S3 slice releases provision; the bridge holds only the charge; FX is zero",
         "REG-05, ACC-01, ACC-02", "passed"),
        ("R10", "Closing stage stocks equal the incoming flows; outflows equal opening stocks", "MIG-02", "passed"),
        ("R10", buckets, "ECL-09", "passed"),
        ("R10", "Charge = closing - opening in every year and book; static books per year", "ACC-01, AT-44", "passed"),
        ("R11", "Every output is hashed in manifest.json; `stress rerun --run <folder>` must reproduce them",
         "section 12.2 reproducibility", "checked by the rerun command"),
    ]
    if config.balance_sheet == "dynamic":
        checks = [(step, ("Opening exposure + supplied volume changes = migration opening; "
                          "credit migration conserves that exposure" if step == "R7" else description),
                   refs, result) for step, description, refs, result in checks]
        checks = [(step, description.replace("outflows equal opening stocks", "outflows equal opening stocks plus volume changes")
                   .replace("static books per year", "dynamic exposure bridge per year"), refs, result)
                  for step, description, refs, result in checks]
    terminal = ps["terminal_rule"]
    return {
        "status": ctx.status_label,
        "input_set": ctx.input_set_hash[:16],
        "parameter_set_id": ps["parameter_set_id"],
        "parameter_set_status": ps["status"],
        "variant": f"{ctx.variant}; selected method, not the design's default: {_selected(ctx)}"
                   if _selected(ctx) else ctx.variant,
        "code_version": ctx.code_version,
        "spec_version": ctx.spec_version,
        "horizon": f"starting point {ps['horizon']['snapshot_date']}, projection {min(years)}-{max(years)}",
        "years": years,
        "snapshot_date": str(ps["horizon"]["snapshot_date"]),
        "balance_sheet": config.balance_sheet,
        "last_reported_year": int(terminal["last_scenario_year"]) + int(terminal["reversion_years"]) + 1,
        "portfolio_names": _portfolio_names(routed.portfolio),
        "checks": checks,
    }


def compare_runs(base: Path, new: Path) -> pd.DataFrame:
    """Quantified difference of the impairment report between two runs (version change)."""
    tables, _, _ = comparison.compare(base, new)
    return tables["impairment"]
