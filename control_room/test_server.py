"""Tests of the control room, run on their own:

    uv run pytest control_room

They sit beside it, not under tests/. The room is no part of the engine and proves no requirement,
and a marked test under tests/ would enter the generated traceability matrix. The first fixture
makes one real run through the page's own setup and job, which takes about three quarters of a minute.
"""

import dataclasses
import http.client
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pandas as pd
import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import preflight
import server

from stress import cli
from stress.contracts.errors import BlockingError
from stress.lineage import CODE_PATHS

nb = server.nb
INPUTS = f"inputs/{server.BOOKS['large']}"
SMALL = f"inputs/{server.BOOKS['small']}"
WALKTHROUGH = "docs/run-workflow/walkthrough.yaml"
RUN = {"inputs": INPUTS, "scenarios": ["baseline", "adverse"], "variant": "core", "balance_sheet": "static",
       "terminal_treatment": "z", "s2_treatment": "repriced", "horizon_runoff": "contractual", "lgd_path": "annual"}
PLAIN = {"schema_version": 1, "status": "SYNTHETIC", "source": "test", "version": "plain", "input_set_hash": "", "run": RUN}
# A derived scenario, a segment parameter and a terminal policy: nothing a flag can say.
CRISIS = {**PLAIN, "version": "test-crisis", "run": {**RUN, "scenarios": ["baseline", "adverse", "deeper"]},
          "scenarios": {"deeper": {"inherits": "adverse", "narrative": "A deeper 2027.", "overrides": [
              {"variable": "gdp_growth", "country": "*", "year": 2027, "value": -6.0, "unit": "percent", "value_type": "growth"}]}},
          "segments": {"P01": {"asset_correlation": 0.2}}, "terminal_policies": {"deeper": {"method": "flat"}}}


def with_hash(doc: dict) -> dict:
    return {**doc, "input_set_hash": preflight.base_of(server.ROOT / INPUTS)["hash"]}


def wait(job, seconds=180):
    end = time.time() + seconds
    while job.exit_code is None and time.time() < end:
        time.sleep(0.1)
    assert job.exit_code is not None, "the job did not finish"
    return job


def plan(doc, name="test"):
    return server.Control(nb.RUNS_DIR).plan({"document": doc, "name": name})


@pytest.fixture(scope="module")
def sealed(tmp_path_factory):
    """One real run of the crisis setup, started as the Start button starts it: saved, then run."""
    patch = pytest.MonkeyPatch()
    patch.setattr(server, "SPECS", tmp_path_factory.mktemp("specifications"))
    control = server.Control(tmp_path_factory.mktemp("runs"))
    job = wait(control.start_run({"document": with_hash(CRISIS), "name": "test-crisis"}))
    assert job.state == "sealed", list(job.lines)
    yield control, control.runs_dir / job.run_id
    patch.undo()


@pytest.fixture(scope="module")
def plain_run(tmp_path_factory):
    """One real run started from flags alone, on the small book: no specification is sealed with it.
    With it come the lines the engine printed, as the job read them."""
    control = server.Control(tmp_path_factory.mktemp("plain-runs"))
    job = wait(control.start_run({"document": {**PLAIN, "run": {**RUN, "inputs": SMALL}}, "name": "plain"}))
    assert job.state == "sealed", list(job.lines)
    return control, control.runs_dir / job.run_id, list(job.lines)


@pytest.fixture
def site(tmp_path):
    """The real server on a free port, over an empty runs folder."""
    running = server.serve(tmp_path, 0)
    threading.Thread(target=running.serve_forever, daemon=True).start()
    yield running
    running.shutdown()
    running.server_close()


@pytest.fixture
def temp_site():
    """The real server over a runs folder in the machine's temporary folder, with that folder. pytest's
    own folders are not always there: the gate puts them inside the repository (tests/ci_gate.py)."""
    with tempfile.TemporaryDirectory(prefix="room-runs-", ignore_cleanup_errors=True) as folder:
        running = server.serve(Path(folder), 0)
        threading.Thread(target=running.serve_forever, daemon=True).start()
        yield running, Path(folder)
        running.shutdown()
        running.server_close()


def call(running, method, path, body=None, **headers):
    connection = http.client.HTTPConnection(server.HOST, running.server_port, timeout=60)
    named = {name.replace("_", "-"): value for name, value in headers.items()}
    connection.request(method, path, body=body, headers=named)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response, payload


def post(running, path, form, **headers):
    return call(running, "POST", path, json.dumps(form), Content_Type="application/json", **headers)


def announce(running, path, length, **headers):
    """A POST that states its length and sends no body: what the server answers before it reads one."""
    connection = http.client.HTTPConnection(server.HOST, running.server_port, timeout=20)
    connection.putrequest("POST", path, skip_host="Host" in headers)
    connection.putheader("Content-Length", str(length))
    for name, value in headers.items():
        connection.putheader(name.replace("_", "-"), value)
    connection.endheaders()
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response, payload


