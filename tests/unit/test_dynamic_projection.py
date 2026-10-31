"""Dynamic volume assumptions affect stock and ECL, with explicit exposure bridges."""

import pandas as pd
import pytest

from stress.cli import execute
from stress.contracts.run import RunConfig
from tests import builders
from tests.unit.test_specification import specification, write_spec


def assumptions(tables, change):
    years = tables["parameter_set"]["horizon"]["projection_years"]
    return [{"scenario": scenario, "year": year, "portfolio": portfolio,
             "drawn_change": change if scenario == "adverse" else 0.0,
             "undrawn_change": change if scenario == "adverse" else 0.0}
            for scenario in ("baseline", "adverse") for year in years
            for portfolio in sorted(tables["facilities"].portfolio.unique())]


@pytest.mark.req("EXP-01", "MIG-02", "ACC-01", "ECL-09")
@pytest.mark.parametrize("change", [-0.2, 0.15, 0.0])
def test_dynamic_volume_reconciles_and_leaves_baseline_unchanged(mini, tmp_path, change):
    inputs = builders.write(mini, tmp_path / "inputs")
    static, manifest = builders.run(inputs, tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC"
    doc = specification(inputs, balance_sheet={"assumptions": assumptions(mini, change)})
    doc["run"]["balance_sheet"] = "dynamic"
    ctx, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                            tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    dynamic = builders.result(ctx, "slices.parquet")
    original = builders.result(static, "slices.parquet")
    pd.testing.assert_frame_equal(dynamic[dynamic.scenario == "baseline"].reset_index(drop=True),
                                  original[original.scenario == "baseline"].reset_index(drop=True))
    moves = builders.result(ctx, "exposure_movements.parquet")
    delta = moves.loc[moves.scenario == "adverse", "gca_change"]
    assert (delta >= 0).all() if change >= 0 else (delta <= 0).all()
    if change == 0:
        pd.testing.assert_frame_equal(dynamic, original)
    stock = dynamic[dynamic.scenario == "adverse"].groupby("year").gca.sum()
    for year in sorted(stock.index)[1:]:
        delta = moves[(moves.scenario == "adverse") & (moves.year == year)].gca_change.sum()
        assert stock[year] == pytest.approx(stock[year - 1] + delta)
    s3 = dynamic[dynamic.slice == "S3_orig"].groupby(["scenario", "year"]).gca.sum()
    assert s3.groupby(level=0).nunique().eq(1).all()
    assert (ctx.reports_dir / "exposure_movements.csv").exists()
    assert not (ctx.reports_dir / "analysis_template_replica.csv").exists()


@pytest.mark.req("EAD-08", "ACC-01")
def test_undrawn_volume_changes_only_off_balance_losses(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    reference, result = builders.run(inputs, tmp_path / "runs")
    assert result["status"] == "SYNTHETIC"
    rows = assumptions(mini, 0.0)
    for row in rows:
        row["undrawn_change"] = 0.5
    doc = specification(inputs, balance_sheet={"assumptions": rows})
    doc["run"]["balance_sheet"] = "dynamic"
    current, result = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                              tmp_path / "runs")
    assert result["status"] == "SYNTHETIC", result.get("blocked")
    old, new = [builders.result(ctx, "charges.parquet") for ctx in (reference, current)]
    pd.testing.assert_series_equal(old.charge_on, new.charge_on)
    assert new.closing_off.sum() > old.closing_off.sum()


@pytest.mark.req("EXP-01")
def test_dynamic_missing_assumption_blocks(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    rows = assumptions(mini, 0.1)
    rows.pop()
    doc = specification(inputs, balance_sheet={"assumptions": rows})
    doc["run"]["balance_sheet"] = "dynamic"
    _, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                          tmp_path / "runs")
    assert manifest["status"] == "BLOCKED"
    assert manifest["blocked"]["code"] == "INVALID_SPECIFICATION"


@pytest.mark.req("EXP-01", "ACC-01", "RPT-05")
@pytest.mark.parametrize("whole_book", [False, True])
def test_complete_runoff_retains_explicit_zero_portfolio(mini, tmp_path, whole_book):
    # Keep P03 performing only; its entire drawn and undrawn stock can then run off.
    drop = (mini["facilities"].portfolio.eq("P03") | whole_book) & mini["facilities"].ifrs_stage.eq(3)
    removed = set(mini["facilities"].loc[drop, "facility_id"])
    for name in ("facilities", "commitments", "opening_provisions"):
        mini[name] = mini[name].loc[~mini[name].facility_id.isin(removed)].copy()
    inputs = builders.write(mini, tmp_path / "inputs")
    rows = assumptions(mini, 0.0)
    for row in rows:
        if (row["portfolio"] == "P03" or whole_book) and row["scenario"] == "adverse":
            row.update(drawn_change=-1.0, undrawn_change=-1.0)
    doc = specification(inputs, balance_sheet={"assumptions": rows})
    doc["run"]["balance_sheet"] = "dynamic"
    ctx, manifest = execute(RunConfig("", (), "core", specification=write_spec(tmp_path / "job.yaml", doc)),
                            tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    books = pd.read_csv(ctx.reports_dir / "dynamic_books.csv")
    empty = books[(books.portfolio == "P03") & (books.scenario == "adverse") & (books.year > 2026)]
    assert set(empty.year) == {2027, 2028, 2029}
    assert empty[["gca", "undrawn", "converted"]].eq(0).all().all()
    stocks = pd.read_csv(ctx.reports_dir / "impairment_by_stage.csv")
    empty = stocks[(stocks.portfolio == "P03") & (stocks.scenario == "adverse") & (stocks.year > 2026)]
    assert len(empty) == 9
    assert empty[["gca", "undrawn", "allowance_on", "provision_off"]].eq(0).all().all()
