"""R1 open the run and R11 seal it.

R1: run ID, input set fixed by hash, git SHA, rule and parameter-set versions, status label
(SYNTHETIC for every preparation run). R11: manifest.json with hashes of every input and
output; a rerun must give identical output hashes. Owns runs/<run_id>/.

OPS-01, OPS-04, SCN-04, REG-01, section 12.2 reproducibility.
"""

import json
import os
import platform
import stat
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version as package_version
from pathlib import Path

import yaml

from stress import __version__
from stress.contracts.artifacts import canonical_hash, sha256_file, verified_manifest
from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import INPUT_MANIFEST
from stress.contracts.run import (
    HORIZON_RUNOFFS,
    LGD_PATHS,
    MODE_SYNTHETIC,
    MODES,
    RUN_CONFIG,
    RUN_LOG,
    RUN_MANIFEST,
    S2_TREATMENTS,
    STATUS_BLOCKED,
    STATUS_SYNTHETIC,
    RunConfig,
    RunContext,
)

STEP_OPEN = "R1"
STEP_SEAL = "R11"
HASH_PREFIX = 16  # input-set folder names use the first 16 hex characters of the set hash
CODE_PATHS = ("src", "foundation", "pyproject.toml", "uv.lock")


def source_fingerprint(root: Path) -> dict:
    files = {}
    for name in CODE_PATHS:
        path = root / name
        candidates = path.rglob("*") if path.is_dir() else [path]
        for file in sorted(candidates):
            if (file.is_file() and "__pycache__" not in file.parts
                    and file.suffix in (".py", ".yaml", ".json", ".toml", ".lock")):
                files[file.relative_to(root).as_posix()] = sha256_file(file)
    return {"sha256": canonical_hash(files), "files": files}


def runtime_environment() -> dict:
    return {"python": platform.python_version(), "platform": platform.platform(),
            "packages": {p: package_version(p) for p in
                         ("numpy", "pandas", "scipy", "pyarrow", "openpyxl", "pyyaml")}}


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                             cwd=Path(__file__).resolve().parent)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def code_version() -> tuple[str, str]:
    """(git SHA or "unknown", code version). Uncommitted engine changes mark it dirty."""
    sha = _git("rev-parse", "HEAD") or "unknown"
    top = _git("rev-parse", "--show-toplevel")
    dirty = ""
    if top:
        status = _git("-C", top, "status", "--porcelain", "--", *CODE_PATHS)
        if status:
            dirty = "+dirty." + source_fingerprint(Path(top))["sha256"][:12]
    else:
        dirty = "+source." + source_fingerprint(Path(__file__).resolve().parents[3])["sha256"][:12]
    return sha, f"{__version__}+{sha[:12]}{dirty}"


def read_input_manifest(input_dir: Path) -> dict:
    path = input_dir / INPUT_MANIFEST
    if not input_dir.is_dir() or not path.is_file():
        raise BlockingError(STEP_OPEN, Block.INPUT_SET_NOT_FOUND,
                            f"no input set with a {INPUT_MANIFEST} at {input_dir}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BlockingError(STEP_OPEN, Block.UNREADABLE_FILE, f"{path}: {exc}") from exc


def open_run(config: RunConfig, runs_dir: Path, now: datetime | None = None) -> RunContext:
    """R1: create runs/<run_id>/ with config.yaml. Blocks on regulatory mode (D9)."""
    if config.mode not in MODES:
        raise BlockingError(STEP_OPEN, Block.INVALID_ARGUMENT, f"unknown mode {config.mode!r}")
    if config.terminal_treatment not in ("z", "parameters"):
        raise BlockingError(STEP_OPEN, Block.INVALID_ARGUMENT, "unknown terminal treatment")
    for name, value, allowed in (("S2 treatment", config.s2_treatment, S2_TREATMENTS),
                                 ("horizon run-off", config.horizon_runoff, HORIZON_RUNOFFS),
                                 ("LGD path", config.lgd_path, LGD_PATHS)):
        if value not in allowed:
            raise BlockingError(STEP_OPEN, Block.INVALID_ARGUMENT, f"unknown {name} {value!r}")
    if config.mode != MODE_SYNTHETIC:
        raise BlockingError(
            STEP_OPEN, Block.REGULATORY_MODE,
            "regulatory mode is unavailable: preparation analyses use synthetic model outputs; "
            "official scenarios, benchmark integration, model validation and approved submission "
            "mappings remain required. Synthetic values never fill an official parameter (GOV-04, D9)",
        )
    if not config.scenarios:
        raise BlockingError(STEP_OPEN, Block.INVALID_ARGUMENT, "no scenario requested")
    if len(set(config.scenarios)) != len(config.scenarios):
        raise BlockingError(STEP_OPEN, Block.INVALID_ARGUMENT, "a scenario is requested twice")
    input_dir = Path(config.inputs)
    manifest = read_input_manifest(input_dir)
    input_hash = manifest.get("input_set_hash", "")
    snapshot = input_dir.name == "data"
    if snapshot:
        sealed = verified_manifest(input_dir.parent)
        if sealed["input_set_hash"] != input_hash:
            raise BlockingError(STEP_OPEN, Block.INPUT_HASH_MISMATCH, "snapshot identity differs")
    if not input_hash or (not snapshot and input_dir.name != input_hash[:HASH_PREFIX]):
        raise BlockingError(STEP_OPEN, Block.INPUT_HASH_MISMATCH,
                            f"folder {input_dir.name} is not named by its input-set hash")
    git_sha, version = code_version()
    spec_version = str(manifest.get("spec_version", "unknown"))
    now = now or datetime.now(UTC)
    run_hash = canonical_hash({
        "config": {**config.as_dict(), "inputs": input_hash},
        "input_set": input_hash, "code": version, "spec": spec_version,
    })[:8]
    tag = "".join(f"+{value}" for value in config.selected_methods().values())  # never reads as the core run
    base = f"{now:%Y%m%dT%H%MZ}-{config.variant}{tag}-{run_hash}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = base
    counter = 2
    while (runs_dir / run_id).exists():
        run_id = f"{base}-{counter}"
        counter += 1
    run_dir = runs_dir / run_id
    run_dir.mkdir()
    config_doc = {**config.as_dict(), "input_set_hash": input_hash}
    (run_dir / RUN_CONFIG).write_text(yaml.safe_dump(config_doc, sort_keys=True), encoding="utf-8",
                                      newline="\n")
    return RunContext(
        run_id=run_id, run_dir=run_dir, config=config, input_set_hash=input_hash,
        input_dir=input_dir, code_version=version, spec_version=spec_version,
        created_at=now.isoformat(timespec="seconds"), status_label=STATUS_SYNTHETIC,
        lineage={"git_sha": git_sha, "engine_version": __version__,
                 "source": source_fingerprint(Path(_git("rev-parse", "--show-toplevel")
                                                 or Path(__file__).resolve().parents[3])),
                 "environment": runtime_environment(),
                 "input_manifest": {k: manifest.get(k) for k in ("generator", "status", "parameter_set_id")}},
    )


def write_table(ctx: RunContext, filename: str, df) -> Path:
    """Write one results table as Parquet. Rows are written in the order given; every step
    hands its tables over sorted by key, so a rerun writes identical bytes."""
    ctx.results_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.results_dir / filename
    if path.exists():
        raise BlockingError(STEP_SEAL, Block.RUN_EXISTS, f"{filename} was already written (write-once)")
    df.reset_index(drop=True).to_parquet(path, index=False, engine="pyarrow", compression="snappy")
    return path


def _hashes(root: Path, sub: str) -> dict[str, str]:
    base = root / sub
    if not base.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): sha256_file(p)
        for p in sorted(base.rglob("*")) if p.is_file()
    }


