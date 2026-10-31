"""Selectable readings of the draft (C14, C15): the default stays the design's, and a selected
reading changes what it should and nothing else."""

import argparse
import importlib.util

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

from stress import cli
from stress.cashflows import build_schedules
from stress.contracts.errors import Block, BlockingError
from stress.contracts.run import LGD_TROUGH, RUNOFF_REPLACED, S2_HELD, RunConfig
from stress.contracts.tables import METHOD_S2_HELD, ROUTE_PERFORMING, SLICES
from stress.ecl import hold_s2
from stress.projection import project_year
from stress.report import WORKBOOK_FILE, ecl_bridge
from tests import builders
from tests.support import ROOT, tolerance


def execute(inputs, runs, **options):
    ctx, manifest = cli.execute(RunConfig(str(inputs), ("baseline", "adverse"), "core", **options), runs)
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    return ctx, manifest


def impairment(ctx) -> pd.DataFrame:
    table = builders.report(ctx, "impairment.csv")
    return table[table["portfolio"] == "Total"].set_index(["scenario", "year"])


def stock(ctx, stage) -> pd.Series:
    slices = builders.result(ctx, "slices.parquet")
    return slices[slices["stage"] == stage].groupby(["scenario", "year"])["allowance_on"].sum()


@pytest.fixture(scope="module")
def default_run(mini_tables, tmp_path_factory):
    root = tmp_path_factory.mktemp("readings")
    inputs = builders.write(builders.copy_tables(mini_tables), root / "inputs")
    return inputs, root, execute(inputs, root / "default")[0]


@pytest.mark.req("ECL-06")
def test_what_stayed_in_s2_keeps_its_allowance_and_only_the_inflow_is_priced():
    perf = pd.DataFrame({"facility_id": ["F", "G", "R"], "grade": ["G5", "G1", "G5"], "stage": [2, 1, 2],
                         "replaced": [False, False, True], "gca": [100.0, 50.0, 100.0], "undrawn": [10.0, 0.0, 0.0],
                         "raw_on": [12.0, 1.0, 12.0], "raw_off": [1.0, 0.0, 0.0], "allowance_on": [12.0, 1.0, 12.0],
                         "provision_off": [1.0, 0.0, 0.0], "method": "s"})
    stayers = pd.DataFrame({"facility_id": ["F", "R"], "grade": ["G5", "G5"], "stayed_gca": [60.0, 60.0],
                            "stayed_undrawn": [5.0, 0.0], "stayed_on": [6.0, 6.0], "stayed_off": [0.5, 0.0]})
    hold_s2(perf, stayers)
    held = perf.set_index("facility_id")
    assert held.loc["F", "allowance_on"] == pytest.approx(6.0 + 0.4 * 12.0)
    assert held.loc["F", "provision_off"] == pytest.approx(0.5 + 0.5 * 1.0)
    assert held.loc["F", "raw_on"] == 12.0 and held.loc["F", "method"] == METHOD_S2_HELD
    assert held.loc["G", "allowance_on"] == 1.0, "S1 is not held"
    assert held.loc["R", "allowance_on"] == 12.0 and held.loc["R", "method"] == "s", "a replacement is valued afresh"


