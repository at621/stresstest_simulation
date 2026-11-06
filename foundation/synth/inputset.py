"""Writing one hashed input set, inputs/<hash>/, with its manifest.

An input set holds six datasets and one TTC matrix file per segment, under matrices/, at the
path the segment's ``ttc_matrix`` names in the parameter set. The folder name is the first 16
hex characters of the set hash: SHA-256 over the sorted (file name, file SHA-256) pairs of all
its files. The manifest records each file's hash and row count and the control totals R2
checks. A new starting point is a new folder; an existing folder is never edited.
"""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import yaml

FILES = {
    "facilities": "facilities.parquet",
    "obligors": "obligors.parquet",
    "commitments": "commitments.parquet",
    "opening_provisions": "opening_provisions.parquet",
    "scenarios": "scenarios.yaml",
    "parameter_set": "parameter_set.yaml",
}
# The TTC matrices are passed in as one table with a segment column and written one file per
# segment; ``load_matrices`` reads them back into that table.
MATRICES = "ttc_pd_matrix"
MATRIX_DIR = "matrices"
MANIFEST = "manifest.json"
APPROVAL = "approval.json"
PREFIX = 16


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_hash(file_hashes: dict[str, str]) -> str:
    text = json.dumps(dict(sorted(file_hashes.items())), separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def control_totals(fac: pd.DataFrame, com: pd.DataFrame, prov: pd.DataFrame) -> dict:
    """The totals R2 recomputes on load: rows, count and GCA per portfolio and stage, undrawn
    per portfolio, and the amount totals."""
    stage = {
        f"{p}|{int(s)}": {"count": len(g), "gca": float(g["gca"].sum())}
        for (p, s), g in fac.groupby(["portfolio", "ifrs_stage"])
    }
    linked = com.merge(fac[["facility_id", "portfolio"]], on="facility_id", how="left")
    return {
        "rows": {"facilities": len(fac), "commitments": len(com), "opening_provisions": len(prov)},
        "by_portfolio_stage": stage,
        "undrawn_by_portfolio": {
            str(p): float(g["nominal_undrawn"].sum()) for p, g in linked.groupby("portfolio")
        },
        "gca_total": float(fac["gca"].sum()),
        "undrawn_total": float(com["nominal_undrawn"].sum()),
        "allowance_on_total": float(prov["allowance_on"].sum()),
        "provision_off_total": float(prov["provision_off"].sum()),
    }


def matrix_paths(parameter_set: dict) -> dict[str, str]:
    """Each segment's TTC matrix file, as its ``ttc_matrix`` names it."""
    return {seg: settings["ttc_matrix"] for body in parameter_set["portfolios"].values()
            for seg, settings in body["segments"].items() if settings.get("ttc_matrix")}


def _write_files(folder: Path, tables: dict[str, pd.DataFrame], documents: dict[str, dict]) -> dict:
    """Write the datasets and the matrix files; return the row count of every file (None for YAML)."""
    rows = {}
    for name, df in tables.items():
        if name != MATRICES:
            df.to_parquet(folder / FILES[name], index=False, engine="pyarrow", compression="snappy")
            rows[FILES[name]] = len(df)
    matrix = tables[MATRICES]
    for seg, path in matrix_paths(documents["parameter_set"]).items():
        cells = matrix[matrix["segment"] == seg].drop(columns="segment").reset_index(drop=True)
        target = folder / path
        if path in rows:
            if not cells.equals(pd.read_parquet(target)):
                raise ValueError(f"two segments name {path} with different matrices")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        cells.to_parquet(target, index=False, engine="pyarrow", compression="snappy")
        rows[path] = len(cells)
    for name, doc in documents.items():
        text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
        (folder / FILES[name]).write_text(text, encoding="utf-8", newline="\n")
        rows[FILES[name]] = None
    return rows


def load_matrices(folder: Path, parameter_set: dict) -> pd.DataFrame:
    """The TTC matrices of an input set as one table with a segment column."""
    frames = [pd.read_parquet(folder / path).assign(segment=seg)
              for seg, path in matrix_paths(parameter_set).items()]
    table = pd.concat(frames, ignore_index=True)
    return table[["segment", *[c for c in table.columns if c != "segment"]]]


def write_input_set(root: Path, tables: dict[str, pd.DataFrame], documents: dict[str, dict],
                    meta: dict) -> Path:
    """Write the datasets, the matrix files and the manifest; return inputs/<hash>/."""
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        tmp_dir = Path(tmp)
        rows = _write_files(tmp_dir, tables, documents)
        hashes = {name: sha256(tmp_dir / name) for name in rows}
        digest = set_hash(hashes)
        manifest = {
            "input_set_hash": digest,
            "files": {name: {"sha256": hashes[name], "rows": rows[name]} for name in sorted(rows)},
            "control_totals": control_totals(tables["facilities"], tables["commitments"],
                                             tables["opening_provisions"]),
            **meta,
        }
        (tmp_dir / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                        encoding="utf-8", newline="\n")
        (tmp_dir / APPROVAL).write_text(json.dumps({
            "input_set_hash": digest, "status": "PENDING_OWNER_APPROVAL",
            "approved_by": None, "approved_on": None,
        }, indent=2), encoding="utf-8", newline="\n")
        target = root / digest[:PREFIX]
        if target.exists():
            same = json.loads((target / MANIFEST).read_text(encoding="utf-8"))["input_set_hash"]
            if same != digest:
                raise FileExistsError(f"{target} exists with another input set")
            return target
        shutil.move(str(tmp_dir), str(target))
        tmp_dir.mkdir()  # let TemporaryDirectory clean up the empty name
    return target


def approve(folder: Path, approver: str, on: str) -> None:
    """Record the owner's approval next to the input set; the data files are not touched."""
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    (folder / APPROVAL).write_text(json.dumps({
        "input_set_hash": manifest["input_set_hash"], "status": "APPROVED",
        "approved_by": approver, "approved_on": on,
    }, indent=2), encoding="utf-8", newline="\n")


def package(source: Path, destination: Path) -> Path:
    """Package user-prepared datasets without generating facilities or recalibrating models.

    The engine performs financial/type validation at R2/R3. This step freezes exactly the
    supplied tables and YAML, creates their manifest and records pending owner approval.
    """
    tables = {name: pd.read_parquet(source / filename) for name, filename in FILES.items()
              if filename.endswith(".parquet")}
    documents = {name: yaml.safe_load((source / filename).read_text(encoding="utf-8"))
                 for name, filename in FILES.items() if filename.endswith(".yaml")}
    ps = documents["parameter_set"]
    tables[MATRICES] = load_matrices(source, ps)
    meta = {"status": "SYNTHETIC", "spec_version": str(ps.get("spec_version", "unapproved")),
            "parameter_set_id": ps["parameter_set_id"], "generator": {"method": "supplied_datasets", "version": "1"}}
    return write_input_set(destination, tables, documents, meta)
