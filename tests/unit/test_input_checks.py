"""R1 to R3 and the command line stop a wrong setting with a block code: the shape of the two YAML
documents, a variant's settings, the variant's name, the run's identity, the control totals and the
optional analysis file. Nothing here changes a result on a valid input set."""

import argparse
import json
import re
import shutil
from datetime import UTC, datetime

import pandas as pd
import pytest
import yaml

from foundation.synth.analysis import build as analysis_package
from foundation.synth.inputset import package
from stress import cli, ingest, scenario, validate
from stress.cli import EXIT_BLOCKED, EXIT_ERROR, build_parser, execute, main
from stress.contracts.artifacts import canonical_hash
from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import PRODUCTS
from stress.contracts.run import RunConfig
from stress.contracts.tables import Z_SOURCE_FLAT, Z_SOURCE_PATH, Z_SOURCE_REVERSION
from stress.ingest.specification import resolve
from stress.lineage import open_run
from tests import builders
from tests.support import ROOT

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def blocked(mini, tmp_path, **kw) -> dict:
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs", **kw)
    assert manifest["status"] == "BLOCKED", "the run must block"
    return manifest["blocked"]


def specification(inputs, path, **sections) -> RunConfig:
    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    run = {"inputs": str(inputs), "scenarios": ["baseline", "adverse"], **sections.pop("run", {})}
    doc = {"schema_version": 1, "status": "SYNTHETIC", "source": "input-check test", "version": "test-v1",
           "input_set_hash": manifest["input_set_hash"], "run": run, **sections}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return RunConfig("", (), "core", specification=str(path))


def hash_of(run_id: str) -> str:
    return re.fullmatch(r"\d{8}T\d{4}Z-.+-([0-9a-f]{8})(-\d+)?", run_id).group(1)


# --- the shape of the two YAML documents (item 3) -----------------------------------------------

def _set(*path, value):
    def change(doc):
        node = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return change


def _drop(*path):
    def change(doc):
        node = doc
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
    return change


def _twice(*path):
    """Repeat the first entry of a list."""
    def change(doc):
        node = doc
        for key in path:
            node = node[key]
        node.append(node[0])
    return change


def _first_index(value):
    def change(doc):
        doc["index_of"][next(iter(doc["index_of"]))] = value
    return change


def _one_pd_short(doc):
    doc["master_scale"]["ttc_pd"].pop()


def _a_variant_named_by_a_number(doc):
    doc["variants"][2027] = doc["variants"]["core"]


SCENARIO_DEFECTS = {
    "a scenario id twice": (_twice("scenarios"), Block.DUPLICATE_KEY),
    "an index_of that is not a mapping": (_set("index_of", value=["residential_price_change"]), Block.BAD_VALUE_TYPE),
    "an index_of entry that is not text": (_first_index(3), Block.BAD_VALUE_TYPE),
    "starting values that are not a list": (_set("starting_values", value={"unemployment": 6.0}),
                                            Block.BAD_VALUE_TYPE),
    "a starting value without a country": (_drop("starting_values", 0, "country"), Block.MISSING_COLUMN),
    "a starting value that is text": (_set("starting_values", 0, "value", value="six"), Block.BAD_VALUE_TYPE),
    "a starting value in an unknown unit": (_set("starting_values", 0, "unit", value="per mille"),
                                            Block.SCENARIO_WITHOUT_UNIT),
    "a country that is not text": (_set("values", 0, "country", value=31), Block.BAD_VALUE_TYPE),
    "a year that is a float": (_set("values", 0, "year", value=2027.0), Block.BAD_VALUE_TYPE),
    "a year that is quoted": (_set("values", 0, "year", value="2027"), Block.BAD_VALUE_TYPE),
    "a value that is true": (_set("values", 0, "value", value=True), Block.BAD_VALUE_TYPE),
    "a value that is text": (_set("values", 0, "value", value="n/a"), Block.BAD_VALUE_TYPE),
    "a year that is text": (_set("values", 0, "year", value="FY2027"), Block.BAD_VALUE_TYPE),
    "a year that is true": (_set("values", 0, "year", value=True), Block.BAD_VALUE_TYPE),
    "no list of values": (_set("values", value=None), Block.BAD_VALUE_TYPE),
    "a value that is not a mapping": (_set("values", 0, value="gdp_growth 2027"), Block.BAD_VALUE_TYPE),
    "a scenario without an id": (_drop("scenarios", 2, "id"), Block.MISSING_COLUMN),
    "no list of scenarios": (_set("scenarios", value="baseline, adverse"), Block.BAD_VALUE_TYPE),
}


