"""Tests of the small dataset and of the setting that chooses a dataset, run with the room's other tests:

    uv run pytest control_room

The full book must stay as it is, the sample must stay whole and run, and the page must open on the
book the setting names or not start.
"""

import json
import shutil
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
CHOSEN, OTHER = "a" * 16, "b" * 16
RETIRED: set[str] = set()  # sets a rebuild replaced; they stay committed, and the page no longer opens on them


def committed_sets() -> list[Path]:
    """Heroku receives what git holds, not whatever else is on this machine."""
    listed = subprocess.run(["git", "ls-files", "inputs"], cwd=ROOT, check=True, capture_output=True, text=True)
    names = {Path(line).parts[1] for line in listed.stdout.split()}
    return sorted(ROOT / "inputs" / name for name in names if server.nb.INPUT_SET_NAME.fullmatch(name))


def table(folder: Path, spec) -> pd.DataFrame:
    return pd.read_parquet(folder / spec.filename)


def document(folder: Path, spec) -> dict:
    return yaml.safe_load((folder / spec.filename).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def small() -> Path:
    return ROOT / "inputs" / server.BOOKS["small"]


def test_the_small_dataset_is_a_tenth_of_the_large_one(small):
    assert FULL.name == server.BOOKS["large"] and small != FULL
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


def test_the_setting_starts_small(small, tmp_path):
    assert server.DATASET == "small"
    assert server.Control(tmp_path).state()["opening"] == f"inputs/{small.name}"


def test_large_opens_the_full_book(tmp_path):
    assert server.Control(tmp_path, "large").state()["opening"] == f"inputs/{FULL.name}"


def test_the_page_opens_on_what_the_server_names():
    assert "newDocument(STATE.opening)" in server.PAGE.read_text(encoding="utf-8")


def test_heroku_receives_both_books():
    """DATASET can then change on the app with no new build."""
    left_out = ROOT / ".slugignore"
    skipped = left_out.read_text(encoding="utf-8").split() if left_out.exists() else []
    assert set(server.BOOKS.values()) <= {path.name for path in committed_sets()}
    assert not [name for name in server.BOOKS.values() if f"/inputs/{name}" in skipped]


@pytest.mark.parametrize("flags, variable, expected", [
    ([], None, "small"), ([], "large", "large"), (["--dataset", "large"], None, "large"),
    (["--dataset", "small"], "large", "small")])
def test_a_flag_beats_the_environment_and_the_environment_beats_the_default(flags, variable, expected, monkeypatch):
    seen = []

    def stop_at_listening(_runs_dir, _port, _host, dataset):
        seen.append(dataset)
        raise OSError("stopped here")

    monkeypatch.setattr(server, "serve", stop_at_listening)
    monkeypatch.delenv("DATASET", raising=False)
    if variable:
        monkeypatch.setenv("DATASET", variable)
    assert server.main(["--no-browser", *flags]) == 1
    assert seen == [expected]


@pytest.mark.parametrize("flags, variable", [(["--dataset", "medium"], None), ([], "Large"), ([], "")])
def test_a_wrong_setting_stops_the_server(flags, variable, monkeypatch, capsys):
    monkeypatch.delenv("DATASET", raising=False)
    if variable is not None:
        monkeypatch.setenv("DATASET", variable)
    with pytest.raises(SystemExit) as stopped:
        server.main(["--no-browser", "--port", "0", *flags])
    assert stopped.value.code == 2
    assert "small or large" in capsys.readouterr().err


def test_a_book_that_is_not_here_stops_the_server_rather_than_opening_another(monkeypatch, capsys):
    monkeypatch.delenv("DATASET", raising=False)
    monkeypatch.setitem(server.BOOKS, "small", "0" * 16)
    with pytest.raises(SystemExit) as stopped:
        server.main(["--no-browser", "--port", "0"])
    assert stopped.value.code == 2
    assert "inputs/0000000000000000" in capsys.readouterr().err


@pytest.fixture
def books(small, tmp_path, monkeypatch):
    """Two books in a folder of their own, free to break."""
    for setting, name in (("small", CHOSEN), ("large", OTHER)):
        shutil.copytree(small, tmp_path / name)
        monkeypatch.setitem(server.BOOKS, setting, name)
    monkeypatch.setattr(server.nb, "INPUTS_DIR", tmp_path)
    monkeypatch.delenv("DATASET", raising=False)
    return tmp_path


def stopped_saying(capsys) -> str:
    with pytest.raises(SystemExit) as stopped:
        server.main(["--no-browser", "--port", "0"])
    assert stopped.value.code == 2
    return capsys.readouterr().err


@pytest.mark.parametrize("name", ["scenarios.yaml", "parameter_set.yaml", "manifest.json", "obligors.parquet",
                                  "facilities.parquet"])
def test_an_unreadable_book_stops_the_server_with_a_message(books, name, capsys):
    (books / CHOSEN / name).write_bytes(b"a: [1")
    assert f"inputs/{CHOSEN}" in stopped_saying(capsys)


def test_a_book_without_its_manifest_is_not_taken_for_a_port_problem(books, capsys):
    (books / CHOSEN / "manifest.json").unlink()
    assert "could not listen" not in stopped_saying(capsys)


def test_a_book_the_engine_cannot_read_stops_the_server(books, capsys):
    path = books / CHOSEN / FACILITIES.filename
    pd.read_parquet(path).drop(columns="credit_status_date").to_parquet(path)
    assert "credit_status_date" in stopped_saying(capsys)


def test_a_broken_book_other_than_the_chosen_one_leaves_the_server_alone(books):
    (books / OTHER / "scenarios.yaml").write_bytes(b"a: [1")
    server.check_dataset("small")
    assert not next(row for row in server.input_inventory() if row["inputs"] == f"inputs/{OTHER}")["runnable"]


def test_every_committed_set_the_engine_can_read_is_a_book_or_retired():
    """A new set must be named, or the page stays on the one it replaced."""
    readable = {path.name for path in committed_sets() if not server.contract_gaps(path)}
    assert set(server.BOOKS.values()) <= readable
    assert readable - set(server.BOOKS.values()) <= RETIRED


@pytest.mark.parametrize("document", ["README.md", "docs/runbook.md", "docs/assumptions.md"])
def test_the_documents_name_the_current_books(document):
    text = (ROOT / document).read_text(encoding="utf-8")
    assert all(name in text for name in server.BOOKS.values())


def test_the_engine_runs_the_small_set(small, tmp_path):
    done = subprocess.run([sys.executable, "-m", "stress.cli", "run", "--inputs", f"inputs/{small.name}",
                           "--scenarios", "baseline,adverse", "--variant", "core", "--runs-dir", str(tmp_path)],
                          cwd=ROOT, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, done.stdout[-2000:]