def texts(value) -> list[str]:
    """Every text in an answer, wherever it sits."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in texts(item)]
    return [text for item in value for text in texts(item)] if isinstance(value, list) else []


def names_the_temporary_folder(value) -> bool:
    roots = {tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())}
    forms = {form for root in roots for form in (root, root.replace("\\", "/"), root.replace("\\", "\\\\"))}
    return any(form.lower() in text.lower() for text in texts(value) for form in forms)


# --- a run from the page is an ordinary sealed run --------------------------------------------------

def test_the_run_is_what_the_setup_said(sealed):
    _, folder = sealed
    view = server.run_view(folder)
    assert view["verified"] and view["status"] == "SYNTHETIC"
    assert view["scenarios"] == ["baseline", "adverse", "deeper"] and view["specification"] == "test-crisis"
    assert view["results"]["kpis"]["deeper"]["cumulative"] > view["results"]["kpis"]["adverse"]["cumulative"]
    sealed_copy = folder / "data" / "specification.yaml"
    assert sealed_copy.is_file() and "asset_correlation: 0.2" in sealed_copy.read_text(encoding="utf-8")


def test_the_summary_ties_to_the_sealed_headline(sealed):
    _, folder = sealed
    view = server.run_view(folder)
    tied = 0
    for line in view["headline_lines"]:
        row = server.HEADLINE.match(line)
        if row:
            kpi = view["results"]["kpis"][row[1]]
            shown = [f"{kpi[k]:,.1f}" for k in ("cumulative", "closing", "s3_gca")]
            assert row[2] == shown[0] == view["headline"][row[1]], "the figure the run history lists"
            assert shown == re.findall(r"EUR ([\d,.\-]+)m", line)
            assert f"{kpi['first_year']:,.1f}" == re.search(r"first year ([\d,.\-]+)m", line)[1]
            tied += 1
    assert tied == 3


@pytest.mark.parametrize("cumulative", [129.7, 1_129.7, -5.0, -1_005.25, 0.0])
def test_the_run_history_reads_a_charge_of_either_sign(tmp_path, cumulative):
    """A net release is a negative cumulative charge, and the history lists it as the engine wrote it."""
    line = (f"baseline: cumulative charge 2027-2029 EUR {cumulative:,.1f}m (first year {1.0:,.1f}m); "
            f"closing provisions 2029 EUR {300.0:,.1f}m; S3 GCA 2029 EUR {80.0:,.1f}m")  # as report.summary_lines writes it
    run_id = "20261109T1200Z-core-0a1b2c3d"
    (tmp_path / run_id).mkdir()
    config = {"inputs": "inputs/0000000000000000", "variant": "core", "scenarios": ["baseline"]}
    manifest = {"run_id": run_id, "status": "SYNTHETIC", "config": config, "input_set_hash": "0" * 64,
                "code_version": "x", "created_at": "2026-11-09T12:00:00+00:00", "summary": {"headline": [line]}}
    (tmp_path / run_id / server.RUN_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    assert server.list_runs(tmp_path)[0]["headline"] == {"baseline": f"{cumulative:,.1f}"}


def test_portfolios_and_stages_add_up_to_the_book(sealed):
    _, folder = sealed
    results = server.run_view(folder)["results"]
    for name in results["scenarios"]:
        total = sum(p["values"][name]["cumulative"] for p in results["portfolios"])
        assert total == pytest.approx(results["kpis"][name]["cumulative"], abs=0.01)
        for row in results["stages"][name]:
            assert sum(row["stock"].values()) == pytest.approx(row["gca"])


def test_a_rerun_from_the_page_reproduces_the_run(sealed):
    control, folder = sealed
    assert server.run_view(folder)["replay"] == {"possible": True}
    job = wait(control.start("rerun", *control.command(["rerun", "--run", control.run_argument(folder.name)])))
    assert job.state == "sealed", list(job.lines)
    assert job.outcome.startswith("reproduced: all")


def test_the_run_loads_back_as_the_setup_it_was_started_with(sealed):
    """Running again with changes: what comes back is exactly what went in."""
    control, folder = sealed
    loaded = server.setup_of({"run": folder.name}, control.runs_dir)
    doc = loaded["document"]
    assert doc["run"]["inputs"] == INPUTS and doc["scenarios"]["deeper"]["overrides"][0]["value"] == -6.0
    assert doc["segments"] == {"P01": {"asset_correlation": 0.2}} and doc["terminal_policies"] == {"deeper": {"method": "flat"}}
    written = (folder / "data" / "specification.yaml").read_text(encoding="utf-8").split("\n", 1)[1]
    assert server.specification_text(doc, server.SPECS) == written
    assert control.preflight({"document": doc, "name": loaded["name"]})["verdict"] == "ready"


def test_a_plain_run_loads_back_as_a_setup_that_can_be_changed(plain_run):
    """Running again with changes, from a run that had no specification. The setup that comes back
    carries a source, a version and its input set's hash, so the first change, which makes it a
    specification, still passes the engine's reading of one."""
    control, folder, _ = plain_run
    assert not (folder / "data" / "specification.yaml").exists()
    loaded = server.setup_of({"run": folder.name}, control.runs_dir)
    doc = loaded["document"]
    assert doc["run"]["inputs"] == SMALL and doc["run"]["scenarios"] == ["baseline", "adverse"]
    assert doc["source"].startswith("Control room, ") and doc["version"] == loaded["name"]
    assert doc["input_set_hash"] == preflight.base_of(server.ROOT / SMALL)["hash"]
    unchanged = control.preflight({"document": doc, "name": loaded["name"]})
    assert unchanged["verdict"] == "ready" and not unchanged["needs_specification"]
    changed = {**doc, "segments": {"P01": {"asset_correlation": 0.2}}}
    answer = control.preflight({"document": changed, "name": loaded["name"]})
    assert answer["needs_specification"] and answer["verdict"] == "ready", answer["blocked"]


def test_the_engine_names_its_run_folder_as_soon_as_it_opens_it(plain_run):
    """The page tells a run in progress from one that did not finish by the folder the job is writing.
    The job learns it from R1's own line, so that line must still say it."""
    _, folder, lines = plain_run
    assert [found[1] for found in map(server.OPENED_LINE.match, lines) if found] == [folder.name]
    job = server.Job("run", "stress run")
    job.add(next(line for line in lines if server.OPENED_LINE.match(line)))
    assert job.run_id == folder.name and job.exit_code is None


def test_a_folder_still_being_written_is_in_progress_and_not_a_run_that_did_not_finish(tmp_path):
    control = server.Control(tmp_path)
    writing, abandoned = "20261109T1200Z-core-0a1b2c3d", "20261108T0900Z-core-11111111"
    for name in (writing, abandoned):
        (tmp_path / name).mkdir()
    assert not any(run.get("in_progress") for run in control.state()["runs"])
    control.job = server.Job("run", "stress run")
    control.job.add(f"stress.R1  run {writing} opened in runs/{writing}")
    listed = {run["run_id"]: run for run in control.state()["runs"]}
    assert listed[writing]["status"] == listed[abandoned]["status"] == "UNSEALED"
    assert listed[writing]["in_progress"] is True and listed[abandoned]["in_progress"] is False
    control.job.finish(1)
    assert not any(run.get("in_progress") for run in control.state()["runs"]), "a job that ended writes no more"
    page = server.PAGE.read_text(encoding="utf-8")
    assert "run.in_progress ? 'In progress' : 'Did not finish'" in page


def test_a_blocked_run_gives_its_reason_and_no_figures(tmp_path):
    subprocess.run([sys.executable, "-m", "stress.cli", "run", "--inputs", INPUTS, "--variant", "annuity",
                    "--horizon-runoff", "replaced", "--runs-dir", str(tmp_path), "-q"],
                   cwd=server.ROOT, capture_output=True, check=False)
    folder = next(tmp_path.iterdir())
    view = server.run_view(folder)
    assert view["status"] == "BLOCKED" and view["blocked"]["step"] == "R5"
    assert view["results"] is None


def test_a_changed_sealed_file_is_refused(sealed, site):
    _, folder = sealed
    copy = site.RequestHandlerClass.control.runs_dir / folder.name
    shutil.copytree(folder, copy)
    report = copy / "results" / "reports" / "impairment.csv"
    report.chmod(stat.S_IWRITE | stat.S_IREAD)
    report.write_text(report.read_text(encoding="utf-8").replace("adverse", "ADVERSE", 1), encoding="utf-8")
    response, payload = call(site, "GET", f"/api/runs/{folder.name}")
    assert response.status == 409 and b"RUN_INTEGRITY" in payload


def test_run_files_are_the_sealed_files(sealed, site):
    _, folder = sealed
    runs = site.RequestHandlerClass.control.runs_dir
    if not (runs / folder.name).exists():
        shutil.copytree(folder, runs / folder.name)
    for name, (relative, _) in server.RUN_FILES.items():
        response, payload = call(site, "GET", f"/api/runs/{folder.name}/{name}")
        assert response.status == 200 and payload == (folder / relative).read_bytes()


# --- adding files by hand, packaging and sign-off ----------------------------------------------------

def add(control, name, path, original=None):
    """A file as the page sends it: its bytes, for one of the six rows."""
    data = Path(path).read_bytes()
    return control.add_file(name, original or Path(path).name, io.BytesIO(data), len(data))


def committed_set_in(tmp_path, monkeypatch) -> Path:
    copy = tmp_path / "inputs" / INPUTS.split("/")[1]
    shutil.copytree(server.ROOT / INPUTS, copy)
    monkeypatch.setattr(nb, "INPUTS_DIR", tmp_path / "inputs")
    return copy


def test_a_file_is_checked_against_its_place_when_it_is_added(tmp_path):
    control = server.Control(tmp_path)
    good = add(control, "facilities", server.ROOT / INPUTS / "facilities.parquet", "facilities_oct.parquet")
    assert good["problem"] is None and good["rows"] == 10_000 and good["original"] == "facilities_oct.parquet"
    assert "Columns missing" in add(control, "facilities", server.ROOT / INPUTS / "obligors.parquet")["problem"]
    assert "not a readable Parquet" in add(control, "facilities", server.ROOT / INPUTS / "scenarios.yaml")["problem"]
    assert "Sections missing" in add(control, "scenarios", server.ROOT / INPUTS / "parameter_set.yaml")["problem"]
    assert "not a readable YAML" in add(control, "scenarios", server.ROOT / INPUTS / "facilities.parquet")["problem"]
    with pytest.raises(server.Refused):
        add(control, "nothing", server.ROOT / INPUTS / "facilities.parquet")


