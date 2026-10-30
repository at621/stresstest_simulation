"""The traceability matrix and source register stay complete and current (requirements section 14)."""

import ast

import pytest
import yaml

from tests import traceability as tr
from tests.support import REQUIREMENTS, ROOT, requirements_text

KNOWN = {"ECL-01", "ECL-02", "ECL-03", "ECL-11", "EXP-03", "EXP-05", "SYN-04", "SYN-PAR-04",
         "SYN-PAR-05", "PD-03", "DAT-04", "CAP-05", "CAP-06"}

MINI_REQUIREMENTS = """**Document version:** 9.9
**Regulatory basis:** EBA **draft** package published on 11 June 2026.

## 2. Alignment

| ID | DRAFT requirement | Source anchor | Required evidence |
|---|---|---|---|
| REG-01 | Use the horizon. | S3, §1.3 | Dates |

## 8. Method

**ECL-01 — DESIGN.** Define expected loss. [S3 ¶55, ¶123–125, Boxes 4–9]

**ECL-02 — DESIGN — a title.** An S3 exposure stays S3, see §5.1 and DAT-04. Passes AT-02.

**DAT-04 — DESIGN.** Keep attributes apart.

## 12. Validation

### 12.2 Controls with required outcomes

| Control | Required result |
|---|---|
| Cash-flow inputs | Block as in ECL-02 |

### 12.3 Proposed tolerances

## 15. Sources

Sources were checked on 17 October 2026. Paragraph numbers refer to the June 2026 draft.

- **S3 — A Draft Methodological Note.** Main; particularly §2 for the retained scope. [PDF](https://example.org/s3.pdf).
"""

MINI_TEST = '''"""AT-02: a case (ECL-01)."""

import pytest


@pytest.mark.at("AT-02")
def test_case():
    pass


@pytest.mark.req("DAT-04")
def test_marked():
    pass
'''


