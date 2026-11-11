"""Section 12.2 controls on settings: a wrong setting in the parameter set, a matrix file or a run
specification stops the run with a block code. It never seals a run with other numbers than the
setting's name promises, and it never ends as an engine fault."""

import ast
import json

import pandas as pd
import pytest
import yaml

from foundation.synth.analysis import build as analysis_package
from stress import ingest, validate
from stress.cli import EXIT_NOT_REPRODUCED, EXIT_OK, execute, main
from stress.contracts.errors import RUN_BLOCKING_REASONS, Block, BlockingError, Reason
from stress.contracts.run import RunConfig
from stress.ingest.specification import resolve
from stress.lineage import open_run
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


UNUSED_VARIANT_SHAPES = {
    "a ccf that is a number": ("utilisation", {"label": "sensitivity", "ccf": 0.75}),
    "a ccf that is a list": ("utilisation", {"label": "sensitivity", "ccf": ["P03", "P05"]}),
    "a variant that is null": ("linear", None),
}


@pytest.mark.control("EAD/CCF contract")
@pytest.mark.parametrize("shape", sorted(UNUSED_VARIANT_SHAPES))
def test_a_variant_no_new_segment_can_inherit_from_blocks_at_r2(mini, tmp_path, shape):
    """A segment a specification creates inherits the ccf of every variant, the unused ones too.
    One it cannot read blocks at R2 with a block code; it must never end the run as a fault."""
    name, settings = UNUSED_VARIANT_SHAPES[shape]
    mini["parameter_set"]["variants"][name] = settings
    inputs = builders.write(mini, tmp_path / "in")
    config = specification(inputs, tmp_path, segments={"P05_PART": {"inherits": "P05"}},
                           assignments=[{"where": {"segment": "P05"}, "segment": "P05_PART"}])
    _, manifest = execute(config, tmp_path / "runs")
    b = manifest.get("blocked", {})
    assert manifest["status"] == "BLOCKED" and (b["step"], b["code"]) == ("R2", Block.BAD_VALUE_TYPE), b
    assert f"variants.{name}" in b["message"], b["message"]


@pytest.mark.control("EAD/CCF contract")
def test_a_new_segment_inherits_only_from_the_variants_that_override_its_parent(mini, tmp_path):
    """An unused variant with no ccf, or a null one, overrides nothing: a new segment inherits
    nothing from it, and the run goes on."""
    variants = mini["parameter_set"]["variants"]
    variants["linear"] = {"label": "not filled in yet", "ccf": None}
    variants["annuity"].pop("ccf", None)
    parent = next(iter(variants["utilisation"]["ccf"]))
    inputs = builders.write(mini, tmp_path / "in")
    config = specification(inputs, tmp_path, segments={"CARVED": {"inherits": parent}},
                           assignments=[{"where": {"segment": parent}, "segment": "CARVED"}])
    ctx = open_run(resolve(config), tmp_path / "runs")
    loaded = ingest.load_inputs(ctx)
    applied = loaded.parameter_set["variants"]
    assert applied["utilisation"]["ccf"]["CARVED"] == applied["utilisation"]["ccf"][parent]
    assert applied["linear"]["ccf"] is None and "ccf" not in applied["annuity"]
    assert validate.validate_and_route(loaded, ctx).rejections.empty


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


@pytest.mark.control("Country or taxonomy mapping")
def test_a_portfolio_that_an_assignment_supplies_is_a_portfolio(mini, tmp_path):
    """R3 tests the portfolio it routes with, as it does the segment. A facility the file leaves
    without a portfolio and a specification files under one runs under that portfolio."""
    fac = mini["facilities"]
    segment = "P04"
    blank = fac.index[fac["segment"] == segment][0]
    filed, portfolio = fac.loc[blank, "facility_id"], fac.loc[blank, "portfolio"]
    fac["portfolio"] = fac["portfolio"].astype(object)
    fac.loc[blank, "portfolio"] = None
    inputs = builders.write(mini, tmp_path / "in")
    config = specification(inputs, tmp_path, assignments=[{"where": {"facility_id": filed}, "segment": segment,
                                                           "portfolio": portfolio}])
    ctx = open_run(resolve(config), tmp_path / "runs")
    routed = validate.validate_and_route(ingest.load_inputs(ctx), ctx)
    assert routed.rejections.empty, routed.rejections["reason_code"].tolist()
    assert routed.portfolio.set_index("facility_id").loc[filed, "portfolio"] == portfolio


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


BLOCKS_ON_A_GIVEN_FILE = {
    "an analysis section about a scenario the run lacks": Block.UNKNOWN_SCENARIO,
    "an analysis file of another schema": Block.BAD_VALUE_TYPE,
    "a specification of another input set": Block.INVALID_SPECIFICATION,
    "an approval of another input set": Block.INPUT_HASH_MISMATCH,
}


@pytest.mark.control("Reproducibility")
@pytest.mark.parametrize("case", sorted(BLOCKS_ON_A_GIVEN_FILE))
def test_a_run_that_blocks_on_a_file_it_was_given_reruns_to_the_same_block(mini_tables, tmp_path, capsys, case):
    """R2 keeps the analysis file, the specification and the approval record in data/ before it
    checks them. A run that blocked on one of them used to seal a folder without it, so its rerun
    stopped on the missing copy instead: another block, or the same code for another reason."""
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    config = RunConfig(inputs.as_posix(), ("baseline", "adverse"), "core")
    given = None
    if case.startswith("an analysis"):
        doc = analysis_package(inputs)
        envelope = {k: doc[k] for k in ("schema_version", "input_set_hash", "status", "source", "version")}
        if "scenario" in case:
            doc = {**envelope, "plausibility": doc["plausibility"]}
            config.scenarios = ("baseline", "severe_adverse")
        else:
            doc = {**envelope, "schema_version": envelope["schema_version"] + 1}
        given = tmp_path / "analysis.yaml"
        given.write_text(yaml.safe_dump(doc), encoding="utf-8")
        config.analysis = str(given)
    elif case.startswith("a specification"):
        config = specification(inputs, tmp_path)
        given = tmp_path / "job.yaml"
        doc = yaml.safe_load(given.read_text(encoding="utf-8"))
        given.write_text(yaml.safe_dump({**doc, "input_set_hash": doc["input_set_hash"][::-1]}), encoding="utf-8")
    else:
        record = json.loads((inputs / "approval.json").read_text(encoding="utf-8"))
        record["input_set_hash"] = record["input_set_hash"][::-1]
        (inputs / "approval.json").write_text(json.dumps(record), encoding="utf-8")
    ctx, first = execute(config, tmp_path / "runs")
    code = BLOCKS_ON_A_GIVEN_FILE[case]
    assert first["status"] == "BLOCKED" and (first["blocked"]["step"], first["blocked"]["code"]) == ("R2", code)
    if given:
        given.unlink()  # the rerun has only the run folder
    capsys.readouterr()
    again = tmp_path / "again"
    assert main(["rerun", "--run", ctx.run_dir.as_posix(), "--runs-dir", str(again), "-q"]) == EXIT_OK
    assert f"blocked again at R2 with {code}" in capsys.readouterr().out
    second = json.loads(next(again.iterdir()).joinpath("manifest.json").read_text(encoding="utf-8"))
    assert second["blocked"] == first["blocked"], "the rerun stopped for the same reason, not only on the same code"


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