@pytest.mark.req("ECL-06")
def test_the_allowance_moves_with_the_exposure_through_the_matrix():
    grades = ("G1", "G2")
    portfolio = pd.DataFrame({
        "facility_id": ["F"], "route": [ROUTE_PERFORMING], "sicr_rank": [2], "qualitative_trigger": [False],
        "segment": ["P03"], "country": ["DE"], "origination_grade": ["G1"], "portfolio": ["P03"]})
    previous = pd.DataFrame({
        "scenario": "adverse", "year": 2027, "facility_id": ["F"], "slice": ["G2"], "stage": [2], "grade": ["G2"],
        "origination_grade": ["G1"], "entry_year": [np.nan], "origin_stage": [np.nan], "gca": [100.0],
        "undrawn": [10.0], "allowance_on": [20.0], "provision_off": [2.0], "generation": [0], "replaced": [False]})
    cells = [("G1", "G1", 1.0), ("G1", "G2", 0.0), ("G1", "D", 0.0), ("G2", "G1", 0.2), ("G2", "G2", 0.7), ("G2", "D", 0.1)]
    pit = pd.DataFrame([{"segment": "P03", "country": "DE", "from_grade": a, "to_grade": b, "probability": p}
                        for a, b, p in cells])
    moved = project_year(SLICES.check(previous, "test"), pit, portfolio, grades, 2028, "adverse",
                         pd.Series({"F": 0}), tolerance("aggregate"), track_s2=True)
    stayed = moved.s2_stayers.set_index("grade")
    assert list(stayed.index) == ["G2"], "what moved to S1 or into default is not an S2 stayer"
    assert stayed.loc["G2", "stayed_gca"] == pytest.approx(70.0)
    assert stayed.loc["G2", "stayed_on"] == pytest.approx(14.0)
    assert stayed.loc["G2", "stayed_off"] == pytest.approx(1.4)


@pytest.mark.req("ECL-06")
def test_held_s2_changes_only_s2_after_the_first_year(default_run, tmp_path):
    inputs, _, base = default_run
    ctx, _ = execute(inputs, tmp_path, s2_treatment=S2_HELD)
    assert np.allclose(stock(ctx, 1), stock(base, 1), rtol=1e-12), "S1 does not move"
    assert np.allclose(stock(ctx, 3), stock(base, 3), rtol=1e-12), "S3 does not move"
    held, repriced = stock(ctx, 2), stock(base, 2)
    assert np.allclose(held.xs(2027, level="year"), repriced.xs(2027, level="year"), rtol=1e-12), (
        "the first year books the scenario with perfect foresight")
    first = builders.result(base, "slices.parquet")
    now = builders.result(ctx, "slices.parquet")
    assert first["gca"].sum() == pytest.approx(now["gca"].sum()), "stages and exposure do not move"
    provisions = builders.result(ctx, "provisions.parquet")
    assert provisions.loc[provisions["year"] == 2027, "method"].ne(METHOD_S2_HELD).all()
    assert provisions.loc[provisions["year"] > 2027, "method"].eq(METHOD_S2_HELD).any()
    original = builders.result(base, "provisions.parquet")
    keys = ["scenario", "year", "facility_id", "slice"]
    raw = provisions.merge(original, on=keys, suffixes=("", "_default"))
    assert np.allclose(raw["raw_on"], raw["raw_on_default"], rtol=1e-12), "raw stays the lifetime ECL"
    assert "S2 treatment held" in (ctx.reports_dir / "summary.md").read_text(encoding="utf-8")
    assert "Selected method" not in (base.reports_dir / "summary.md").read_text(encoding="utf-8")


@pytest.mark.req("OPS-04")
def test_notebooks_read_the_selected_reading_from_the_configuration():
    spec = importlib.util.spec_from_file_location("nbtools", ROOT / "notebooks" / "nbtools.py")
    nbtools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nbtools)
    older = {"inputs": "i", "scenarios": ["baseline"], "variant": "core", "mode": "synthetic"}
    assert nbtools._selected(older) == "", "a manifest from before the options is the default"
    assert nbtools._selected({**older, "s2_treatment": S2_HELD, "unknown_key": 1}) == S2_HELD


@pytest.mark.control("Reproducibility")
def test_a_selected_reading_reruns_from_its_manifest(default_run, tmp_path):
    inputs, _, _ = default_run
    ctx, _ = execute(inputs, tmp_path, s2_treatment=S2_HELD, horizon_runoff=RUNOFF_REPLACED, lgd_path=LGD_TROUGH)
    args = argparse.Namespace(run=str(ctx.run_dir), runs_dir=str(tmp_path / "replays"))
    assert cli.cmd_rerun(args) == cli.EXIT_OK


