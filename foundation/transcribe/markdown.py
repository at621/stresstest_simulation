"""Reading the requirements markdown: sections, tables, requirement paragraphs and numbers."""

import re
from decimal import Decimal
from pathlib import Path

REQUIREMENTS_FILE = "EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md"

# A number as written in the spec: optional sign, thousands commas, decimals, exponent, percent.
# It must not follow a letter, digit, dot, section sign or hyphen, so "S1", "AT-25", "End-2029",
# "§5.2" and "PD-03" are not read as numbers.
NUMBER = re.compile(r"(?<![\w.§\-])(-?\d+(?:,\d{3})*(?:\.\d+)?(?:e-?\d+)?)(%?)")
FRACTION = re.compile(r"(?<![\w.§\-])(\d+)/(\d+)(?![\d%])")

WORD_NUMBERS = {
    "zero": 0.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "ten": 10.0,
    "one-sixth": 1 / 6,
    "five-sixths": 5 / 6,
}


class Spec:
    """The requirements document, split into lines for section and table lookup."""

    def __init__(self, path: Path):
        self.path = path
        self.text = path.read_text(encoding="utf-8")
        self.lines = self.text.splitlines()
        match = re.search(r"\*\*Document version:\*\*\s*([\d.]+)", self.text)
        if not match:
            raise ValueError("requirements document has no version line")
        self.version = match.group(1)
        match = re.search(r"\*\*Reference date:\*\*\s*(.+?)\s*$", self.text, re.MULTILINE)
        self.reference_date = match.group(1) if match else ""

    def section(self, heading_prefix: str) -> list[str]:
        """Lines under the heading that starts with ``heading_prefix`` (e.g. "### 5.1")."""
        start = None
        level = 0
        for i, line in enumerate(self.lines):
            if start is None and line.startswith(heading_prefix):
                start = i + 1
                level = len(line) - len(line.lstrip("#"))
                continue
            if start is not None and line.startswith("#"):
                this_level = len(line) - len(line.lstrip("#"))
                if this_level <= level:
                    return self.lines[start:i]
        if start is None:
            raise KeyError(f"section {heading_prefix!r} not found")
        return self.lines[start:]

    def table(self, heading_prefix: str, index: int = 0) -> list[dict[str, str]]:
        """The ``index``-th markdown table in a section, as a list of row dicts by header."""
        tables: list[list[str]] = []
        current: list[str] = []
        for line in self.section(heading_prefix):
            if line.startswith("|"):
                current.append(line)
            elif current:
                tables.append(current)
                current = []
        if current:
            tables.append(current)
        rows = tables[index]
        header = split_row(rows[0])
        out = []
        for row in rows[2:]:
            cells = split_row(row)
            out.append(dict(zip(header, cells)))
        return out

    def requirement(self, req_id: str) -> str:
        """The paragraph of a bold-labelled requirement such as ``**ECL-10 — DESIGN ...**``."""
        pattern = re.compile(r"^\*\*" + re.escape(req_id) + r"\b.*$", re.MULTILINE)
        match = pattern.search(self.text)
        if not match:
            raise KeyError(f"requirement {req_id} not found")
        return match.group(0)

    def paragraph_containing(self, phrase: str) -> str:
        for para in self.text.split("\n\n"):
            if phrase in para:
                return para.strip()
        raise KeyError(f"no paragraph contains {phrase!r}")


def split_row(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def to_float(token: str, percent: bool = False) -> float:
    value = Decimal(token.replace(",", ""))
    if percent:
        value = value / 100
    return float(value)


def numbers(text: str) -> list[float]:
    """Every number in ``text`` in order, percentages as decimal fractions."""
    return [to_float(m.group(1), m.group(2) == "%") for m in NUMBER.finditer(text)]


def first(pattern: str, text: str, percent: bool | None = None) -> float:
    """The number captured by group 1 of ``pattern``; ``percent`` reads a trailing % sign."""
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"pattern {pattern!r} not found in {text!r}")
    token = match.group(1)
    is_pct = token.endswith("%") if percent is None else percent
    return to_float(token.rstrip("%"), is_pct)


def all_after(pattern: str, text: str) -> list[float]:
    """All numbers in the text that follows the first match of ``pattern`` up to ';'."""
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"pattern {pattern!r} not found in {text!r}")
    rest = text[match.end():].split(";")[0]
    return numbers(rest)


def allowed_numbers(text: str) -> list[float]:
    """Numbers a transcription may contain: written numbers, fractions and number words."""
    found = []
    for m in NUMBER.finditer(text):
        found.append(to_float(m.group(1)))
        if m.group(2) == "%":
            found.append(to_float(m.group(1), True))
    for m in FRACTION.finditer(text):
        found.append(int(m.group(1)) / int(m.group(2)))
    lowered = text.lower()
    for word, value in WORD_NUMBERS.items():
        if re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", lowered):
            found.append(value)
    return found


def check_transcribed(value, source: str, where: str) -> None:
    """Fail if any number in ``value`` does not appear in ``source`` (no number typed by hand)."""
    allowed = allowed_numbers(source)
    for leaf in leaves(value):
        if isinstance(leaf, bool) or not isinstance(leaf, (int, float)):
            continue
        if not any(abs(leaf - a) <= 1e-12 * max(1.0, abs(a)) for a in allowed):
            raise ValueError(f"{where}: {leaf!r} does not appear in the source text {source!r}")


def leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from leaves(item)
    else:
        yield value