@pytest.fixture
def repo(tmp_path):
    """A very small repository with everything the generator reads."""
    files = {
        REQUIREMENTS.relative_to(ROOT): MINI_REQUIREMENTS,
        tr.ORACLES / "AT-02.yaml": yaml.safe_dump({"id": "AT-02", "references": []}),
        tr.ASSUMPTIONS: "| A1 | Topic | Says DAT-04 |\n",
        tr.STATUS_FILE: yaml.safe_dump({"requirements": {
            "REG-01": {"status": "deferred", "reason": "Not yet", "decided_in": ["A1"]}}}),
        "tests/unit/test_mini.py": MINI_TEST,
        "src/stress/mini.py": '"""ECL-01-ECL-02."""\n',
        "foundation/mini.yaml": "# nothing named here\n",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def set_status(repo, entries):
    (repo / tr.STATUS_FILE).write_text(yaml.safe_dump({"requirements": entries}), encoding="utf-8")


@pytest.mark.control("Repository rules")
def test_committed_files_are_current():
    stale = tr.check()
    assert not stale, f"stale: {stale}. Run `uv run python -m tests.traceability` and commit them."


@pytest.mark.control("Repository rules")
def test_check_reports_a_stale_file_and_write_clears_it(repo):
    assert sorted(tr.check(repo)) == sorted(p.as_posix() for p in (tr.MATRIX, tr.REGISTER))
    tr.write(repo)
    assert tr.check(repo) == []
    set_status(repo, {"REG-01": {"status": "deferred", "reason": "Changed", "decided_in": ["A1"]}})
    assert tr.check(repo) == [tr.MATRIX.as_posix()]


@pytest.mark.control("Repository rules")
def test_a_requirement_with_no_status_fails(repo):
    set_status(repo, {})
    with pytest.raises(tr.TraceabilityError, match="REG-01"):
        tr.build(repo)


@pytest.mark.control("Repository rules")
def test_every_requirement_has_exactly_one_status():
    text = requirements_text()
    requirements, _, rows = tr._rows(ROOT, text)
    assert [r.requirement.id for r in rows] == list(requirements)
    assert {r.status for r in rows} <= set(tr.STATUSES)


@pytest.mark.control("Repository rules")
def test_statuses_derive_from_links(repo):
    tr.write(repo)
    matrix = (repo / tr.MATRIX).read_text(encoding="utf-8")
    assert "| REG-01 | Use the horizon | `deferred` |" in matrix
    assert "| ECL-01 | Define expected loss | `tested` | AT-02 |" in matrix  # test docstring
    assert "| ECL-02 | A title | `tested` | AT-02 |" in matrix  # requirement text names the case
    assert "| DAT-04 | Keep attributes apart | `tested` |  | `unit/test_mini.py::test_marked` |" in matrix


@pytest.mark.control("Repository rules")
@pytest.mark.parametrize("dash", ["-", "‐", "‑", "‒", "–", "—", "―",
                                  "−"])
def test_a_range_expands_with_whichever_dash_appears(dash):
    assert tr.find_ids(f"ECL-01{dash}ECL-03", KNOWN) == {"ECL-01", "ECL-02", "ECL-03"}
    assert tr.find_ids(f"ECL-01 {dash} ECL-03", KNOWN) == {"ECL-01", "ECL-02", "ECL-03"}
    assert tr.find_ids(f"CAP-05{dash}06", KNOWN) == {"CAP-05", "CAP-06"}
    assert tr.find_ids(f"SYN-PAR-04{dash}SYN-PAR-05", KNOWN) == {"SYN-PAR-04", "SYN-PAR-05"}


@pytest.mark.control("Repository rules")
def test_a_range_keeps_only_requirements_that_exist():
    assert tr.find_ids("EXP-03–EXP-05", KNOWN) == {"EXP-03", "EXP-05"}


@pytest.mark.control("Repository rules")
def test_a_dash_after_an_id_is_not_a_range():
    assert tr.find_ids("ECL-02 - 11 months", KNOWN) == {"ECL-02"}
    assert tr.find_ids("ECL-02 — ECL-11 is the rule, see PD-03", KNOWN) >= {"ECL-02", "ECL-11", "PD-03"}


@pytest.mark.control("Repository rules")
def test_an_id_matches_only_as_a_whole_word():
    assert tr.find_ids("XPD-03 and PD-031", KNOWN) == set()
    assert tr.find_ids("SYN-PAR-04", KNOWN) == {"SYN-PAR-04"}
    assert tr.find_ids("SYN-04", KNOWN) == {"SYN-04"}
    assert tr.find_ids("CAP-05/06 and SYN-04/SYN-PAR-05", KNOWN) == {"CAP-05", "CAP-06", "SYN-04",
                                                                     "SYN-PAR-05"}
    assert tr.AT_ID.findall("DAT-04 is not a case, AT-05 is") == ["AT-05"]


@pytest.mark.control("Repository rules")
@pytest.mark.parametrize("entry, message", [
    ({"status": "tested", "reason": "x"}, "not allowed"),
    ({"status": "built", "reason": "x"}, "not allowed"),
    ({"status": "unknown", "reason": "x"}, "not allowed"),
    ({"status": "deferred"}, "no reason"),
    ({"status": "deferred", "reason": "x"}, "no decision"),
    ({"status": "deferred", "reason": "x", "decided_in": ["A99"]}, "not in"),
    ({"status": "process", "reason": "x"}, "no evidence"),
    ({"status": "process", "reason": "x", "evidence": ["docs/nothing.md"]}, "does not exist"),
    ({"reason": "x", "tests": ["unit/test_mini.py::test_gone"]}, "not a test"),
    ({"reason": "x", "acceptance": ["AT-99"]}, "not an acceptance case"),
    ({"reason": "x", "code": [{"path": "src/stress/mini.py", "contains": "gone"}]}, "does not contain"),
    ({"reason": "x", "invented": True}, "unknown fields"),
])
def test_the_hand_kept_file_is_checked(repo, entry, message):
    set_status(repo, {"REG-01": entry})
    with pytest.raises(tr.TraceabilityError, match=message):
        tr.build(repo)


@pytest.mark.control("Repository rules")
def test_a_status_for_an_unknown_requirement_fails(repo):
    set_status(repo, {"REG-01": {"status": "deferred", "reason": "x", "decided_in": ["A1"]},
                      "NOT-99": {"status": "deferred", "reason": "x", "decided_in": ["A1"]}})
    with pytest.raises(tr.TraceabilityError, match="NOT-99"):
        tr.build(repo)


@pytest.mark.control("Repository rules")
def test_unmet_needs_no_decision_and_is_counted(repo):
    set_status(repo, {"REG-01": {"status": "deferred", "reason": tr.UNMET, "note": "Why."}})
    tr.write(repo)
    matrix = (repo / tr.MATRIX).read_text(encoding="utf-8")
    assert f"1 are unmet with no recorded decision. Their reason reads \"{tr.UNMET}\": REG-01." in matrix
    assert f"{tr.UNMET}. Why. |" in matrix


@pytest.mark.control("Repository rules")
def test_needs_review_flags_an_unmet_requirement_a_test_now_names(repo):
    set_status(repo, {"REG-01": {"status": "deferred", "reason": "x", "decided_in": ["A1"]},
                      "DAT-04": {"status": "deferred", "reason": tr.UNMET}})
    assert tr.needs_review(repo) == ["DAT-04"]


@pytest.mark.control("Repository rules")
def test_markers_are_read_from_function_class_and_module(tmp_path):
    path = tmp_path / "test_marks.py"
    path.write_text('''
import pytest
pytestmark = pytest.mark.req("PD-03")

class TestGroup:
    @pytest.mark.at("AT-02")
    def test_method(self):
        pass

@pytest.mark.parametrize("x", [pytest.param(1, marks=pytest.mark.req("ECL-01"))])
def test_param(x):
    pass
''', encoding="utf-8")
    method, param = tr.marked_tests(path, "test_marks.py")
    assert (method.node, method.ats, method.reqs) == ("test_marks.py::TestGroup::test_method",
                                                      ("AT-02",), ("PD-03",))
    assert set(param.reqs) == {"PD-03", "ECL-01"}


@pytest.mark.control("Repository rules")
def test_a_marker_that_is_not_a_literal_fails(tmp_path):
    path = tmp_path / "test_marks.py"
    path.write_text('import pytest\nNAME = "PD-03"\n@pytest.mark.req(NAME)\ndef test_x():\n    pass\n',
                    encoding="utf-8")
    with pytest.raises(tr.TraceabilityError, match="text literal"):
        tr.marked_tests(path, "test_marks.py")


@pytest.mark.control("Repository rules")
def test_citations_expand_and_stage_three_is_not_a_source():
    sources = tr.parse_sources(MINI_REQUIREMENTS)
    cited = tr.parse_citations(MINI_REQUIREMENTS, sources)
    assert cited["S3", "¶124"] == {"ECL-01"}
    assert cited["S3", "Box 6"] == {"ECL-01"}
    assert cited["S3", "§1.3"] == {"REG-01"}
    assert cited["S3", "§2"] == {"§15"}
    assert ("S3", "§5.1") not in cited
    assert not any(owner == "ECL-02" for owners in cited.values() for owner in owners)


@pytest.mark.control("Repository rules")
def test_a_citation_of_a_source_missing_from_the_list_fails():
    text = MINI_REQUIREMENTS.replace("[S3 ¶55", "[S9 ¶55")
    with pytest.raises(tr.TraceabilityError, match="S9"):
        tr.parse_citations(text, tr.parse_sources(text))


@pytest.mark.control("Repository rules")
def test_the_register_shows_an_approval_only_if_recorded(repo):
    tr.write(repo)
    register = (repo / tr.REGISTER).read_text(encoding="utf-8")
    rows = [line for line in register.splitlines() if line.startswith("| S3")]
    assert rows and all(f"| {tr.NOT_APPROVED} |" in row for row in rows)
    (repo / tr.APPROVALS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (repo / tr.APPROVALS_FILE).write_text('approvals: {"S3 ¶124": "2027-02-15"}\n', encoding="utf-8")
    tr.write(repo)
    register = (repo / tr.REGISTER).read_text(encoding="utf-8")
    dated = [line for line in register.splitlines() if "2027-02-15" in line]
    assert len(dated) == 1 and "| ¶124 |" in dated[0]
    (repo / tr.APPROVALS_FILE).write_text('approvals: {"S3 ¶999": "2027-02-15"}\n', encoding="utf-8")
    with pytest.raises(tr.TraceabilityError, match="¶999"):
        tr.build(repo)


@pytest.mark.control("Repository rules")
def test_the_committed_register_invents_no_approval_date():
    recorded = yaml.safe_load((ROOT / tr.APPROVALS_FILE).read_text(encoding="utf-8"))["approvals"]
    if not recorded:
        rows = (ROOT / tr.REGISTER).read_text(encoding="utf-8").splitlines()
        rows = [row for row in rows if row.startswith("| S")]
        assert rows and all(f"| {tr.NOT_APPROVED} |" in row for row in rows)


@pytest.mark.control("Repository rules")
def test_the_generator_imports_neither_part_of_the_engine():
    tree = ast.parse((ROOT / "tests" / "traceability.py").read_text(encoding="utf-8"))
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
             for alias in node.names]
    names += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [n for n in names if n.split(".")[0] in ("stress", "foundation")]


@pytest.mark.control("Repository rules")
def test_the_template_covers_gov_03_and_the_final_package_checklist():
    text = (ROOT / tr.REGISTER.parent / "gov-03-impact-assessment-template.md").read_text(
        encoding="utf-8")
    for area in ("Data", "Perimeter", "Calculations", "Assumptions", "Reporting", "Acceptance cases"):
        assert f"| {area}: " in text, area
    for item in ("¶123–125", "Boxes 4–9", "¶113–118", "¶145–146", "¶153", "¶562–564",
                 "Template columns"):
        assert f"| {item} |" in text, item
