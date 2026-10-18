"""Writing one hashed input set, inputs/<hash>/, with its manifest.

The folder name is the first 16 hex characters of the set hash: SHA-256 over the sorted
(file name, file SHA-256) pairs of the seven datasets. The manifest records each file's hash
and row count and the control totals R2 checks. A new starting point is a new folder; an
existing folder is never edited.
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
    "ttc_pd_matrix": "ttc_pd_matrix.parquet",
    "scenarios": "scenarios.yaml",
    "parameter_set": "parameter_set.yaml",
}
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


def _write_files(folder: Path, tables: dict[str, pd.DataFrame], documents: dict[str, dict]) -> None:
    for name, df in tables.items():
        df.to_parquet(folder / FILES[name], index=False, engine="pyarrow", compression="snappy")
    for name, doc in documents.items():
        text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
        (folder / FILES[name]).write_text(text, encoding="utf-8", newline="\n")


def write_input_set(root: Path, tables: dict[str, pd.DataFrame], documents: dict[str, dict],
                    meta: dict) -> Path:
    """Write the seven datasets and the manifest; return inputs/<hash>/."""
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        tmp_dir = Path(tmp)
        _write_files(tmp_dir, tables, documents)
        hashes = {FILES[n]: sha256(tmp_dir / FILES[n]) for n in FILES}
        digest = set_hash(hashes)
        manifest = {
            "input_set_hash": digest,
            "files": {
                FILES[n]: {"sha256": hashes[FILES[n]],
                           "rows": len(tables[n]) if n in tables else None}
                for n in FILES
            },
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
