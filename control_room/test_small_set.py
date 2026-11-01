"""Tests of the small input set that Heroku hosts, run with the room's other tests:

    uv run pytest control_room

The full book must stay as it is and keep opening first; the sample must stay whole and run.
"""

import json
import subprocess
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import preflight
import server
import small_set

from stress.contracts.inputs import (
    COMMITMENTS,
    FACILITIES,
    OBLIGORS,
    OPENING_PROVISIONS,
    PARAMETER_SET,
    SCENARIOS,
    TTC_PD_MATRIX,
)

ROOT = server.ROOT
FULL = small_set.FULL


def committed_sets() -> list[Path]:
    """Heroku receives what git holds, not whatever else is on this machine."""
    listed = subprocess.run(["git", "ls-files", "inputs"], cwd=ROOT, check=True, capture_output=True, text=True)
    names = {Path(line).parts[1] for line in listed.stdout.split()}
    return sorted(ROOT / "inputs" / name for name in names if server.nb.INPUT_SET_NAME.fullmatch(name))


def hosted_sets() -> list[Path]:
    """What is left on Heroku once .slugignore has removed its folders."""
    left_out = (ROOT / ".slugignore").read_text(encoding="utf-8").split()
    return [path for path in committed_sets() if f"/inputs/{path.name}" not in left_out]


def table(folder: Path, spec) -> pd.DataFrame:
    return pd.read_parquet(folder / spec.filename)


def document(folder: Path, spec) -> dict:
    return yaml.safe_load((folder / spec.filename).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def small() -> Path:
    found = hosted_sets()
    assert len(found) == 1, found
    return found[0]


def test_heroku_gets_the_small_set_alone(small):
    assert small != FULL
    assert len(table(small, FACILITIES)) == pytest.approx(len(table(FULL, FACILITIES)) / small_set.SHARE, abs=10)


def test_each_portfolio_and_stage_keeps_a_tenth_and_never_vanishes(small):
    full = table(FULL, FACILITIES).groupby(small_set.CELL).size()
    kept = table(small, FACILITIES).groupby(small_set.CELL).size()
    assert kept.to_dict() == {cell: max(1, round(count / small_set.SHARE)) for cell, count in full.items()}


def stage_three_share(book: pd.DataFrame) -> float:
    return book.loc[book["ifrs_stage"] == 3, "gca"].sum() / book["gca"].sum()


def test_the_sample_is_a_tenth_of_the_book_and_keeps_its_stage_three_share(small):
    full, kept = table(FULL, FACILITIES), table(small, FACILITIES)
    assert kept["gca"].sum() == pytest.approx(full["gca"].sum() / small_set.SHARE, rel=0.06)
    assert stage_three_share(kept) == pytest.approx(stage_three_share(full), abs=0.005)


def test_every_segment_is_still_there(small):
    assert set(table(small, FACILITIES)["segment"]) == set(table(FULL, FACILITIES)["segment"])


def test_every_row_belongs_to_a_kept_facility(small):
    facilities = table(small, FACILITIES)
    ids = set(facilities["facility_id"])
    assert set(table(small, OPENING_PROVISIONS)["facility_id"]) == ids
    assert set(table(small, COMMITMENTS)["facility_id"]) <= ids
    assert set(table(small, OBLIGORS)["obligor_id"]) == set(facilities["obligor_id"])


@pytest.mark.parametrize("spec, key", [(FACILITIES, "facility_id"), (OBLIGORS, "obligor_id"), (COMMITMENTS, "facility_id"),
                                       (OPENING_PROVISIONS, "facility_id")])
def test_a_kept_row_is_the_full_book_row(small, spec, key):
    kept, full = table(small, spec), table(FULL, spec)
    same = full[full[key].isin(kept[key])].reset_index(drop=True)
    pd.testing.assert_frame_equal(kept.reset_index(drop=True), same)


def test_the_committed_set_is_what_the_script_chooses(small):
    assert set(small_set.chosen(table(FULL, FACILITIES))) == set(table(small, FACILITIES)["facility_id"])


def test_matrices_scenarios_and_parameters_are_the_full_books(small):
    pd.testing.assert_frame_equal(table(small, TTC_PD_MATRIX), table(FULL, TTC_PD_MATRIX))
    for spec in (SCENARIOS, PARAMETER_SET):
        assert document(small, spec) == document(FULL, spec)


def test_a_stage_with_no_facilities_reads_as_a_difference_not_a_fault(small):
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        groups = preflight.against_requirements(small)
    rows = [row for group in groups if group.title == "Stage PD calibration" for row in group.rows]
    empty = [row for row in rows if row["actual"] is None]
    assert empty and not any(row["ok"] for row in empty)
    json.dumps(rows, allow_nan=False)


def test_the_full_book_stays_untouched():
    manifest = json.loads((FULL / "manifest.json").read_text(encoding="utf-8"))
    assert FULL.name == manifest["input_set_hash"][:16]
    measured = preflight.differences(FULL)
    assert not measured["differing"] and not measured["unmeasured"]


def test_the_page_opens_on_the_full_book_while_it_is_here(small):
    assert small.name in {row["inputs"].split("/")[1] for row in server.input_inventory()}
    first = next(row for row in server.input_inventory() if row["runnable"])
    assert first["inputs"] == f"inputs/{FULL.name}"


def test_the_page_keeps_the_servers_order():
    opening = next(line for line in server.PAGE.read_text(encoding="utf-8").splitlines() if "const savedSets" in line)
    assert ".sort(" not in opening


def test_the_engine_runs_the_small_set(small, tmp_path):
    done = subprocess.run([sys.executable, "-m", "stress.cli", "run", "--inputs", f"inputs/{small.name}",
                           "--scenarios", "baseline,adverse", "--variant", "core", "--runs-dir", str(tmp_path)],
                          cwd=ROOT, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, done.stdout[-2000:]
