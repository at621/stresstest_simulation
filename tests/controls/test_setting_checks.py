"""Section 12.2 controls on settings: a wrong setting in the parameter set, a matrix file or a run
specification stops the run with a block code. It never seals a run with other numbers than the
setting's name promises, and it never ends as an engine fault."""

import ast
import json

import pandas as pd
import pytest
import yaml

from stress.cli import EXIT_NOT_REPRODUCED, EXIT_OK, execute, main
from stress.contracts.errors import RUN_BLOCKING_REASONS, Block, BlockingError, Reason
from stress.contracts.run import RunConfig
from stress.report.template import TEMPLATE_CLASS
from tests import builders
from tests.support import ROOT

CODES = {str(code) for code in (*Block, *Reason)}


def blocked(mini, tmp_path, **kw) -> dict:
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs", **kw)
    assert manifest["status"] == "BLOCKED", "the run must block"
    return manifest["blocked"]


def specification(inputs, tmp_path, **sections) -> RunConfig:
    """A run specification on ``inputs``, written beside it."""
    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    run = {"inputs": str(inputs), "scenarios": ["baseline", "adverse"], **sections.pop("run", {})}
    doc = {"schema_version": 1, "status": "SYNTHETIC", "source": "setting-check test", "version": "test-v1",
           "input_set_hash": manifest["input_set_hash"], "run": run, **sections}
    path = tmp_path / "job.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return RunConfig("", (), "core", specification=str(path))


# --- a variant's settings (EAD-04, EAD-10) ------------------------------------------------------

@pytest.mark.control("EAD/CCF contract")
def test_a_variant_ccf_for_a_segment_the_run_does_not_know_blocks(mini, tmp_path):
    """A misspelt segment under a variant's ccf would otherwise seal a run named for the variant
    with the commitments' own CCF."""
    variant = mini["parameter_set"]["variants"]["utilisation"]
    wrong = {f"{segment} ": value for segment, value in variant["ccf"].items()}
    variant["ccf"] = wrong
    b = blocked(mini, tmp_path, variant="utilisation")
    assert (b["step"], b["code"]) == ("R3", Block.UNKNOWN_VARIANT)
    assert all(repr(segment) in b["message"] for segment in wrong), b["message"]


@pytest.mark.control("EAD/CCF contract")
def test_a_new_segment_takes_its_parents_variant_ccf(mini, tmp_path):
    """A specification that files a segment's facilities under a new segment changes no CCF: the
    new segment inherits the parent's override in every variant."""
    inputs = builders.write(mini, tmp_path / "in")
    plain, manifest = builders.run(inputs, tmp_path / "plain", variant="utilisation")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    variant = mini["parameter_set"]["variants"]["utilisation"]["ccf"]
    parent = next(iter(variant))
    config = specification(inputs, tmp_path, run={"variant": "utilisation"},
                           segments={"CARVED": {"inherits": parent, "template_class": TEMPLATE_CLASS[parent]}},
                           assignments=[{"where": {"segment": parent}, "segment": "CARVED"}])
    carved, manifest = execute(config, tmp_path / "carved")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    keys = ["facility_id", "scenario", "year"]
    before = builders.result(plain, "lgd_of_year.parquet").sort_values(keys).reset_index(drop=True)
    after = builders.result(carved, "lgd_of_year.parquet").sort_values(keys).reset_index(drop=True)
    assert before["ccf"].notna().any(), "the book has commitments the variant converts"
    pd.testing.assert_series_equal(after["ccf"], before["ccf"])
    charges = [builders.result(run, "charges.parquet").sort_values(keys).reset_index(drop=True)
               for run in (plain, carved)]
    pd.testing.assert_frame_equal(charges[1], charges[0])
    effective = json.loads((carved.reports_dir / "effective_specification.json").read_text(encoding="utf-8"))
    applied = effective["parameter_set"]["variants"]["utilisation"]["ccf"]
    assert applied["CARVED"] == applied[parent] == variant[parent]


# --- a specification's SICR multiple (MIG-07) ---------------------------------------------------

def _grade_explained_s2(mini, segment) -> pd.Series:
    """The segment's Stage 2 facilities that no qualitative trigger holds there: only the SICR
    line explains their stage."""
    fac = mini["facilities"]
    days = mini["parameter_set"]["sicr_triggers"]["dpd_days"]
    flagged = (fac["dpd"] >= days) | fac["watchlist"].eq(True) | fac["forborne"].eq(True)
    return fac.loc[(fac["segment"] == segment) & (fac["ifrs_stage"] == 2) & ~flagged, "facility_id"]