def seal_run(ctx: RunContext, blocked: BlockingError | None = None, summary: dict | None = None) -> dict:
    """R11: write manifest.json with every input and output hash, then make the folder
    read-only. A blocked run is sealed too, with status BLOCKED and the reason."""
    outputs = _hashes(ctx.run_dir, "results")
    manifest = {
        "run_id": ctx.run_id,
        "status": STATUS_BLOCKED if blocked else ctx.status_label,
        "label": ctx.status_label,
        "mode": ctx.config.mode,
        "created_at": ctx.created_at,
        "sealed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {**ctx.config.as_dict(), "input_set_hash": ctx.input_set_hash},
        "input_set_hash": ctx.input_set_hash,
        "code_version": ctx.code_version,
        "spec_version": ctx.spec_version,
        **ctx.lineage,
        "config_sha256": sha256_file(ctx.run_dir / RUN_CONFIG),
        "inputs": _hashes(ctx.run_dir, "data"),
        "outputs": outputs,
        "outputs_digest": canonical_hash(outputs),
        # The log carries times, so it is hashed for integrity but kept out of the outputs that
        # a rerun must reproduce.
        "log": ({RUN_LOG: sha256_file(ctx.run_dir / RUN_LOG)}
                if (ctx.run_dir / RUN_LOG).exists() else {}),
        "summary": summary or {},
    }
    if blocked:
        manifest["blocked"] = {"step": blocked.step, "code": str(blocked.code), "message": blocked.message}
    path = ctx.run_dir / RUN_MANIFEST
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8",
                    newline="\n")
    make_read_only(ctx.run_dir)
    return manifest


def make_read_only(root: Path) -> None:
    for p in root.rglob("*"):
        if p.is_file():
            os.chmod(p, stat.S_IREAD)


def read_manifest(run_dir: Path) -> dict:
    return verified_manifest(run_dir)


def check_replay_environment(manifest: dict) -> None:
    """A strict rerun checks its runtime before spending time projecting a different model."""
    root = Path(_git("rev-parse", "--show-toplevel") or Path(__file__).resolve().parents[3])
    if manifest.get("source") and manifest["source"] != source_fingerprint(root):
        raise BlockingError("rerun", "SOURCE_MISMATCH", "restore the sealed run's source revision before rerunning")
    if manifest.get("environment") and manifest["environment"] != runtime_environment():
        raise BlockingError("rerun", "ENVIRONMENT_MISMATCH", "restore the sealed run's Python and package environment")


def compare_outputs(first: dict, second: dict) -> list[str]:
    """Output files whose hash differs between two sealed runs (reproducibility control)."""
    a, b = first.get("outputs", {}), second.get("outputs", {})
    return sorted(name for name in set(a) | set(b) if a.get(name) != b.get(name))
