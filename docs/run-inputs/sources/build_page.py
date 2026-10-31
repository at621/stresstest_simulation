"""Build the run inputs page from the engine's input contract and one input set.

    uv run python docs/run-inputs/sources/build_page.py inputs/<hash>

The definitions are hand-written in definitions.py. Column lists, current values and parameter
values come from the code and the data, and the build stops if a field has no definition.
"""

import html
import json
import re
import sys
from pathlib import Path

import pandas as pd
import yaml
from definitions import (
    ANALYSIS_SECTIONS,
    ANALYSIS_TOP,
    APPROVAL,
    CLI_OPTIONS,
    COMMITMENTS,
    FACILITIES,
    MANIFEST,
    MEANINGS,
    OBLIGORS,
    OPENING_PROVISIONS,
    PARAMETER_PATHS,
    SCENARIO_RECORD,
    SCENARIO_START,
    SCENARIO_TOP,
    SCENARIO_VALUE,
    SEGMENT_FIELDS,
    SPEC_ASSIGNMENT,
    SPEC_MODEL,
    SPEC_OTHER,
    SPEC_PATH,
    SPEC_RUN,
    SPEC_SCENARIO,
    SPEC_SEGMENT,
    SPEC_TOP,
    TTC_PD_MATRIX,
)

from stress import cli
from stress.contracts import inputs as contract
from stress.contracts.specification import RUN_FIELDS, TOP_FIELDS

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent / "stress-run-inputs.html"
ROLES = {"calc": "drives results", "check": "checked only", "report": "reports only", "none": "not read"}
AMOUNTS = {"principal", "accrued_interest", "gca", "contractual_limit", "nominal_undrawn", "allowance_on",
           "provision_off", "overlay_amount"}
PERCENTS = {"interest_rate", "ttc_lgd", "accounting_ccf"}
TABLES = (("facilities", contract.FACILITIES, FACILITIES), ("obligors", contract.OBLIGORS, OBLIGORS),
          ("commitments", contract.COMMITMENTS, COMMITMENTS),
          ("opening_provisions", contract.OPENING_PROVISIONS, OPENING_PROVISIONS),
          ("ttc_pd_matrix", contract.TTC_PD_MATRIX, TTC_PD_MATRIX))


def rich(text) -> str:
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(str(text), quote=False))


def pill(role: str) -> str:
    return f'<span class="pill r-{role}">{ROLES[role]}</span>'


def euro(value: float) -> str:
    size = abs(value)
    if size >= 1e9:
        return f"€{value / 1e9:,.2f}bn"
    if size >= 1e6:
        return f"€{value / 1e6:,.1f}m"
    if size >= 1e3:
        return f"€{value / 1e3:,.1f}k"
    return f"€{value:,.2f}"


def counts(series: pd.Series) -> str:
    table = series.astype(str).value_counts()
    if len(table) == 1:
        return f"{table.index[0]} on all {table.iloc[0]:,} rows"
    if table.nunique() == 1:
        return f"{', '.join(sorted(table.index, key=lambda v: series.astype(str).eq(v).idxmax()))}: "                f"{table.iloc[0]:,} rows each"
    return " · ".join(f"{name}: {number:,}" for name, number in table.items())


def current(series: pd.Series, name: str) -> str:
    """One line on what the current input set holds in a column."""
    present = series.dropna()
    blanks = len(series) - len(present)
    if present.empty:
        return f"Blank on all {len(series):,} rows"
    if pd.api.types.is_bool_dtype(present):
        text = counts(present.map({True: "true", False: "false"}))
    elif name in AMOUNTS and present.nunique() > 1:
        text = f"{euro(present.min())} to {euro(present.max())}, total {euro(present.sum())}"
    elif name in AMOUNTS:
        text = euro(present.iloc[0])
    elif name in PERCENTS and present.nunique() > 1:
        text = f"{present.min():.2%} to {present.max():.2%}"
    elif name in PERCENTS:
        text = f"{present.iloc[0]:.0%}"
    elif present.nunique() <= 11:
        text = counts(present)
    elif pd.api.types.is_numeric_dtype(present):
        text = f"{present.min():,.4g} to {present.max():,.4g}"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(present.iloc[0])):
        text = f"{min(present)} to {max(present)}"
    else:
        text = f"{present.iloc[0]} to {present.iloc[-1]}, {present.nunique():,} distinct"
    return f"{text}. Blank on {blanks:,} rows" if blanks else text


