"""The R10 reports and the Excel workbook say what the results say, for any number of scenarios
and for static and dynamic runs (RPT-05, RPT-06; owner decisions of 9 November 2026, A45).

openpyxl reads a formula's text and nothing has calculated it, so ``Book`` recomputes a formula
from the cells it names. No expected figure is typed here: each one is recomputed from the run's
own result tables or read from its inputs.
"""

import json
import re

import pandas as pd
import pytest
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from stress.cli import execute
from stress.contracts.run import RunConfig
from stress.models import LGD, PREPAYMENT, REGISTRY
from stress.report import SUMMARY_FILE, WORKBOOK_FILE
from tests import builders
from tests.support import ROOT, assert_close, tolerance
from tests.unit.test_specification import specification, write_spec

GROWTH = 0.1  # the volume change of the dynamic run: an input of these tests, not a result
MILLION = 1_000_000.0
STAGE_KEYS = ["scenario", "year", "portfolio", "stage"]

_TOKEN = re.compile(r"""\s*(?:(?P<number>\d+(?:\.\d+)?)|"(?P<text>[^"]*)"|'(?P<sheet>[^']+)'!"""
                    r"""|(?P<cell>\$?[A-Z]{1,3}\$?\d+)|(?P<call>[A-Z]+)\(|(?P<op>[-+*/(),:]))""")


class Book:
    """A sealed workbook. ``value`` gives a cell's value and recomputes a formula from the cells
    it names: the four operations, IFERROR, SUM and SUMIFS, which are all this workbook uses."""

    def __init__(self, path):
        self.wb = load_workbook(path)
        self._seen = {}

    def __getitem__(self, sheet):
        return self.wb[sheet]

    def value(self, sheet: str, ref: str):
        key = (sheet, ref.replace("$", ""))
        if key not in self._seen:
            value = self.wb[sheet][key[1]].value
            if isinstance(value, str) and value.startswith("="):
                value = self._evaluate(self._parse(sheet, value[1:]))
            self._seen[key] = value
        return self._seen[key]

    def number(self, sheet: str, ref: str) -> float:
        return _number(self.value(sheet, ref))

    def _parse(self, sheet: str, text: str):
        tokens, at = [], 0
        while at < len(text):
            match = _TOKEN.match(text, at)
            assert match, f"cannot read the formula at {text[at:]!r}"
            tokens.append((match.lastgroup, match.group(match.lastgroup)))
            at = match.end()
        tokens.append(("end", ""))
        place = [0]

        def take(kind=None, value=None):
            token = tokens[place[0]]
            assert (kind is None or token[0] == kind) and (value is None or token[1] == value), (text, token)
            place[0] += 1
            return token

        def ahead(*values):
            return tokens[place[0]][0] == "op" and tokens[place[0]][1] in values

        def chain(part, *operators):
            node = part()
            while ahead(*operators):
                node = ("op", take()[1], node, part())
            return node

        def expression():
            return chain(lambda: chain(factor, "*", "/"), "+", "-")

        def cells(name):
            first = take("cell")[1]
            if ahead(":"):
                take()
                return ("range", name, first, take("cell")[1])
            return ("cell", name, first)

        def factor():
            kind, value = tokens[place[0]]
            if kind == "number":
                return ("value", float(take()[1]))
            if kind == "text":
                return ("value", take()[1])
            if kind == "sheet":
                take()
                return cells(value)
            if kind == "cell":
                return cells(sheet)
            if kind == "call":
                take()
                arguments = [expression()]
                while ahead(","):
                    take()
                    arguments.append(expression())
                take("op", ")")
                return ("call", value, arguments)
            if ahead("-"):
                take()
                return ("op", "-", ("value", 0.0), factor())
            take("op", "(")
            node = expression()
            take("op", ")")
            return node

        tree = expression()
        take("end")
        return tree

    def _evaluate(self, node):
        kind = node[0]
        if kind == "value":
            return node[1]
        if kind == "cell":
            return self.value(node[1], node[2])
        if kind == "range":
            first, last = node[2].replace("$", ""), node[3].replace("$", "")
            return [self.value(node[1], cell.coordinate) for row in self.wb[node[1]][f"{first}:{last}"]
                    for cell in row]
        if kind == "op":
            a, b = _number(self._evaluate(node[2])), _number(self._evaluate(node[3]))
            return {"+": a + b, "-": a - b, "*": a * b}[node[1]] if node[1] != "/" else a / b
        name, arguments = node[1], node[2]
        if name == "IFERROR":
            try:
                return self._evaluate(arguments[0])
            except ZeroDivisionError:
                return self._evaluate(arguments[1])
        if name == "SUM":
            return sum(_number(v) for a in arguments for v in _listed(self._evaluate(a)))
        assert name == "SUMIFS", f"{name} is not a function these tests can recompute"
        values = self._evaluate(arguments[0])
        tests = [(self._evaluate(r), str(self._evaluate(c))) for r, c in zip(arguments[1::2], arguments[2::2])]
        return sum(_number(v) for i, v in enumerate(values) if all(str(r[i]) == c for r, c in tests))


