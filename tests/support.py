"""Test helpers: oracle loading from docs/spec/ and the section 12.3 tolerances.

Expected values come from docs/spec/, never typed into a test.
"""

from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "docs" / "spec"
REQUIREMENTS = SPEC_DIR / "EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md"
INPUTS_DIR = ROOT / "inputs"

# Control names for tests of the repository rules themselves (docs/architecture.md section 2).
REPOSITORY_CONTROL = "Repository rules"
MARKERS = ("at", "req", "control")


@cache
def requirements_text() -> str:
    return REQUIREMENTS.read_text(encoding="utf-8")


@cache
def control_names() -> frozenset[str]:
    text = requirements_text().split("### 12.2", 1)[1].split("### 12.3", 1)[0]
    names = {line.split("|")[1].strip() for line in text.splitlines() if line.startswith("| ")}
    names.discard("Control")
    return frozenset(names | {REPOSITORY_CONTROL})


@cache
def oracle(at_id: str) -> dict:
    """The oracle record of an acceptance case, transcribed by O1."""
    path = SPEC_DIR / "oracles" / f"{at_id}.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@cache
def spec_yaml(name: str) -> dict:
    with (SPEC_DIR / name).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def tolerance(name: str) -> dict:
    return spec_yaml("targets.yaml")["tolerances"][name]


def within(actual: float, expected: float, tol: dict) -> bool:
    """Section 12.3 comparison for one value."""
    kind = tol["kind"]
    if kind == "exact":
        return actual == expected
    if kind == "abs":
        return abs(actual - expected) <= tol["abs"]
    if kind == "max_abs_rel":
        return abs(actual - expected) <= max(tol["abs"], tol["rel"] * abs(expected))
    raise ValueError(f"unknown tolerance kind {kind!r}")


def assert_close(actual, expected, tol: dict | str, what: str = "") -> None:
    if isinstance(tol, str):
        tol = tolerance(tol)
    if isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected), f"{what}: length {len(actual)} != {len(expected)}"
        for k, (a, e) in enumerate(zip(actual, expected)):
            assert_close(a, e, tol, f"{what}[{k}]")
        return
    assert within(float(actual), float(expected), tol), (
        f"{what}: {actual!r} differs from oracle {expected!r} beyond {tol}"
    )


def eur(million: float) -> float:
    """Spec tables are in EUR millions; the engine works in EUR."""
    return million * 1_000_000
