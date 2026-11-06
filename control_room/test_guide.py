"""Tests of the guide to step 1, run with the room's other tests:

    uv run pytest control_room

The guide must say what the engine enforces, so each list is held against the engine's own contract.
"""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import guide
import server

from stress.contracts.errors import RUN_BLOCKING_REASONS, Block, Reason
from stress.contracts.inputs import (
    APPROACHES,
    DATASETS,
    PARAMETER_SET_TOP_KEYS,
    PRODUCTS,
    REPAYMENT_PROFILES,
    SCENARIO_TOP_KEYS,
    SCENARIO_UNITS,
    SCENARIO_VALUE_FIELDS,
    SEGMENT_PARAMETERS,
    TABLE_DATASETS,
    TERM_PRODUCTS,
    TTC_MATRIX,
)
from stress.contracts.preparation import COLLATERAL_INDEX
from stress.contracts.status import ALL_STATUSES

PAGE = guide.step_one()
FILES = {entry["name"]: entry for entry in PAGE["files"]}
# What stops a run for a reason other than a file's contents: an integrity check, a choice the page makes
# itself, or a check of what the engine calculated.
NOT_ABOUT_THE_FILES = {
    Block.REGULATORY_MODE, Block.INVALID_ARGUMENT, Block.RUN_EXISTS, Block.INPUT_SET_NOT_FOUND,
    Block.INPUT_HASH_MISMATCH, Block.CONTROL_TOTAL_MISMATCH, Block.UNKNOWN_SCENARIO, Block.PD_IDENTITY,
    Block.LGD_OUT_OF_RANGE, Block.STATIC_BALANCE, Block.S3_RELEASE, Block.NOT_PERMITTED_MOVEMENT,
    Block.RECONCILIATION}


def test_it_covers_every_kind_of_file_in_the_order_of_the_page():
    assert list(FILES) == [spec.name for spec in guide.GUIDED]
    assert {spec.name for spec in DATASETS} | {TTC_MATRIX.name} == set(FILES)


@pytest.mark.parametrize("spec", (*TABLE_DATASETS, TTC_MATRIX), ids=lambda spec: spec.name)
def test_a_table_lists_the_contracts_columns_each_with_a_meaning(spec):
    shown = FILES[spec.name]["columns"]
    assert [column["name"] for column in shown] == list(spec.column_names)
    assert all(column["meaning"] and column["kind"] in guide.KINDS.values() for column in shown)


def test_no_meaning_is_left_for_a_column_that_has_gone():
    assert set(guide.MEANINGS) == {spec.name for spec in (*TABLE_DATASETS, TTC_MATRIX)}
    for spec in (*TABLE_DATASETS, TTC_MATRIX):
        assert set(guide.MEANINGS[spec.name]) == set(spec.column_names)


@pytest.mark.parametrize("name, keys", [("scenarios", SCENARIO_TOP_KEYS), ("parameter_set", PARAMETER_SET_TOP_KEYS)])
def test_a_yaml_file_lists_the_contracts_sections_first(name, keys):
    shown = FILES[name]["sections"]
    assert [section["name"] for section in shown][:len(keys)] == list(keys)
    assert all(section["holds"] for section in shown)


def test_the_sections_a_run_needs_beyond_the_contracts_are_listed():
    assert {"starting_values", "index_of"} <= {section["name"] for section in FILES["scenarios"]["sections"]}


def test_nested_fields_come_from_the_contract():
    scenarios = {section["name"]: section["holds"] for section in FILES["scenarios"]["sections"]}
    assert all(field in scenarios["values"] for field in SCENARIO_VALUE_FIELDS)
    parameters = {section["name"]: section["holds"] for section in FILES["parameter_set"]["sections"]}
    assert all(field in parameters["portfolios"] for field in SEGMENT_PARAMETERS)


def test_every_reason_the_engine_can_reject_a_record_is_explained():
    named = {reason for rules in guide.RECORD_RULES.values() for _, reasons in rules for reason in reasons}
    assert named == set(Reason)


def test_a_rule_names_only_reasons_with_the_same_consequence():
    for rules in guide.RECORD_RULES.values():
        for text, reasons in rules:
            assert len({reason in RUN_BLOCKING_REASONS for reason in reasons}) == 1, text


