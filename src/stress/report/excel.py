"""R10 Excel report: results/reports/stress_report.xlsx.

One workbook that shows what happened in the run, by portfolio, baseline next to adverse, in
EUR millions. Engine results are written as values (blue); every derived figure (totals,
coverage, cost of risk, adverse minus baseline, the summary KPIs) is an Excel formula (black),
so the sheet recalculates and can be traced. Display formats round; the stored values do not.

The file is byte-for-byte reproducible: fixed document times and fixed zip entry times, so a
rerun gives the same output hash (section 12.2 reproducibility).
"""

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

MILLION = 1_000_000.0
FONT = "Arial"
BLUE = "0000FF"  # engine output values
BLACK = "000000"  # formulas
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
GROUP_FILLS = {
    "baseline": PatternFill("solid", fgColor="DDEBF7"),
    "adverse": PatternFill("solid", fgColor="FCE4D6"),
    "difference": PatternFill("solid", fgColor="EDEDED"),
    "": PatternFill("solid", fgColor="D9D9D9"),
}
TOTAL_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="BFBFBF")
FORMATS = {
    "eur": '#,##0.0;(#,##0.0);"-"',
    "eur2": '#,##0.00;(#,##0.00);"-"',
    "pct": '0.00%;(0.00%);"-"',
    "pct1": '0.0%;(0.0%);"-"',
    "bp": '#,##0" bp";(#,##0" bp");"-"',
    "int": '#,##0;(#,##0);"-"',
    "num": '0.00;(0.00);"-"',
    "num4": '0.0000;(0.0000);"-"',
    "x": '0.00"x";(0.00"x");"-"',
    "text": "@",
}
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass
class Col:
    key: str
    header: str
    fmt: str = "eur"
    value: str | None = None  # DataFrame column written as a value
    formula: str | None = None  # template: {key} is that column's letter, {r} the row
    width: float = 12
    group: str = ""


def _font(color: str = BLACK, bold: bool = False, size: int = 10, italic: bool = False) -> Font:
    return Font(name=FONT, size=size, bold=bold, color=color, italic=italic)


def _cell(ws: Worksheet, row: int, col: int, value, fmt: str | None = None, color: str = BLACK,
          bold: bool = False):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = _font(color, bold)
    if fmt:
        cell.number_format = FORMATS[fmt]
    return cell


def write_table(ws: Worksheet, df: pd.DataFrame, cols: list[Col], top: int, left: int = 1,
                total_rows: pd.Series | None = None, autofilter: bool = True) -> dict:
    """Write a table with a header (and a group header row when columns are grouped).

    Returns the letters of every column key and the first and last data rows, so formulas on
    other sheets can reference the table.
    """
    letters = {c.key: get_column_letter(left + i) for i, c in enumerate(cols)}
    row = top
    if any(c.group for c in cols):
        start = 0
        while start < len(cols):
            end = start
            while end + 1 < len(cols) and cols[end + 1].group == cols[start].group:
                end += 1
            label = {"baseline": "Baseline", "adverse": "Adverse",
                     "difference": "Adverse - baseline"}.get(cols[start].group, cols[start].group)
            cell = ws.cell(row=row, column=left + start, value=label or None)
            if end > start:
                ws.merge_cells(start_row=row, start_column=left + start, end_row=row,
                               end_column=left + end)
            for k in range(start, end + 1):
                g = ws.cell(row=row, column=left + k)
                g.fill = GROUP_FILLS.get(cols[start].group, GROUP_FILLS[""])
            cell.font = _font(bold=True)
            cell.alignment = Alignment(horizontal="center")
            start = end + 1
        row += 1
    for i, c in enumerate(cols):
        h = ws.cell(row=row, column=left + i, value=c.header)
        h.font = _font("FFFFFF", bold=True)
        h.fill = HEADER_FILL
        h.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[letters[c.key]].width = max(ws.column_dimensions[letters[c.key]].width or 0, c.width)
    ws.row_dimensions[row].height = 30
    header_row = row
    first = row + 1
    for n, data in enumerate(df.to_dict("records")):
        r = first + n
        is_total = bool(total_rows.iloc[n]) if total_rows is not None else False
        for i, c in enumerate(cols):
            if c.formula is not None:
                value = c.formula.format(r=r, **letters)
                cell = _cell(ws, r, left + i, value, None if c.fmt == "text" else c.fmt, BLACK, is_total)
            else:
                value = data[c.value]
                if isinstance(value, float) and pd.isna(value):
                    value = None
                elif hasattr(value, "item"):
                    value = value.item()
                cell = _cell(ws, r, left + i, value, None if c.fmt == "text" else c.fmt,
                             BLACK if c.fmt == "text" else BLUE, is_total)
            cell.border = Border(bottom=THIN)
            if is_total:
                cell.fill = TOTAL_FILL
    last = first + len(df) - 1
    if autofilter and len(df):
        ws.auto_filter.ref = f"{get_column_letter(left)}{header_row}:{get_column_letter(left + len(cols) - 1)}{last}"
    return {"letters": letters, "first": first, "last": last, "header": header_row}


