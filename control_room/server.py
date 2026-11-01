"""Control room: one page that takes a run through four steps.

    uv run python control_room/server.py      # serves and opens http://127.0.0.1:8770

1. Files and settings: the seven files the run needs, each one replaceable by hand, the run settings,
   and the engine's own check of all of it (R1 to R4, calculating nothing).
2. Review the files: each file's contents, and the changes for this run.
3. Run: what will run, Start, and the engine's progress.
4. Outcomes: the sealed run's figures, its reproduction and a comparison.

The page opens on the small or the large dataset, as --dataset or the DATASET environment variable says.

Every action is an engine or one-off command: `stress run`, `stress rerun`, `foundation.synth package`,
`foundation.synth approve`. Files added on the page wait in a temporary folder until the seven are
packaged as inputs/<hash>/, so the input folders stay written by the one-off step alone. A setup a
flag cannot say is written as a specification YAML under this folder's specifications/ and runs with
--specification. This server listens on the loopback address and answers only its own page. Given
another --host it is a public site with no sign-in, and answers only over https, from its own site.
"""

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pandas as pd
import pyarrow.parquet as pq
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "notebooks"))  # nbtools

import guide
import preflight

import nbtools as nb
from stress.cli import EXIT_BLOCKED, EXIT_ERROR, EXIT_NOT_REPRODUCED, EXIT_OK, STEPS
from stress.contracts.errors import BlockingError
from stress.contracts.inputs import DATASETS, TABLE_DATASETS
from stress.contracts.run import (
    COMPARISONS_DIR,
    HORIZON_RUNOFFS,
    LGD_PATHS,
    REPORTS_DIR,
    RESULTS_DIR,
    RUN_LOG,
    RUN_MANIFEST,
    S2_TREATMENTS,
    RunConfig,
)
from stress.contracts.specification import RUN_FIELDS, TOP_FIELDS
from stress.lineage import check_replay_environment, read_manifest

HOST = "127.0.0.1"
PORT = 8770
HERE = Path(__file__).resolve().parent
ROOT = nb.ROOT
PAGE = HERE / "index.html"
SPECS = HERE / "specifications"  # the room's own setups, saved as the engine reads them
BOOKS = {"small": "70a9337b7d75f668", "large": "d62d0386f2c5256e"}  # docs/assumptions.md A41
DATASET = "small"  # the book the page opens on, unless --dataset or the DATASET environment variable says otherwise
PAGE_POLICY = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
               "script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
# Never listed, read or written here: the protected folders and tool caches.
CLOSED = {"archive", ".git", ".venv", "__pycache__", "node_modules", ".ruff_cache", ".pytest_cache", ".hypothesis"}
CLOSED_PATHS = (Path("inputs/bank"),)
RUN_FILES = {
    "report": (Path(RESULTS_DIR, REPORTS_DIR, "stress_report.xlsx"),
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "summary": (Path(RESULTS_DIR, REPORTS_DIR, "summary.md"), "text/plain; charset=utf-8"),
    "log": (Path(RUN_LOG), "text/plain; charset=utf-8"),
}

REQUIRED_SCENARIO = "baseline"  # adverse reverts toward it; R4 blocks a run without it
READINGS = (  # the choices the draft leaves open; each default is the design's, docs/assumptions.md C14 to C16
    {"field": "terminal_treatment", "flag": "--terminal-treatment", "label": "After 2029",
     "help": "How the stress fades once the scenario years end.",
     "default": "z", "choices": {"z": "The macro index Z returns to baseline",
                                 "parameters": "PD and LGD return to baseline over six years"}},
    {"field": "s2_treatment", "flag": "--s2-treatment", "label": "Stage 2 provisions",
     "help": "What happens to a Stage 2 provision after the year it is booked.",
     "default": S2_TREATMENTS[0],
     "choices": dict(zip(S2_TREATMENTS, ("Recalculated each year-end", "Held once booked")))},
    {"field": "horizon_runoff", "flag": "--horizon-runoff", "label": "Repayments inside 2027 to 2029",
     "help": "Whether loans run off during the projection years when lifetime losses are valued.",
     "default": HORIZON_RUNOFFS[0], "bullet_only": HORIZON_RUNOFFS[1],
     "choices": dict(zip(HORIZON_RUNOFFS, ("Contractual maturity and prepayment apply",
                                           "Every facility stays alive, no prepayment")))},
    {"field": "lgd_path", "flag": "--lgd-path", "label": "LGD on property-secured loans",
     "help": "Which Z sets the LGD of an adverse default year.",
     "default": LGD_PATHS[0], "choices": dict(zip(LGD_PATHS, ("Z of the default year", "Worst Z of the path")))},
)
SPEC_OF = {spec.name: spec for spec in DATASETS}

HEADLINE = re.compile(r"(\S+): cumulative charge \S+ EUR ([\d,.]+)m")
STEP_LINE = re.compile(r"stress\.(R\d+)\s+(.*)")
RUN_LINE = re.compile(r"(?:re)?run (\S+): [A-Z_]+$")
PACKAGED_LINE = re.compile(r"input set (?:.*/)?([0-9a-f]{16})$")
OUTCOME_LINE = re.compile(r"blocked at .*|reproduced: .*|NOT reproduced.*|input set .*|approved .*")
RUN_ROUTE = re.compile(r"/api/runs/([^/]+)(?:/(report|summary|log))?")
INPUT_ROUTE = re.compile(r"/api/inputs/([^/]+)(?:/(preview|matrix))?")
FILE_ROUTE = re.compile(r"/api/files/([a-z_]+)")
RUN_NAME = re.compile(r"\d{8}T\d{4}Z-[\w+.-]+")
SETUP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")  # one file name, no path in it
APPROVER = re.compile(r"[\w][\w .@'-]{0,63}")
INPUT_FOLDER = re.compile(r"inputs/[0-9a-f]{16}")
BODY_LIMIT = 256 * 1024
FILE_LIMIT = 8 * 1024 ** 3  # one added file; a local copy, so the limit only guards against a mistake
CHUNK = 1024 * 1024
LOG_TAIL = 14
# Ctrl+C reaches every process of a console. The engine gets its own group, so that stopping this
# server cannot leave a run folder unsealed.
DETACHED = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
            else {"start_new_session": True})


