"""Repository rules of docs/architecture.md section 2 that tests can hold."""

import ast
import types

import pytest

from tests.conftest import pytest_collection_modifyitems
from tests.support import ROOT, SPEC_DIR

STEPS = ("lineage", "ingest", "validate", "scenario", "cashflows", "params", "projection", "ecl",
         "accounting", "report", "capital")


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


@pytest.mark.control("Repository rules")
def test_no_imports_across_parts_or_steps():
    for path in (ROOT / "src" / "stress").rglob("*.py"):
        for name in imports(path):
            assert not name.startswith("foundation"), f"{path}: the engine imports {name}"
            parts = path.relative_to(ROOT / "src").parts
            if len(parts) > 2 and parts[1] in STEPS:
                for other in STEPS:
                    if other != parts[1]:
                        assert not name.startswith(f"stress.{other}"), f"{path}: step imports {name}"
    for path in (ROOT / "foundation").rglob("*.py"):
        for name in imports(path):
            assert not name.startswith("stress"), f"{path}: one-off step imports {name}"


@pytest.mark.control("Repository rules")
def test_every_acceptance_case_has_exactly_one_test():
    oracle_ids = sorted(p.stem for p in (SPEC_DIR / "oracles").glob("AT-*.yaml"))
    found = []
    for path in (ROOT / "tests" / "acceptance").glob("test_*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "at":
                found.append(node.args[0].value)
    assert sorted(found) == oracle_ids


@pytest.mark.control("Repository rules")
def test_unmarked_test_fails_collection():
    item = types.SimpleNamespace(nodeid="tests/x.py::test_unmarked", iter_markers=list)
    with pytest.raises(pytest.UsageError):
        pytest_collection_modifyitems(None, None, [item])
    mark = types.SimpleNamespace(name="req", args=("NOT-99",))
    item = types.SimpleNamespace(nodeid="tests/x.py::test_bad_id", iter_markers=lambda: [mark])
    with pytest.raises(pytest.UsageError):
        pytest_collection_modifyitems(None, None, [item])