def _number(value) -> float:
    return 0.0 if value is None else float(value)


def _listed(value) -> list:
    return value if isinstance(value, list) else [value]


def workbook(ctx) -> Book:
    return Book(ctx.reports_dir / WORKBOOK_FILE)


def header_row(ws, first: str) -> int:
    """The row of a table's column headers: the one whose first cell reads ``first``."""
    return next(row[0].row for row in ws.iter_rows(max_col=1) if row[0].value == first)


def columns(ws, row: int) -> dict[str, str]:
    """Column letter by header of an ungrouped table."""
    return {cell.value: cell.column_letter for cell in ws[row] if cell.value is not None}


def grouped_columns(ws, row: int) -> dict[tuple[str | None, str], str]:
    """Column letter by (group header, header): the group header sits in the row above, in the
    first cell of its merged range."""
    out, group = {}, None
    for cell in ws[row]:
        above = ws.cell(row=row - 1, column=cell.column).value
        group = above if above is not None else group
        if cell.value is not None:
            out[(group, cell.value)] = cell.column_letter
    return out


def records(ws, row: int) -> list[int]:
    """The data rows under a header row, to the first empty first cell."""
    out = []
    for cells in ws.iter_rows(min_row=row + 1, max_col=1):
        if cells[0].value is None:
            break
        out.append(cells[0].row)
    return out


def referenced(formula: str) -> set[str]:
    """The column letters a formula names."""
    return set(re.findall(r"\$?([A-Z]{1,3})\$?\d+", formula))


def stage_stocks(ctx, tables: dict) -> pd.DataFrame:
    """Exposure and provisions per scenario, year, book and stage, summed from the slices."""
    slices = builders.result(ctx, "slices.parquet").merge(tables["facilities"][["facility_id", "portfolio"]],
                                                         on="facility_id", validate="many_to_one")
    return slices.groupby(STAGE_KEYS)[["gca", "undrawn", "allowance_on", "provision_off"]].sum()


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0  # the workbook shows a dash for an empty book


def scenario_labels(tables: dict) -> dict[str, str]:
    return {s["id"]: s["label"] for s in tables["scenarios"]["scenarios"]}


def summary_of(ctx) -> list[str]:
    return (ctx.reports_dir / SUMMARY_FILE).read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="module")
def small_runs(mini_tables, tmp_path_factory):
    """Sealed runs of one small book: static with two scenarios and with every scenario of the
    set, and dynamic with no volume change and with ``GROWTH`` in every book, year and scenario."""
    tables = builders.copy_tables(mini_tables)
    root = tmp_path_factory.mktemp("report_runs")
    inputs = builders.write(tables, root / "inputs")
    every = tuple(s["id"] for s in tables["scenarios"]["scenarios"])
    assert len(every) > 2, "the set holds scenarios beyond baseline and adverse (A43)"
    out = {"tables": tables, "specifications": {}}
    runs = {"static": lambda: builders.run(inputs, root / "runs"),
            "every": lambda: builders.run(inputs, root / "runs", scenarios=every)}
    for name, change in (("unchanged", 0.0), ("grown", GROWTH)):
        rows = [{"scenario": scenario, "year": year, "portfolio": portfolio, "drawn_change": change,
                 "undrawn_change": change}
                for scenario in ("baseline", "adverse")
                for year in tables["parameter_set"]["horizon"]["projection_years"]
                for portfolio in sorted(tables["facilities"]["portfolio"].unique())]
        doc = specification(inputs, balance_sheet={"assumptions": rows})
        doc["run"]["balance_sheet"] = "dynamic"
        out["specifications"][name] = doc
        path = write_spec(root / f"{name}.yaml", doc)
        runs[name] = lambda path=path: execute(RunConfig("", (), "core", specification=path), root / "runs")
    for name, start in runs.items():
        out[name], manifest = start()
        assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    return out