@pytest.mark.control("Grade and stage")
def test_a_sicr_multiple_that_contradicts_reported_stages_blocks(mini, tmp_path):
    """Owner's decision of 9 November 2026: a specification may not move the SICR line away from
    the reported stages. It used to drop every facility the new line could not explain and seal."""
    segment = "P01"
    moved = _grade_explained_s2(mini, segment)
    assert len(moved), "the book has Stage 2 facilities only the SICR line explains"
    inputs = builders.write(mini, tmp_path / "in")
    k = builders.settings(mini, segment)["sicr_k"]
    # No grade is Stage 2 at this multiple: the threshold k x lifetime PD passes 100%.
    never = k / min(mini["parameter_set"]["master_scale"]["ttc_pd"])
    ctx, manifest = execute(specification(inputs, tmp_path, segments={segment: {"sicr_k": never}}),
                            tmp_path / "runs")
    b = manifest.get("blocked", {})
    assert manifest["status"] == "BLOCKED" and (b["step"], b["code"]) == ("R3", Reason.SICR_OVERRIDE_CONFLICT), b
    assert segment in b["message"] and f"{len(moved)} facilit" in b["message"], b["message"]
    assert Reason.SICR_OVERRIDE_CONFLICT in RUN_BLOCKING_REASONS
    logged = builders.result(ctx, "rejections.parquet")
    behind = logged.loc[logged["reason_code"] == Reason.SICR_OVERRIDE_CONFLICT, "record_id"]
    assert sorted(behind) == sorted(moved), "rejections.parquet lists every facility behind the block"
    assert not (ctx.results_dir / "slices.parquet").exists()


