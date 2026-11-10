"""OPS-01: a sealed run names its source snapshot, scenarios, parameter set, versions and the
approver of its input set."""

import json

import pytest
import yaml

from foundation.synth.inputset import approve
from stress import __version__
from stress.contracts.artifacts import sha256_file
from tests import builders

SCENARIOS = ("baseline", "adverse")


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.req("OPS-01")
def test_the_manifest_names_what_the_run_was_made_from_and_who_approved_it(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    source = _json(inputs / "manifest.json")
    with (inputs / "parameter_set.yaml").open(encoding="utf-8") as fh:
        parameter_set = yaml.safe_load(fh)
    ctx, pending = builders.run(inputs, tmp_path / "runs", scenarios=SCENARIOS)
    assert pending["status"] == "SYNTHETIC", pending.get("blocked")
    # Source snapshot: the input set by its hash, and every file of the run's own copy by its hash.
    assert pending["input_set_hash"] == source["input_set_hash"] == pending["config"]["input_set_hash"]
    assert pending["input_manifest"] == {key: source[key] for key in ("generator", "status", "parameter_set_id")}
    assert all(pending["input_manifest"].values()), "the generator, its status and the parameter set are named"
    for name, record in source["files"].items():
        assert pending["inputs"][f"data/{name}"] == record["sha256"] == sha256_file(ctx.data_dir / name), name
    # Scenarios, parameter set, and the versions of the code and of the requirements.
    assert tuple(pending["config"]["scenarios"]) == SCENARIOS
    assert pending["parameter_set"] == {key: parameter_set[key] for key in ("parameter_set_id", "version", "status")}
    assert all(pending["parameter_set"].values())
    assert pending["code_version"] == ctx.code_version and pending["code_version"].startswith(__version__)
    assert pending["engine_version"] == __version__
    assert pending["spec_version"] == str(source["spec_version"])
    # Approver. Not yet approved: the run says so and names nobody.
    assert pending["approval"] == _json(inputs / "approval.json")
    assert pending["approval"]["status"] == "PENDING_OWNER_APPROVAL"
    assert pending["approval"]["approved_by"] is None and pending["approval"]["approved_on"] is None
    # Approved: the run carries the approver and the date, bound to this input set.
    approve(inputs, "the owner of the files", "2026-11-09")
    _, approved = builders.run(inputs, tmp_path / "runs", scenarios=SCENARIOS)
    assert approved["approval"] == _json(inputs / "approval.json")
    assert approved["approval"] == {"input_set_hash": source["input_set_hash"], "status": "APPROVED",
                                    "approved_by": "the owner of the files", "approved_on": "2026-11-09"}
    assert approved["input_set_hash"] == pending["input_set_hash"], "an approval does not change the input set"