# --- 1. the Summary sheet for any number of scenarios -------------------------------------------

@pytest.mark.req("RPT-05")
@pytest.mark.parametrize("name", ["static", "every"])
def test_summary_charts_stand_clear_of_every_scenario_column(small_runs, name):
    ctx = small_runs[name]
    ws = workbook(ctx)["Summary"]
    top = header_row(ws, "Metric")
    assert set(ctx.scenarios) <= {cell.value for cell in ws[top]}, "one column per scenario"
    used = max(cell.column for row in ws.iter_rows() for cell in row if cell.value is not None)
    assert len(ws._charts) == 2
    for chart in ws._charts:
        # The anchor counts columns from zero, so it lies right of the last used column when
        # it is at least that column's number.
        assert chart.anchor._from.col >= used, f"a chart covers column {get_column_letter(used)}"


# --- 2. the EAD profile on the performing stock -------------------------------------------------

@pytest.mark.req("EAD-05")
def test_ead_profile_reports_the_performing_stock_in_static_and_dynamic_runs(small_runs):
    static, tables = small_runs["static"], small_runs["tables"]
    profile = builders.report(static, "ead_profile.csv")
    # A dynamic run that changes no volume holds the same slices, so it reports the same profile.
    pd.testing.assert_frame_equal(profile, builders.report(small_runs["unchanged"], "ead_profile.csv"), check_exact=True)
    # A bullet book defaults on its balance at the valuation date: bucket 1 is the performing GCA.
    stocks = stage_stocks(static, tables).reset_index()
    performing = stocks[stocks["stage"] < 3].groupby(["scenario", "year", "portfolio"])["gca"].sum()
    first = profile[profile["default_bucket"] == 1].set_index(["scenario", "valuation_year", "portfolio"])["balance"]
    assert len(first) == len(performing)
    for key, balance in first.items():
        assert_close(balance, performing[key], "aggregate", f"bucket-1 balance {key}")
    # What defaulted since the snapshot is no longer in it.
    snapshot = int(tables["parameter_set"]["horizon"]["snapshot_year"])
    by_year = first.groupby(level=["scenario", "valuation_year"]).sum()
    for (scenario, year), balance in by_year.items():
        if year > snapshot:
            assert balance < by_year[(scenario, snapshot)] - tolerance("aggregate")["abs"]


# --- 3. the Stage migration sheet ----------------------------------------------------------------

@pytest.mark.req("MIG-02", "EXP-01")
@pytest.mark.parametrize("name", ["static", "grown"])
def test_stage_sheet_check_is_the_formula_its_subtitle_gives_and_ties(small_runs, name):
    book = workbook(small_runs[name])
    ws = book["Stage migration"]
    top = header_row(ws, "Scenario")
    cols = columns(ws, top)
    opening = {cols[h] for h in cols if h.startswith("Opening")}
    closing = {cols[h] for h in cols if h.startswith("Closing")}
    volume = {cols[h] for h in cols if h.startswith("Volume change")}
    dynamic = name == "grown"
    assert len(opening) == len(closing) == 3
    # Only the performing stages change volume, and only a dynamic run shows the columns.
    assert len(volume) == (2 if dynamic else 0)
    stated = "Check = closing - (opening + volume change)" if dynamic else "Check = closing - opening"
    assert stated in ws["A2"].value
    tie = tolerance("aggregate")["abs"] / MILLION
    moved = 0.0
    rows = records(ws, top)
    assert rows
    for row in rows:
        formula = ws[f"{cols['Check total']}{row}"].value
        assert referenced(formula) == opening | closing | volume, "the check names the stocks it ties"
        assert abs(book.number("Stage migration", f"{cols['Check total']}{row}")) <= tie
        moved += sum(abs(book.number("Stage migration", f"{letter}{row}")) for letter in volume)
    assert (moved > 0) == dynamic
    if dynamic:  # the sheet shows the volume change the run recorded
        recorded = builders.result(small_runs[name], "exposure_movements.parquet")["gca_change"].sum()
        shown = sum(book.number("Stage migration", f"{letter}{row}") for letter in volume for row in rows)
        assert_close(shown * MILLION, recorded, "aggregate", "volume change")