def _title(ws: Worksheet, title: str, subtitle: str) -> None:
    ws.cell(row=1, column=1, value=title).font = _font(bold=True, size=14)
    ws.cell(row=2, column=1, value=subtitle).font = _font(italic=True, color="595959")


def _m(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = out[c] / MILLION
    return out


def _range(sheet: str, table: dict, key: str) -> str:
    letter = table["letters"][key]
    return f"'{sheet}'!${letter}${table['first']}:${letter}${table['last']}"


# --- sheets -------------------------------------------------------------------------------------

def sheet_impairment(wb: Workbook, imp: pd.DataFrame) -> dict:
    ws = wb.create_sheet("Impairment")
    _title(ws, "Impairment: opening, charge and closing provisions",
           "EUR millions. Charge = closing - opening (ACC-01); a negative charge is a release. "
           "On-balance allowance and off-balance provision kept apart (EAD-08).")
    df = _m(imp, ["opening_on", "opening_off", "charge_on", "charge_off", "closing_on", "closing_off",
                  "cumulative_charge", "fx_movement", "overlay_closing"])
    df["year"] = df["year"].astype(str)
    df = df.sort_values(["scenario", "portfolio", "year"], key=lambda s: s.map(_order) if s.name == "scenario" else s)
    cols = [
        Col("scenario", "Scenario", "text", "scenario", width=11),
        Col("year", "Year", "text", "year", width=7),
        Col("portfolio", "Portfolio", "text", "portfolio", width=10),
        Col("oon", "Opening allowance (on)", value="opening_on"),
        Col("ooff", "Opening provision (off)", value="opening_off"),
        Col("otot", "Opening total", formula="={oon}{r}+{ooff}{r}"),
        Col("con", "Charge (on)", value="charge_on"),
        Col("coff", "Charge (off)", value="charge_off"),
        Col("ctot", "Charge total", formula="={con}{r}+{coff}{r}"),
        Col("clon", "Closing allowance (on)", value="closing_on"),
        Col("cloff", "Closing provision (off)", value="closing_off"),
        Col("cltot", "Closing total", formula="={clon}{r}+{cloff}{r}"),
        Col("cum", "Cumulative charge", value="cumulative_charge"),
        Col("fx", "FX movement", value="fx_movement", width=9),
        Col("check", "Bridge check (opening + charge - closing)", formula="={otot}{r}+{ctot}{r}+{fx}{r}-{cltot}{r}", width=14),
    ]
    table = write_table(ws, df, cols, top=4, total_rows=df["portfolio"] == "Total")
    ws.freeze_panes = ws.cell(row=table["first"], column=4)
    return table


def _order(name: str) -> tuple:
    return (name != "baseline", name)


def sheet_results(wb: Workbook, imp: pd.DataFrame, by_stage: pd.DataFrame, scenarios: list[str],
                  years: list[int]) -> dict:
    """The main comparison: per portfolio and year, baseline next to adverse."""
    ws = wb.create_sheet("Results by portfolio")
    _title(ws, "Results by portfolio: baseline and adverse side by side",
           "EUR millions at each year-end. Coverage = provisions / GCA. Cost of risk = charge / GCA. "
           "S3 = credit-impaired exposure; it never cures (EXP-02).")
    stage = by_stage.copy()
    stage["provisions"] = stage["allowance_on"] + stage["provision_off"]
    gca = stage.groupby(["scenario", "year", "portfolio", "stage"])["gca"].sum().unstack("stage", fill_value=0.0)
    gca.columns = [f"s{c}" for c in gca.columns]
    gca = gca.reset_index()
    total = gca.groupby(["scenario", "year"])[["s1", "s2", "s3"]].sum().reset_index()
    total["portfolio"] = "Total"
    gca = pd.concat([gca, total], ignore_index=True)
    merged = imp.merge(gca, on=["scenario", "year", "portfolio"], how="left")
    merged["provisions"] = merged["closing_on"] + merged["closing_off"]
    merged = merged[merged["year"].isin(years)]
    portfolios = sorted(p for p in merged["portfolio"].unique() if p != "Total") + ["Total"]
    rows = []
    for p in portfolios:
        for y in years:
            rec = {"portfolio": p, "year": str(y)}
            for s in scenarios:
                m = merged[(merged["scenario"] == s) & (merged["portfolio"] == p) & (merged["year"] == y)]
                if m.empty:
                    continue
                m = m.iloc[0]
                rec["gca"] = (m["s1"] + m["s2"] + m["s3"]) / MILLION
                for k in ("s1", "s2", "s3", "provisions", "charge_total", "cumulative_charge"):
                    rec[f"{s}_{k}"] = m[k] / MILLION
            rows.append(rec)
    df = pd.DataFrame(rows)
    cols = [Col("portfolio", "Portfolio", "text", "portfolio", width=10),
            Col("year", "Year", "text", "year", width=7),
            Col("gca", "GCA (static)", value="gca", width=11)]
    for s in scenarios:
        cols += [
            Col(f"{s}_s2", "S2 GCA", value=f"{s}_s2", group=s),
            Col(f"{s}_s3", "S3 GCA", value=f"{s}_s3", group=s),
            Col(f"{s}_s3r", "S3 ratio", "pct", formula=f"=IFERROR({{{s}_s3}}{{r}}/{{gca}}{{r}},0)", group=s, width=9),
            Col(f"{s}_prov", "Provisions", value=f"{s}_provisions", group=s),
            Col(f"{s}_cov", "Coverage", "pct", formula=f"=IFERROR({{{s}_prov}}{{r}}/{{gca}}{{r}},0)", group=s, width=9),
            Col(f"{s}_chg", "Charge in year", value=f"{s}_charge_total", group=s),
            Col(f"{s}_cor", "Cost of risk", "bp", formula=f"=IFERROR({{{s}_chg}}{{r}}/{{gca}}{{r}}*10000,0)", group=s, width=10),
            Col(f"{s}_cum", "Cumulative charge", value=f"{s}_cumulative_charge", group=s),
        ]
    if len(scenarios) == 2:
        b, a = scenarios
        cols += [
            Col("d_s3", "S3 GCA", formula=f"={{{a}_s3}}{{r}}-{{{b}_s3}}{{r}}", group="difference"),
            Col("d_prov", "Provisions", formula=f"={{{a}_prov}}{{r}}-{{{b}_prov}}{{r}}", group="difference"),
            Col("d_cov", "Coverage", "pct", formula=f"={{{a}_cov}}{{r}}-{{{b}_cov}}{{r}}", group="difference", width=9),
            Col("d_cum", "Cumulative charge", formula=f"={{{a}_cum}}{{r}}-{{{b}_cum}}{{r}}", group="difference"),
        ]
    table = write_table(ws, df, cols, top=4, total_rows=df["portfolio"] == "Total")
    ws.freeze_panes = ws.cell(row=table["first"], column=4)
    table["portfolios"] = portfolios
    return table


def sheet_portfolios(wb: Workbook, start: pd.DataFrame, portfolio: pd.DataFrame, names: dict) -> dict:
    """The book at the starting point (end-2026), by portfolio."""
    ws = wb.create_sheet("Portfolios")
    _title(ws, "Portfolios at the starting point (31 December 2026)",
           "EUR millions; counts in facilities. Converted commitments at the input-set CCF. "
           "Opening provisions are the frozen O4 allowances (SYN-PAR-09).")
    cells = start[start["stage"] != "all"].copy()
    cells["stage"] = cells["stage"].astype(int)
    by = cells.pivot_table(index="portfolio", columns="stage", values="accepted_gca", aggfunc="sum", fill_value=0.0)
    by = by.reindex(columns=[1, 2, 3], fill_value=0.0)  # a book without S2 or S3 still has the column
    agg = cells.groupby("portfolio").agg(
        facilities=("accepted_count", "sum"), undrawn=("undrawn", "sum"),
        converted=("converted_commitments", "sum"), allowance=("opening_allowance_on", "sum"),
        provision=("opening_provision_off", "sum"))
    irb = portfolio[portfolio["regulatory_approach"] == "IRB"].groupby("portfolio")["gca"].sum()
    df = agg.join(by).reset_index()
    df["name"] = df["portfolio"].map(names).fillna("")
    df["irb"] = df["portfolio"].map(irb).fillna(0.0)
    for c in ("undrawn", "converted", "allowance", "provision", 1, 2, 3, "irb"):
        df[c] = df[c] / MILLION
    df = df.rename(columns={1: "s1", 2: "s2", 3: "s3"})
    df["facilities"] = df["facilities"].astype(int)
    n = len(df)
    first = 5
    total = {"portfolio": "Total", "name": "", **{c: None for c in df.columns if c not in ("portfolio", "name")}}
    df = pd.concat([df, pd.DataFrame([total])], ignore_index=True)
    is_total = df["portfolio"] == "Total"
    cols = [
        Col("portfolio", "Portfolio", "text", "portfolio", width=10),
        Col("name", "Name", "text", "name", width=48),
        Col("fac", "Facilities", "int", "facilities", width=10),
        Col("s1", "S1 GCA", value="s1"), Col("s2", "S2 GCA", value="s2"), Col("s3", "S3 GCA", value="s3"),
        Col("gca", "GCA", formula="={s1}{r}+{s2}{r}+{s3}{r}"),
        Col("share", "Share of book", "pct1", formula=f"=IFERROR({{gca}}{{r}}/{{gca}}{first + n},0)", width=9),
        Col("s3r", "S3 ratio", "pct", formula="=IFERROR({s3}{r}/{gca}{r},0)", width=9),
        Col("und", "Undrawn", value="undrawn"),
        Col("conv", "Converted commitments", value="converted"),
        Col("ead", "GCA + converted", formula="={gca}{r}+{conv}{r}"),
        Col("allow", "Opening allowance (on)", value="allowance"),
        Col("prov", "Opening provision (off)", value="provision"),
        Col("cov", "Opening coverage", "pct", formula="=IFERROR(({allow}{r}+{prov}{r})/{gca}{r},0)", width=10),
        Col("irb", "IRB GCA", value="irb"),
        Col("irbs", "IRB share", "pct1", formula="=IFERROR({irb}{r}/{gca}{r},0)", width=9),
    ]
    table = write_table(ws, df, cols, top=4, total_rows=is_total, autofilter=False)
    total_row = table["last"]
    for key in ("fac", "s1", "s2", "s3", "und", "conv", "allow", "prov", "irb"):
        letter = table["letters"][key]
        c = ws[f"{letter}{total_row}"]
        c.value = f"=SUM({letter}{table['first']}:{letter}{total_row - 1})"
        c.font = _font(bold=True)
    ws.freeze_panes = ws.cell(row=table["first"], column=3)
    return table


def sheet_stage(wb: Workbook, migration: pd.DataFrame) -> dict:
    ws = wb.create_sheet("Stage migration")
    _title(ws, "Stage migration: opening stocks, flows during the year, closing stocks",
           "EUR millions of GCA. Flows are sums of rating-matrix cells grouped by each facility's "
           "SICR line (MIG-08); S3 never cures. Check = closing - (opening + flows in - flows out).")
    df = migration.copy()
    df["year"] = df["year"].astype(str)
    money = [c for c in df.columns if c.startswith(("opening_", "flow_", "closing_"))]
    df = _m(df, money)
    df = df.sort_values(["scenario", "portfolio", "year"], key=lambda s: s.map(_order) if s.name == "scenario" else s)
    flow_cols = [c for c in ("flow_S1_S1", "flow_S1_S2", "flow_S1_S3", "flow_S2_S1", "flow_S2_S2", "flow_S2_S3", "flow_S3_S3") if c in df]
    cols = [Col("scenario", "Scenario", "text", "scenario", width=11),
            Col("year", "Year", "text", "year", width=7),
            Col("portfolio", "Portfolio", "text", "portfolio", width=10)]
    cols += [Col(f"o{s}", f"Opening {s}", value=f"opening_{s}", group="Opening") for s in ("S1", "S2", "S3")]
    cols += [Col(c, c.replace("flow_", "").replace("_", " to "), value=c, group="Flows", width=10) for c in flow_cols]
    cols += [Col(f"c{s}", f"Closing {s}", value=f"closing_{s}", group="Closing") for s in ("S1", "S2", "S3")]
    cols.append(Col("check", "Check total", formula="=({cS1}{r}+{cS2}{r}+{cS3}{r})-({oS1}{r}+{oS2}{r}+{oS3}{r})", width=10))
    table = write_table(ws, df, cols, top=4)
    ws.freeze_panes = ws.cell(row=table["first"], column=4)
    return table


def sheet_coverage(wb: Workbook, by_stage: pd.DataFrame) -> dict:
    ws = wb.create_sheet("Coverage by stage")
    _title(ws, "Exposure and provisions by stage", "EUR millions. Coverage = (allowance + provision) / GCA.")
    df = _m(by_stage, ["gca", "undrawn", "allowance_on", "provision_off"])
    df["year"] = df["year"].astype(str)
    df["stage"] = "S" + df["stage"].astype(int).astype(str)
    df = df.sort_values(["scenario", "portfolio", "year", "stage"], key=lambda s: s.map(_order) if s.name == "scenario" else s)
    cols = [Col("scenario", "Scenario", "text", "scenario", width=11),
            Col("year", "Year", "text", "year", width=7),
            Col("portfolio", "Portfolio", "text", "portfolio", width=10),
            Col("stage", "Stage", "text", "stage", width=7),
            Col("gca", "GCA", value="gca"), Col("und", "Undrawn", value="undrawn"),
            Col("on", "Allowance (on)", value="allowance_on"), Col("off", "Provision (off)", value="provision_off"),
            Col("cov", "Coverage", "pct", formula="=IFERROR(({on}{r}+{off}{r})/{gca}{r},0)", width=9)]
    table = write_table(ws, df, cols, top=4)
    ws.freeze_panes = ws.cell(row=table["first"], column=5)
    return table


def sheet_cohorts(wb: Workbook, cohorts: pd.DataFrame) -> dict:
    ws = wb.create_sheet("S3 cohorts")
    _title(ws, "Credit-impaired (S3) cohorts",
           "EUR millions. The original end-2026 cohort and each new cohort by entry year and origin "
           "stage (MIG-03); allowances never fall below their floor (ECL-11).")
    df = _m(cohorts, ["gca", "undrawn", "allowance_on", "provision_off"])
    df["year"] = df["year"].astype(str)
    df = df.sort_values(["scenario", "portfolio", "year", "cohort"], key=lambda s: s.map(_order) if s.name == "scenario" else s)
    cols = [Col("scenario", "Scenario", "text", "scenario", width=11),
            Col("year", "Year", "text", "year", width=7),
            Col("portfolio", "Portfolio", "text", "portfolio", width=10),
            Col("cohort", "Cohort", "text", "cohort", width=20),
            Col("gca", "GCA", value="gca"), Col("und", "Undrawn", value="undrawn"),
            Col("on", "Allowance (on)", value="allowance_on"), Col("off", "Provision (off)", value="provision_off"),
            Col("cov", "Coverage", "pct", formula="=IFERROR(({on}{r}+{off}{r})/{gca}{r},0)", width=9)]
    table = write_table(ws, df, cols, top=4)
    ws.freeze_panes = ws.cell(row=table["first"], column=5)
    return table


def sheet_parameters(wb: Workbook, z: pd.DataFrame, pd_tab: pd.DataFrame, lgd_tab: pd.DataFrame,
                     scenarios: list[str], years: list[int], last_reported: int) -> None:
    ws = wb.create_sheet("Parameters")
    _title(ws, "Scenario drivers and risk parameters",
           "Z > 0 is a better economy than average (SCN-08). One-year PD weighted by drawn exposure "
           "(RPT-06); LGD weighted by GCA. Adverse Z reverts to baseline 2029 over six years (ECL-10).")
    # Z by segment, scenario and year (common paths: the same in every country).
    zz = z[z["year"] <= last_reported].groupby(["segment", "scenario", "year"])["z"].mean().unstack("year").reset_index()
    zz = zz.sort_values(["scenario", "segment"], key=lambda s: s.map(_order) if s.name == "scenario" else s)
    z_years = [c for c in zz.columns if c not in ("segment", "scenario")]
    zdf = zz.rename(columns={y: str(y) for y in z_years})
    zcols = [Col("segment", "Segment", "text", "segment", width=10), Col("scenario", "Scenario", "text", "scenario", width=11)]
    zcols += [Col(f"y{y}", str(y), "num", str(y), width=8, group="Z-score by year") for y in z_years]
    t = write_table(ws, zdf, zcols, top=4, autofilter=False)
    row = t["last"] + 3
    # One-year PD by portfolio and stage.
    ws.cell(row=row - 1, column=1, value="One-year PD, drawn-exposure weighted (RPT-06)").font = _font(bold=True)
    pdp = pd_tab[pd_tab["stage"] < 3].copy()
    wide = pdp.pivot_table(index=["portfolio", "stage"], columns=["scenario", "year"], values="one_year_pd").reset_index()
    wide.columns = [f"{a}_{b}" if b != "" else a for a, b in wide.columns]
    wide["stage"] = "S" + wide["stage"].astype(int).astype(str)
    pcols = [Col("portfolio", "Portfolio", "text", "portfolio", width=10), Col("stage", "Stage", "text", "stage", width=7)]
    for s in scenarios:
        pcols += [Col(f"{s}{y}", str(y), "pct", f"{s}_{y}", width=8, group=s) for y in [years[0] - 1, *years] if f"{s}_{y}" in wide]
    if len(scenarios) == 2 and f"{scenarios[1]}_{years[0]}" in wide:
        b, a = scenarios
        pcols.append(Col("mult", f"Adverse / baseline {years[0]}", "x",
                         formula=f"=IFERROR({{{a}{years[0]}}}{{r}}/{{{b}{years[0]}}}{{r}},0)", width=12, group="difference"))
    t = write_table(ws, wide, pcols, top=row, autofilter=False)
    row = t["last"] + 3
    ws.cell(row=row - 1, column=1, value="LGD of the year, GCA weighted (LGD-12)").font = _font(bold=True)
    lw = lgd_tab.pivot_table(index="segment", columns=["scenario", "year"], values="exposure_weighted_lgd").reset_index()
    lw.columns = [f"{a}_{b}" if b != "" else a for a, b in lw.columns]
    lcols = [Col("segment", "Segment", "text", "segment", width=10)]
    for s in scenarios:
        lcols += [Col(f"{s}{y}", str(y), "pct", f"{s}_{y}", width=8, group=s) for y in years if f"{s}_{y}" in lw]
    write_table(ws, lw, lcols, top=row, autofilter=False)


def sheet_starting_point(wb: Workbook, start: pd.DataFrame, scenarios: list[str]) -> None:
    ws = wb.create_sheet("Starting point")
    _title(ws, "Starting-point reconciliation (31 December 2026)",
           "Loaded = accepted + rejected, by portfolio and stage. EUR millions. The engine's own "
           "end-2026 view is a diagnostic next to the frozen O4 allowance (assumption A16).")
    df = start[start["stage"] != "all"].copy()
    money = ["loaded_gca", "rejected_gca", "accepted_gca", "undrawn", "converted_commitments",
             "opening_allowance_on", "opening_provision_off"]
    engine = [c for c in df.columns if c.startswith("engine_2026_")]
    df = _m(df, money + engine)
    df["stage"] = "S" + df["stage"].astype(int).astype(str)
    cols = [Col("portfolio", "Portfolio", "text", "portfolio", width=10), Col("stage", "Stage", "text", "stage", width=7),
            Col("lc", "Loaded facilities", "int", "loaded_count", width=10),
            Col("rc", "Rejected", "int", "rejected_count", width=9),
            Col("ac", "Accepted", "int", "accepted_count", width=9),
            Col("lg", "Loaded GCA", value="loaded_gca"), Col("rg", "Rejected GCA", value="rejected_gca"),
            Col("ag", "Accepted GCA", value="accepted_gca"),
            Col("chk", "Check (loaded - accepted - rejected)", formula="={lg}{r}-{ag}{r}-{rg}{r}", width=14),
            Col("ao", "Frozen allowance (on)", value="opening_allowance_on"),
            Col("po", "Frozen provision (off)", value="opening_provision_off")]
    for s in scenarios:
        if f"engine_2026_{s}_on" in df:
            cols.append(Col(f"e{s}", f"Engine end-2026, {s}", value=f"engine_2026_{s}_on", width=13))
    write_table(ws, df, cols, top=4)


def sheet_checks(wb: Workbook, checks: list[tuple[str, str, str, str]], rejections: pd.DataFrame) -> None:
    ws = wb.create_sheet("Checks")
    _title(ws, "Checks performed in this run",
           "Every check below passed: a failing check blocks the run, which is then sealed BLOCKED "
           "with its reason. Times and durations are in runs/<run_id>/run.log.")
    df = pd.DataFrame(checks, columns=["step", "check", "requirement", "result"])
    cols = [Col("step", "Step", "text", "step", width=7), Col("check", "Check", "text", "check", width=70),
            Col("req", "Requirement", "text", "requirement", width=24), Col("res", "Result", "text", "result", width=40)]
    t = write_table(ws, df, cols, top=4, autofilter=False)
    for r in range(t["first"], t["last"] + 1):
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    row = t["last"] + 3
    ws.cell(row=row - 1, column=1, value="Rejected records by reason").font = _font(bold=True)
    if rejections.empty:
        ws.cell(row=row, column=1, value="None: every record of the input set was accepted.").font = _font()
    else:
        counts = rejections.groupby(["record_type", "reason_code"]).size().reset_index(name="records")
        write_table(ws, counts, [Col("t", "Record type", "text", "record_type", width=16),
                                 Col("c", "Reason", "text", "reason_code", width=30),
                                 Col("n", "Records", "int", "records", width=10)], top=row, autofilter=False)


def sheet_notes(wb: Workbook, meta: dict) -> None:
    ws = wb.create_sheet("Notes")
    _title(ws, "How to read this workbook", "")
    lines = [
        ("Status", f"{meta['status']}: a synthetic preparation run. Not an EBA submission, not a bank forecast (OPS-04)."),
        ("Units", "Amounts in EUR millions; rates and ratios as percentages. Values are unrounded; formats round the display only."),
        ("Colours", "Blue numbers are engine results written by the run. Black cells are Excel formulas over them."),
        ("Baseline / adverse", "Two scenarios through the same code, never blended (REG-07). 'Adverse - baseline' columns are formulas."),
        ("Static balance", "GCA and undrawn stay at end-2026 levels every year; matured facilities are replaced like for like (EXP-01, EXP-05)."),
        ("Charge", "Charge = closing - opening provisions in the year; a negative charge is a release. The 2027 opening is the frozen O4 allowance."),
        ("Coverage", "Provisions (on- plus off-balance) / GCA."),
        ("Cost of risk", "Charge in the year / GCA, in basis points."),
        ("S3", "Credit-impaired exposure: the original end-2026 cohort plus new cohorts by entry year and origin stage. No cures, sales or write-offs."),
        ("Parameters", f"Parameter set {meta['parameter_set_id']} ({meta['parameter_set_status']}). Open owner inputs and the assumptions taken are in docs/assumptions.md."),
        ("Run identity", "The run ID and its times are in manifest.json and run.log; they are kept out of this file so a rerun reproduces it byte for byte."),
        ("Detail", "Facility-level results are in results/*.parquet; the CSV reports next to this file hold the same tables unpivoted."),
    ]
    for i, (k, v) in enumerate(lines, start=4):
        ws.cell(row=i, column=1, value=k).font = _font(bold=True)
        c = ws.cell(row=i, column=2, value=v)
        c.font = _font()
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 110


def sheet_summary(ws: Worksheet, meta: dict, imp_t: dict, results_t: dict, portfolios_t: dict,
                  scenarios: list[str], years: list[int]) -> None:
    _title(ws, "Credit stress test: results summary",
           f"{meta['status']} run · amounts in EUR millions · {meta['horizon']}")
    info = [
        ("Status", meta["status"]),
        ("Input set", meta["input_set"]),
        ("Parameter set", f"{meta['parameter_set_id']} ({meta['parameter_set_status']})"),
        ("Variant", meta["variant"]),
        ("Scenarios", ", ".join(scenarios)),
        ("Code version", meta["code_version"]),
        ("Requirements version", meta["spec_version"]),
    ]
    for i, (k, v) in enumerate(info, start=4):
        ws.cell(row=i, column=1, value=k).font = _font(bold=True)
        ws.cell(row=i, column=2, value=v).font = _font()
    top = 4 + len(info) + 2
    ws.cell(row=top - 1, column=1, value="Key results, whole book").font = _font(bold=True, size=11)
    header = ["Metric", *scenarios] + (["Adverse - baseline"] if len(scenarios) == 2 else [])
    for j, h in enumerate(header, start=1):
        c = ws.cell(row=top, column=j, value=h)
        c.font = _font("FFFFFF", bold=True)
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center")
    sheet = "Impairment"
    rng = {k: _range(sheet, imp_t, k) for k in ("scenario", "year", "portfolio", "otot", "ctot", "cltot", "cum")}
    gca_cell = f"'Portfolios'!${portfolios_t['letters']['gca']}${portfolios_t['last']}"
    res_port = _range("Results by portfolio", results_t, "portfolio")
    res_year = _range("Results by portfolio", results_t, "year")
    first, last = str(years[0]), str(years[-1])

    def sumifs(value_key: str, scen_col: str, year: str) -> str:
        return (f'=SUMIFS({rng[value_key]},{rng["scenario"]},{scen_col}${top},{rng["year"]},"{year}",'
                f'{rng["portfolio"]},"Total")')

    metrics: list[tuple[str, str, object]] = [("Opening GCA", "eur", lambda col: f"={gca_cell}")]
    metrics.append((f"Opening provisions {years[0] - 1}", "eur", lambda col: sumifs("otot", col, first)))
    for y in years:
        metrics.append((f"Charge {y}", "eur", lambda col, y=y: sumifs("ctot", col, str(y))))
    metrics.append((f"Cumulative charge {first}-{last}", "eur", lambda col: sumifs("cum", col, last)))
    metrics.append((f"Closing provisions {last}", "eur", lambda col: sumifs("cltot", col, last)))
    base_row = top + 1
    rows = {}
    for i, (label, fmt, f) in enumerate(metrics):
        r = base_row + i
        rows[label] = r
        ws.cell(row=r, column=1, value=label).font = _font()
        for j, _ in enumerate(scenarios, start=2):
            col = get_column_letter(j)
            _cell(ws, r, j, f(col), fmt)
    r = base_row + len(metrics)
    extra = []
    gca_row = rows["Opening GCA"]
    for j, scen in enumerate(scenarios, start=2):
        extra.append((j, get_column_letter(j), _range("Results by portfolio", results_t, f"{scen}_s3")))
    labels = [
        (f"Coverage {last} (provisions / GCA)", "pct", lambda col: f"=IFERROR({col}{rows[f'Closing provisions {last}']}/{col}{gca_row},0)"),
        ("Average annual cost of risk", "bp",
         lambda col: f"=IFERROR({col}{rows[f'Cumulative charge {first}-{last}']}/{len(years)}/{col}{gca_row}*10000,0)"),
    ]
    for k, (label, fmt, f) in enumerate(labels):
        ws.cell(row=r + k, column=1, value=label).font = _font()
        for j, col, _ in extra:
            _cell(ws, r + k, j, f(col), fmt)
        rows[label] = r + k
    r += len(labels)
    ws.cell(row=r, column=1, value=f"S3 GCA {last}").font = _font()
    for j, col, s3_range in extra:
        _cell(ws, r, j, f'=SUMIFS({s3_range},{res_port},"Total",{res_year},"{last}")', "eur")
    rows["s3"] = r
    ws.cell(row=r + 1, column=1, value=f"S3 ratio {last}").font = _font()
    for j, col, _ in extra:
        _cell(ws, r + 1, j, f"=IFERROR({col}{r}/{col}{gca_row},0)", "pct")
    end = r + 1
    if len(scenarios) == 2:
        for rr in range(base_row, end + 1):
            fmt = ws.cell(row=rr, column=2).number_format
            c = ws.cell(row=rr, column=4, value=f"=C{rr}-B{rr}")
            c.font = _font()
            c.number_format = fmt
            ws.cell(row=rr, column=4).fill = GROUP_FILLS["difference"]
    for rr in range(base_row, end + 1):
        for j in range(1, len(header) + 1):
            ws.cell(row=rr, column=j).border = Border(bottom=THIN)
    ws.column_dimensions["A"].width = 34
    for j in range(2, len(header) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 18

    # Chart data: cumulative charge by portfolio, and provisions by year (formulas).
    chart_top = end + 3
    ws.cell(row=chart_top - 1, column=1, value=f"Cumulative charge {first}-{last} by portfolio").font = _font(bold=True, size=11)
    ws.cell(row=chart_top, column=1, value="Portfolio").font = _font(bold=True)
    for j, scen in enumerate(scenarios, start=2):
        ws.cell(row=chart_top, column=j, value=scen).font = _font(bold=True)
    ports = [p for p in results_t["portfolios"] if p != "Total"]
    for i, p in enumerate(ports, start=1):
        rr = chart_top + i
        ws.cell(row=rr, column=1, value=p).font = _font()
        for j, _ in enumerate(scenarios, start=2):
            col = get_column_letter(j)
            f = (f'=SUMIFS({rng["cum"]},{rng["scenario"]},{col}${chart_top},{rng["year"]},"{last}",'
                 f'{rng["portfolio"]},$A{rr})')
            _cell(ws, rr, j, f, "eur")
    bar = BarChart()
    bar.type = "col"
    bar.title = f"Cumulative charge {first}-{last} (EUR m)"
    bar.y_axis.title = "EUR m"
    bar.add_data(Reference(ws, min_col=2, max_col=1 + len(scenarios), min_row=chart_top, max_row=chart_top + len(ports)),
                 titles_from_data=True)
    bar.set_categories(Reference(ws, min_col=1, min_row=chart_top + 1, max_row=chart_top + len(ports)))
    bar.height, bar.width = 7.5, 16
    _show_axes(bar)
    ws.add_chart(bar, "F4")

    line_top = chart_top + len(ports) + 3
    ws.cell(row=line_top - 1, column=1, value="Total provisions by year-end").font = _font(bold=True, size=11)
    ws.cell(row=line_top, column=1, value="Year").font = _font(bold=True)
    for j, scen in enumerate(scenarios, start=2):
        ws.cell(row=line_top, column=j, value=scen).font = _font(bold=True)
    all_years = [years[0] - 1, *years]
    for i, y in enumerate(all_years, start=1):
        rr = line_top + i
        ws.cell(row=rr, column=1, value=str(y)).font = _font()
        for j, _ in enumerate(scenarios, start=2):
            col = get_column_letter(j)
            if y == years[0] - 1:
                f = sumifs("otot", col, first).replace(f"{col}${top}", f"{col}${line_top}")
            else:
                f = sumifs("cltot", col, str(y)).replace(f"{col}${top}", f"{col}${line_top}")
            _cell(ws, rr, j, f, "eur")
    chart = LineChart()
    chart.title = "Total provisions (EUR m)"
    chart.y_axis.title = "EUR m"
    chart.add_data(Reference(ws, min_col=2, max_col=1 + len(scenarios), min_row=line_top, max_row=line_top + len(all_years)),
                   titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=line_top + 1, max_row=line_top + len(all_years)))
    chart.height, chart.width = 7.5, 16
    for series in chart.series:
        series.smooth = False  # year-end points joined by straight lines
    _show_axes(chart)
    ws.add_chart(chart, "F21")
    ws.freeze_panes = None


def _show_axes(chart) -> None:
    """openpyxl 3.1 writes axes as deleted unless told otherwise; show values and categories."""
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.y_axis.number_format = "#,##0"
    chart.y_axis.majorGridlines = chart.y_axis.majorGridlines
    chart.legend.position = "b"


# --- workbook -----------------------------------------------------------------------------------

def _apply_font(wb: Workbook) -> None:
    for ws in wb.worksheets:
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.sheet_view.showGridLines = False
        for row in ws.iter_rows():
            for cell in row:
                if cell.font is None or cell.font.name != FONT:
                    f = cell.font
                    cell.font = Font(name=FONT, size=f.size or 10, bold=f.bold, italic=f.italic,
                                     color=f.color)


def _deterministic(data: bytes, stamp: datetime) -> bytes:
    """Fix the zip entry times and the document times so equal content gives equal bytes."""
    iso = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            body = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                text = body.decode("utf-8")
                text = re.sub(r"(<dcterms:(created|modified)[^>]*>)[^<]*(</dcterms:\2>)", rf"\g<1>{iso}\g<3>", text)
                body = text.encode("utf-8")
            entry = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o600 << 16
            dst.writestr(entry, body)
    return out.getvalue()


def write_workbook(path: Path, meta: dict, tables: dict) -> None:
    scenarios = sorted(tables["impairment"]["scenario"].unique(), key=_order)
    years = meta["years"]
    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    portfolios_t = sheet_portfolios(wb, tables["start"], tables["portfolio"], meta["portfolio_names"])
    results_t = sheet_results(wb, tables["impairment"], tables["by_stage"], scenarios, years)
    imp_t = sheet_impairment(wb, tables["impairment"])
    sheet_stage(wb, tables["migration"])
    sheet_coverage(wb, tables["by_stage"])
    sheet_cohorts(wb, tables["cohorts"])
    sheet_parameters(wb, tables["z"], tables["portfolio_pd"], tables["lgd"], scenarios, years,
                     meta["last_reported_year"])
    sheet_starting_point(wb, tables["start"], scenarios)
    sheet_checks(wb, meta["checks"], tables["rejections"])
    sheet_notes(wb, meta)
    sheet_summary(summary, meta, imp_t, results_t, portfolios_t, scenarios, years)
    _apply_font(wb)
    stamp = datetime.fromisoformat(meta["snapshot_date"])
    wb.properties.creator = "stress engine"
    wb.properties.title = "Credit stress test results"
    wb.properties.created = stamp
    wb.properties.modified = stamp
    wb.properties.lastModifiedBy = "stress engine"
    wb.calculation.fullCalcOnLoad = True  # Excel computes every formula when the file opens
    buffer = io.BytesIO()
    wb.save(buffer)
    path.write_bytes(_deterministic(buffer.getvalue(), stamp))
