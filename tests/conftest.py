"""Shared test helpers: oracle loading from docs/spec/ and the section 12.3 tolerances.

Every test carries ``@pytest.mark.at(...)``, ``req(...)`` or ``control(...)``; collection fails
otherwise, and also when a marker names an ID that the requirements do not contain.
Expected values come from docs/spec/, never typed into a test. Helpers are in tests/support.py.
"""

import re
from pathlib import Path

import pytest
from hypothesis.configuration import set_hypothesis_home_dir

from tests import builders
from tests.support import MARKERS, SPEC_DIR, control_names, requirements_text

# Hypothesis keeps its example database under tests/, not at the repository root.
set_hypothesis_home_dir(Path(__file__).parent / ".hypothesis")


@pytest.fixture(scope="session")
def full_inputs(tmp_path_factory):
    """The synthetic input set, rebuilt by O2-O4 in a temporary folder."""
    return builders.full_input_set(tmp_path_factory.mktemp("inputs"))


@pytest.fixture(scope="session")
def full_tables(full_inputs):
    return builders.load(full_inputs)


@pytest.fixture(scope="session")
def core_run(full_inputs, tmp_path_factory):
    """One core run of both scenarios on the full synthetic book."""
    ctx, manifest = builders.run(full_inputs, tmp_path_factory.mktemp("runs"))
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    return ctx, manifest


@pytest.fixture(scope="session")
def mini_tables(full_tables):
    return builders.mini(full_tables)


@pytest.fixture(scope="session")
def reference_runs(full_tables, tmp_path_factory):
    """The AT-34/AT-35/AT-42 reference facilities, run in the core and utilisation variants."""
    from tests.support import oracle

    tables, ids = builders.reference_set(builders.mini(full_tables, per_cell=3),
                                         oracle("AT-34"), oracle("AT-42"))
    inputs = builders.write(tables, tmp_path_factory.mktemp("reference_inputs"))
    runs = tmp_path_factory.mktemp("reference_runs")
    out = {"ids": ids, "inputs": inputs, "runs_dir": runs}
    for variant in ("core", "utilisation"):
        ctx, manifest = builders.run(inputs, runs, variant=variant)
        assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
        out[variant] = (ctx, manifest)
    return out


@pytest.fixture
def mini(mini_tables):
    """A fresh, editable copy of the small input set."""
    return builders.copy_tables(mini_tables)


def pytest_collection_modifyitems(session, config, items):
    unmarked = []
    unknown = []
    oracle_ids = {p.stem for p in (SPEC_DIR / "oracles").glob("AT-*.yaml")}
    text = requirements_text()
    for item in items:
        marks = [m for m in item.iter_markers() if m.name in MARKERS]
        if not marks:
            unmarked.append(item.nodeid)
            continue
        for mark in marks:
            for value in mark.args:
                if mark.name == "at" and value not in oracle_ids:
                    unknown.append(f"{item.nodeid}: at({value!r}) has no oracle")
                elif mark.name == "req" and not re.search(r"\b" + re.escape(value) + r"\b", text):
                    unknown.append(f"{item.nodeid}: req({value!r}) is not in the requirements")
                elif mark.name == "control" and value not in control_names():
                    unknown.append(f"{item.nodeid}: control({value!r}) is not a section 12.2 control")
    problems = []
    if unmarked:
        problems.append("tests without an at, req or control marker:\n  " + "\n  ".join(unmarked))
    if unknown:
        problems.append("markers naming unknown IDs:\n  " + "\n  ".join(unknown))
    if problems:
        raise pytest.UsageError("\n".join(problems))
