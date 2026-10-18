"""Section 6.2 illustrative macroeconomic paths with units and SYNTHETIC status, the SCN-05
compounded indices, and the section 8.7 calibration targets."""

import re

from foundation.transcribe.markdown import Spec, check_transcribed, first, to_float

# Row label of the section 6.2 table -> variable id, value type. Structural, not numerical.
VARIABLES = (
    ("Real GDP annual growth", "gdp_growth", "growth"),
    ("Unemployment level", "unemployment", "level"),
    ("Residential property annual price change", "residential_price_change", "growth"),
    ("CRE annual price change", "cre_price_change", "growth"),
    ("Reference interest rate level", "reference_rate", "level"),
)
INDEX_OF = {
    "residential_price_change": "residential_price_index",
    "cre_price_change": "cre_price_index",
}


def _variable(label: str) -> tuple[str, str, str]:
    for prefix, var, value_type in VARIABLES:
        if label.startswith(prefix):
            unit = "percent" if label.rstrip().endswith("%") else "unknown"
            return var, value_type, unit
    raise KeyError(f"unknown scenario variable {label!r}")


def scenario_paths(spec: Spec, countries: list[str]) -> dict:
    lines = [ln for ln in spec.section("### 6.2") if ln.startswith("|")]
    header = [c.strip() for c in lines[0].strip().strip("|").split("|")]
    # Header: Variable and unit | Baseline 2027 | 2028 | 2029 | Adverse 2027 | 2028 | 2029
    columns: list[tuple[str, int]] = []
    current = None
    for cell in header[1:]:
        match = re.match(r"(?:(Baseline|Adverse)\s+)?(\d{4})$", cell)
        if not match:
            raise ValueError(f"unexpected scenario header cell {cell!r}")
        if match.group(1):
            current = match.group(1).lower()
        columns.append((current, int(match.group(2))))

    variables: dict[str, dict] = {}
    paths: dict[str, dict] = {"baseline": {}, "adverse": {}}
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        var, value_type, unit = _variable(cells[0])
        variables[var] = {"label": cells[0].rsplit(",", 1)[0], "unit": unit, "value_type": value_type}
        for (scenario, year), cell in zip(columns, cells[1:]):
            paths[scenario].setdefault(var, {})[year] = to_float(cell)
        check_transcribed(
            {s: paths[s][var] for s in paths}, line, f"6.2 {var}"
        )

    intro = spec.paragraph_containing("Starting unemployment is")
    starting = {
        "unemployment": {"value": first(r"Starting unemployment is ([\d.]+)%", intro, False),
                         "unit": "percent", "value_type": "level"},
        "reference_rate": {"value": first(r"reference rate is ([\d.]+)%", intro, False),
                           "unit": "percent", "value_type": "level"},
        "residential_price_index": {"value": first(r"property indices are ([\d.]+)", intro, False),
                                    "unit": "index", "value_type": "index"},
        "cre_price_index": {"value": first(r"property indices are ([\d.]+)", intro, False),
                            "unit": "index", "value_type": "index"},
    }
    check_transcribed(starting, intro, "6.2 starting values")

    scn05 = spec.requirement("SCN-05")
    num = r"(\d+(?:\.\d+)?)"
    resi = re.search(
        rf"residential index shall be {num} in (\d{{4}}), {num} in (\d{{4}}) and {num} in (\d{{4}})", scn05
    )
    cre = re.search(rf"CRE indices shall be {num}, {num} and {num}", scn05)
    years = [int(resi.group(i)) for i in (2, 4, 6)]
    expected_indices = {
        "adverse": {
            "residential_price_index": dict(zip(years, (to_float(resi.group(i)) for i in (1, 3, 5)))),
            "cre_price_index": dict(zip(years, (to_float(cre.group(i)) for i in (1, 2, 3)))),
        }
    }
    check_transcribed(expected_indices, scn05, "SCN-05")

    first_year = min(y for _, y in columns)
    return {
        "source": {"document": spec.path.name, "version": spec.version, "section": "6.2"},
        "status": "SYNTHETIC",
        "source_type": "synthetic",
        "note": "Illustrative common paths for all six countries; not official scenarios (SCN-04).",
        "countries": countries,
        "starting_year": first_year - 1,
        "years": sorted({y for _, y in columns}),
        "variables": variables,
        "starting_values": starting,
        "paths": paths,
        "index_of": INDEX_OF,
        "expected_indices": expected_indices,
    }


def calibration_targets(spec: Spec) -> dict:
    segments: dict[str, dict] = {}
    for row in spec.table("### 8.7"):
        label = row["Reference segment"].strip()
        portfolio = label.split()[0]
        if "general governments" in label:
            seg = f"{portfolio}_GG"
        elif "credit institutions" in label:
            seg = f"{portfolio}_CI"
        else:
            seg = portfolio
        record = {
            "label": label,
            "portfolio": portfolio,
            "s1_pd": to_float(row["Opening S1 12-month PD"].rstrip("%"), True),
            "s2_pd": to_float(row["Opening S2 12-month PD"].rstrip("%"), True),
            "reference_lgd": to_float(row["Opening performing LGD"].rstrip("%"), True),
            "reference_life_years": to_float(row["Reference remaining life"].split()[0]),
            "reference_eir": to_float(row["Reference EIR"].rstrip("%"), True),
        }
        check_transcribed(record, " ".join(row.values()), f"8.7 {seg}")
        segments[seg] = record
    return {
        "source": {"document": spec.path.name, "version": spec.version, "section": "8.7"},
        "status": "SYNTHETIC",
        "rule": "SYN-PAR-05: drawn-exposure-weighted average one-year TTC PD of the grades holding "
                "each stage's exposures equals the stage target",
        "segments": segments,
    }