def column_table(groups, spec, data: pd.DataFrame) -> str:
    defined = [row[0] for _, rows in groups for row in rows]
    assert sorted(defined) == sorted(spec.column_names), set(defined) ^ set(spec.column_names)
    kinds = {c.name: c for c in spec.columns}
    body = []
    for title, rows in groups:
        if len(groups) > 1:
            body.append(f'<tr class="group"><td colspan="5">{title}</td></tr>')
        for name, role, meaning, rule in rows:
            col = kinds[name]
            blank = "yes" if col.nullable else "no"
            note = f'<div class="rule">{rich(rule)}</div>' if rule else ""
            body.append(f"<tr><td><code>{name}</code></td><td>{col.kind}</td><td>{blank}</td>"
                        f"<td>{pill(role)}<div>{rich(meaning)}</div>{note}</td>"
                        f"<td>{rich(current(data[name], name))}</td></tr>")
    for name in [c for c in data.columns if c.endswith("__status")]:
        base = name.removesuffix("__status")
        body.append(f"<tr><td><code>{name}</code></td><td>str</td><td>no</td><td>{pill('check')}"
                    f"<div>Status of <code>{base}</code>: tells a true blank from a missing value.</div></td>"
                    f"<td>{rich(counts(data[name]))}</td></tr>")
    return ('<div class="scroll"><table class="tbl cols"><thead><tr><th>Column</th><th>Type</th><th>Blank</th>'
            "<th>Definition and rule</th><th>In the current set</th></tr></thead><tbody>"
            + "".join(body) + "</tbody></table></div>")


def field_table(rows, headers=("Field", "Role", "Type", "Definition", "Allowed"), values=None) -> str:
    """Rows of (field, role, type, definition, allowed), with a current value when given."""
    head = list(headers) + (["Current value"] if values is not None else [])
    body = []
    for name, role, kind, meaning, allowed in rows:
        tag = pill(role) if role in ROLES else rich(role)
        cells = f"<td><code>{html.escape(name)}</code></td><td>{tag}</td><td>{kind}</td><td>{rich(meaning)}</td>"
        cells += f"<td>{rich(allowed)}</td>"
        if values is not None:
            cells += f"<td>{rich(values.get(name, ''))}</td>"
        body.append(f"<tr>{cells}</tr>")
    titles = "".join(f"<th>{h}</th>" for h in head)
    return (f'<div class="scroll"><table class="tbl fields"><thead><tr>{titles}</tr></thead><tbody>'
            + "".join(body) + "</tbody></table></div>")


SPEC_HEADERS = ("Field", "Required", "Type", "Definition", "Allowed")


def walk(node, path=""):
    """Every leaf path of a document."""
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}" if path else str(key))
    else:
        yield path, node


def show(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict) and not value:
        return "empty"
    return "null" if value is None else str(value)


def parameter_values(ps: dict) -> dict:
    """Current values by documented path; every other leaf of the file stops the build."""
    documented = {row[0] for row in PARAMETER_PATHS}
    values: dict[str, list] = {}
    for path, value in walk({k: v for k, v in ps.items() if k != "segments"}):
        generic = re.sub(r"^variants\.[^.]+\.", "variants.<id>.", path)
        generic = re.sub(r"(repayment_profile|ccf)\.[^.]+$", r"\1.<id>", generic)
        generic = re.sub(r"\.ccf$", ".ccf.<id>", generic)
        generic = re.sub(r"^sicr_triggers\.definitions\.[^.]+$", "sicr_triggers.definitions.<id>", generic)
        assert generic in documented, f"no definition for {path}"
        values.setdefault(generic, []).append(show(value))
    return {path: ("; ".join(dict.fromkeys(items))) for path, items in values.items()}


def segment_table(ps: dict) -> str:
    fields = ("rho", "sicr_k", "lgd_w", "cpr_ttc", "cpr_v", "ccf")
    allowed = {"portfolio", "z_drivers", *fields}
    body = []
    for name, row in ps["segments"].items():
        assert set(row) == allowed, name
        cells = "".join(f'<td class="n">{show(row[f])}</td>' for f in fields)
        body.append(f"<tr><td><code>{name}</code></td><td>{row['portfolio']}</td>{cells}</tr>")
    head = "".join(f'<th class="n">{f}</th>' for f in fields)
    return (f'<div class="scroll"><table class="tbl narrow"><thead><tr><th>Segment</th><th>Portfolio</th>{head}'
            "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>")