@pytest.mark.req("SCN-01", "SCN-02", "DAT-02")
@pytest.mark.parametrize("defect", sorted(SCENARIO_DEFECTS))
def test_a_scenarios_file_of_the_wrong_shape_blocks_at_r2(mini, tmp_path, defect):
    """A boolean is not a number: ``value: true`` used to be read as 1.0 and sealed. Most of the
    others ended as engine faults. A year is a whole number as YAML reads one, so a quoted year
    and ``2027.0``, which the engine used to convert, are refused too (A44)."""
    change, code = SCENARIO_DEFECTS[defect]
    change(mini["scenarios"])
    b = blocked(mini, tmp_path)
    assert (b["step"], b["code"]) == ("R2", code), b


PARAMETER_DEFECTS = {
    "a status that is a list": (_set("status", value=["PROPOSED"]), Block.BAD_VALUE_TYPE, "status"),
    "a version that is true": (_set("version", value=True), Block.BAD_VALUE_TYPE, "version"),
    "a blank parameter_set_id": (_set("parameter_set_id", value=" "), Block.BAD_VALUE_TYPE, "parameter_set_id"),
    "a snapshot date in another format": (_set("horizon", "snapshot_date", value="31/12/2026"),
                                          Block.BAD_VALUE_TYPE, "snapshot_date"),
    "one master-scale PD short": (_one_pd_short, Block.BAD_VALUE_TYPE, "ttc_pd"),
    "a master-scale PD above one": (_set("master_scale", "ttc_pd", 0, value=1.5), Block.BAD_VALUE_TYPE, "ttc_pd"),
    "a grade twice": (_twice("master_scale", "grades"), Block.BAD_VALUE_TYPE, "grades"),
    "a negative tolerance": (_set("tolerances", "amount", "abs", value=-0.01), Block.BAD_VALUE_TYPE, "amount"),
    "reversion years as a float": (_set("terminal_rule", "reversion_years", value=6.0), Block.BAD_VALUE_TYPE,
                                   "reversion_years"),
    "a projection year that is quoted": (_set("horizon", "projection_years", value=["2027", "2028", "2029"]),
                                         Block.BAD_VALUE_TYPE, "projection_years"),
    "no last_bucket_year": (_drop("horizon", "last_bucket_year"), Block.MISSING_PARAMETER, "last_bucket_year"),
    "no snapshot_date": (_drop("horizon", "snapshot_date"), Block.MISSING_PARAMETER, "snapshot_date"),
    "no grades": (_drop("master_scale", "grades"), Block.MISSING_PARAMETER, "grades"),
    "no aggregate tolerance": (_drop("tolerances", "aggregate"), Block.MISSING_PARAMETER, "aggregate"),
    "projection years as text": (_set("horizon", "projection_years", value="2027-2029"), Block.BAD_VALUE_TYPE,
                                 "projection_years"),
    "a tolerance as text": (_set("tolerances", "amount", "abs", value="0.01"), Block.BAD_VALUE_TYPE, "amount"),
    "a tolerance that is true": (_set("tolerances", "aggregate", "rel", value=True), Block.BAD_VALUE_TYPE,
                                 "aggregate"),
    "a segment ccf as text": (_set("portfolios", "P03", "segments", "P03", "ccf", value="half"),
                              Block.BAD_VALUE_TYPE, "P03"),
    "zero reversion years": (_set("terminal_rule", "reversion_years", value=0), Block.BAD_VALUE_TYPE,
                             "reversion_years"),
    "no variants": (_set("variants", value=None), Block.BAD_VALUE_TYPE, "variants"),
    "a variant without a repayment profile": (_drop("variants", "core", "repayment_profile"),
                                              Block.MISSING_PARAMETER, "repayment_profile"),
    "a variant ccf that is not a mapping": (_set("variants", "core", "ccf", value=0.75),
                                            Block.BAD_VALUE_TYPE, "variants.core.ccf"),
    "a null ccf in the run's variant": (_set("variants", "core", "ccf", value=None), Block.BAD_VALUE_TYPE,
                                        "variants.core.ccf"),
    "a variant named by a number": (_a_variant_named_by_a_number, Block.BAD_VALUE_TYPE, "variant's name"),
    "an unused variant whose ccf is a number": (_set("variants", "utilisation", "ccf", value=0.75),
                                                Block.BAD_VALUE_TYPE, "variants.utilisation.ccf"),
    "an unused variant whose ccf is a list": (_set("variants", "utilisation", "ccf", value=["P03", "P05"]),
                                              Block.BAD_VALUE_TYPE, "variants.utilisation.ccf"),
    "an unused variant that is null": (_set("variants", "linear", value=None), Block.BAD_VALUE_TYPE,
                                       "variants.linear"),
    "a variant ccf as text": (_set("variants", "core", "ccf", "P03", value="three quarters"),
                              Block.BAD_VALUE_TYPE, "variants.core.ccf.P03"),
}


