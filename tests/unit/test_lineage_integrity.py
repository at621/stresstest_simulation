"""Content identity and tamper detection independent of financial calculations."""

import json

import pytest

from stress import lineage
from stress.contracts.errors import BlockingError


@pytest.mark.req("OPS-01")
def test_same_dirty_filename_different_content_has_different_identity(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    file = src / "example.py"
    file.write_text("first", encoding="utf-8")
    monkeypatch.setattr(lineage, "_git", lambda *a: str(tmp_path) if "--show-toplevel" in a
                        else " M src/example.py" if "status" in a else "a" * 40)
    first = lineage.code_version()
    file.write_text("second", encoding="utf-8")
    assert first != lineage.code_version()


@pytest.mark.req("OPS-04")
def test_read_manifest_checks_bytes_and_rejects_path_escape(tmp_path):
    (tmp_path / "results").mkdir()
    result = tmp_path / "results/result.csv"
    result.write_text("original", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("mode: synthetic", encoding="utf-8")
    outputs = {"results/result.csv": lineage.sha256_file(result)}
    doc = {"outputs": outputs, "outputs_digest": lineage.canonical_hash(outputs),
           "inputs": {}, "log": {}, "config_sha256": lineage.sha256_file(config)}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    assert lineage.read_manifest(tmp_path)["outputs"] == outputs
    result.write_text("tampered", encoding="utf-8")
    with pytest.raises(BlockingError):
        lineage.read_manifest(tmp_path)
    doc["outputs"] = {"../outside.csv": "unknown"}
    doc["outputs_digest"] = lineage.canonical_hash(doc["outputs"])
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(BlockingError):
        lineage.read_manifest(tmp_path)
