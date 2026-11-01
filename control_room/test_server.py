"""Tests of the control room, run on their own:

    uv run pytest control_room

They sit beside it, not under tests/. The room is no part of the engine and proves no requirement,
and a marked test under tests/ would enter the generated traceability matrix. The first fixture
makes one real run through the page's own setup and job, which takes about three quarters of a minute.
"""

import http.client
import io
import json
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import preflight
import server

from stress.lineage import CODE_PATHS

nb = server.nb
INPUTS = "inputs/d62d0386f2c5256e"
WALKTHROUGH = "docs/run-workflow/walkthrough.yaml"
RUN = {"inputs": INPUTS, "scenarios": ["baseline", "adverse"], "variant": "core", "balance_sheet": "static",
       "terminal_treatment": "z", "s2_treatment": "repriced", "horizon_runoff": "contractual", "lgd_path": "annual"}
PLAIN = {"schema_version": 1, "status": "SYNTHETIC", "source": "test", "version": "plain", "input_set_hash": "", "run": RUN}
# A derived scenario, a segment parameter and a terminal policy: nothing a flag can say.
CRISIS = {**PLAIN, "version": "test-crisis", "run": {**RUN, "scenarios": ["baseline", "adverse", "deeper"]},
          "scenarios": {"deeper": {"inherits": "adverse", "narrative": "A deeper 2027.", "overrides": [
              {"variable": "gdp_growth", "country": "*", "year": 2027, "value": -6.0, "unit": "percent", "value_type": "growth"}]}},
          "segments": {"P01": {"rho": 0.2}}, "terminal_policies": {"deeper": {"method": "flat"}}}


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


@pytest.fixture
def site(tmp_path):
    """The real server on a free port, over an empty runs folder."""
    running = server.serve(tmp_path, 0)
    threading.Thread(target=running.serve_forever, daemon=True).start()
    yield running
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


# --- a run from the page is an ordinary sealed run --------------------------------------------------

def test_the_run_is_what_the_setup_said(sealed):
    _, folder = sealed
    view = server.run_view(folder)
    assert view["verified"] and view["status"] == "SYNTHETIC"
    assert view["scenarios"] == ["baseline", "adverse", "deeper"] and view["specification"] == "test-crisis"
    assert view["results"]["kpis"]["deeper"]["cumulative"] > view["results"]["kpis"]["adverse"]["cumulative"]
    sealed_copy = folder / "data" / "specification.yaml"
    assert sealed_copy.is_file() and "rho: 0.2" in sealed_copy.read_text(encoding="utf-8")


def test_the_summary_ties_to_the_sealed_headline(sealed):
    _, folder = sealed
    view = server.run_view(folder)
    tied = 0
    for line in view["headline_lines"]:
        row = server.HEADLINE.match(line)
        if row:
            kpi = view["results"]["kpis"][row[1]]
            shown = [f"{kpi[k]:,.1f}" for k in ("cumulative", "closing", "s3_gca")]
            assert shown == re.findall(r"EUR ([\d,.\-]+)m", line)
            assert f"{kpi['first_year']:,.1f}" == re.search(r"first year ([\d,.\-]+)m", line)[1]
            tied += 1
    assert tied == 3


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
    assert doc["segments"] == {"P01": {"rho": 0.2}} and doc["terminal_policies"] == {"deeper": {"method": "flat"}}
    written = (folder / "data" / "specification.yaml").read_text(encoding="utf-8").split("\n", 1)[1]
    assert server.specification_text(doc, server.SPECS) == written
    assert control.preflight({"document": doc, "name": loaded["name"]})["verdict"] == "ready"


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
    """A file as the page sends it: its bytes, for one of the seven places."""
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


def test_seven_files_added_by_hand_become_a_set_and_leave_the_list(tmp_path, monkeypatch):
    """The committed set's seven files, added one by one, package to the very same input set."""
    monkeypatch.setattr(nb, "INPUTS_DIR", tmp_path / "inputs")
    (tmp_path / "inputs").mkdir()
    control = server.Control(tmp_path)
    for role in preflight.file_roles():
        add(control, role["name"], server.ROOT / INPUTS / role["file"])
    job = wait(control.use_files({}))
    assert job.state == "done" and job.input_set == INPUTS.split("/")[1], list(job.lines)
    saved = tmp_path / "inputs" / job.input_set
    assert (saved / "manifest.json").is_file()
    assert json.loads((saved / "approval.json").read_text())["status"] == "PENDING_OWNER_APPROVAL"
    assert control.added == {} and not (control.held / "facilities.parquet").exists()