@lru_cache(maxsize=64)
def _parsed_yaml(path: Path, stamp: int):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def read_yaml(path: Path):
    return _parsed_yaml(path, path.stat().st_mtime_ns)


def from_root(path: Path) -> str:
    return (path.relative_to(ROOT) if path.is_relative_to(ROOT) else path).as_posix()


def relative_to_folder(target: Path, folder: Path) -> str:
    """A path as a specification in `folder` must state it: relative, with .. where needed."""
    return Path(os.path.relpath(target, folder)).as_posix()


def closed(path: Path) -> bool:
    """A folder this room never lists, reads or writes."""
    relative = path.relative_to(ROOT) if path.is_relative_to(ROOT) else None
    if relative is None:
        return False
    return bool(CLOSED & set(relative.parts)) or any(relative.is_relative_to(p) for p in CLOSED_PATHS)


# --- what is available ---------------------------------------------------------------------------

def contract_gaps(folder: Path) -> list[str]:
    """Columns the input contract needs and this set lacks: R2 would block on each of them."""
    gaps = []
    for spec in TABLE_DATASETS:
        present = pq.read_schema(folder / spec.filename).names
        gaps += [f"{spec.name}.{name}" for name in spec.column_names if name not in present]
    return gaps


def why_unusable(gaps: list[str]) -> str:
    """In words: what stops today's engine reading an input set."""
    if any(gap.startswith("unreadable") for gap in gaps):
        return "It could not be read."
    by_table: dict[str, list[str]] = {}
    for gap in gaps:
        table, column = gap.split(".", 1)
        by_table.setdefault(table, []).append(column)
    parts = [f"{preflight.FILE_GUIDE[table][0]} file has no {preflight.listed(columns)} column"
             f"{'s' if len(columns) > 1 else ''}" for table, columns in by_table.items()]
    return f"The {' and the '.join(parts)}, which the engine needs."


def input_inventory() -> list[dict]:
    """Every input set with what it holds and whether today's engine can read it."""
    rows = nb.input_sets().to_dict("records")
    for row in rows:
        folder = nb.INPUTS_DIR / row["inputs"].split("/")[1]
        manifest = folder / "manifest.json"
        row["saved_at"] = datetime.fromtimestamp(manifest.stat().st_mtime).isoformat(timespec="minutes")
        try:
            totals = json.loads(manifest.read_text(encoding="utf-8"))["control_totals"]
            cells = totals["by_portfolio_stage"].values()
            parameters = read_yaml(folder / "parameter_set.yaml")
            gaps = contract_gaps(folder)
            row.update(
                facilities=sum(c["count"] for c in cells), gca=sum(c["gca"] for c in cells) / nb.MILLION,
                gaps=gaps, runnable=not gaps, why_not=why_unusable(gaps) if gaps else None,
                scenarios=[{"id": s["id"], "label": s["label"]}
                           for s in read_yaml(folder / "scenarios.yaml")["scenarios"]],
                variants=[{"id": name, "label": spec["label"],
                           "bullet": set(spec["repayment_profile"].values()) == {"bullet"}}
                          for name, spec in parameters["variants"].items()])
        except (OSError, KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError) as exc:
            # One unreadable set must not hide the others: it is listed, and it cannot be chosen.
            row.update(facilities=None, gca=None, gaps=[f"unreadable: {exc}"], runnable=False,
                       why_not=why_unusable(["unreadable"]), scenarios=[], variants=[])
    return rows


def check_dataset(dataset: str) -> None:
    """A wrong setting stops the server: a page quietly open on the other book would pass for the chosen one."""
    if dataset not in BOOKS:
        raise Refused(f"the dataset is {' or '.join(BOOKS)}, not {dataset!r}")
    folder = nb.INPUTS_DIR / BOOKS[dataset]
    try:
        preflight.base_of(folder)
        gaps = contract_gaps(folder)
    except (OSError, KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError) as exc:
        gaps = [f"{type(exc).__name__}: {exc}"]
    if gaps:
        raise Refused(f"the {dataset} dataset, inputs/{folder.name}, is missing or the engine cannot read it: {gaps[0]}")


# --- reading runs --------------------------------------------------------------------------------

def _money(value) -> float | None:
    return None if pd.isna(value) else float(value) / nb.MILLION