# --- 4. coverage is the on-balance allowance over GCA in every report (A45) ----------------------

@pytest.mark.req("RPT-05")
def test_workbook_coverage_by_stage_is_on_balance_allowance_over_gca(small_runs):
    ctx = small_runs["static"]
    book = workbook(ctx)
    stocks = stage_stocks(ctx, small_runs["tables"])
    ws = book["Coverage by stage"]
    assert "Coverage = on-balance allowance / GCA" in ws["A2"].value
    top = header_row(ws, "Scenario")
    cols = columns(ws, top)
    rows = records(ws, top)
    assert len(rows) == len(stocks)
    off_balance = 0.0
    for row in rows:
        scenario, year, portfolio, stage = (ws[f"{cols[h]}{row}"].value
                                            for h in ("Scenario", "Year", "Portfolio", "Stage"))
        key = (scenario, int(year), portfolio, int(stage.removeprefix("S")))
        cell = stocks.loc[key]
        assert_close(book.number(ws.title, f"{cols['Coverage']}{row}"), ratio(cell["allowance_on"], cell["gca"]),
                     "rate", f"coverage {key}")
        # The off-balance provision stays on the sheet as an amount.
        assert_close(book.number(ws.title, f"{cols['Provision (off)']}{row}") * MILLION, cell["provision_off"],
                     "amount", f"off-balance provision {key}")
        off_balance += cell["provision_off"]
    assert off_balance > 0, "the book holds off-balance provisions, so the two definitions differ"
    # The CSV report carries the same ratio with its parts.
    report = builders.report(ctx, "impairment_by_stage.csv").set_index(STAGE_KEYS)
    for key, cell in stocks.iterrows():
        assert_close(report.loc[key, "coverage_numerator"], cell["allowance_on"], "amount")
        assert_close(report.loc[key, "coverage_denominator"], cell["gca"], "amount")


@pytest.mark.req("RPT-05")
def test_workbook_s3_cohort_coverage_is_on_balance_allowance_over_gca(small_runs):
    ctx = small_runs["static"]
    book = workbook(ctx)
    ws = book["S3 cohorts"]
    top = header_row(ws, "Scenario")
    cols = columns(ws, top)
    cohorts = builders.report(ctx, "s3_cohorts.csv")
    rows = records(ws, top)
    assert len(rows) == len(cohorts)
    for row in rows:
        allowance, gca = (book.number(ws.title, f"{cols[h]}{row}") for h in ("Allowance (on)", "GCA"))
        assert_close(book.number(ws.title, f"{cols['Coverage']}{row}"), ratio(allowance, gca), "rate")
        assert referenced(ws[f"{cols['Coverage']}{row}"].value) == {cols["Allowance (on)"], cols["GCA"]}
    stocks = stage_stocks(ctx, small_runs["tables"]).reset_index()
    assert_close(sum(book.number(ws.title, f"{cols['Allowance (on)']}{row}") for row in rows) * MILLION,
                 stocks.loc[stocks["stage"] == 3, "allowance_on"].sum(), "aggregate", "S3 allowance")