def test_an_added_file_never_chooses_where_it_lands(tmp_path):
    control = server.Control(tmp_path)
    view = add(control, "scenarios", server.ROOT / INPUTS / "scenarios.yaml", "..\\..\\pyproject.yaml")
    assert view["original"] == "pyproject.yaml"
    assert [p.name for p in control.held.iterdir()] == ["scenarios.yaml"]


def test_a_broken_transfer_leaves_the_earlier_file(tmp_path):
    control = server.Control(tmp_path)
    source = server.ROOT / INPUTS / "scenarios.yaml"
    view = add(control, "scenarios", source)
    with pytest.raises(server.Refused):
        control.add_file("scenarios", "x.yaml", io.BytesIO(b"cut"), 1000)
    assert control.added["scenarios"] is view
    assert (control.held / "scenarios.yaml").read_bytes() == source.read_bytes()
    assert [p.name for p in control.held.iterdir()] == ["scenarios.yaml"], "the broken transfer left no file of its own"


class Meeting(io.BytesIO):
    """A transfer that stops halfway until the other transfer is halfway too."""

    def __init__(self, data: bytes, halfway: threading.Barrier):
        super().__init__(data)
        self.halfway, self.met = halfway, False

    def read(self, size=-1):
        if self.tell() >= len(self.getvalue()) // 2 and not self.met:
            self.met = True
            self.halfway.wait(timeout=20)
        return super().read(min(size, max(1, len(self.getvalue()) // 2)))


def test_two_transfers_to_one_row_at_once_each_arrive_whole(tmp_path):
    """Each writes a file of its own, so neither can write into the other's. The row ends with one of
    the two files, whole, and with the line that belongs to it."""
    control = server.Control(tmp_path)
    first = (server.ROOT / INPUTS / "scenarios.yaml").read_bytes()
    second = first + b"\n# a second version, sent at the same moment\n"
    halfway = threading.Barrier(2)
    answers, faults = {}, []

    def send(label, data):
        try:
            answers[label] = control.add_file("scenarios", f"{label}.yaml", Meeting(data, halfway), len(data))
        except Exception as exc:  # noqa: BLE001 - whatever went wrong is the finding
            faults.append(exc)

    senders = [threading.Thread(target=send, args=pair) for pair in (("first", first), ("second", second))]
    for sender in senders:
        sender.start()
    for sender in senders:
        sender.join(timeout=60)
    assert not faults and set(answers) == {"first", "second"}
    assert all(answer["problem"] is None for answer in answers.values())
    held = (control.held / "scenarios.yaml").read_bytes()
    assert held in (first, second), "one of the two, and not a mix of both"
    kept = control.added["scenarios"]
    assert kept["bytes"] == len(held) and kept["original"] == ("first.yaml" if held == first else "second.yaml")
    assert [p.name for p in control.held.iterdir()] == ["scenarios.yaml"]


def test_files_added_by_hand_become_a_set_and_leave_the_list(tmp_path, monkeypatch):
    """The committed set's six files, added one by one, with its own matrix files, package to the very
    same input set. Without a saved set there are no matrix files, and nothing is packaged."""
    committed_set_in(tmp_path, monkeypatch)
    control = server.Control(tmp_path)
    for role in preflight.file_roles():
        add(control, role["name"], server.ROOT / INPUTS / role["file"])
    with pytest.raises(server.Refused, match="still missing: Rating transitions"):
        control.use_files({})
    job = wait(control.use_files({"base": INPUTS}))
    assert job.state == "done" and job.input_set == INPUTS.split("/")[1], list(job.lines)
    saved = tmp_path / "inputs" / job.input_set
    assert (saved / "manifest.json").is_file()
    assert json.loads((saved / "approval.json").read_text())["status"] == "PENDING_OWNER_APPROVAL"
    assert control.added == {} and not (control.held / "facilities.parquet").exists()


def test_replacing_one_file_keeps_the_other_five_the_matrix_files_and_the_saved_set(tmp_path, monkeypatch):
    original = committed_set_in(tmp_path, monkeypatch)
    before = {p.relative_to(original).as_posix(): p.read_bytes() for p in original.rglob("*") if p.is_file()}
    changed = tmp_path / "scenarios_new.yaml"
    changed.write_text((original / "scenarios.yaml").read_text(encoding="utf-8") + "\n# revised\n", encoding="utf-8")
    table = pd.read_parquet(original / "obligors.parquet")
    table.loc[0, "principal_activity"] = "Changed by hand"
    table.to_parquet(tmp_path / "obligors_new.parquet", index=False)
    control = server.Control(tmp_path)
    assert add(control, "obligors", tmp_path / "obligors_new.parquet")["problem"] is None
    job = wait(control.use_files({"base": INPUTS}))
    assert job.state == "done" and job.input_set != original.name, list(job.lines)
    fresh = tmp_path / "inputs" / job.input_set
    assert pd.read_parquet(fresh / "obligors.parquet").loc[0, "principal_activity"] == "Changed by hand"
    assert (fresh / "scenarios.yaml").read_bytes() == (original / "scenarios.yaml").read_bytes()
    assert {p.relative_to(original).as_posix(): p.read_bytes() for p in original.rglob("*") if p.is_file()} == before


def test_files_that_are_not_complete_or_not_right_are_not_packaged(tmp_path, monkeypatch):
    committed_set_in(tmp_path, monkeypatch)
    control = server.Control(tmp_path)
    add(control, "obligors", server.ROOT / INPUTS / "obligors.parquet")
    with pytest.raises(server.Refused, match="still missing: Facilities"):
        control.use_files({})
    add(control, "commitments", server.ROOT / INPUTS / "obligors.parquet")
    with pytest.raises(server.Refused, match="Commitments: Columns missing"):
        control.use_files({"base": INPUTS})
    with pytest.raises(server.Refused):
        control.use_files({"base": "inputs/0000000000000000"})
    assert control.job is None


def test_a_file_added_during_the_packaging_stays_on_the_list(tmp_path, monkeypatch):
    committed_set_in(tmp_path, monkeypatch)
    control = server.Control(tmp_path)
    add(control, "obligors", server.ROOT / INPUTS / "obligors.parquet")
    job = control.use_files({"base": INPUTS})
    add(control, "obligors", server.ROOT / INPUTS / "obligors.parquet", "newer.parquet")
    with pytest.raises(server.Busy):
        control.use_files({"base": INPUTS})
    wait(job)
    assert control.added["obligors"]["original"] == "newer.parquet"


def test_a_yaml_file_with_runaway_aliases_is_named_and_cannot_be_packaged(tmp_path, monkeypatch):
    """Ten aliases to ten aliases, twelve levels deep: a few hundred bytes that stand for a million
    million values. The file is named as not read when it is added, and it joins no set."""
    committed_set_in(tmp_path, monkeypatch)
    control = server.Control(tmp_path)
    levels = ["a0: &a0 [" + ", ".join(["x"] * 10) + "]"]
    levels += [f"a{n}: &a{n} [" + ", ".join([f"*a{n - 1}"] * 10) + "]" for n in range(1, 12)]
    data = (server.ROOT / INPUTS / "scenarios.yaml").read_bytes() + ("\n".join(levels) + "\n").encode()
    began = time.perf_counter()
    view = control.add_file("scenarios", "scenarios.yaml", io.BytesIO(data), len(data))
    assert "aliases expand" in view["problem"] and time.perf_counter() - began < 30
    with pytest.raises(server.Refused, match="Scenarios: .*aliases expand"):
        control.use_files({"base": INPUTS})
    assert control.job is None and sorted(p.name for p in (tmp_path / "inputs").iterdir()) == [INPUTS.split("/")[1]]


@pytest.mark.parametrize("spoil", [
    lambda scenarios, parameters: scenarios["scenarios"][1].update(label=float("nan")),
    lambda scenarios, parameters: parameters["variants"]["core"].update(label=float("nan")),
    lambda scenarios, parameters: scenarios["scenarios"][0].update(label=[["a"] * 10] * 10),
], ids=["a scenario labelled .nan", "a variant labelled .nan", "a label that is a list"])
def test_a_set_the_page_cannot_list_is_shown_as_unreadable_and_the_state_still_loads(tmp_path, monkeypatch, spoil):
    """A label that is not text has no place in the state every visitor loads: .nan has no JSON form at
    all. That one set is listed as unreadable, the others stay, and the state is served."""
    good = committed_set_in(tmp_path, monkeypatch)
    bad = tmp_path / "inputs" / ("f" * 16)
    shutil.copytree(good, bad)
    scenarios = yaml.safe_load((bad / "scenarios.yaml").read_text(encoding="utf-8"))
    parameters = yaml.safe_load((bad / "parameter_set.yaml").read_text(encoding="utf-8"))
    spoil(scenarios, parameters)
    (bad / "scenarios.yaml").write_text(yaml.safe_dump(scenarios, sort_keys=False), encoding="utf-8")
    (bad / "parameter_set.yaml").write_text(yaml.safe_dump(parameters, sort_keys=False), encoding="utf-8")
    state = server.Control(tmp_path, "large").state()
    json.dumps(state, allow_nan=False)
    rows = {row["inputs"]: row for row in state["inputs"]}
    assert rows[INPUTS]["runnable"] and rows[INPUTS]["scenarios"]
    spoilt = rows[f"inputs/{bad.name}"]
    assert not spoilt["runnable"] and spoilt["facilities"] is None and "unreadable" in spoilt["gaps"][0]
    assert spoilt["scenarios"] == [] and spoilt["variants"] == []


def test_older_sets_say_in_words_why_they_cannot_run():
    rows = server.input_inventory()
    assert next(r for r in rows if r["inputs"] == INPUTS)["why_not"] is None
    older = [r for r in rows if not r["runnable"]]
    assert older and all("Facilities file has no credit_status_date column" in r["why_not"]
                         or "Parameters file has no portfolios section" in r["why_not"] for r in older)
    assert any("Parameters file has no portfolios section" in r["why_not"] for r in older)
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r["saved_at"]) for r in rows)


def test_approval_is_recorded_by_the_one_off_step_and_nothing_else_changes(tmp_path, monkeypatch):
    copy = committed_set_in(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "ROOT", tmp_path)  # a run's paths are read from here
    before = {p.relative_to(copy).as_posix(): p.read_bytes() for p in copy.rglob("*")
              if p.is_file() and p.name != "approval.json"}
    job = wait(server.Control(tmp_path).approve({"inputs": INPUTS, "approver": "O. Wner"}))
    assert job.state == "done", list(job.lines)
    approval = json.loads((copy / "approval.json").read_text(encoding="utf-8"))
    assert approval["status"] == "APPROVED" and approval["approved_by"] == "O. Wner"
    assert {p.relative_to(copy).as_posix(): p.read_bytes() for p in copy.rglob("*")
              if p.is_file() and p.name != "approval.json"} == before
    for bad in ({"inputs": "inputs/0000000000000000", "approver": "x"}, {"inputs": INPUTS, "approver": "x; rm"},
                {"inputs": INPUTS, "approver": ""}):
        with pytest.raises(server.Refused):
            server.Control(tmp_path).approve(bad)


# --- the setup: flags for a plain run, a file for the rest, and only what is on offer ------------------

def test_a_plain_setup_is_the_documented_command():
    _, flags, _ = plan(PLAIN)
    assert flags is not None
    _, shown = server.Control(nb.RUNS_DIR).command(flags)
    assert shown == f"uv run stress run --inputs {INPUTS} --scenarios baseline,adverse --variant core"


def test_a_changed_reading_reaches_the_command():
    _, flags, _ = plan({**PLAIN, "run": {**RUN, "s2_treatment": "held", "lgd_path": "trough"}})
    assert flags[-4:] == ["--s2-treatment", "held", "--lgd-path", "trough"]


def test_what_a_flag_cannot_say_goes_through_a_file():
    _, flags, name = plan(CRISIS, "deeper")
    assert flags is None and name == "deeper"
    _, flags, _ = plan({**PLAIN, "run": {**RUN, "balance_sheet": "dynamic"}})
    assert flags is None, "dynamic volumes live in a specification"
    _, flags, _ = plan({**PLAIN, "segments": {}, "scenarios": {}})
    assert flags is not None, "an empty section is no section"


@pytest.mark.parametrize("doc", [
    {**PLAIN, "run": {**RUN, "variant": "core --mode regulatory"}},
    {**PLAIN, "run": {**RUN, "inputs": "inputs/514ed0e86e3dc760"}},  # older contract: R2 would block
    {**PLAIN, "run": {**RUN, "inputs": "inputs/bank"}},
    {**PLAIN, "run": {**RUN, "inputs": "../pyproject.toml"}},
    {**PLAIN, "run": {**RUN, "scenarios": ["adverse"]}},  # R4 blocks without baseline
    {**PLAIN, "run": {**RUN, "scenarios": "baseline"}},
    {**PLAIN, "run": {**RUN, "scenarios": []}},
    {**PLAIN, "run": {**RUN, "s2_treatment": "anything"}},
    {**PLAIN, "run": {**RUN, "variant": "annuity", "horizon_runoff": "replaced"}},  # R5 blocks: bullet only
    {**PLAIN, "run": {**RUN, "analysis": "pyproject.toml"}},
    {**PLAIN, "run": {**RUN, "analysis": "inputs/bank/anything.yaml"}},
    {**PLAIN, "run": {**RUN, "runs_dir": "/elsewhere"}},
    {**PLAIN, "nonsense": {}},
    {**PLAIN, "segments": []},
    {"run": "not a mapping"},
    "not a document",
    # A setup that runs from a specification: its variant names the run folder all the same.
    {**CRISIS, "run": {**CRISIS["run"], "variant": "x/../../escaped"}},
    {**CRISIS, "run": {**CRISIS["run"], "variant": "nothing"}},
    {**CRISIS, "run": {**CRISIS["run"], "variant": ["core"]}},
    {**PLAIN, "run": {**RUN, "balance_sheet": "dynamic", "variant": "..\\escaped"}},
])
def test_a_setup_outside_the_offer_is_refused(doc):
    with pytest.raises(server.Refused):
        plan(doc)


def test_a_variant_the_set_does_not_hold_is_refused_before_anything_is_checked_or_written(tmp_path, monkeypatch):
    """With flags the variant was always checked. With a specification it reached the engine, which
    names the run folder by it before it has judged anything. Now neither the sanity checks nor Start
    take it, and Start writes no file."""
    monkeypatch.setattr(server, "SPECS", tmp_path / "specifications")
    monkeypatch.setattr(preflight, "dry_run", lambda config: pytest.fail("the engine was asked"))
    control = server.Control(tmp_path / "runs")
    form = {"document": {**with_hash(CRISIS), "run": {**CRISIS["run"], "variant": "x/../../escaped"}}, "name": "escape"}
    for action in (control.preflight, control.start_run):
        with pytest.raises(server.Refused, match="variant .* is not on offer"):
            action(form)
    assert control.job is None and not (tmp_path / "specifications").exists()
    doc, flags, _ = plan({**CRISIS, "run": {**CRISIS["run"], "variant": "annuity"}})
    assert flags is None and doc["run"]["variant"] == "annuity", "a variant of the set is taken on this path too"


def test_a_start_refused_because_a_job_is_in_progress_writes_nothing(tmp_path, monkeypatch):
    """The setup is saved as part of the start, never before it. A second visitor's Start, refused,
    must not replace the file the first visitor's run is about to read."""
    monkeypatch.setattr(server, "SPECS", tmp_path / "specifications")
    control = server.Control(tmp_path / "runs")
    first = server.save_specification("shared-name", with_hash(CRISIS))  # what the first visitor's Start wrote
    before = first.read_bytes()
    running = control.start("run", [sys.executable, "-c", "import time; time.sleep(3)"], "the first visitor's run")
    other = {**with_hash(CRISIS), "segments": {"P01": {"asset_correlation": 0.99}}}
    for name in ("shared-name", "another-name"):
        with pytest.raises(server.Busy):
            control.start_run({"document": other, "name": name})
    assert first.read_bytes() == before
    assert sorted(p.name for p in (tmp_path / "specifications").iterdir()) == ["shared-name.yaml"]
    wait(running)


def test_the_sanity_checks_do_not_need_the_temporary_folder_on_the_repositorys_drive(tmp_path, monkeypatch):
    """The check writes its specification into a temporary folder, which on Windows can sit on another
    drive than the repository. No relative path leads from one drive to another, so the file states
    its input set, and its analysis package, in full."""
    relative = os.path.relpath

    def across_drives(path, start=os.curdir):
        if "stress-preflight-" in str(start):
            raise ValueError("path is on mount 'D:', start on mount 'C:'")
        return relative(path, start)

    monkeypatch.setattr(os.path, "relpath", across_drives)
    stated = {}
    judge = preflight.dry_run

    def reading(config):
        stated.update(yaml.safe_load(Path(config.specification).read_text(encoding="utf-8"))["run"])
        return judge(config)

    monkeypatch.setattr(preflight, "dry_run", reading)
    doc = {**CRISIS, "run": {**CRISIS["run"], "inputs": SMALL},
           "input_set_hash": preflight.base_of(server.ROOT / SMALL)["hash"]}
    answer = server.Control(tmp_path).preflight({"document": doc, "name": "another-drive"})
    assert answer["needs_specification"] and answer["verdict"] == "ready", answer["blocked"] or answer["fault"]
    assert Path(stated["inputs"]).is_absolute() and Path(stated["inputs"]) == server.ROOT / SMALL
    saved = yaml.safe_load(answer["yaml"])["run"]["inputs"]
    assert not Path(saved).is_absolute() and saved == server.relative_to_folder(server.ROOT / SMALL, server.SPECS), \
        "the setup to be saved still states its paths from its own folder"
    with_analysis = {**doc, "run": {**doc["run"], "analysis": "docs/examples/analysis.yaml"}}
    full = yaml.safe_load(server.specification_text(with_analysis, None))["run"]
    assert Path(full["analysis"]) == server.ROOT / "docs/examples/analysis.yaml" and Path(full["inputs"]).is_absolute()


def test_a_setup_that_names_no_scenarios_is_checked_with_the_ones_the_engine_would_run(tmp_path, monkeypatch):
    """`stress run --specification` runs baseline and adverse when the file names none. The sanity
    checks build the run as the command does, so they judge what Start would start."""
    built = []

    def stop_here(config, runs_dir):
        built.append(config)
        raise BlockingError("R1", "STOPPED_BY_THE_TEST", "the configuration is all this test needs")

    monkeypatch.setattr(cli, "execute", stop_here)
    path = tmp_path / "specification.yaml"
    assert cli.cmd_run(cli.build_parser().parse_args(["run", "--specification", str(path)])) == cli.EXIT_BLOCKED
    assert dataclasses.asdict(built[0]) == dataclasses.asdict(server.specification_config(path))
    assert built[0].scenarios == server.ENGINE_SCENARIOS and built[0].variant == server.ENGINE_VARIANT
    silent = {**with_hash(CRISIS), "run": {**CRISIS["run"], "inputs": SMALL, "scenarios": []}, "scenarios": {},
              "terminal_policies": {}, "input_set_hash": preflight.base_of(server.ROOT / SMALL)["hash"]}
    control = server.Control(tmp_path)
    answer = control.preflight({"document": silent, "name": "silent"})
    assert answer["needs_specification"] and "scenarios:" not in answer["yaml"].split("segments:")[0]
    assert {row["scenario"] for row in answer["z"]} == set(server.ENGINE_SCENARIOS)
    assert tuple(control.state()["default_scenarios"]) == server.ENGINE_SCENARIOS
    page = server.PAGE.read_text(encoding="utf-8")
    assert "if (!DOC.run.scenarios?.length) DOC.run.scenarios = [...STATE.default_scenarios];" in page
    assert page.count("adopt(answer.document)") == 2, "a setup loaded from a run, and one applied as YAML"


@pytest.mark.parametrize("name", ["../escape", "docs/x", "a b", "", "x" * 65, None])
def test_a_setup_name_is_one_file_name(name):
    with pytest.raises(server.Refused):
        server.checked_name(name)


def test_saving_writes_only_under_the_specifications_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SPECS", tmp_path / "specifications")
    path = server.save_specification("a.b-c_1", with_hash(CRISIS))
    assert path == tmp_path / "specifications" / "a.b-c_1.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Written by the control room")
    doc = preflight.parse_yaml(text, path.parent)
    assert doc["run"]["inputs"] == INPUTS and doc["scenarios"] == CRISIS["scenarios"]
    with pytest.raises(server.Refused):
        server.save_specification("../escape", with_hash(CRISIS))
    assert sorted(p.name for p in (tmp_path / "specifications").iterdir()) == ["a.b-c_1.yaml"]