def test_a_record_rule_says_what_the_engine_does():
    for name, rules in guide.RECORD_RULES.items():
        shown = {rule["text"]: rule["effect"] for rule in FILES[name]["rules"]}
        for text, reasons in rules:
            assert shown[text] == (guide.STOPS if reasons[0] in RUN_BLOCKING_REASONS else guide.LEFT_OUT), text


def test_every_way_a_file_can_stop_the_run_has_a_place():
    named = {block for table in (guide.FILE_RULES, guide.LATE_RULES) for rules in table.values()
             for _, blocks in rules for block in blocks}
    assert named | set(guide.GENERAL_BLOCKS) | NOT_ABOUT_THE_FILES == set(Block)


def test_the_rules_that_pass_the_checks_and_then_stop_the_run_are_shown_apart():
    for name, rules in guide.LATE_RULES.items():
        shown = {rule["text"]: rule["effect"] for rule in FILES[name]["rules"]}
        assert all(shown[text] == guide.LATE for text, _ in rules)


def test_an_unsecured_loan_is_told_what_ltv_needs():
    late = [rule["text"] for rule in FILES["facilities"]["rules"] if rule["effect"] == guide.LATE]
    assert any("not_applicable" in text and "ltv__status" in text for text in late)


def test_a_scenario_value_is_said_to_follow_its_unit():
    assert SCENARIO_UNITS["percent"] == 0.01 and SCENARIO_UNITS["decimal"] == 1.0
    warning = FILES["scenarios"]["warning"]
    assert "1.5 with unit percent" in warning and "0.015 with unit decimal" in warning


def test_the_collateral_list_and_the_price_indices_are_the_engines():
    columns = {column["name"]: column for column in FILES["facilities"]["columns"]}
    assert columns["collateral_type"]["values"] == list(COLLATERAL_INDEX)
    late = " ".join(rule["text"] for rule in FILES["scenarios"]["rules"] if rule["effect"] == guide.LATE)
    assert all(index in late for index in COLLATERAL_INDEX.values())


def test_what_no_check_catches_is_said_outright():
    assert "Fill in portfolio" in FILES["facilities"]["warning"]
    assert all(word in FILES["facilities"]["warning"] for word in ("regulatory_approach", *APPROACHES))
    assert "runs as linear" in FILES["parameter_set"]["warning"]
    assert all(profile in FILES["parameter_set"]["warning"] for profile in REPAYMENT_PROFILES)


def test_the_decimal_rule_is_kept_to_the_tables():
    line = next(text for text in PAGE["every_file"] if "5% is 0.05" in text)
    assert line.startswith("In the tables") and "own unit" in line


def test_allowed_values_come_from_the_contract():
    columns = {column["name"]: column for column in FILES["facilities"]["columns"]}
    assert columns["product"]["values"] == list(PRODUCTS)
    assert columns["ifrs_stage"]["values"] == ["1", "2", "3"]
    assert all(product in str(FILES["commitments"]["rules"]) for product in TERM_PRODUCTS)


def test_nothing_promises_that_a_column_may_be_blank():
    """The engine never reads the contract's nullable flag, so the guide does not state it."""
    assert not any("blank" in column for columns in (f["columns"] or [] for f in PAGE["files"]) for column in columns)


def test_the_status_words_are_the_engines():
    assert all(str(status) in " ".join(PAGE["every_file"]) for status in ALL_STATUSES)


def test_the_baseline_rule_names_the_scenario_the_room_requires():
    assert any(server.REQUIRED_SCENARIO in rule["text"] for rule in FILES["scenarios"]["rules"])


def test_the_page_carries_no_rule_codes():
    text = json.dumps(PAGE)
    assert not any(code in text for code in ("EAD-", "SCP-", "MIG-", "DAT-", "R2", "R3", "R4", "section 8"))


def test_the_page_offers_the_guide_and_not_several_files():
    page = server.PAGE.read_text(encoding="utf-8")
    assert "Add several files" not in page
    assert "What this step expects" in page and "/api/guide" in page
    assert 'id="files-tools"' not in page


def test_each_consequence_reads_as_what_happens_if_a_rule_fails():
    page = server.PAGE.read_text(encoding="utf-8")
    assert "These stop the run" not in page
    assert all(f"['{effect}', 'If not, " in page for effect in (guide.STOPS, guide.LATE, guide.LEFT_OUT))