@pytest.mark.req("RPT-05")
@pytest.mark.parametrize("name", ["static", "every"])
def test_results_sheet_and_summary_coverage_are_on_balance_allowance_over_gca(small_runs, name):
    ctx, tables = small_runs[name], small_runs["tables"]
    book = workbook(ctx)
    labels = scenario_labels(tables)
    stocks = stage_stocks(ctx, tables).reset_index()
    ws = book["Results by portfolio"]
    assert "Coverage = on-balance allowance / GCA" in ws["A2"].value
    top = header_row(ws, "Portfolio")
    cols = grouped_columns(ws, top)
    rows = records(ws, top)
    last = max(int(ws[f"B{row}"].value) for row in rows)
    for scenario in ctx.scenarios:
        group = labels[scenario]
        closing = {}
        for row in rows:
            book_name, year = ws[f"A{row}"].value, int(ws[f"B{row}"].value)
            part = stocks[(stocks["scenario"] == scenario) & (stocks["year"] == year)]
            part = part if book_name == "Total" else part[part["portfolio"] == book_name]
            where = f"{scenario} {book_name} {year}"

            def shown(header, row=row, group=group):
                return book.number(ws.title, f"{cols[(group, header)]}{row}")

            assert_close(shown("Coverage"), ratio(part["allowance_on"].sum(), part["gca"].sum()), "rate",
                         f"coverage {where}")
            assert_close(shown("Allowance (on)") * MILLION, part["allowance_on"].sum(), "aggregate", where)
            assert_close(shown("Provision (off)") * MILLION, part["provision_off"].sum(), "aggregate", where)
            assert_close(shown("Provisions"), shown("Allowance (on)") + shown("Provision (off)"), "rate", where)
            if book_name == "Total" and year == last:
                closing = part[["gca", "allowance_on", "provision_off"]].sum()
        # The Summary sheet gives the same coverage, and both parts of the closing provisions.
        summary = book["Summary"]
        head = header_row(summary, "Metric")
        letter = next(cell.column_letter for cell in summary[head] if cell.value == scenario)
        metric = {str(row[0].value).strip(): row[0].row for row in summary.iter_rows(min_row=head + 1, max_col=1)
                  if row[0].value is not None}

        def figure(start, letter=letter, metric=metric):
            row = next(r for label, r in metric.items() if label.startswith(start))
            return book.number("Summary", f"{letter}{row}")

        assert f"Coverage {last} (on-balance allowance / GCA)" in metric
        assert_close(figure("Coverage"), ratio(closing["allowance_on"], closing["gca"]), "rate",
                     f"summary coverage {scenario}")
        assert_close(figure("of which on-balance allowance") * MILLION, closing["allowance_on"], "aggregate")
        assert_close(figure("of which off-balance provision") * MILLION, closing["provision_off"], "aggregate")
        assert_close(figure("Closing provisions") * MILLION, closing["allowance_on"] + closing["provision_off"],
                     "aggregate")
    notes = {row[0].value: row[1].value for row in book["Notes"].iter_rows(max_col=2) if row[0].value}
    assert notes["Coverage"].startswith("On-balance allowance / GCA")


@pytest.mark.req("RPT-05")
def test_portfolios_sheet_opening_coverage_is_on_balance_allowance_over_gca(small_runs):
    ctx = small_runs["static"]
    book = workbook(ctx)
    ws = book["Portfolios"]
    top = header_row(ws, "Portfolio")
    cols = columns(ws, top)
    snapshot = int(small_runs["tables"]["parameter_set"]["horizon"]["snapshot_year"])
    stocks = stage_stocks(ctx, small_runs["tables"]).reset_index()
    opening = stocks[(stocks["scenario"] == "baseline") & (stocks["year"] == snapshot)]
    rows = records(ws, top)
    assert [ws[f"A{row}"].value for row in rows][-1] == "Total"
    for row in rows:
        name = ws[f"A{row}"].value
        part = opening if name == "Total" else opening[opening["portfolio"] == name]
        assert_close(book.number(ws.title, f"{cols['Opening coverage']}{row}"),
                     ratio(part["allowance_on"].sum(), part["gca"].sum()), "rate", f"opening coverage {name}")
        assert_close(book.number(ws.title, f"{cols['Opening provision (off)']}{row}") * MILLION,
                     part["provision_off"].sum(), "aggregate", f"opening off-balance provision {name}")


# --- 5. SICR attribution by trigger flag ---------------------------------------------------------

@pytest.mark.req("MIG-05", "RPT-05")
def test_sicr_attribution_keys_on_whether_days_past_due_reach_the_trigger(core_run, full_tables):
    ctx, _ = core_run
    days = full_tables["parameter_set"]["sicr_triggers"]["dpd_days"]
    table = builders.report(ctx, "analysis_sicr_attribution.csv")
    flag = "(True|False)"
    assert table["flags"].str.fullmatch(f"dpd_at_least_{days}={flag};watchlist={flag};forborne={flag}").all()
    assert table.groupby(["scenario", "year", "trigger"]).size().max() <= 2 ** 3, "three flags, eight combinations"
    # The S2 exposure by combination, recomputed from the slices and the facilities' own flags.
    facts = full_tables["facilities"][["facility_id", "dpd", "watchlist", "forborne"]]
    s2 = builders.result(ctx, "slices.parquet")
    s2 = s2[s2["stage"] == 2].merge(facts, on="facility_id", validate="many_to_one")
    s2["flags"] = (f"dpd_at_least_{days}=" + (s2["dpd"] >= days).astype(str) + ";watchlist="
                   + s2["watchlist"].astype(bool).astype(str) + ";forborne=" + s2["forborne"].astype(bool).astype(str))
    keys = ["scenario", "year", "flags"]
    expected = s2.groupby(keys)["gca"].sum()
    reported = table.groupby(keys)["gca"].sum()
    assert set(reported.index) == set(expected.index)
    for key, gca in reported.items():
        assert_close(gca, expected[key], "aggregate", f"S2 GCA {key}")
    assert s2["dpd"].nunique() > 2 ** 3, "the book holds more distinct day counts than combinations"