def test_replacing_one_file_keeps_the_other_six_and_the_saved_set(tmp_path, monkeypatch):
    original = committed_set_in(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in original.iterdir()}
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
    assert {p.name: p.read_bytes() for p in original.iterdir()} == before


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


def test_older_sets_say_in_words_why_they_cannot_run():
    rows = server.input_inventory()
    assert next(r for r in rows if r["inputs"] == INPUTS)["why_not"] is None
    older = [r for r in rows if not r["runnable"]]
    assert older and all("Facilities file has no credit_status_date column" in r["why_not"] for r in older)
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r["saved_at"]) for r in rows)


def test_approval_is_recorded_by_the_one_off_step_and_nothing_else_changes(tmp_path, monkeypatch):
    copy = committed_set_in(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "ROOT", tmp_path)  # a run's paths are read from here
    before = {p.name: p.read_bytes() for p in copy.iterdir() if p.name != "approval.json"}
    job = wait(server.Control(tmp_path).approve({"inputs": INPUTS, "approver": "O. Wner"}))
    assert job.state == "done", list(job.lines)
    approval = json.loads((copy / "approval.json").read_text(encoding="utf-8"))
    assert approval["status"] == "APPROVED" and approval["approved_by"] == "O. Wner"
    assert {p.name: p.read_bytes() for p in copy.iterdir() if p.name != "approval.json"} == before
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
])
def test_a_setup_outside_the_offer_is_refused(doc):
    with pytest.raises(server.Refused):
        plan(doc)


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
    packaging.add("input set inputs/d62d0386f2c5256e")
    assert packaging.input_set == "d62d0386f2c5256e"


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
    assert state["anchor"] == "baseline"
    assert [role["label"] for role in state["roles"]][:2] == ["Facilities", "Obligors"]
    response, payload = post(site, "/api/remove-file", {"name": "scenarios"})
    assert response.status == 200 and json.loads(payload)["added"] == {}


def test_the_page_carries_no_status_labels(site):
    _, payload = call(site, "GET", "/")
    for label in (b"Synthetic only", b"engine code committed", b"from flags", b"would block", b"on contract", b"repo-chip",
                  b">Theme<", b"Step ${STEP}", b"reverts to it", b"See what is in the files", b"GCA",
                  b"Nothing is calculated until"):
        assert label not in payload


def test_a_plain_form_post_cannot_start_a_run(site):
    response, _ = call(site, "POST", "/api/start", json.dumps({"document": PLAIN}), Content_Type="text/plain")
    assert response.status == 415
    assert site.RequestHandlerClass.control.job is None


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
    assert nb.DIVERGING.name == "diverging"
    assert not hasattr(nb, "NO_SUCH_NAME")


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
    "/api/inputs/d62d0386f2c5256e/preview?table=nothing", "/api/inputs/d62d0386f2c5256e/matrix?segment=nothing", "/nothing",
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
    response, payload = call(site, "GET", "/api/inputs/d62d0386f2c5256e")
    view = json.loads(payload)
    assert response.status == 200 and "P01" in view["base"]["segments"] and view["summary"]["facilities"]["rows"] == 10_000
    assert [f["file"] for f in view["files"]][:2] == ["facilities.parquet", "obligors.parquet"]
    response, payload = call(site, "GET", "/api/inputs/d62d0386f2c5256e/preview?table=facilities&q=F07001")
    assert response.status == 200 and json.loads(payload)["total"] == 1
    response, payload = call(site, "GET", "/api/inputs/d62d0386f2c5256e/matrix?segment=P01")
    assert response.status == 200 and len(json.loads(payload)["grid"]) == 11
    text = (server.ROOT / WALKTHROUGH).read_text(encoding="utf-8")
    response, payload = post(site, "/api/yaml", {"yaml": text})
    assert response.status == 200 and json.loads(payload)["document"]["run"]["inputs"] == INPUTS
    response, payload = post(site, "/api/yaml", {"yaml": text + "\nrun: {}\n"})
    assert response.status == 400 and b"duplicate" in payload