@pytest.mark.req("SYN-PAR-06", "DAT-02")
@pytest.mark.parametrize("defect", sorted(PARAMETER_DEFECTS))
def test_a_parameter_set_of_the_wrong_shape_blocks_at_r2(mini, tmp_path, defect):
    change, code, named = PARAMETER_DEFECTS[defect]
    change(mini["parameter_set"])
    b = blocked(mini, tmp_path)
    assert (b["step"], b["code"]) == ("R2", code), b
    assert named in b["message"], b["message"]


@pytest.mark.req("DAT-02")
def test_a_missing_scenario_value_is_still_missing_and_not_a_wrong_shape(mini, tmp_path):
    """``value: null`` is a missing value with a status of its own, not a defect of the file."""
    row = {**mini["scenarios"]["values"][0], "variable": "unused_driver", "value": None, "completeness": "missing"}
    mini["scenarios"]["values"].append(row)
    ctx = open_run(RunConfig(builders.write(mini, tmp_path / "in").as_posix(), ("baseline", "adverse"), "core"),
                   tmp_path / "runs", NOW)
    values = ingest.load_inputs(ctx).scenario_values
    unused = values[values["variable"] == "unused_driver"]
    assert unused["value"].isna().all() and (unused["value_status"] == "missing").all()


# --- a variant's settings (item 1) --------------------------------------------------------------

@pytest.mark.req("EAD-10")
@pytest.mark.parametrize("defect", ["an unknown word", "an unknown product"])
def test_a_variant_repayment_profile_the_run_does_not_know_blocks(mini, tmp_path, defect):
    """An unknown word used to run as linear, and a misspelt product fell to the default, each
    sealed under the variant's name."""
    profile = mini["parameter_set"]["variants"]["annuity"]["repayment_profile"]
    product = next(p for p in PRODUCTS if p in profile)
    if defect == "an unknown word":
        profile[product] = profile[product][1:]
        named = profile[product]
    else:
        named = product[1:]
        profile[named] = profile.pop(product)
    b = blocked(mini, tmp_path, variant="annuity")
    assert (b["step"], b["code"]) == ("R3", Block.UNKNOWN_VARIANT), b
    assert repr(named) in b["message"], b["message"]


@pytest.mark.req("SYN-PAR-06", "EAD-10")
def test_what_no_step_of_the_run_reads_does_not_stop_it(mini, tmp_path):
    """R2 and R3 check what this run reads. An unused variant need not be complete: it may lack
    ``repayment_profile``, have a null ``ccf`` or name a segment of another run. The records kept
    for people (``conventions``, ``variables``) are not checked at all."""
    variants = mini["parameter_set"]["variants"]
    variants["utilisation"]["ccf"] = {"A_SEGMENT_OF_ANOTHER_RUN": 0.75}
    variants["linear"] = {"label": "not filled in yet", "ccf": None}
    mini["parameter_set"]["conventions"] = "see the methodology note"
    mini["scenarios"]["variables"] = "see the release note"
    ctx = open_run(RunConfig(builders.write(mini, tmp_path / "in").as_posix(), ("baseline", "adverse"), "core"),
                   tmp_path / "runs", NOW)
    routed = validate.validate_and_route(ingest.load_inputs(ctx), ctx)
    assert routed.rejections.empty