# --- 6. segment models at rate precision ---------------------------------------------------------

@pytest.mark.req("MOD-01")
def test_segment_models_report_keeps_sensitivities_at_rate_precision(mini, tmp_path):
    # Sensitivities with more than two decimals: w = 1/7 and v = 1/9 for one segment.
    builders.neutral(mini, "P03", lgd_w=1 / 7, cpr_v=1 / 9)
    ctx, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    models = builders.report(ctx, "segment_models.csv")
    stated = models[models["sensitivity"].notna()]
    assert set(stated["model"]) == {LGD, PREPAYMENT}, "a PD model has no sensitivity of its own"
    for row in stated.itertuples(index=False):
        assert_close(row.sensitivity, REGISTRY[row.name].sensitivity, "rate", f"{row.segment} {row.model}")


# --- 7. converted commitments say which CCF they use ---------------------------------------------

@pytest.mark.req("EAD-06")
@pytest.mark.parametrize("variant", ["core", "utilisation"])
def test_converted_commitments_are_shown_at_the_input_and_the_applied_ccf(reference_runs, variant):
    ctx, _ = reference_runs[variant]
    tables = builders.load(reference_runs["inputs"])
    commitments = tables["commitments"].merge(tables["facilities"][["facility_id", "portfolio"]], on="facility_id")
    at_input = (commitments["nominal_undrawn"] * commitments["accounting_ccf"]).groupby(commitments["portfolio"]).sum()
    books = builders.report(ctx, "static_books.csv")
    opening = books[(books["year"] == books["year"].min()) & (books["scenario"] == "baseline")]
    applied = opening.set_index("portfolio")["converted"]
    start = builders.report(ctx, "starting_point_reconciliation.csv")
    totals = start[start["stage"] == "all"].set_index("portfolio")
    book = workbook(ctx)
    ws = book["Portfolios"]
    top = header_row(ws, "Portfolio")
    cols = columns(ws, top)
    sheet = {ws[f"A{row}"].value: row for row in records(ws, top)}
    for portfolio in totals.index:
        expected = at_input.get(portfolio, 0.0)
        assert_close(totals.loc[portfolio, "converted_commitments"], expected, "aggregate", portfolio)
        assert_close(totals.loc[portfolio, "converted_commitments_applied_ccf"], applied[portfolio], "aggregate",
                     portfolio)
        row = sheet[portfolio]
        assert_close(book.number(ws.title, f"{cols['Converted commitments (input-set CCF)']}{row}") * MILLION,
                     expected, "aggregate", portfolio)
        assert_close(book.number(ws.title, f"{cols['Converted commitments (applied CCF)']}{row}") * MILLION,
                     applied[portfolio], "aggregate", portfolio)
    # Only a variant that overrides the CCF makes the two differ; each place names the CCF it uses.
    differs = abs(applied.sum() - at_input.sum()) > tolerance("aggregate")["abs"]
    assert differs == (variant == "utilisation")
    assert f"the CCF the run applied (variant {variant})" in ws["A2"].value
    assert any(f"Converted at the CCF the run applied (variant {variant})" in line for line in summary_of(ctx))


# --- 8. summary.md -------------------------------------------------------------------------------

def _tables_of(lines: list[str]) -> dict[str, list[list[str]]]:
    """The data rows of each section's table, by heading."""
    out, heading = {}, None
    for line in lines:
        if line.startswith("## "):
            heading = line[3:]
        elif line.startswith("| ") and not line.startswith("| Scenario") and heading:
            out.setdefault(heading, []).append([cell.strip() for cell in line.strip("|").split("|")])
    return out