def driver_table(ps: dict) -> str:
    variables, stats = [], {}
    for row in ps["segments"].values():
        for variable, coef in row["z_drivers"].items():
            if variable not in variables:
                variables.append(variable)
            pair = (coef["mean"], coef["sd"])
            assert stats.setdefault(variable, pair) == pair, variable
    head = "".join(f'<th class="n"><code>{v}</code></th>' for v in variables)
    mean = "".join(f'<td class="n">{stats[v][0]}</td>' for v in variables)
    sd = "".join(f'<td class="n">{stats[v][1]}</td>' for v in variables)
    body = [f'<tr class="group"><td>mean, all segments</td>{mean}</tr>',
            f'<tr class="group"><td>sd, all segments</td>{sd}</tr>']
    for name, row in ps["segments"].items():
        cells = "".join(f'<td class="n">{row["z_drivers"].get(v, {}).get("beta", "–")}</td>' for v in variables)
        body.append(f"<tr><td><code>{name}</code> beta</td>{cells}</tr>")
    return (f'<div class="scroll"><table class="tbl narrow"><thead><tr><th></th>{head}</tr></thead><tbody>'
            + "".join(body) + "</tbody></table></div>")


def scale_table(ps: dict) -> str:
    grades, pds = ps["master_scale"]["grades"], ps["master_scale"]["ttc_pd"]
    head = "".join(f'<th class="n">{g}</th>' for g in grades)
    cells = "".join(f'<td class="n">{p:.2%}</td>' for p in pds)
    return (f'<div class="scroll"><table class="tbl narrow"><thead><tr><th>Grade</th>{head}</tr></thead><tbody>'
            f"<tr><td>TTC PD</td>{cells}</tr></tbody></table></div>")


def variant_table(ps: dict) -> str:
    body = []
    for name, row in ps["variants"].items():
        rule = ", ".join(f"{k}: {v}" for k, v in row["repayment_profile"].items())
        ccf = ", ".join(f"{k}: {v}" for k, v in row["ccf"].items()) or "none"
        body.append(f"<tr><td><code>{name}</code></td><td>{html.escape(row['label'])}</td><td>{rule}</td>"
                    f"<td>{ccf}</td></tr>")
    return ('<div class="scroll"><table class="tbl narrow"><thead><tr><th>Variant</th><th>Label</th>'
            "<th>Repayment profile</th><th>CCF override</th></tr></thead><tbody>" + "".join(body)
            + "</tbody></table></div>")


def path_table(doc: dict) -> str:
    values = pd.DataFrame(doc["values"])
    assert values.groupby(["scenario", "variable", "year"]).value.nunique().max() == 1
    wide = values.drop_duplicates(["scenario", "variable", "year"]).pivot_table(
        index="variable", columns=["scenario", "year"], values="value")
    years = sorted(values.year.unique())
    head = "".join(f'<th colspan="{len(years)}" class="grp">{s}</th>' for s in ("baseline", "adverse"))
    sub = "".join(f'<th class="n{" grp" if i == 0 else ""}">{y}</th>'
                  for _ in range(2) for i, y in enumerate(years))
    body = []
    for variable in wide.index:
        cells = "".join(f'<td class="n{" grp" if i == 0 else ""}">'
                        + f"{wide.loc[variable, (s, y)]:.1f}".replace("-", "−") + "</td>"
                        for s in ("baseline", "adverse") for i, y in enumerate(years))
        body.append(f"<tr><td><code>{variable}</code></td>{cells}</tr>")
    return (f'<div class="scroll"><table class="tbl narrow"><thead><tr><th rowspan="2">Variable, percent</th>{head}</tr>'
            f"<tr>{sub}</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>")


def assert_shared_default_column(matrix: pd.DataFrame, ps: dict) -> None:
    """The default column of every matrix equals the master scale; the page says so."""
    scale = dict(zip(ps["master_scale"]["grades"], ps["master_scale"]["ttc_pd"]))
    to_d = matrix[(matrix.to_grade == "D") & (matrix.from_grade != "D")]
    assert (to_d.probability - to_d.from_grade.map(scale)).abs().max() < 1e-9


def full_matrices(matrix: pd.DataFrame, segments) -> str:
    grades = matrix.drop_duplicates("from_rank").sort_values("from_rank").from_grade.tolist()
    parts = []
    for segment in segments:
        cells = matrix[matrix.segment == segment]
        wide = cells.pivot_table(index="from_grade", columns="to_grade", values="probability")
        head = "".join(f'<th class="n">{g}</th>' for g in grades)
        body = []
        for start in grades:
            row = "".join(f'<td class="n">{wide.loc[start, end]:.2%}</td>' for end in grades)
            body.append(f"<tr><td>{start}</td>{row}</tr>")
        parts.append(f"<h4><code>{segment}</code></h4>"
                     f'<div class="scroll"><table class="tbl narrow mat"><thead><tr><th>From \\ to</th>{head}</tr>'
                     "</thead><tbody>" + "".join(body) + "</tbody></table></div>")
    return "".join(parts)