@pytest.mark.parametrize("query", [{"run": "../../pyproject.toml"}, {"spec": WALKTHROUGH}, {}])
def test_only_a_run_of_this_room_loads_as_a_setup(query):
    with pytest.raises(server.Refused):
        server.setup_of(query, nb.RUNS_DIR)


def test_only_folders_named_by_a_hash_are_input_sets(tmp_path, monkeypatch):
    (tmp_path / "bank").mkdir()
    (tmp_path / "bank" / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(nb, "INPUTS_DIR", tmp_path)
    assert server.input_inventory() == []


def test_the_contract_decides_which_input_sets_are_usable():
    usable = {row["inputs"]: row["runnable"] for row in server.input_inventory()}
    assert usable[INPUTS] and not usable["inputs/514ed0e86e3dc760"]


def test_the_room_is_outside_the_engine_identity():
    """code_version hashes these paths, so a file in them would change every later run ID."""
    assert not any(HERE.is_relative_to(server.ROOT / path) for path in CODE_PATHS)


# --- the job --------------------------------------------------------------------------------------

def test_a_job_follows_the_engine_log():
    job = server.Job("run", "stress run")
    for line in ("stress.R2  start: load inputs", "stress.R2  done in 1.0 s",
                 "stress.R7  start: project the year (adverse 2028)", "stress.R11 sealing the run as SYNTHETIC",
                 "run 20261031T2029Z-core-3e7f2cd1: SYNTHETIC"):
        job.add(line)
    assert job.reached == ["R1", "R2", "R7", "R11"]
    assert job.step == "R11" and job.detail == server.STEPS["R11"]
    assert job.run_id == "20261031T2029Z-core-3e7f2cd1"
    packaging = server.Job("package", "package")
    packaging.add("input set inputs/57bf340df85d5a54")
    assert packaging.input_set == "57bf340df85d5a54"


@pytest.mark.parametrize(("kind", "code", "state"), [
    ("run", 0, "sealed"), ("run", 1, "fault"), ("run", 2, "blocked"), ("rerun", 3, "not_reproduced"),
    ("package", 0, "done"), ("approve", 1, "fault"),
])
def test_the_exit_code_decides_the_outcome(kind, code, state):
    job = server.Job(kind, kind)
    job.finish(code)
    assert job.state == state


def test_one_job_at_a_time(tmp_path):
    control = server.Control(tmp_path)
    slow = [sys.executable, "-c", "import time; time.sleep(1.5)"]
    job = control.start("run", slow, "slow")
    with pytest.raises(server.Busy):
        control.start("run", slow, "slow")
    wait(job)
    wait(control.start("run", [sys.executable, "-c", "pass"], "quick"))


def test_a_job_ends_even_if_what_follows_it_fails(tmp_path):
    """A job left as running would refuse every later start, for everyone, until the server restarts."""
    control = server.Control(tmp_path)

    def fails():
        raise OSError("the held file could not be removed")

    job = wait(control.start("package", [sys.executable, "-c", "print('input set inputs/0123456789abcdef')"], "package",
                             after=fails), 30)
    assert job.state == "done" and job.input_set == "0123456789abcdef", "the step itself went through"
    assert "the held file could not be removed" in job.as_dict()["log"][-1]
    wait(control.start("run", [sys.executable, "-c", "pass"], "the next job starts"))


@pytest.mark.parametrize(("lines", "shown"), [
    (["stress.R5     BLOCKED STATIC_BALANCE: replaced works on bullet schedules only",
      "run 20261109T1200Z-annuity+replaced-0a1b2c3d: BLOCKED", "folder runs/20261109T1200Z-annuity+replaced-0a1b2c3d",
      "blocked at R5: STATIC_BALANCE: replaced works on bullet schedules only"],
     "replaced works on bullet schedules only"),
    (["stress.R1     blocked: INVALID_ARGUMENT: no scenario requested",
      "stress     [R1] INVALID_ARGUMENT: no scenario requested"], "no scenario requested"),
    (["blocked at engine: INTERNAL_ERROR: KeyError: 'portfolios'"], "KeyError: 'portfolios'"),
    (["NOT reproduced: 3 output(s) differ"], "NOT reproduced: 3 output(s) differ"),
    (["Traceback (most recent call last):", "ValueError: no such thing"], "ValueError: no such thing"),
])
def test_a_stopped_job_shows_the_engines_message_without_its_step_and_code(lines, shown):
    """As step 4 shows a sealed run that stopped: the words. The step and the block code stay in the log."""
    job = server.Job("run", "stress run")
    for line in lines:
        job.add(line)
    job.finish(2)
    assert job.as_dict()["message"] == shown and job.as_dict()["log"] == lines


def test_a_real_block_reads_as_its_message_on_the_page(tmp_path):
    """The engine's own lines, from a run that R5 stops, through the job the page follows."""
    control = server.Control(tmp_path)
    job = wait(control.start("run", *control.command(["run", "--inputs", SMALL, "--variant", "annuity",
                                                      "--horizon-runoff", "replaced"])))
    assert job.state == "blocked", list(job.lines)
    sealed = server.run_view(tmp_path / job.run_id)["blocked"]
    assert job.as_dict()["message"] == sealed["message"] and sealed["code"] not in job.as_dict()["message"]


# --- requests -------------------------------------------------------------------------------------

def test_the_page_is_served_with_its_policy(site):
    response, payload = call(site, "GET", "/")
    assert response.status == 200 and b"control room" in payload
    assert "default-src 'none'" in response.getheader("Content-Security-Policy")
    response, payload = call(site, "GET", "/api/job")
    assert json.loads(payload) == {"state": "idle"}


def test_another_host_is_refused(site):
    """DNS rebinding: a foreign name that resolves to this address must not read anything."""
    assert call(site, "GET", "/api/state", Host="attacker.example")[0].status == 403


def test_another_site_cannot_start_anything(site):
    for path, form in (("/api/start", {"document": PLAIN}), ("/api/use-files", {"base": INPUTS}),
                       ("/api/remove-file", {"name": "facilities"}),
                       ("/api/approve", {"inputs": INPUTS, "approver": "x"})):
        response, _ = post(site, path, form, Origin="https://attacker.example")
        assert response.status == 403
    response, _ = call(site, "POST", "/api/files/scenarios", b"x", Content_Type="application/octet-stream",
                       Origin="https://attacker.example")
    assert response.status == 403
    assert site.RequestHandlerClass.control.job is None and site.RequestHandlerClass.control.added == {}


def test_a_file_arrives_as_bytes_and_shows_in_the_state(site):
    data = (server.ROOT / INPUTS / "scenarios.yaml").read_bytes()
    response, _ = call(site, "POST", "/api/files/scenarios", data, Content_Type="text/plain")
    assert response.status == 415
    response, _ = call(site, "POST", "/api/files/scenarios", b"", Content_Type="application/octet-stream")
    assert response.status == 413
    response, _ = call(site, "POST", "/api/files/nothing", b"x", Content_Type="application/octet-stream")
    assert response.status == 400
    response, payload = call(site, "POST", "/api/files/scenarios", data, Content_Type="application/octet-stream",
                             X_File_Name="my%20paths.yaml")
    assert response.status == 200 and json.loads(payload)["original"] == "my paths.yaml"
    _, payload = call(site, "GET", "/api/state")
    state = json.loads(payload)
    assert state["added"]["scenarios"]["problem"] is None and "repo" not in state and "files" not in state
    assert state["anchor"] == "baseline" and "typical_seconds" not in state
    assert [role["label"] for role in state["roles"]][:2] == ["Facilities", "Obligors"]
    assert {role["limit"] for role in state["roles"]} == {server.FILE_LIMIT}, "a local page takes a file of any likely size"
    response, payload = post(site, "/api/remove-file", {"name": "scenarios"})
    assert response.status == 200 and json.loads(payload)["added"] == {}


def test_the_page_carries_no_status_labels(site):
    _, payload = call(site, "GET", "/")
    for label in (b"Synthetic only", b"engine code committed", b"from flags", b"would block", b"on contract", b"repo-chip",
                  b">Theme<", b"Step ${STEP}", b"reverts to it", b"See what is in the files", b"GCA",
                  b"Nothing is calculated until", b"data-theme", b"localStorage", b"seven"):
        assert label not in payload


def test_a_plain_form_post_cannot_start_a_run(site):
    response, _ = call(site, "POST", "/api/start", json.dumps({"document": PLAIN}), Content_Type="text/plain")
    assert response.status == 415
    assert site.RequestHandlerClass.control.job is None


@pytest.mark.parametrize("length", [-1, -262145, "many"])
@pytest.mark.parametrize(("path", "kind"), [("/api/preflight", "application/json"),
                                            ("/api/files/scenarios", "application/octet-stream")])
def test_a_length_that_is_no_length_is_refused_before_anything_is_read(site, path, kind, length):
    """Taken as it stands, a negative length reads until the sender hangs up, however much it sends."""
    response, payload = announce(site, path, length, Content_Type=kind)
    assert response.status == 400 and b"Content-Length" in payload
    assert site.RequestHandlerClass.control.added == {}


def test_a_setup_is_saved_only_by_starting_its_run(site, tmp_path, monkeypatch):
    """There is no route that only saves: it had no caller on the page, and wrote a file for anyone who asked."""
    monkeypatch.setattr(server, "SPECS", tmp_path / "specifications")
    response, _ = post(site, "/api/save", {"document": with_hash(CRISIS), "name": "anyone"})
    assert response.status == 404 and not (tmp_path / "specifications").exists()


def test_a_pasted_setup_with_runaway_aliases_gets_a_short_refusal_at_once(site):
    """Four hundred bytes that stand for ten million values. Written out into the answer, a few levels
    more would take the server down for everyone; refused, the answer is a line. Seven levels and not
    twelve, so that this test, should the refusal ever be lost, fails on a long answer and not by
    exhausting the machine."""
    levels = ["  a0: &a0 [" + ", ".join(["x"] * 10) + "]"]
    levels += [f"  a{n}: &a{n} [" + ", ".join([f"*a{n - 1}"] * 10) + "]" for n in range(1, 7)]
    text = ("schema_version: 1\nstatus: SYNTHETIC\nsource: s\nversion: v\ninput_set_hash: h\n"
            f"run: {{inputs: {INPUTS}}}\nreporting:\n" + "\n".join(levels) + "\nadditional_values: *a6\n")
    began = time.perf_counter()
    response, payload = post(site, "/api/yaml", {"yaml": text})
    assert response.status == 400 and b"aliases expand" in payload
    assert len(payload) < 500 and time.perf_counter() - began < 20
    once = ("schema_version: 1\nstatus: SYNTHETIC\nsource: s\nversion: v\ninput_set_hash: h\n"
            f"run: {{inputs: {INPUTS}}}\nscenarios:\n"
            "  deeper: &deeper {inherits: adverse, narrative: A deeper year., overrides: []}\n  deeper_again: *deeper\n")
    response, payload = post(site, "/api/yaml", {"yaml": once})
    read = json.loads(payload)["document"]["scenarios"]
    assert response.status == 200 and read["deeper_again"] == read["deeper"], "an alias as such is read"


def test_no_answer_names_a_temporary_folder_of_the_server(temp_site, monkeypatch):
    """Added files, sanity checks and packaging work in temporary folders, and the engine's messages
    name them. What reaches the browser says `(temporary folder)` instead. Here the runs folder is one
    too, so the command a sanity check shows would name it."""
    site, folder = temp_site
    assert names_the_temporary_folder({"shown": f"--runs-dir {folder}"}), "the check below can fail"
    response, payload = post(site, "/api/preflight", {"document": with_hash(CRISIS), "name": "x"})
    answer = json.loads(payload)
    assert response.status == 200 and "--runs-dir (temporary folder)" in answer["shown"]
    assert not names_the_temporary_folder(answer)
    committed_set_in(folder, monkeypatch)
    control = site.RequestHandlerClass.control
    add(control, "obligors", server.ROOT / INPUTS / "obligors.parquet")
    response, payload = post(site, "/api/use-files", {"base": INPUTS})
    assert response.status == 202 and "shown" not in json.loads(payload), "the packaging command names the held folder"
    job = wait(control.job)
    assert str(control.held) in job.shown and job.state == "done", list(job.lines)
    assert not names_the_temporary_folder(json.loads(call(site, "GET", "/api/job")[1]))
    held = str(control.held / "assembled" / "facilities.parquet")
    for message in (f"cannot read {held}", f"[Errno 2] No such file or directory: {held!r}",
                    f"see {held.replace(os.sep, '/')}", {"log": [held, {"path": Path(held)}]}):
        cleaned = server.without_temp_paths(message)
        assert not names_the_temporary_folder(cleaned if isinstance(cleaned, dict) else {"text": cleaned}), message
        assert "facilities.parquet" in json.dumps(cleaned), "the file's own name stays"


# --- hosted ---------------------------------------------------------------------------------------

@pytest.fixture
def hosted(tmp_path):
    """The real server as a router that ends TLS reaches it."""
    running = server.serve(tmp_path, 0, "localhost")
    threading.Thread(target=running.serve_forever, daemon=True).start()
    yield running
    running.shutdown()
    running.server_close()


def router():
    return {"Host": "room.example", "X_Forwarded_Proto": "https"}


def test_only_a_host_beyond_this_machine_is_hosted(hosted, site):
    assert hosted.RequestHandlerClass.hosted and not site.RequestHandlerClass.hosted
    assert hosted.RequestHandlerClass.control.hosted and not site.RequestHandlerClass.control.hosted


def test_a_hosted_page_takes_a_file_of_limited_size_and_refuses_a_larger_one_unread(hosted, site):
    """Anyone with the address can send a file, and it is held and read to be checked: 64 MB for a
    table, 4 MB for a YAML file. A local page keeps the limit that only guards against a mistake."""
    megabyte = 1024 ** 2
    assert server.file_limit("facilities", True) == 64 * megabyte and server.file_limit("scenarios", True) == 4 * megabyte
    assert server.file_limit("facilities", False) == server.file_limit("scenarios", False) == server.FILE_LIMIT > 64 * megabyte
    limits = {role["name"]: role["limit"] for role in hosted.RequestHandlerClass.control.state()["roles"]}
    assert limits == {"facilities": 64 * megabyte, "obligors": 64 * megabyte, "commitments": 64 * megabyte,
                      "opening_provisions": 64 * megabyte, "scenarios": 4 * megabyte, "parameter_set": 4 * megabyte}
    sent = {"Content_Type": "application/octet-stream", **router()}
    for name, limit in limits.items():
        response, payload = announce(hosted, f"/api/files/{name}", limit + 1, **sent)
        assert response.status == 413 and f"{limit // megabyte} MB".encode() in payload, name
    assert hosted.RequestHandlerClass.control.added == {}
    data = (server.ROOT / INPUTS / "scenarios.yaml").read_bytes()
    response, payload = call(hosted, "POST", "/api/files/scenarios", data, **sent)
    assert response.status == 200 and json.loads(payload)["problem"] is None, "a file within the limit is taken"
    page = server.PAGE.read_text(encoding="utf-8")
    assert "file.size > role.limit" in page, "the page says so before it sends the whole file"


def test_plain_http_goes_to_https(hosted):
    response, _ = call(hosted, "GET", "/api/state?x=1", Host="room.example", X_Forwarded_Proto="http")
    assert response.status == 308 and response.getheader("Location") == "https://room.example/api/state?x=1"
    response, _ = call(hosted, "GET", "/", **router())
    assert response.status == 200


def test_the_room_opens_to_anyone_from_any_host_name(hosted):
    response, payload = call(hosted, "GET", "/api/job", **router())
    assert response.status == 200 and json.loads(payload) == {"state": "idle"}


def test_another_site_cannot_start_a_run(hosted):
    response, _ = post(hosted, "/api/start", {"document": PLAIN}, Origin="https://attacker.example", **router())
    assert response.status == 403
    response, _ = post(hosted, "/api/start", {"document": PLAIN}, Origin="http://room.example", **router())
    assert response.status == 403
    assert hosted.RequestHandlerClass.control.job is None
    response, payload = post(hosted, "/api/start", {"document": {"run": "not a mapping"}},
                             Origin="https://room.example", **router())
    assert response.status == 400, payload  # past the gate, and refused for what it says


def test_the_page_does_not_compare_the_files_with_the_requirements():
    assert "differ from the requirements" not in server.PAGE.read_text(encoding="utf-8")
    assert "differences" not in server.Control(nb.RUNS_DIR).preflight({"document": with_hash(PLAIN), "name": "check"})


def test_the_results_use_the_ebas_labels():
    page = server.PAGE.read_text(encoding="utf-8")
    assert all(label in page for label in ("Impairment losses", "Stock of provisions", "Stage 3 exposure",
                                           "coverage ratio"))
    assert not any(label in page for label in ("Annual charge", "Cumulative charge", "Closing provisions",
                                               "'S3'", "S3 gross carrying amount"))


def test_a_scenario_is_listed_with_its_description_and_the_paths_side_by_side():
    page = server.PAGE.read_text(encoding="utf-8")
    listed = page[page.index("function scenarioRow"):page.index("const paramsNote")]
    assert "['In run', 'Scenario', 'Description', '']" in listed and "macroPaths(true)" in listed
    assert "'Comes from'" not in page and "terminalControl" not in page and "scenarioCard" not in page
    assert "'Drives'" in page and "macroPaths(false)" in page


def test_the_steps_carry_only_the_standard_labels():
    page = server.PAGE.read_text(encoding="utf-8")
    start = page.index("function stepNote")
    body = page[start:page.index("function stoppedLine")]
    assert set(re.findall(r"'([^']+)'", body)) == {"You are here", "Passed", "Not passed"}


def test_the_guide_to_step_one_is_served(site):
    response, payload = call(site, "GET", "/api/guide")
    assert response.status == 200 and len(json.loads(payload)["files"]) == 7


def test_the_room_listens_on_the_host_it_is_given(monkeypatch):
    seen = []

    def stop(_, __, *rest):
        seen.extend(rest)
        raise OSError("enough")

    monkeypatch.setattr(server, "serve", stop)
    assert server.main(["--host", "0.0.0.0", "--no-browser"]) == 1
    assert seen[0] == "0.0.0.0"


def test_the_room_starts_without_matplotlib():
    """A hosted install has the engine's dependencies only, and the room draws its charts in the browser."""
    code = "import sys; sys.modules['matplotlib'] = None; import server; print(server.nb.ROOT)"
    subprocess.run([sys.executable, "-c", code], cwd=HERE, check=True, capture_output=True)


def test_the_notebooks_still_find_their_colour_ramp():
    """The room shares nbtools, which loads matplotlib only when a notebook asks for the ramp."""
    code = ("import sys; import nbtools as nb; assert 'matplotlib' not in sys.modules; "
            "assert nb.DIVERGING.name == 'diverging' and 'matplotlib' in sys.modules")
    subprocess.run([sys.executable, "-c", code], cwd=server.ROOT / "notebooks", check=True, capture_output=True)


def step_of_the_page(start: str, end: str) -> str:
    page = server.PAGE.read_text(encoding="utf-8")
    return page[page.index(start):page.index(end)]


def test_a_comparison_does_not_outlive_the_run_it_was_chosen_for():
    """Left in place, it would set the next run against the last one's choice, or against itself."""
    body = step_of_the_page("async function selectRun", "async function selectCompare")
    assert "if (id !== selectedRun) { COMPARE = null; ++compareTicket; }" in body
    assert body.index("COMPARE = null") < body.index("selectedRun = id")


def test_one_failed_request_does_not_end_the_following_of_a_job():
    """While it follows a job the page keeps asking, and once the server knows no job any more it says
    that the server restarted, instead of showing a run in progress for good."""
    body = step_of_the_page("async function poll", "// --- step 4")
    failed = body[body.index("catch {"):body.index("unanswered = false")]
    assert "pollIn(3000)" in failed and "unanswered = true" in failed and "jobRunning = false" not in failed
    assert "if (JOB && (jobRunning || watching)) await jobGone()" in body
    gone = step_of_the_page("async function jobGone", "async function poll")
    assert "state: 'gone'" in gone and "await reloadState()" in gone
    page = server.PAGE.read_text(encoding="utf-8")
    assert "A run in progress still finishes" not in page and "gone: ['block'" in page
    assert "if (jobRunning && unanswered) return" in step_of_the_page("function nowOf", "function renderWhere")


def test_a_segment_is_offered_the_models_of_its_own_portfolio():
    """The engine takes a segment's models from the portfolio it is filed under in the parameter set,
    whatever portfolio a run reports it under. The page offers the same list it reads `Drives` from."""
    page = server.PAGE.read_text(encoding="utf-8")
    row = step_of_the_page("function segmentRow", "function segmentsTable")
    assert "model_choices[base.portfolio]" in row and "model_choices[held.portfolio" not in page
    assert "base.model_choices[from.portfolio]" in step_of_the_page("function drives", "function drivesText")


def test_heroku_starts_this_server():
    assert f"{HERE.name}/{Path(server.__file__).name} --host 0.0.0.0 --port $PORT" in (server.ROOT / "Procfile").read_text()


def test_a_refused_setup_starts_nothing(site):
    response, payload = post(site, "/api/start", {"document": {**PLAIN, "run": {**RUN, "variant": "nothing"}}})
    assert response.status == 400 and b"not on offer" in payload
    response, payload = post(site, "/api/use-files", {})
    assert response.status == 400 and b"still missing" in payload
    assert site.RequestHandlerClass.control.job is None


@pytest.mark.parametrize("path", [
    "/docs/run-workflow/stress-run-workflow.html", "/api/runs/..%2F..%2Fpyproject.toml", "/api/runs/comparisons",
    "/api/runs/20261031T2029Z-core-3e7f2cd1", "/api/inputs/bank", "/api/inputs/..%2F..", "/api/inputs/0000000000000000",
    f"/api/{INPUTS}/preview?table=nothing", f"/api/{INPUTS}/matrix?segment=nothing", "/nothing",
    "/api/browse?path=docs", "/api/text?path=pyproject.toml",
])
def test_nothing_outside_the_offer_is_served(site, path):
    assert call(site, "GET", path)[0].status == 404


@pytest.mark.parametrize("path", ["/api/setup?run=..%2F..%2Fpyproject.toml", "/api/setup?spec=docs%2Frunbook.md"])
def test_a_closed_or_absent_path_is_refused(site, path):
    assert call(site, "GET", path)[0].status == 400


def test_the_routes_of_the_steps_answer(site):
    response, payload = post(site, "/api/preflight", {"document": PLAIN, "name": "x"})
    answer = json.loads(payload)
    assert response.status == 200 and answer["verdict"] == "ready" and answer["shown"].startswith("uv run stress run")
    assert not answer["needs_specification"] and answer["yaml"].startswith("schema_version: 1")
    response, payload = call(site, "GET", f"/api/{INPUTS}")
    view = json.loads(payload)
    assert response.status == 200 and "P01" in view["base"]["segments"] and view["summary"]["facilities"]["rows"] == 10_000
    assert [f["file"] for f in view["files"]][:2] == ["facilities.parquet", "obligors.parquet"]
    response, payload = call(site, "GET", f"/api/{INPUTS}/preview?table=facilities&q=F07001")
    assert response.status == 200 and json.loads(payload)["total"] == 1
    response, payload = call(site, "GET", f"/api/{INPUTS}/matrix?segment=P01")
    assert response.status == 200 and len(json.loads(payload)["grid"]) == 11
    text = (server.ROOT / WALKTHROUGH).read_text(encoding="utf-8")
    response, payload = post(site, "/api/yaml", {"yaml": text})
    assert response.status == 200 and json.loads(payload)["document"]["run"]["inputs"] == INPUTS
    response, payload = post(site, "/api/yaml", {"yaml": text + "\nrun: {}\n"})
    assert response.status == 400 and b"duplicate" in payload