# --- the variant's name (item 4) ----------------------------------------------------------------

@pytest.mark.req("OPS-01")
@pytest.mark.parametrize("name", ["a/b", "x/../../escaped", "..\\escaped", "core best", ".."])
def test_a_variant_name_that_is_not_a_plain_name_blocks_before_a_folder_is_made(mini_tables, tmp_path, capsys, name):
    """The variant enters the run folder's name. A separator in it used to end as a raw traceback,
    or seal a folder outside the runs directory."""
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    home = tmp_path / "deep" / "home"
    before = {p.name for p in tmp_path.rglob("*")}
    code = main(["run", "--inputs", inputs.as_posix(), "--variant", name, "--runs-dir", str(home / "runs"), "-q"])
    assert code == EXIT_BLOCKED and Block.INVALID_ARGUMENT in capsys.readouterr().err
    made = {p.name for p in tmp_path.rglob("*")} - before
    assert not made, f"nothing is written for a refused name: {sorted(made)}"


@pytest.mark.req("OPS-01")
def test_a_variant_name_in_a_specification_is_checked_the_same_way(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    config = specification(inputs, tmp_path / "job.yaml", run={"variant": "a/b"})
    with pytest.raises(BlockingError) as caught:
        execute(config, tmp_path / "runs")
    assert (caught.value.step, caught.value.code) == ("R1", Block.INVALID_ARGUMENT)
    assert not (tmp_path / "runs").exists()


# --- duplicates met by a specification (item 5) -------------------------------------------------

@pytest.mark.req("SCP-01", "DAT-02")
@pytest.mark.parametrize("field", ["country", "nace_code"])
def test_a_duplicate_obligor_under_an_assignment_by_borrower_blocks_without_a_fault(mini, tmp_path, field):
    obl = mini["obligors"]
    fac = mini["facilities"]
    borrower = obl[obl["obligor_id"].isin(set(fac.loc[fac["segment"] == "P02", "obligor_id"]))].iloc[[0]]
    mini["obligors"] = pd.concat([obl, borrower], ignore_index=True)
    inputs = builders.write(mini, tmp_path / "in")
    config = specification(inputs, tmp_path / "job.yaml", segments={"P02_PART": {"inherits": "P02"}},
                           assignments=[{"where": {"segment": "P02", field: str(borrower[field].iloc[0])},
                                         "segment": "P02_PART"}])
    _, manifest = execute(config, tmp_path / "runs")
    b = manifest.get("blocked", {})
    assert manifest["status"] == "BLOCKED" and (b["step"], b["code"]) == ("R2", Block.DUPLICATE_KEY), b
    assert "obligor_id" in b["message"]


# --- the command line (items 6 and 7) -----------------------------------------------------------

@pytest.mark.req("EXP-01")
def test_dynamic_on_the_command_line_is_refused_at_once(mini_tables, tmp_path, capsys):
    """A dynamic run needs the volume assumptions of a specification, so the flag alone could
    never succeed: it opened a run, loaded the set and blocked."""
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    code = main(["run", "--inputs", inputs.as_posix(), "--balance-sheet", "dynamic",
                 "--runs-dir", str(tmp_path / "runs"), "-q"])
    err = capsys.readouterr().err
    assert code == EXIT_BLOCKED and "--specification" in err and Block.INVALID_ARGUMENT in err, err
    assert not (tmp_path / "runs").exists()
    commands = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    flag = next(a for a in commands.choices["run"]._actions if "--balance-sheet" in a.option_strings)
    assert flag.help and "specification" in flag.help


@pytest.mark.req("EXP-01")
def test_a_block_on_the_volume_assumptions_names_the_step_that_found_it(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    config = specification(inputs, tmp_path / "job.yaml", run={"balance_sheet": "dynamic"})
    _, manifest = execute(config, tmp_path / "runs")
    b = manifest.get("blocked", {})
    assert manifest["status"] == "BLOCKED" and (b["step"], b["code"]) == ("R3", Block.INVALID_SPECIFICATION), b


@pytest.mark.req("OPS-01")
def test_a_specification_without_inputs_is_not_told_to_use_a_flag_it_may_not_use(mini_tables, tmp_path, capsys):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    config = specification(inputs, tmp_path / "job.yaml")
    doc = yaml.safe_load((tmp_path / "job.yaml").read_text(encoding="utf-8"))
    del doc["run"]["inputs"]
    (tmp_path / "job.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(BlockingError) as caught:
        resolve(config)
    assert "run.inputs" in caught.value.message and "--inputs" not in caught.value.message
    # The flag beside a specification is refused, which is why the message may not name it.
    assert main(["run", "--specification", str(tmp_path / "job.yaml"), "--inputs", inputs.as_posix(),
                 "--runs-dir", str(tmp_path / "runs")]) == EXIT_BLOCKED
    assert "not both" in capsys.readouterr().err


@pytest.mark.req("OPS-04")
def test_an_engine_fault_seals_the_run_as_blocked_and_exits_with_its_own_code(mini_tables, tmp_path, monkeypatch,
                                                                              capsys):
    """Exit 1 is an engine fault, exit 2 a block: the README and the runbook list both."""
    def fault(ctx):
        raise RuntimeError("planted fault")
    monkeypatch.setattr(cli, "pipeline", fault)
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    code = main(["run", "--inputs", inputs.as_posix(), "--runs-dir", str(tmp_path / "runs"), "-q"])
    assert code == EXIT_ERROR != EXIT_BLOCKED
    sealed = json.loads(next((tmp_path / "runs").iterdir()).joinpath("manifest.json").read_text(encoding="utf-8"))
    assert sealed["status"] == "BLOCKED"
    assert (sealed["blocked"]["step"], sealed["blocked"]["code"]) == ("engine", Block.INTERNAL_ERROR)
    for document in ("README.md", "docs/runbook.md"):
        text = (ROOT / document).read_text(encoding="utf-8")
        assert re.search(r"[Ee]xit code[s]?:? .*\b1\b.*fault", text), f"{document} does not explain exit code 1"


# --- the run ID (item 8) ------------------------------------------------------------------------

@pytest.mark.req("OPS-01")
def test_a_plain_run_keeps_the_identity_it_had(mini_tables, tmp_path):
    """The 8-character hash of a run without a specification or an analysis file is the one the
    formula before 9 November 2026 gave: its settings, the input set, the code and the spec."""
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    config = RunConfig(inputs=inputs.as_posix(), scenarios=("baseline", "adverse"), variant="core")
    ctx = open_run(config, tmp_path / "runs", NOW)
    assert config.as_dict()["analysis"] is None and config.as_dict()["specification"] is None
    before = canonical_hash({
        "config": {**config.as_dict(), "inputs": ctx.input_set_hash},
        "input_set": ctx.input_set_hash, "code": ctx.code_version, "spec": ctx.spec_version,
    })[:8]
    assert ctx.run_id == f"{NOW:%Y%m%dT%H%MZ}-core-{before}"


@pytest.mark.req("OPS-01")
def test_the_run_hash_follows_what_a_specification_says_not_where_it_is(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    swap = {"segments": {"P02": {"pd_model": "p02.pd_nonlinear"}}}
    here = open_run(resolve(specification(inputs, tmp_path / "here" / "job.yaml", **swap)), tmp_path / "runs", NOW)
    there = open_run(resolve(specification(inputs, tmp_path / "there" / "renamed.yaml", **swap)),
                     tmp_path / "runs", NOW)
    other = open_run(resolve(specification(inputs, tmp_path / "here" / "job.yaml",
                                           segments={"P02": {"pd_model": "p02.pd"}})), tmp_path / "runs", NOW)
    assert hash_of(here.run_id) == hash_of(there.run_id) != hash_of(other.run_id)


@pytest.mark.req("OPS-01")
def test_the_run_hash_follows_what_an_analysis_file_says_not_where_it_is(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    doc = analysis_package(inputs)
    first, second = tmp_path / "a" / "analysis.yaml", tmp_path / "b" / "copy.yaml"
    for path in (first, second):
        path.parent.mkdir()
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    def opened(path):
        config = RunConfig(inputs.as_posix(), ("baseline", "adverse"), "core", analysis=str(path))
        return hash_of(open_run(resolve(config), tmp_path / "runs", NOW).run_id)

    same_content = opened(first), opened(second)
    first.write_text(yaml.safe_dump({**doc, "version": doc["version"] + " revised"}), encoding="utf-8")
    assert same_content[0] == same_content[1], "the same analysis at another path is the same run"
    assert opened(first) != same_content[0], "another analysis at the same path is another run"


@pytest.mark.req("OPS-01")
def test_a_run_whose_specification_changes_the_calculation_is_not_named_as_the_core_run(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    plain = open_run(RunConfig(inputs.as_posix(), ("baseline", "adverse"), "core"), tmp_path / "runs", NOW)
    only_run = open_run(resolve(specification(inputs, tmp_path / "a.yaml")), tmp_path / "runs", NOW)
    swapped = open_run(resolve(specification(inputs, tmp_path / "b.yaml",
                                             segments={"P02": {"pd_model": "p02.pd_nonlinear"}})),
                       tmp_path / "runs", NOW)
    crisis = {"crisis": {"inherits": "adverse", "narrative": "a named crisis"}}
    added = open_run(resolve(specification(inputs, tmp_path / "c.yaml", scenarios=crisis,
                                           run={"scenarios": ["baseline", "crisis"], "s2_treatment": "held"})),
                     tmp_path / "runs", NOW)
    assert "-core-" in plain.run_id and "-core-" in only_run.run_id
    assert "-core+spec-" in swapped.run_id, swapped.run_id
    assert "-core+held+spec-" in added.run_id, added.run_id
    # The control room lists run folders by its own pattern: read it there, do not retype it.
    server = (ROOT / "control_room" / "server.py").read_text(encoding="utf-8")
    run_name = re.search(r'^RUN_NAME = re\.compile\(r"(.+)"\)$', server, re.MULTILINE).group(1)
    for ctx in (plain, only_run, swapped, added):
        assert re.fullmatch(run_name, ctx.run_id), f"{ctx.run_id} is not a run name to the control room"


# --- an analysis section that needs a scenario the run does not hold (item 9) -------------------

@pytest.mark.req("OPS-07")
@pytest.mark.parametrize("section", ["plausibility", "climate"])
def test_an_analysis_section_that_needs_adverse_blocks_a_run_without_it(mini, tmp_path, section):
    """Without adverse the plausibility sheet was left out while readiness said it was provided,
    and the climate table held rows labelled with a scenario the run did not have."""
    inputs = builders.write(mini, tmp_path / "in")
    doc = analysis_package(inputs)
    envelope = {k: doc[k] for k in ("schema_version", "input_set_hash", "status", "source", "version")}
    path = tmp_path / "analysis.yaml"
    path.write_text(yaml.safe_dump({**envelope, section: doc[section]}), encoding="utf-8")
    config = RunConfig(inputs.as_posix(), ("baseline", "severe_adverse"), "core", analysis=str(path))
    _, manifest = execute(config, tmp_path / "runs")
    b = manifest.get("blocked", {})
    assert manifest["status"] == "BLOCKED" and (b["step"], b["code"]) == ("R2", Block.UNKNOWN_SCENARIO), b
    assert section in b["message"] and "adverse" in b["message"], b["message"]


# --- packaging supplied datasets (item 10) ------------------------------------------------------

def _source(mini, tmp_path, change):
    """A copy of a written input set whose parameter set is then changed by hand, as a user's
    prepared folder would be."""
    source = tmp_path / "source"
    shutil.copytree(builders.write(mini, tmp_path / "in"), source)
    doc = yaml.safe_load((source / "parameter_set.yaml").read_text(encoding="utf-8"))
    change(doc)
    (source / "parameter_set.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return source


@pytest.mark.req("OPS-01", "DAT-03")
def test_packaging_refuses_a_segment_without_a_matrix_file(mini, tmp_path):
    """It used to seal the set with that segment's matrix file left out, a set the engine blocks."""
    source = _source(mini, tmp_path, _drop("portfolios", "P02", "segments", "P02", "ttc_matrix"))
    with pytest.raises(ValueError, match="P02.*ttc_matrix"):
        package(source, tmp_path / "packaged")
    assert not (tmp_path / "packaged").exists() or not any((tmp_path / "packaged").iterdir())


@pytest.mark.req("OPS-01", "DAT-03")
def test_packaging_refuses_the_older_form_of_the_parameter_set_in_plain_words(mini, tmp_path):
    def older(doc):
        doc["segments"] = {segment: body for portfolio in doc.pop("portfolios").values()
                           for segment, body in portfolio["segments"].items()}
    source = _source(mini, tmp_path, older)
    with pytest.raises(ValueError, match="portfolios"):
        package(source, tmp_path / "packaged")


# --- control totals (item 12) -------------------------------------------------------------------

def _manifest(inputs, change):
    path = inputs / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")


@pytest.mark.req("DAT-03")
@pytest.mark.parametrize("gone", ["control_totals", "undrawn_by_portfolio", "rows"])
def test_a_manifest_without_its_control_totals_blocks(mini, tmp_path, gone):
    """It used to pass, and the log said the control totals matched the manifest."""
    inputs = builders.write(mini, tmp_path / "in")
    _manifest(inputs, _drop("control_totals") if gone == "control_totals" else _drop("control_totals", gone))
    _, manifest = builders.run(inputs, tmp_path / "runs")
    b = manifest.get("blocked", {})
    assert manifest["status"] == "BLOCKED" and (b["step"], b["code"]) == ("R2", Block.CONTROL_TOTAL_MISMATCH), b


@pytest.mark.req("DAT-03")
def test_undrawn_by_portfolio_is_compared_with_the_manifest(mini, tmp_path):
    """R2 recomputed it and compared nothing: an amount moved between two portfolios keeps the
    total and passed."""
    inputs = builders.write(mini, tmp_path / "in")
    tolerance = mini["parameter_set"]["tolerances"]["aggregate"]

    def move(doc):
        by = doc["control_totals"]["undrawn_by_portfolio"]
        first, second = sorted(by)[:2]
        amount = 10 * max(tolerance["abs"], tolerance["rel"] * by[first])
        by[first], by[second] = by[first] + amount, by[second] - amount
    _manifest(inputs, move)
    _, manifest = builders.run(inputs, tmp_path / "runs")
    b = manifest.get("blocked", {})
    assert manifest["status"] == "BLOCKED" and (b["step"], b["code"]) == ("R2", Block.CONTROL_TOTAL_MISMATCH), b
    assert "undrawn" in b["message"]


# --- how a Z after the last scenario year is labelled (item 14) ---------------------------------

@pytest.mark.req("ECL-10")
def test_a_z_held_flat_after_the_horizon_is_labelled_flat(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    config = specification(inputs, tmp_path / "job.yaml",
                           scenarios={"held": {"inherits": "adverse", "narrative": "adverse, held after 2029"}},
                           terminal_policies={"held": {"method": "flat"}},
                           run={"scenarios": ["baseline", "adverse", "held"]})
    ctx = open_run(resolve(config), tmp_path / "runs", NOW)
    loaded = ingest.load_inputs(ctx)
    z = scenario.build_drivers(loaded, ctx).z
    last = int(loaded.parameter_set["terminal_rule"]["last_scenario_year"])
    after = z[z["year"] > last]
    held = after[after["scenario"] == "held"]
    end = z[(z["scenario"] == "held") & (z["year"] == last)].set_index(["segment", "model", "country"])["z"]
    assert (held["z"].to_numpy() == end.reindex(pd.MultiIndex.from_frame(held[["segment", "model", "country"]]))
            .to_numpy()).all(), "the policy holds Z at its last scenario year"
    assert set(held["z_source"]) == {Z_SOURCE_FLAT}
    adverse = after[after["scenario"] == "adverse"]
    moving = (adverse["adverse_weight"] > 0) & (adverse["adverse_weight"] < 1)
    assert moving.any() and set(adverse.loc[moving, "z_source"]) == {Z_SOURCE_REVERSION}
    assert set(adverse.loc[~moving, "z_source"]) == {Z_SOURCE_FLAT}
    assert set(z.loc[z["year"] <= last, "z_source"]) == {Z_SOURCE_PATH}
