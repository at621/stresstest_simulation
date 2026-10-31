"""Retained difference report between two sealed runs (section 12.2, version change).

Runs are write-once, so the report sits beside them: runs/comparisons/<base>__<new>/ unless
--out says otherwise. It compares the reports of both runs and holds no time, so the same two
runs give the same bytes under the same code. A row that only one run has keeps an empty
difference: missing is never zero.
"""

import json
from pathlib import Path

import pandas as pd

from stress.contracts.artifacts import sha256_file, verified_manifest
from stress.contracts.errors import BlockingError
from stress.contracts.inputs import INPUT_MANIFEST
from stress.contracts.run import (
    COMPARISONS_DIR,
    REPORTS_DIR,
    RESULTS_DIR,
    RUN_MANIFEST,
    STATUS_BLOCKED,
)

STEP = "compare"
SUMMARY_FILE = "summary.md"
RECORD_FILE = "comparison.json"
MILLION = 1_000_000.0
AMOUNT_DP = 2
RATE_DP = 10
RATES = ("coverage_rate", "one_year_pd", "z", "exposure_weighted_lgd")
# Report of a run, name in the comparison, keys, compared columns.
TABLES = (
    ("impairment.csv", "impairment", ("scenario", "year", "portfolio"),
     ("closing_on", "closing_off", "charge_total", "cumulative_charge")),
    ("impairment_by_stage.csv", "stage_stocks", ("scenario", "year", "portfolio", "stage"),
     ("gca", "undrawn", "allowance_on", "provision_off", "coverage_rate")),
    ("portfolio_pd.csv", "portfolio_pd", ("scenario", "year", "portfolio", "stage"), ("one_year_pd",)),
    ("lgd_by_z.csv", "lgd_by_segment", ("scenario", "year", "segment"), ("z", "exposure_weighted_lgd")),
)


def difference(base: pd.DataFrame, new: pd.DataFrame, keys: tuple[str, ...],
               columns: tuple[str, ...]) -> pd.DataFrame:
    wanted = [*keys, *columns]
    joined = base[wanted].merge(new[wanted], on=list(keys), how="outer", suffixes=("_base", "_new"))
    for col in columns:
        joined[f"{col}_diff"] = joined[f"{col}_new"] - joined[f"{col}_base"]
    return joined


def compare(base: Path, new: Path) -> tuple[dict[str, pd.DataFrame], dict, dict]:
    """The difference tables and the manifests of two verified runs."""
    manifests = verified_manifest(base), verified_manifest(new)
    for run, manifest in zip((base, new), manifests):
        if manifest["status"] == STATUS_BLOCKED:  # a run blocked at R10 has some reports, so look at its status
            raise BlockingError(STEP, "RUN_INTEGRITY", f"{run.name} sealed as BLOCKED, so it has no results to compare")
    tables = {}
    for report, name, keys, columns in TABLES:
        left, right = (pd.read_csv(run / RESULTS_DIR / REPORTS_DIR / report) for run in (base, new))
        tables[name] = difference(left, right, keys, columns)
    return tables, *manifests


def default_folder(base: Path, new: Path) -> Path:
    return new.parent / COMPARISONS_DIR / f"{base.name}__{new.name}"