def analysis_table() -> str:
    body = "".join(f"<tr><td><code>{html.escape(name)}</code></td><td>{rich(role)}</td><td>{rich(fields)}</td></tr>"
                   for name, role, fields in ANALYSIS_SECTIONS)
    return ('<div class="scroll"><table class="tbl fields"><thead><tr><th>Section</th><th>Purpose</th><th>Fields</th>'
            "</tr></thead><tbody>" + body + "</tbody></table></div>")


def cli_table() -> str:
    parser = cli.build_parser()
    run = next(a for a in parser._subparsers._group_actions[0].choices.items() if a[0] == "run")[1]
    real = {max(a.option_strings, key=len) for a in run._actions if a.option_strings} - {"--help"}
    assert real == {name for name, _ in CLI_OPTIONS}, real ^ {name for name, _ in CLI_OPTIONS}
    body = "".join(f"<tr><td><code>{name}</code></td><td>{rich(text)}</td></tr>" for name, text in CLI_OPTIONS)
    return ('<div class="scroll"><table class="tbl narrow"><thead><tr><th>Option</th><th>Meaning</th></tr></thead>'
            "<tbody>" + body + "</tbody></table></div>")


def overview(folder: Path, frames: dict, doc: dict) -> str:
    rows = [(spec.filename, "Parquet", "Required", f"{len(frames[name]):,}", MEANINGS[name], f"#{name}")
            for name, spec, _ in TABLES]
    rows += [("scenarios.yaml", "YAML", "Required", f"{len(doc['values']):,} values",
              "one value of one variable, country and year", "#scenarios"),
             ("parameter_set.yaml", "YAML", "Required", "1 document", "every model and run parameter", "#parameters"),
             ("manifest.json", "JSON", "Required", "1 document", "hashes and control totals of the set", "#manifest"),
             ("approval.json", "JSON", "Optional", "1 document", "the owner's sign-off", "#manifest"),
             ("Run specification", "YAML", "Optional", "1 file per experiment", "portfolios, models, crises, volumes",
              "#specification"),
             ("Analysis file", "YAML", "Optional", "1 file", "inputs of the preparation analyses", "#analysis")]
    body = "".join(f'<tr><td><a href="{link}">{html.escape(name)}</a></td><td>{kind}</td><td>{need}</td>'
                   f'<td class="n">{size}</td><td>{rich(meaning)}</td></tr>'
                   for name, kind, need, size, meaning, link in rows)
    return ('<div class="scroll"><table class="tbl narrow"><thead><tr><th>Input</th><th>Format</th><th>Needed</th>'
            '<th class="n">Size now</th><th>One row or file holds</th></tr></thead><tbody>' + body + "</tbody></table></div>")


def table_sections(frames: dict) -> str:
    joins = {
        "facilities": "The hub table. Every other table hangs off a facility or is chosen by one of its attributes.",
        "obligors": "Facilities join on <code>obligor_id</code>. Several facilities can share one obligor.",
        "commitments": "Joins to <code>facilities</code> on <code>facility_id</code>. A facility has at most one "
                       "commitment, and only a revolver or guarantee may have an undrawn amount.",
        "opening_provisions": "Joins to <code>facilities</code> on <code>facility_id</code>, one to one. This is "
                              "frozen: a run reads it and never recomputes it.",
        "ttc_pd_matrix": "Facilities join on <code>segment</code>. R3 uses the matrix for the SICR line, and R6 "
                         "shifts it by Z into PiT matrices.",
    }
    parts = []
    for name, spec, groups in TABLES:
        data = frames[name]
        key = ", ".join(spec.key)
        parts.append(f'<section id="{name}"><h2><span class="kicker">Required table</span>'
                     f'<code class="h">{spec.filename}</code></h2><p class="meta">Key <code>{key}</code> · '
                     f"{len(data):,} rows · {len(data.columns)} columns · one row is {MEANINGS[name]}</p>"
                     f'<p class="prose">{joins[name]}</p>'
                     f"{column_table(groups, spec, data)}%%AFTER_{name}%%</section>")
    return "".join(parts)