@pytest.mark.req("OPS-04")
def test_a_selected_run_cannot_be_read_as_the_core_run(default_run, tmp_path):
    inputs, _, base = default_run
    ctx, manifest = execute(inputs, tmp_path, s2_treatment=S2_HELD, horizon_runoff=RUNOFF_REPLACED)
    assert "-core+held+replaced-" in ctx.run_id and "+" not in base.run_id
    assert any("Selected method" in line and "S2 treatment held" in line for line in manifest["summary"]["headline"])
    assert "horizon run-off replaced" in (ctx.reports_dir / "summary.md").read_text(encoding="utf-8")
    book = load_workbook(ctx.reports_dir / WORKBOOK_FILE)
    cells = {str(cell.value) for sheet in book.worksheets for line in sheet.iter_rows() for cell in line}
    assert any("selected method" in text and "S2 treatment held" in text for text in cells)
    assert any("no run-off inside the horizon" in text for text in cells)
    assert any("plus the held S2 amount" in text for text in cells)
    readiness = builders.report(ctx, "analysis_readiness.csv").set_index("gate")
    assert readiness.loc["s2_treatment", "state"] == S2_HELD


@pytest.mark.req("OPS-04")
@pytest.mark.parametrize("option, words", [({"lgd_path": LGD_TROUGH}, "worst Z"),
                                           ({"terminal_treatment": "parameters"},
                                            "PD and LGD revert linearly, and Z still drives prepayment")])
def test_the_checks_sheet_names_a_reading_that_changes_its_rows(default_run, tmp_path, option, words):
    inputs, _, _ = default_run
    ctx, _ = execute(inputs, tmp_path, **option)
    checks = load_workbook(ctx.reports_dir / WORKBOOK_FILE)["Checks"]
    rows = [[str(cell.value) for cell in row] for row in checks.iter_rows()]
    assert {row[0] for row in rows if any(words in cell for cell in row)} == {"R4", "R6"}


@pytest.mark.req("OPS-01")
@pytest.mark.parametrize("option", [{"s2_treatment": "hold"}, {"horizon_runoff": "replacedd"}, {"lgd_path": "trough2"}])
def test_an_unknown_reading_blocks_at_r1(default_run, tmp_path, option):
    inputs, _, _ = default_run
    with pytest.raises(BlockingError) as caught:
        cli.execute(RunConfig(str(inputs), ("baseline", "adverse"), "core", **option), tmp_path)
    assert caught.value.code == Block.INVALID_ARGUMENT
    assert not list(tmp_path.iterdir()), "no run folder is opened"


@pytest.mark.req("ECL-09")
def test_buckets_and_the_held_amount_tie_to_the_booked_provisions(default_run, tmp_path):
    inputs, _, base = default_run
    ctx, _ = execute(inputs, tmp_path, s2_treatment=S2_HELD)
    held = builders.report(ctx, "analysis_ecl_bridge.csv")
    tol = tolerance("aggregate")
    assert np.allclose(held["ecl_on"] + held["held_on"], held["allowance_on"], rtol=tol["rel"], atol=tol["abs"])
    assert np.allclose(held["ecl_off"] + held["held_off"], held["provision_off"], rtol=tol["rel"], atol=tol["abs"])
    assert (held.loc[held["year"] <= 2027, ["held_on", "held_off"]] == 0).all().all()
    assert held.loc[held["year"] > 2027, "held_on"].abs().gt(0).any()
    default = builders.report(base, "analysis_ecl_bridge.csv")
    assert len(default) and (default[["held_on", "held_off"]] == 0).all().all()