def _rounded(table: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(RATE_DP if col.startswith(RATES) else AMOUNT_DP)
    return out


def _changed(table: pd.DataFrame) -> tuple[int, int]:
    """Rows that differ, and rows only one run has. A value missing from both is no difference."""
    columns = [c.removesuffix("_diff") for c in table.columns if c.endswith("_diff")]
    diffs = table[[f"{c}_diff" for c in columns]]
    base = table[[f"{c}_base" for c in columns]].isna().to_numpy()
    new = table[[f"{c}_new" for c in columns]].isna().to_numpy()
    return int((diffs.abs() > 0).any(axis=1).sum()), int((base != new).any(axis=1).sum())


def _million(value: float, sign: str = "") -> str:
    return "n/a" if pd.isna(value) else f"{value / MILLION:{sign},.1f}"


def _identity(base: dict, new: dict) -> list[str]:
    rows = [("Run", base["run_id"], new["run_id"]),
            ("Status", base["status"], new["status"]),
            ("Input set", base["input_set_hash"][:16], new["input_set_hash"][:16]),
            ("Variant", base["config"]["variant"], new["config"]["variant"]),
            ("Code", base["code_version"], new["code_version"]),
            ("Spec version", base["spec_version"], new["spec_version"]),
            ("Outputs digest", base["outputs_digest"][:16], new["outputs_digest"][:16])]
    shown = {"inputs", "input_set_hash", "scenarios", "variant"}
    for name in sorted((set(base["config"]) | set(new["config"])) - shown):
        rows.append((name, base["config"].get(name, "not recorded"), new["config"].get(name, "not recorded")))
    return ["| | Base | New |", "|---|---|---|", *[f"| {a} | {b} | {c} |" for a, b, c in rows]]


def _headline(tables: dict[str, pd.DataFrame]) -> list[str]:
    imp = tables["impairment"]
    last = imp["year"].max()
    final = imp[(imp["year"] == last) & (imp["portfolio"] == "Total")]
    md = [f"## Total book at end-{last}, EUR m", "",
          "| Scenario | Cumulative charge, base | New | Difference | Closing provisions, base | New | Difference |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for r in final.itertuples(index=False):
        provisions = (r.closing_on_base + r.closing_off_base, r.closing_on_new + r.closing_off_new)
        md.append(f"| {r.scenario} | {_million(r.cumulative_charge_base)} | {_million(r.cumulative_charge_new)} | "
                  f"{_million(r.cumulative_charge_diff, '+')} | {_million(provisions[0])} | "
                  f"{_million(provisions[1])} | {_million(provisions[1] - provisions[0], '+')} |")
    return md


def _coverage(allowance: float, gca: float) -> str:
    return f"{allowance / gca:.2%}" if gca > 0 else "n/a"  # a gap is not above zero, so it stays n/a


def _by_stage(tables: dict[str, pd.DataFrame]) -> list[str]:
    stages = tables["stage_stocks"]
    last = stages["year"].max()
    columns = ["gca_base", "gca_new", "allowance_on_base", "allowance_on_new"]
    sums = stages[stages["year"] == last].groupby(["scenario", "stage"])[columns].agg(
        lambda part: part.sum(skipna=False)).reset_index()  # a row in one run only is not a zero
    md = [f"## Stage stocks and on-balance coverage at end-{last}", "",
          "| Scenario | Stage | GCA base, EUR m | GCA new, EUR m | Coverage base | Coverage new |",
          "|---|---:|---:|---:|---:|---:|"]
    for r in sums.itertuples(index=False):  # coverage from summed parts, never an average of ratios
        md.append(f"| {r.scenario} | S{r.stage} | {_million(r.gca_base)} | {_million(r.gca_new)} | "
                  f"{_coverage(r.allowance_on_base, r.gca_base)} | {_coverage(r.allowance_on_new, r.gca_new)} |")
    return md


def _by_book(tables: dict[str, pd.DataFrame]) -> list[str]:
    imp = tables["impairment"]
    last = imp["year"].max()
    books = imp[(imp["year"] == last) & (imp["portfolio"] != "Total")]
    table = books.pivot(index="portfolio", columns="scenario", values="cumulative_charge_diff") / MILLION
    md = [f"## Difference in cumulative charge by book to end-{last}, EUR m", "",
          "| Book | " + " | ".join(table.columns) + " |", "|---|" + "---:|" * len(table.columns)]
    return md + [f"| {book} | " + " | ".join("n/a" if pd.isna(v) else f"{v:+,.2f}" for v in row) + " |"
                 for book, row in zip(table.index, table.to_numpy())]


def summary(tables: dict[str, pd.DataFrame], base: dict, new: dict) -> str:
    counts = {name: _changed(table) for name, table in tables.items()}
    md = ["# Comparison of two sealed runs", "", *_identity(base, new), "", *_headline(tables), "",
          *_by_stage(tables), "", *_by_book(tables), "", "## What differs", "",
          "| Table | Rows | Rows that differ | Rows in one run only |", "|---|---:|---:|---:|"]
    md += [f"| {name} | {len(tables[name]):,} | {a:,} | {b:,} |" for name, (a, b) in counts.items()]
    return "\n".join([*md, ""])


def _in_a_sealed_folder(folder: Path) -> bool:
    """A sealed run and an input set each hold a manifest, and both are write-once."""
    resolved = folder.resolve()
    return any((path / name).is_file() for path in (resolved, *resolved.parents)
               for name in (RUN_MANIFEST, INPUT_MANIFEST))


def write_report(tables: dict[str, pd.DataFrame], base: dict, new: dict, folder: Path) -> None:
    """The difference tables, a summary and a record that ties them to both runs."""
    if _in_a_sealed_folder(folder):
        raise BlockingError(STEP, "RUN_INTEGRITY", "sealed folders are write-once: choose one outside them")
    folder.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        _rounded(table).to_csv(folder / f"{name}.csv", index=False, lineterminator="\n")
    (folder / SUMMARY_FILE).write_text(summary(tables, base, new), encoding="utf-8", newline="\n")
    names = sorted([f"{name}.csv" for name in tables] + [SUMMARY_FILE])
    record = {
        side: {"run_id": m["run_id"], "input_set_hash": m["input_set_hash"], "code_version": m["code_version"],
               "outputs_digest": m["outputs_digest"], "config": m["config"]}
        for side, m in (("base", base), ("new", new))
    }
    record["files"] = {name: sha256_file(folder / name) for name in names}
    (folder / RECORD_FILE).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                                      newline="\n")