@pytest.mark.control("Grade and stage")
def test_a_sicr_multiple_that_contradicts_no_stage_still_runs(mini, tmp_path):
    segment = "P01"
    inputs = builders.write(mini, tmp_path / "in")
    k = builders.settings(mini, segment)["sicr_k"]
    close = k * (1 + 1e-12)  # another number, and the same line for every facility
    ctx, manifest = execute(specification(inputs, tmp_path, segments={segment: {"sicr_k": close}}),
                            tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    assert builders.result(ctx, "rejections.parquet").empty
    effective = json.loads((ctx.reports_dir / "effective_specification.json").read_text(encoding="utf-8"))
    assert effective["parameter_set"]["segments"][segment]["sicr_k"] == close != k


@pytest.mark.control("Grade and stage")
def test_a_stage_the_input_sets_own_line_cannot_explain_is_still_only_rejected(mini, tmp_path):
    """The block is for what the specification breaks. A facility the input set's own line cannot
    explain is rejected as before, with or without the override (A17)."""
    segment = "P01"
    fac = mini["facilities"]
    odd = fac.index[(fac["segment"] == segment) & (fac["ifrs_stage"] == 1)][0]
    fac.loc[odd, "ifrs_stage"] = 2  # no grade move and no trigger behind this Stage 2
    inputs = builders.write(mini, tmp_path / "in")
    k = builders.settings(mini, segment)["sicr_k"]
    ctx, manifest = execute(specification(inputs, tmp_path, segments={segment: {"sicr_k": k * (1 + 1e-12)}}),
                            tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    logged = builders.result(ctx, "rejections.parquet")
    reasons = set(logged.loc[logged["record_id"] == fac.loc[odd, "facility_id"], "reason_code"])
    assert Reason.STAGE_GRADE_CONFLICT in reasons and Reason.SICR_OVERRIDE_CONFLICT not in reasons


# --- matrix files -------------------------------------------------------------------------------

@pytest.mark.control("Rating matrices")
@pytest.mark.parametrize("column", ["to_rank", "from_rank"])
def test_a_matrix_rank_outside_the_scale_blocks(mini, tmp_path, column):
    table = mini["ttc_pd_matrix"]
    cell = table.index[(table["segment"] == "P01") & (table["from_grade"] == "G2") & (table["to_grade"] == "G3")]
    table.loc[cell, column] = len(mini["parameter_set"]["master_scale"]["grades"]) + 50
    b = blocked(mini, tmp_path)
    assert (b["step"], b["code"]) == ("R3", Block.INVALID_MATRIX), b


# --- duplicates met by a specification ----------------------------------------------------------

@pytest.mark.control("Duplicate facility")
def test_a_duplicate_facility_under_a_specification_ccf_blocks_without_a_fault(mini, tmp_path):
    """Without a specification both copies are rejected and the run goes on. A specification's
    ccf is checked per facility, and a facility that is there twice has no single segment."""
    com = mini["commitments"]
    fac = mini["facilities"]
    twice = fac[fac["facility_id"] == com["facility_id"].iloc[0]]
    segment = twice["segment"].iloc[0]
    mini["facilities"] = pd.concat([fac, twice], ignore_index=True)
    inputs = builders.write(mini, tmp_path / "in")
    config = specification(inputs, tmp_path, segments={segment: {"ccf": float(com["accounting_ccf"].iloc[0])}})
    _, manifest = execute(config, tmp_path / "runs")
    b = manifest.get("blocked", {})
    assert manifest["status"] == "BLOCKED" and (b["step"], b["code"]) == ("R2", Block.DUPLICATE_KEY), b
    assert "facility_id" in b["message"]


# --- a facility with no portfolio ---------------------------------------------------------------

@pytest.mark.control("Country or taxonomy mapping")
def test_a_facility_without_a_portfolio_is_rejected(mini, tmp_path):
    """One blank portfolio on a segment's first facility used to take the whole segment's Stage 3
    out of the totals by portfolio, with no record rejected."""
    fac = mini["facilities"].sort_values("facility_id").reset_index(drop=True)
    segment = "P04"
    first = fac.index[fac["segment"] == segment][0]
    lost = fac.loc[first, "facility_id"]
    portfolio = fac.loc[first, "portfolio"]
    fac["portfolio"] = fac["portfolio"].astype(object)
    fac.loc[first, "portfolio"] = None
    mini["facilities"] = fac
    ctx, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    logged = builders.result(ctx, "rejections.parquet")
    assert Reason.MISSING_PORTFOLIO in set(logged.loc[logged["record_id"] == lost, "reason_code"])
    slices = builders.result(ctx, "slices.parquet")
    assert lost not in set(slices["facility_id"])
    kept = fac[(fac["segment"] == segment) & (fac["facility_id"] != lost)]
    migration = builders.report(ctx, "stage_migration.csv")
    book = migration[migration["portfolio"] == portfolio]
    assert len(book), "the segment's other facilities stay in their portfolio's totals"
    opening = book[book["year"] == book["year"].min()].iloc[0]
    assert opening["opening_S3"] == pytest.approx(kept.loc[kept["ifrs_stage"] == 3, "gca"].sum())
    summary = (ctx.reports_dir / "summary.md").read_text(encoding="utf-8")
    gap = next(line for line in summary.splitlines() if "DATA GAP" in line)
    shown = f"{fac.loc[first, 'gca'] / 1_000_000:,.1f}m"
    assert shown in gap, f"the rejected facility's GCA stays visible (OPS-07): {gap}"


# --- block codes --------------------------------------------------------------------------------

@pytest.mark.control("Repository rules")
def test_every_blocking_error_names_a_member_of_the_code_lists():
    """contracts/errors.py: every BlockingError a step raises uses a member of Block or the Reason
    that blocked the run. A code typed as text at a raise site is in no list a reader can find."""
    typed = []
    for path in sorted((ROOT / "src" / "stress").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "BlockingError"
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)):
                typed.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {node.args[1].value!r}")
    assert not typed, "block codes typed as text:\n  " + "\n  ".join(typed)


@pytest.mark.control("Repository rules")
def test_the_codes_of_a_fault_a_specification_and_a_rerun_are_members():
    assert {"INTERNAL_ERROR", "INVALID_SPECIFICATION", "RUN_INTEGRITY", "SOURCE_MISMATCH", "ENVIRONMENT_MISMATCH",
            "INVALID_INPUT", "MISSING_INPUT", "INVALID_HORIZON", "INVALID_SCOPE", "UNSTABLE_SELECTION",
            "NON_MONOTONE"} <= {str(code) for code in Block}
    assert len(CODES) == len(Block) + len(Reason), "a code is in one list only"


# --- rerun --------------------------------------------------------------------------------------

def _stopping_at_r4(monkeypatch, error):
    """A run that loads and validates its inputs and then stops, as a fault or as a block."""
    def stop(loaded, ctx):
        raise error
    monkeypatch.setattr("stress.cli.scenario.build_drivers", stop)


@pytest.mark.control("Reproducibility")
def test_a_rerun_compares_the_block_and_says_what_it_reproduced(mini_tables, tmp_path, monkeypatch, capsys):
    """A blocked run has few results or none, so equal output hashes alone say nothing: the
    rejection log is the same whatever stopped the run after it. The rerun must stop at the same
    step with the same code."""
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    _stopping_at_r4(monkeypatch, RuntimeError("planted fault"))
    ctx, first = builders.run(inputs, tmp_path / "runs")
    assert first["status"] == "BLOCKED" and first["blocked"]["code"] == Block.INTERNAL_ERROR
    capsys.readouterr()
    assert main(["rerun", "--run", ctx.run_dir.as_posix(), "-q"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "reproduced: all" not in out, "a block that came back is not a set of reproduced results"
    assert "blocked again" in out and Block.INTERNAL_ERROR in out, out
    _stopping_at_r4(monkeypatch, BlockingError("R4", Block.MISSING_SCENARIO_VALUE, "planted block"))
    assert main(["rerun", "--run", ctx.run_dir.as_posix(), "-q"]) == EXIT_NOT_REPRODUCED
    err = capsys.readouterr().err
    assert Block.INTERNAL_ERROR in err and Block.MISSING_SCENARIO_VALUE in err, err


@pytest.mark.control("Reproducibility")
def test_a_rerun_of_a_specification_run_keeps_its_hash(mini_tables, tmp_path, capsys):
    """The 8-character hash names what was run. It used to hold the path of the specification, so
    the rerun, which reads the sealed copy, got another one."""
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    config = specification(inputs, tmp_path, segments={"P02": {"pd_model": "p02.pd_nonlinear"}})
    ctx, manifest = execute(config, tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    capsys.readouterr()
    assert main(["rerun", "--run", ctx.run_dir.as_posix(), "--runs-dir", str(tmp_path / "again"), "-q"]) == EXIT_OK
    out = capsys.readouterr().out
    again = out.split("rerun ", 1)[1].split(":", 1)[0]
    assert again.rsplit("-", 1)[1] == ctx.run_id.rsplit("-", 1)[1], (ctx.run_id, again)