@pytest.mark.req("OPS-01")
def test_summary_lists_the_reports_written_and_keeps_one_scenario_order(small_runs):
    ctx, tables = small_runs["every"], small_runs["tables"]
    lines = summary_of(ctx)
    listed = next(line for line in lines if line.startswith("Reports in this folder"))
    written = {path.name for path in ctx.reports_dir.iterdir()}
    assert set(re.findall(r"[\w.+-]+\.(?:csv|json|xlsx|md)", listed)) == written
    assert WORKBOOK_FILE in written and SUMMARY_FILE in written
    # The headline's order of scenarios is the order of every table.
    headline = [line[2:].split(":")[0] for line in lines if line.startswith("- ") and "cumulative charge" in line]
    assert headline[0] == "baseline" and set(headline) == set(ctx.scenarios)
    sections = _tables_of(lines)
    assert len(sections) == 3
    for heading, rows in sections.items():
        assert list(dict.fromkeys(row[0] for row in rows)) == headline, heading
    # The books table starts at the snapshot, and its heading says so.
    horizon = tables["parameter_set"]["horizon"]
    heading, rows = next((h, r) for h, r in sections.items() if "books" in h)
    assert {int(row[1]) for row in rows} == {int(horizon["snapshot_year"]), *map(int, horizon["projection_years"])}
    assert "starting point and each projected year" in heading


@pytest.mark.req("OPS-01")
def test_summary_and_workbook_name_the_run_specification(small_runs):
    doc = small_runs["specifications"]["grown"]
    ctx = small_runs["grown"]
    named = f"run specification \"{doc['source']}\", version {doc['version']}"
    intro = summary_of(ctx)[2]
    assert named in intro and ctx.config.specification_hash[:16] in intro
    assert "specification" not in summary_of(small_runs["static"])[2]
    info = {row[0].value: row[1].value for row in workbook(ctx)["Summary"].iter_rows(max_col=2) if row[0].value}
    assert info["Run specification"] == f"{doc['source']}, version {doc['version']}"
    plain = {row[0].value for row in workbook(small_runs["static"])["Summary"].iter_rows(max_col=1)}
    assert "Run specification" not in plain


# --- 9. the effective specification --------------------------------------------------------------

@pytest.mark.req("OPS-01", "GOV-02")
def test_effective_specification_lists_the_segment_model_conflict(small_runs):
    ctx = small_runs["static"]
    doc = json.loads((ctx.reports_dir / "effective_specification.json").read_text(encoding="utf-8"))
    listed = doc["known_methodology_conflicts"]
    recorded = set(re.findall(r"^\| (C\d+) \|", (ROOT / "docs" / "assumptions.md").read_text(encoding="utf-8"),
                              flags=re.MULTILINE))
    assert set(listed) <= recorded and len(set(listed)) == len(listed)
    # C20: each segment's own PD, LGD and prepayment model against SCN-08's one Z.
    assert "C20" in listed


# --- 10. scenario labels in the workbook's group headers -----------------------------------------

@pytest.mark.req("SCN-01", "RPT-05")
def test_workbook_group_headers_show_scenario_labels(small_runs):
    labels = scenario_labels(small_runs["tables"])
    assert all(label != name for name, label in labels.items())
    ws = workbook(small_runs["every"])["Results by portfolio"]
    top = header_row(ws, "Portfolio")
    assert {cell.value for cell in ws[top - 1] if cell.value} == set(labels.values())
    parameters = workbook(small_runs["every"])["Parameters"]
    shown = [cell.value for row in parameters.iter_rows() for cell in row if cell.value is not None]
    for name, label in labels.items():
        assert shown.count(label) == 2, "the PD and the LGD table each head a group with the label"
        # The id stays where it is data: the Scenario column of the Z table.
        assert all(cell.column_letter == "C" for row in parameters.iter_rows() for cell in row
                   if cell.value == name)
    # With two scenarios the comparison group is named by the same labels.
    ws = workbook(small_runs["static"])["Results by portfolio"]
    groups = {cell.value for cell in ws[header_row(ws, "Portfolio") - 1] if cell.value}
    assert groups == {labels["baseline"], labels["adverse"], f"{labels['adverse']} - {labels['baseline']}"}