def build(folder: Path) -> str:
    frames = {name: pd.read_parquet(folder / spec.filename) for name, spec, _ in TABLES}
    scenarios = yaml.safe_load((folder / "scenarios.yaml").read_text(encoding="utf-8"))
    ps = yaml.safe_load((folder / "parameter_set.yaml").read_text(encoding="utf-8"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    approval = json.loads((folder / "approval.json").read_text(encoding="utf-8"))

    assert {row[0] for row in SPEC_TOP} == TOP_FIELDS, {row[0] for row in SPEC_TOP} ^ TOP_FIELDS
    assert {row[0] for row in SPEC_RUN} == RUN_FIELDS, {row[0] for row in SPEC_RUN} ^ RUN_FIELDS
    assert set(contract.SCENARIO_TOP_KEYS) <= {row[0] for row in SCENARIO_TOP}
    assert set(scenarios) == {row[0] for row in SCENARIO_TOP}, set(scenarios) ^ {row[0] for row in SCENARIO_TOP}
    assert set(contract.SCENARIO_VALUE_FIELDS) == {row[0] for row in SCENARIO_VALUE}
    assert set(scenarios["scenarios"][0]) == {row[0] for row in SCENARIO_RECORD}
    assert set(scenarios["starting_values"][0]) == {row[0] for row in SCENARIO_START}
    assert set(contract.PARAMETER_SET_TOP_KEYS) <= {row[0].split(".")[0] for row in PARAMETER_PATHS} | {"segments"}
    file_fields = {"files.<file>.sha256", "files.<file>.rows"}
    assert set(manifest) - {"files"} == {row[0] for row in MANIFEST} - file_fields
    assert set(approval) == {row[0] for row in APPROVAL}

    values = parameter_values(ps)
    full_hash = manifest["input_set_hash"]
    tokens = {
        "%%HASH%%": full_hash[:16], "%%FULL_HASH%%": full_hash,
        "%%OVERVIEW%%": overview(folder, frames, scenarios), "%%CLI%%": cli_table(),
        "%%TABLES%%": table_sections(frames),
        "%%SCENARIO_TOP%%": field_table(SCENARIO_TOP), "%%SCENARIO_RECORD%%": field_table(SCENARIO_RECORD),
        "%%SCENARIO_VALUE%%": field_table(SCENARIO_VALUE), "%%SCENARIO_START%%": field_table(SCENARIO_START),
        "%%PATHS%%": path_table(scenarios),
        "%%PARAMETERS%%": field_table(PARAMETER_PATHS, values=values),
        "%%SEGMENT_FIELDS%%": field_table(SEGMENT_FIELDS), "%%SEGMENTS%%": segment_table(ps),
        "%%DRIVERS%%": driver_table(ps), "%%SCALE%%": scale_table(ps), "%%VARIANTS%%": variant_table(ps),
        "%%MANIFEST%%": field_table(MANIFEST), "%%APPROVAL%%": field_table(APPROVAL),
        "%%SPEC_TOP%%": field_table(SPEC_TOP, SPEC_HEADERS), "%%SPEC_RUN%%": field_table(SPEC_RUN, SPEC_HEADERS),
        "%%SPEC_SCENARIO%%": field_table(SPEC_SCENARIO, SPEC_HEADERS),
        "%%SPEC_PATH%%": field_table(SPEC_PATH, SPEC_HEADERS),
        "%%SPEC_MODEL%%": field_table(SPEC_MODEL, SPEC_HEADERS),
        "%%SPEC_SEGMENT%%": field_table(SPEC_SEGMENT, SPEC_HEADERS),
        "%%SPEC_ASSIGNMENT%%": field_table(SPEC_ASSIGNMENT, SPEC_HEADERS),
        "%%SPEC_OTHER%%": field_table(SPEC_OTHER, SPEC_HEADERS),
        "%%ANALYSIS_TOP%%": field_table(ANALYSIS_TOP, SPEC_HEADERS), "%%ANALYSIS%%": analysis_table(),
        "%%N_COLUMNS%%": str(sum(len(spec.columns) for _, spec, _ in TABLES)),
    }
    page = (HERE / "template.html").read_text(encoding="utf-8")
    for token, value in tokens.items():
        page = page.replace(token, value)
    matrix = frames["ttc_pd_matrix"]
    assert_shared_default_column(matrix, ps)
    others = [s for s in sorted(matrix.segment.unique()) if s != "P05"]
    page = page.replace("%%AFTER_ttc_pd_matrix%%", (
        '<p class="prose">In all seven matrices the one-year PD to D equals the master scale. The matrices '
        "differ in how exposure moves between performing grades. The full matrix of P05 is below, in percent.</p>"
        + full_matrices(matrix, ["P05"])
        + "<details><summary>The other six matrices</summary><div class=\"inner\">"
        + full_matrices(matrix, others) + "</div></details>"))
    page = re.sub(r"%%AFTER_\w+%%", "", page)
    assert "%%" not in page, re.findall(r"%%\w+%%", page)
    return page


if __name__ == "__main__":
    TARGET.write_text(build(Path(sys.argv[1])), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")