def _share(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None  # no base is no rate, not zero


def scenario_order(names) -> list[str]:
    """As the report's headline: baseline first, then by name."""
    return sorted(set(names), key=lambda s: (s != REQUIRED_SCENARIO, s))


def _listed(path: Path) -> dict:
    """One line of the run history, from the manifest as written; opening a run verifies it."""
    manifest = path / RUN_MANIFEST
    if not manifest.is_file():
        return {"run_id": path.name, "status": "UNSEALED"}
    m = json.loads(manifest.read_text(encoding="utf-8"))
    headline = dict(row.groups() for row in map(HEADLINE.match, m.get("summary", {}).get("headline", [])) if row)
    config = m["config"]
    spec = m.get("specification") or {}  # the setup's own version survives the sealed copy's file name
    return {"run_id": m["run_id"], "status": m["status"], "variant": config["variant"],
            "selected": nb._selected(config), "scenarios": config["scenarios"],
            "balance_sheet": config.get("balance_sheet", "static"),
            "specification": (spec.get("version") or Path(config["specification"]).stem) if config.get("specification") else None,
            "analysis": bool(config.get("analysis")), "input_set": m["input_set_hash"][:16],
            "code_version": m["code_version"], "created_at": m["created_at"], "sealed_at": m.get("sealed_at"),
            "blocked": m.get("blocked"), "headline": headline}


def list_runs(runs_dir: Path) -> list[dict]:
    """Every run folder, newest first."""
    if not runs_dir.is_dir():
        return []
    folders = (p for p in runs_dir.iterdir() if p.is_dir() and p.name != COMPARISONS_DIR)
    return [_listed(path) for path in sorted(folders, key=lambda p: p.name, reverse=True)]


def typical_seconds(runs: list[dict]) -> float | None:
    """The median wall time of the latest sealed runs, to say how long a start takes."""
    spans = [(datetime.fromisoformat(r["sealed_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds()
             for r in runs[:10] if r.get("sealed_at")]
    return statistics.median(spans) if spans else None


def replay_state(manifest: dict) -> dict:
    """Would `stress rerun` accept this run here? The engine's own check answers."""
    try:
        check_replay_environment(manifest)
    except BlockingError as exc:
        return {"possible": False, "code": str(exc.code), "reason": exc.message}
    return {"possible": True}


def results_of(run: nb.Run) -> dict:
    """The summary figures, built as R10 builds its headline so that the two always agree."""
    impairment = run.report("impairment")
    stages = run.report("impairment_by_stage")
    migration = run.report("stage_migration")
    total = impairment[impairment["portfolio"] == "Total"]
    scenarios = scenario_order(total["scenario"])
    years = sorted(int(y) for y in total["year"].unique())
    first, last = years[0], years[-1]
    by_year, by_stage, kpis = {}, {}, {}
    for name in scenarios:
        path = total[total["scenario"] == name].sort_values("year")
        by_year[name] = [{"year": int(r.year), "opening": _money(r.opening_on + r.opening_off),
                          "charge": _money(r.charge_total), "closing": _money(r.closing_on + r.closing_off),
                          "cumulative": _money(r.cumulative_charge)} for r in path.itertuples()]
        part = stages[stages["scenario"] == name]
        by_stage[name] = []
        for year, cells in part.groupby("year"):
            row = {"year": int(year), "gca": _money(cells["gca"].sum()), "coverage": {}, "stock": {}}
            for stage, cell in cells.groupby("stage"):
                row["stock"][int(stage)] = _money(cell["gca"].sum())
                row["coverage"][int(stage)] = _share(cell["coverage_numerator"].sum(), cell["coverage_denominator"].sum())
            row["coverage"]["all"] = _share(cells["coverage_numerator"].sum(), cells["coverage_denominator"].sum())
            by_stage[name].append(row)
        moved = migration[(migration["scenario"] == name) & (migration["year"] == last)]
        kpis[name] = {"cumulative": by_year[name][-1]["cumulative"], "first_year": by_year[name][0]["charge"],
                      "closing": by_year[name][-1]["closing"], "s3_gca": _money(moved["closing_S3"].sum()),
                      "opening_gca": by_stage[name][0]["gca"], "closing_gca": by_stage[name][-1]["gca"],
                      "coverage": by_stage[name][-1]["coverage"]["all"]}
    names = run.portfolio_names()
    portfolios = []
    for portfolio, rows in impairment[impairment["portfolio"] != "Total"].groupby("portfolio"):
        held = stages[stages["portfolio"] == portfolio]
        values = {}
        for name in scenarios:
            final = rows[(rows["scenario"] == name) & (rows["year"] == last)].iloc[0]
            cells = held[(held["scenario"] == name) & (held["year"] == last)]
            values[name] = {"cumulative": _money(final["cumulative_charge"]),
                            "closing": _money(final["closing_on"] + final["closing_off"]),
                            "gca": _money(cells["gca"].sum()),
                            "coverage": _share(cells["coverage_numerator"].sum(), cells["coverage_denominator"].sum())}
        opening = held[held["year"] == held["year"].min()]
        portfolios.append({"portfolio": portfolio, "name": names.get(portfolio, ""), "values": values,
                           "opening_gca": _money(opening[opening["scenario"] == scenarios[0]]["gca"].sum())})
    return {"scenarios": scenarios, "years": years, "first": first, "last": last, "impairment": by_year,
            "stages": by_stage, "kpis": kpis, "portfolios": portfolios}


def run_view(path: Path) -> dict:
    """One sealed run for the page. nb.Run verifies its hashes first, as report and compare do."""
    run = nb.Run(path)
    m = run.manifest
    view = {
        **_listed(path), "label": m["label"], "mode": m["mode"],
        "parameter_set": m.get("parameter_set", {}), "digest": m["outputs_digest"][:16], "verified": True,
        "rejections": m.get("rejections"), "headline_lines": m.get("summary", {}).get("headline", []),
        "replay": replay_state(m), "outputs": len(m["outputs"]),
        "files": {key: (run.path / relative).is_file() for key, (relative, _) in RUN_FILES.items()},
        "results": None, "unreadable": None,
    }
    if not run.blocked:
        try:
            view["results"] = results_of(run)
        except (OSError, KeyError, IndexError) as exc:
            view["unreadable"] = f"this run's reports have an older shape: {exc}"
    return view


# --- the setup ------------------------------------------------------------------------------------

class Refused(ValueError):
    """A request asks for something the page does not offer."""


def _one_of(value, allowed, what: str):
    if value not in allowed:
        raise Refused(f"{what} {value!r} is not on offer")
    return value


def checked_yaml(value) -> Path:
    """A YAML file of the repository, outside the closed folders."""
    if not isinstance(value, str) or not value:
        raise Refused("name a YAML file")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or closed(path) or path.suffix != ".yaml" or not path.is_file():
        raise Refused(f"{value!r} is not a YAML file this room opens")
    return path


def checked_document(form: dict, inputs: list[dict]) -> dict:
    """The setup a request carries, with its shape and its paths checked here. Its contents are the
    engine's to judge: the dry run reads it as R2 would."""
    doc = form.get("document")
    if not isinstance(doc, dict) or not isinstance(doc.get("run"), dict):
        raise Refused("send a setup with a run section")
    if set(doc) - TOP_FIELDS:
        raise Refused(f"unknown sections {sorted(set(doc) - TOP_FIELDS)}")
    run = doc["run"]
    if set(run) - RUN_FIELDS:
        raise Refused(f"unknown run settings {sorted(set(run) - RUN_FIELDS)}")
    listed = {row["inputs"] for row in inputs}
    folder = run.get("inputs")
    if not isinstance(folder, str) or not INPUT_FOLDER.fullmatch(folder) or folder not in listed:
        raise Refused(f"input set {folder!r} is not on offer")
    if run.get("analysis"):
        checked_yaml(run["analysis"])
    for name in ("scenarios", "segments", "terminal_policies", "balance_sheet", "models", "reporting"):
        if name in doc and not isinstance(doc[name], dict):
            raise Refused(f"{name} must be a mapping")
    for name in ("assignments", "additional_values"):
        if name in doc and not isinstance(doc[name], list):
            raise Refused(f"{name} must be a list")
    return doc


def run_arguments(doc: dict, inputs: list[dict]) -> list[str]:
    """The `stress run` flags of a plain setup. Only what the page offers gets through, so no text
    from the browser reaches the command line."""
    run = doc["run"]
    usable = {row["inputs"]: row for row in inputs if row["runnable"]}
    chosen = usable[_one_of(run.get("inputs"), usable, "input set")]
    variants = {v["id"]: v for v in chosen["variants"]}
    variant = _one_of(run.get("variant") or "core", variants, "variant")
    known = [s["id"] for s in chosen["scenarios"]]
    scenarios = run.get("scenarios") or []
    if not isinstance(scenarios, list) or not scenarios:
        raise Refused("choose at least one scenario")
    for name in scenarios:
        _one_of(name, known, "scenario")
    if REQUIRED_SCENARIO not in scenarios:
        raise Refused(f"a run needs {REQUIRED_SCENARIO}: R4 blocks without it")
    args = ["run", "--inputs", chosen["inputs"], "--scenarios",
            ",".join(name for name in known if name in scenarios), "--variant", variant]
    for reading in READINGS:
        value = run.get(reading["field"]) or reading["default"]
        _one_of(value, reading["choices"], reading["label"])
        if value == reading.get("bullet_only") and not variants[variant]["bullet"]:
            raise Refused(f"{value} works on bullet schedules only: R5 blocks on {variant}")
        if value != reading["default"]:
            args += [reading["flag"], value]
    if run.get("analysis"):
        args += ["--analysis", from_root(checked_yaml(run["analysis"]))]
    return args


def run_config(doc: dict) -> RunConfig:
    """A plain setup as cli.cmd_run would build it, with absolute paths so that a dry run does not
    depend on where the server was started."""
    run = doc["run"]
    readings = {r["field"]: run.get(r["field"]) or r["default"] for r in READINGS}
    return RunConfig(inputs=str(ROOT / run["inputs"]), scenarios=tuple(run.get("scenarios") or []),
                     variant=run.get("variant") or "core", balance_sheet=run.get("balance_sheet") or "static",
                     analysis=str(ROOT / run["analysis"]) if run.get("analysis") else None, **readings)


def specification_text(doc: dict, folder: Path) -> str:
    """The YAML of a setup as a file in `folder` must state it."""
    run = doc["run"]
    analysis = relative_to_folder(ROOT / run["analysis"], folder) if run.get("analysis") else None
    spec = preflight.specification_document(doc, relative_to_folder(ROOT / run["inputs"], folder), analysis)
    return preflight.yaml_text(spec)


def checked_name(name) -> str:
    if not isinstance(name, str) or not SETUP_NAME.fullmatch(name):
        raise Refused("a setup name is letters, digits, dots, dashes and underscores, 64 at most")
    return name


def checked_approver(name) -> str:
    if not isinstance(name, str) or not APPROVER.fullmatch(name.strip()):
        raise Refused("an approver is a name of up to 64 letters, digits, spaces, dots, dashes or @")
    return name.strip()


def save_specification(name: str, doc: dict) -> Path:
    """One file under specifications/, written exactly as the engine will read it."""
    path = SPECS / f"{checked_name(name)}.yaml"
    SPECS.mkdir(exist_ok=True)
    stamp = datetime.now().astimezone().isoformat(timespec="minutes")
    header = f"# Written by the control room on {stamp}. A synthetic run setup; not an estimate.\n"
    path.write_text(header + specification_text(doc, SPECS), encoding="utf-8", newline="\n")
    return path


def document_of_config(config: dict, input_set: str) -> dict:
    """A sealed run's config.yaml as a setup: what a plain run was started with."""
    run = {"inputs": f"inputs/{input_set}", "scenarios": list(config["scenarios"]), "variant": config["variant"],
           "balance_sheet": config.get("balance_sheet", "static")}
    run.update({r["field"]: config.get(r["field"], r["default"]) for r in READINGS})
    return {"schema_version": 1, "status": "SYNTHETIC", "source": "", "version": "", "input_set_hash": "",
            "run": run}


def setup_of(query: dict, runs_dir: Path) -> dict:
    """What an earlier run was started with, as a setup to change and run again."""
    run_id = str(query.get("run"))
    folder = runs_dir / run_id
    if not RUN_NAME.fullmatch(run_id) or not folder.is_dir():
        raise Refused(f"no run {run_id}")
    manifest = read_manifest(folder)
    input_set = manifest["input_set_hash"][:16]
    sealed = folder / "data" / "specification.yaml"
    notes = []
    if sealed.is_file():
        doc = preflight.parse_yaml(sealed.read_text(encoding="utf-8"), None)
        doc["run"]["inputs"] = f"inputs/{input_set}"
    else:
        doc = document_of_config(manifest["config"], input_set)
    if manifest["config"].get("analysis"):
        original = Path(manifest["config"]["analysis"])
        try:
            doc["run"]["analysis"] = from_root(checked_yaml(from_root(original)))
        except Refused:
            doc["run"].pop("analysis", None)
            notes.append(f"its analysis package {from_root(original)} is no longer there, so it is left out")
    return {"document": doc, "name": f"setup-{run_id[:8]}-{run_id[9:13]}", "from": run_id, "notes": notes}


# --- starting a job ------------------------------------------------------------------------------

@dataclass
class Job:
    """One engine or one-off process. Its own output lines are its progress."""

    kind: str
    shown: str
    started: float = field(default_factory=time.time)
    lines: deque = field(default_factory=lambda: deque(maxlen=400))
    reached: list = field(default_factory=lambda: ["R1"])
    step: str = "R1"
    detail: str = STEPS["R1"]
    run_id: str | None = None
    input_set: str | None = None
    outcome: str | None = None
    exit_code: int | None = None
    finished: float | None = None
    after: Callable[[], None] | None = None  # what follows a clean end, before the page can see it

    def add(self, line: str) -> None:
        self.lines.append(line)
        reached = STEP_LINE.match(line)
        if reached:
            code, text = reached.groups()
            if code != self.step or text.startswith("start: "):
                self.step = code
                self.detail = text.removeprefix("start: ") if text.startswith("start: ") else STEPS[code]
            if code not in self.reached:
                self.reached.append(code)
        named = RUN_LINE.match(line)
        if named:
            self.run_id = named[1]
        packaged = PACKAGED_LINE.match(line)
        if packaged:
            self.input_set = packaged[1]
        outcome = OUTCOME_LINE.match(line)
        if outcome:
            self.outcome = line

    def finish(self, exit_code: int) -> None:
        self.exit_code, self.finished = exit_code, time.time()

    @property
    def state(self) -> str:
        if self.exit_code is None:
            return "running"
        if self.kind in ("package", "approve"):
            return "done" if self.exit_code == 0 else "fault"
        return {EXIT_OK: "sealed", EXIT_BLOCKED: "blocked",
                EXIT_NOT_REPRODUCED: "not_reproduced"}.get(self.exit_code, "fault")

    def as_dict(self) -> dict:
        tail = list(self.lines)
        return {"kind": self.kind, "shown": self.shown, "state": self.state, "step": self.step,
                "detail": self.detail, "reached": self.reached, "run_id": self.run_id, "input_set": self.input_set,
                "exit_code": self.exit_code, "elapsed": (self.finished or time.time()) - self.started,
                "log": tail[-LOG_TAIL:], "message": self.outcome or (tail[-1] if tail else None)}


class Busy(RuntimeError):
    """The engine is already running; one job at a time."""


class Control:
    """What the page's requests share: where runs go, the book it opens on, and the one job in hand."""

    def __init__(self, runs_dir: Path, dataset: str = DATASET):
        self.runs_dir = runs_dir
        self.opening = f"inputs/{BOOKS[dataset]}"
        self.job: Job | None = None
        self.lock = threading.Lock()
        self._holding = tempfile.TemporaryDirectory(prefix="stress-room-files-", ignore_cleanup_errors=True)
        self.held = Path(self._holding.name)  # files added on the page, until they join a set
        self.added: dict[str, dict] = {}

    def command(self, args: list[str]) -> tuple[list[str], str]:
        """(what is executed, what the page shows). The two differ only in how stress is called."""
        where = [] if self.runs_dir == nb.RUNS_DIR else ["--runs-dir", str(self.runs_dir)]
        full = [*args, *where]
        return [sys.executable, "-m", "stress.cli", *full], "uv run stress " + " ".join(full)

    @staticmethod
    def one_off(args: list[str]) -> tuple[list[str], str]:
        return [sys.executable, "-m", "foundation.synth", *args], "uv run python -m foundation.synth " + " ".join(args)

    def run_argument(self, run_id: str) -> str:
        return from_root(self.runs_dir / run_id)

    def _refuse_if_busy(self) -> None:
        if self.job and self.job.exit_code is None:
            raise Busy(f"a {self.job.kind} is already in progress")

    def start(self, kind: str, command: list[str], shown: str, after: Callable[[], None] | None = None) -> Job:
        with self.lock:
            self._refuse_if_busy()
            self.job = job = Job(kind, shown, after=after)
            try:
                process = subprocess.Popen(
                    command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    **DETACHED)
            except OSError as exc:
                job.add(f"could not start: {exc}")
                job.finish(EXIT_ERROR)
                return job
        threading.Thread(target=self._follow, args=(job, process), daemon=True).start()
        return job

    @staticmethod
    def _follow(job: Job, process: subprocess.Popen) -> None:
        for line in process.stdout:
            job.add(line.rstrip())
        code = process.wait()
        if code == 0 and job.after:
            job.after()
        job.finish(code)

    def folder(self, run_id: str) -> Path | None:
        path = self.runs_dir / run_id
        return path if RUN_NAME.fullmatch(run_id) and path.is_dir() else None

    def plan(self, form: dict) -> tuple[dict, list[str] | None, str]:
        """The checked setup, its arguments if no new file is needed, and the name it would be saved under."""
        inputs = input_inventory()
        doc = checked_document(form, inputs)
        name = checked_name(form.get("name") or "setup")
        if preflight.needs_specification(doc):
            return doc, None, name
        return doc, run_arguments(doc, inputs), name

    def preflight(self, form: dict) -> dict:
        """What the engine says about a setup before anything is calculated, and what it would run."""
        try:
            doc, flags, name = self.plan(form)
        except Refused:
            # An input set today's engine cannot read is still judged by the engine, so that the page
            # shows its block (R2, the missing column) rather than a refusal; Start still refuses it.
            inputs = input_inventory()
            doc = checked_document(form, inputs)
            if preflight.needs_specification(doc) or next(r for r in inputs if r["inputs"] == doc["run"]["inputs"])["runnable"]:
                raise
            verdict = preflight.dry_run(run_config(doc))
            return {**verdict, "needs_specification": False, "shown": "", "yaml": specification_text(doc, SPECS)}
        if flags is None:
            with tempfile.TemporaryDirectory(prefix="stress-preflight-") as temp:
                path = Path(temp) / "specification.yaml"
                path.write_text(specification_text(doc, path.parent), encoding="utf-8", newline="\n")
                config = RunConfig(inputs="", scenarios=(REQUIRED_SCENARIO,), variant="core", specification=str(path))
                verdict = preflight.dry_run(config)
            shown = self.command(["run", "--specification", from_root(SPECS / f"{name}.yaml")])[1]
        else:
            verdict = preflight.dry_run(run_config(doc))
            shown = self.command(flags)[1]
        return {**verdict, "needs_specification": flags is None, "shown": shown,
                "yaml": specification_text(doc, SPECS)}

    def start_run(self, form: dict) -> Job:
        """Start exactly what the page showed: the flags, or the file saved under the name shown."""
        doc, flags, name = self.plan(form)
        if flags is None:
            flags = ["run", "--specification", from_root(save_specification(name, doc))]
        return self.start("run", *self.command(flags))

    def add_file(self, name: str, original: str, stream, length: int) -> dict:
        """A file the page sends for one of the seven places. It waits here, and only `use_files` puts
        it into a set. A file that fails its check stays listed, with what is wrong with it, because
        that is what the person needs to see; it cannot be used."""
        spec = SPEC_OF.get(name)
        if spec is None:
            raise Refused(f"the run has no file called {name}")
        target = self.held / spec.filename
        partial = target.with_suffix(".part")
        with partial.open("wb") as out:
            left = length
            while left:
                chunk = stream.read(min(CHUNK, left))
                if not chunk:
                    raise Refused("the file did not arrive in full")
                out.write(chunk)
                left -= len(chunk)
        os.replace(partial, target)  # a transfer that broke off leaves the earlier file in place
        shown = Path(original.replace("\\", "/")).name[:200] or spec.filename  # shown, never a path
        view = {"name": name, "original": shown, "bytes": length, **preflight.inspected(spec, target)}
        with self.lock:
            self.added[name] = view
        return view

    def remove_file(self, name: str) -> None:
        spec = SPEC_OF.get(name)
        if spec is None:
            raise Refused(f"the run has no file called {name}")
        with self.lock:
            self.added.pop(name, None)
        (self.held / spec.filename).unlink(missing_ok=True)

    def use_files(self, form: dict) -> Job:
        """O-step: the files added here, with the saved set's files for the other places, frozen as
        inputs/<hash>/ with pending approval. A set with the same contents comes back unchanged."""
        base = form.get("base") or None
        saved = None
        if base is not None:
            saved = nb.INPUTS_DIR / _one_of(base, {row["inputs"] for row in input_inventory()}, "saved set").split("/")[1]
        with self.lock:
            self._refuse_if_busy()
            used = dict(self.added)
            assembled = self.held / "assembled"
            shutil.rmtree(assembled, ignore_errors=True)
            assembled.mkdir()
        absent = []
        for spec in DATASETS:
            source = self.held / spec.filename if spec.name in used else saved and saved / spec.filename
            if source and source.is_file():
                shutil.copyfile(source, assembled / spec.filename)
            else:
                absent.append(preflight.FILE_GUIDE[spec.name][0])
        if absent:
            raise Refused(f"still missing: {', '.join(absent)}")
        wrong = [f"{preflight.FILE_GUIDE[f['name']][0]}: {f['problem']}"
                 for f in preflight.prepared_status(assembled)["files"] if f["problem"]]
        if wrong:
            raise Refused(" ".join(wrong))

        def release() -> None:  # a file added while the packaging ran stays on the list
            with self.lock:
                taken = [name for name, view in used.items() if self.added.get(name) is view]
            for name in taken:
                self.remove_file(name)

        return self.start("package", *self.one_off(["package", "--source", str(assembled), "--out", from_root(nb.INPUTS_DIR)]),
                          after=release)

    def approve(self, form: dict) -> Job:
        """O-step: record the owner's approval beside an input set. The data files are not touched."""
        listed = {row["inputs"] for row in input_inventory()}
        folder = _one_of(form.get("inputs"), listed, "input set")
        approver = checked_approver(form.get("approver"))
        return self.start("approve", *self.one_off(["approve", from_root(nb.INPUTS_DIR / folder.split("/")[1]),
                                                    "--approver", approver]))

    def state(self) -> dict:
        """Everything the page shows that does not belong to one run or one input set."""
        runs = list_runs(self.runs_dir)
        return {
            "steps": STEPS, "typical_seconds": typical_seconds(runs), "runs": runs, "readings": READINGS,
            "inputs": input_inventory(), "opening": self.opening, "roles": preflight.file_roles(), "added": self.added,
            "anchor": REQUIRED_SCENARIO, "inputs_dir": from_root(nb.INPUTS_DIR),
        }


def input_view(folder: Path) -> dict:
    """One input set: its files as they stand, and, when they can be read, what they offer and hold."""
    view = {"folder": f"inputs/{folder.name}", "files": preflight.files_of(folder), "base": None, "summary": None,
            "approval": preflight.approval_of(folder), "error": None}
    try:
        view["base"] = preflight.base_of(folder)
        view["summary"] = preflight.table_summary(folder)
    except (OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
        view["error"] = f"{type(exc).__name__}: {exc}"
    return view


# --- serving -------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    """A loopback server is still reachable from any page open in the browser. So a request counts
    only with this server's own Host (no DNS rebinding) and no foreign Origin (no cross-site start).
    Hosted, the server sits behind a router that ends TLS, so a request counts only over https and
    with no foreign Origin. There is no sign-in: whoever has the address has the page."""

    control: Control
    hosted: bool = False
    server_version = "StressControlRoom"

    def log_message(self, *_) -> None:
        pass

    def _send(self, status: int, body: bytes, content_type: str, **headers) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in headers.items():
                self.send_header(name.replace("_", "-"), value)
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            pass  # the page went away

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, allow_nan=False, default=str).encode(), "application/json")

    def _ours(self) -> bool:
        if self.hosted:
            return self._ours_hosted()
        hosts = {f"{HOST}:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host") in hosts and (origin is None or origin in {f"http://{h}" for h in hosts}):
            return True
        self._json(403, {"error": "this server answers only its own page"})
        return False

    def _ours_hosted(self) -> bool:
        host = self.headers.get("Host", "")
        if self.headers.get("X-Forwarded-Proto") != "https":
            self._send(308, b"", "text/plain", Location=f"https://{host}{self.path}")
        elif self.headers.get("Origin") not in (None, f"https://{host}"):
            self._json(403, {"error": "this server answers only its own page"})
        else:
            return True
        return False

    def do_GET(self) -> None:
        if self._ours():
            self._answering(self._get)

    def _answering(self, handle) -> None:
        """A request that fails says why; it must not read as an empty answer."""
        try:
            handle()
        except Refused as exc:
            self._json(400, {"error": str(exc)})
        except BlockingError as exc:  # a file the engine refuses to read
            self._json(400, {"error": f"{exc.code}: {exc.message}"})
        except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _get(self) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        run = RUN_ROUTE.fullmatch(path)
        inputs = INPUT_ROUTE.fullmatch(path)
        control = self.control
        if path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8", Content_Security_Policy=PAGE_POLICY)
        elif path == "/api/state":
            self._json(200, control.state())
        elif path == "/api/job":
            self._json(200, control.job.as_dict() if control.job else {"state": "idle"})
        elif path == "/api/guide":
            self._json(200, guide.step_one())
        elif path == "/api/setup":
            self._json(200, setup_of(query, control.runs_dir))
        elif inputs:
            self._inputs(unquote(inputs[1]), inputs[2], query)
        elif run:
            self._run(unquote(run[1]), run[2])
        else:
            self._json(404, {"error": "not found"})

    def _inputs(self, name: str, what: str | None, query: dict) -> None:
        """One input set by its hash. Only a name of that form reaches a file, as in nbtools."""
        folder = nb.INPUTS_DIR / name
        if not nb.INPUT_SET_NAME.fullmatch(name) or not folder.is_dir():
            self._json(404, {"error": f"no input set {name}"})
        elif what == "preview":
            try:
                offset = int(query.get("offset", "0"))
            except ValueError:
                offset = 0
            body = preflight.preview(folder, query.get("table", ""), offset, query.get("q", ""))
            self._json(200 if body else 404, body or {"error": "no such table"})
        elif what == "matrix":
            body = preflight.matrix_of(folder, query.get("segment", ""))
            self._json(200 if body else 404, body or {"error": "no such segment"})
        else:
            self._json(200, input_view(folder))

    def _run(self, run_id: str, name: str | None) -> None:
        folder = self.control.folder(run_id)
        if folder is None:
            self._json(404, {"error": f"no run {run_id}"})
        elif name:
            relative, content_type = RUN_FILES[name]
            target = folder / relative
            if not target.is_file():
                self._json(404, {"error": f"this run has no {name}"})
                return
            headers = {}
            if name == "report":
                headers["Content_Disposition"] = f'attachment; filename="{run_id}-{target.name}"'
            self._send(200, target.read_bytes(), content_type, **headers)
        else:
            try:
                self._json(200, run_view(folder))
            except BlockingError as exc:  # a sealed file changed, or the folder was never sealed
                self._json(409, {"error": f"{exc.code}: {exc.message}"})

    def do_POST(self) -> None:
        if not self._ours():
            return
        length = int(self.headers.get("Content-Length") or 0)
        path = urlsplit(self.path).path
        kind = self.headers.get_content_type()
        added = FILE_ROUTE.fullmatch(path)
        if added:  # a file's bytes, not a form. Neither type can come from a plain cross-site form.
            if kind != "application/octet-stream":
                self._json(415, {"error": "send the file's bytes"})
            elif not 0 < length <= FILE_LIMIT:
                self._json(413, {"error": "that file is empty or too large"})
            else:
                original = unquote(self.headers.get("X-File-Name") or "")
                self._answering(lambda: self._json(200, self.control.add_file(added[1], original, self.rfile, length)))
        elif kind != "application/json":
            self._json(415, {"error": "send JSON"})
        elif length > BODY_LIMIT:
            self._json(413, {"error": "too large"})
        else:
            body = self.rfile.read(length)
            self._answering(lambda: self._post(path, body))

    def _post(self, path: str, body: bytes) -> None:
        control = self.control
        try:
            form = json.loads(body or b"{}")
            if not isinstance(form, dict):
                raise Refused("send an object")
            if path == "/api/preflight":
                self._json(200, control.preflight(form))
            elif path == "/api/yaml":
                text = form.get("yaml")
                if not isinstance(text, str):
                    raise Refused("send the YAML text")
                self._json(200, {"document": preflight.parse_yaml(text, SPECS)})
            elif path == "/api/save":
                doc, _, name = control.plan(form)
                self._json(200, {"path": from_root(save_specification(name, doc))})
            elif path == "/api/start":
                self._json(202, control.start_run(form).as_dict())
            elif path == "/api/rerun":
                run_id = str(form.get("run_id"))
                if control.folder(run_id) is None:
                    raise Refused(f"no run {run_id}")
                command, shown = control.command(["rerun", "--run", control.run_argument(run_id)])
                self._json(202, control.start("rerun", command, shown).as_dict())
            elif path == "/api/remove-file":
                control.remove_file(str(form.get("name")))
                self._json(200, {"added": control.added})
            elif path == "/api/use-files":
                self._json(202, control.use_files(form).as_dict())
            elif path == "/api/approve":
                self._json(202, control.approve(form).as_dict())
            else:
                self._json(404, {"error": "not found"})
        except ValueError as exc:  # a Refused is one; so is bad JSON
            self._json(400, {"error": str(exc)})
        except Busy as exc:
            self._json(409, {"error": str(exc)})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"  # on Windows the option lets a second server share the port


def serve(runs_dir: Path, port: int = PORT, host: str = HOST, dataset: str = DATASET) -> Server:
    check_dataset(dataset)
    handler = type("BoundHandler", (Handler,), {"control": Control(runs_dir, dataset), "hosted": host != HOST})
    return Server((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Control room for the stress engine.")
    parser.add_argument("--host", default=HOST, help=f"listen here instead; anything but {HOST} is a public site with no sign-in")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--runs-dir", type=Path, default=nb.RUNS_DIR, help="where runs are read and written")
    parser.add_argument("--no-browser", action="store_true", help="do not open the page")
    parser.add_argument("--dataset", default=os.environ.get("DATASET", DATASET),
                        help=f"the book the page opens on, {' or '.join(BOOKS)}; default DATASET from the environment, else {DATASET}")
    args = parser.parse_args(argv)
    try:
        server = serve(args.runs_dir.resolve(), args.port, args.host, args.dataset)
    except Refused as exc:
        parser.error(str(exc))
    except OSError as exc:
        print(f"could not listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    url = f"http://{args.host}:{server.server_port}"
    print(f"control room at {url} (Ctrl+C stops it; a run in progress finishes on its own)", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