@pytest.mark.req("ECL-09")
def test_a_performing_slice_may_differ_from_raw_only_when_held():
    excess = 2 * tolerance("amount")["abs"]
    provisions = pd.DataFrame({"scenario": "adverse", "year": 2028, "stage": 2, "method": ["s2_lifetime"],
                               "raw_on": [10.0], "raw_off": [0.0], "allowance_on": [10.0 + excess], "provision_off": [0.0]})
    buckets = pd.DataFrame({"scenario": "adverse", "valuation_year": 2028, "ecl_on": [10.0], "ecl_off": [0.0]})
    results = {"provisions": provisions, "ecl_buckets": buckets}
    with pytest.raises(BlockingError, match="raw value"):
        ecl_bridge(results, tolerance("aggregate"), tolerance("amount"))
    ok = ecl_bridge({**results, "provisions": provisions.assign(method=METHOD_S2_HELD)}, tolerance("aggregate"),
                    tolerance("amount"))
    assert ok["held_on"].iloc[0] == pytest.approx(excess)


@pytest.mark.req("ECL-09")
def test_a_year_with_no_buckets_blocks_rather_than_drops_out():
    provisions = pd.DataFrame({"scenario": "adverse", "year": [2027, 2028], "stage": 2, "method": "s2_lifetime",
                               "raw_on": [10.0, 10.0], "raw_off": [0.0, 0.0], "allowance_on": [10.0, 10.0],
                               "provision_off": [0.0, 0.0]})
    buckets = pd.DataFrame({"scenario": "adverse", "valuation_year": [2027], "ecl_on": [10.0], "ecl_off": [0.0]})
    for table in (buckets, buckets.iloc[:0]):
        with pytest.raises(BlockingError, match="every scenario and year"):
            ecl_bridge({"provisions": provisions, "ecl_buckets": table}, tolerance("aggregate"), tolerance("amount"))


@pytest.mark.req("ECL-03")
@pytest.mark.parametrize("variant", ["annuity", "linear"])
def test_replaced_blocks_where_it_would_still_amortise(default_run, tmp_path, variant):
    inputs, _, _ = default_run
    config = RunConfig(str(inputs), ("baseline", "adverse"), variant, horizon_runoff=RUNOFF_REPLACED)
    _, manifest = cli.execute(config, tmp_path)
    assert manifest["status"] == "BLOCKED" and manifest["blocked"]["code"] == Block.INVALID_ARGUMENT
    assert "amortisation" in manifest["blocked"]["message"]


@pytest.mark.req("ECL-03")
def test_no_facility_runs_off_inside_the_horizon_when_replaced(mini):
    ps = mini["parameter_set"]
    portfolio = pd.DataFrame({
        "facility_id": ["F"], "route": [ROUTE_PERFORMING], "product": ["revolver"], "accrued_in_gca": [True],
        "gca": [100.0], "principal": [100.0], "accrued_interest": [0.0], "interest_rate": [0.05],
        "residual_maturity": [1.5]})
    contractual = build_schedules(portfolio, ps, "core")
    replaced = build_schedules(portfolio, ps, "core", RUNOFF_REPLACED)
    rest = replaced.groupby("valuation_year")["remaining_maturity"].first()
    last = ps["terminal_rule"]["last_scenario_year"]
    assert (rest.index + rest >= last).all(), "every valuation date reaches the end of the horizon"
    assert contractual.groupby("valuation_year")["remaining_maturity"].first().loc[2026] == 1.5
    assert rest.loc[2026] == last - 2026


@pytest.mark.req("ECL-03")
def test_run_off_only_moves_the_timing_of_the_charge(default_run, tmp_path):
    inputs, _, base = default_run
    ctx, _ = execute(inputs, tmp_path, horizon_runoff=RUNOFF_REPLACED)
    params = builders.result(ctx, "parameters.parquet")
    inside = params[params["bucket_year"] <= 2029]
    assert inside["prepayment_rate"].eq(0).all()
    assert params.loc[params["bucket_year"] > 2029, "prepayment_rate"].gt(0).any()
    a, b = impairment(base), impairment(ctx)
    assert np.allclose(a.xs(2029, level="year")["cumulative_charge"], b.xs(2029, level="year")["cumulative_charge"],
                       rtol=1e-6, atol=1.0), "no horizon slice is left at the end-2029 valuation"
    assert not np.allclose(a.xs(2027, level="year")["charge_total"], b.xs(2027, level="year")["charge_total"],
                           rtol=1e-6)
