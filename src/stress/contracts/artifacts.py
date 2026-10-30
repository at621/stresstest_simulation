"""Shared verification of sealed artifacts, not projection-time input ingestion."""

import hashlib
import json
from pathlib import Path

from stress.contracts.errors import BlockingError


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(data) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verified_manifest(run_dir: Path) -> dict:
    root = run_dir.resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        outputs = manifest["outputs"]
        if canonical_hash(outputs) != manifest["outputs_digest"]:
            raise ValueError("output inventory digest differs")
        checks = {"config.yaml": manifest["config_sha256"]}
        for section, prefix in (("inputs", "data/"), ("outputs", "results/"), ("log", "run.log")):
            for name, expected in manifest.get(section, {}).items():
                path = (root / name).resolve()
                if (not name.startswith(prefix) or ".." in Path(name).parts or not path.is_relative_to(root)
                        or (section == "log" and name != "run.log")
                        or not path.is_file() or sha256_file(path) != expected):
                    raise ValueError(f"{section} integrity failed: {name}")
        for name, expected in checks.items():
            if sha256_file(root / name) != expected:
                raise ValueError(f"integrity failed: {name}")
        return manifest
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise BlockingError("audit", "RUN_INTEGRITY", str(exc)) from exc
