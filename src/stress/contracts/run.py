"""The run as invoked and the folder it writes (runs/<run_id>/)."""

from dataclasses import dataclass, field
from pathlib import Path

MODE_SYNTHETIC = "synthetic"
MODE_REGULATORY = "regulatory"
MODES = (MODE_SYNTHETIC, MODE_REGULATORY)

STATUS_SYNTHETIC = "SYNTHETIC"
STATUS_BLOCKED = "BLOCKED"

BASELINE = "baseline"
ADVERSE = "adverse"

RUN_CONFIG = "config.yaml"
RUN_MANIFEST = "manifest.json"
RUN_LOG = "run.log"  # timed step log; outside results/, so it never enters the output hashes
DATA_DIR = "data"
RESULTS_DIR = "results"
REPORTS_DIR = "reports"


@dataclass
class RunConfig:
    """What the user asked for. Written to config.yaml; contains no run ID or time."""

    inputs: str  # path of the input set
    scenarios: tuple[str, ...]
    variant: str
    mode: str = MODE_SYNTHETIC

    def as_dict(self) -> dict:
        return {
            "inputs": self.inputs,
            "scenarios": list(self.scenarios),
            "variant": self.variant,
            "mode": self.mode,
        }


@dataclass
class RunContext:
    """Created by R1. Every step that writes uses these folders."""

    run_id: str
    run_dir: Path
    config: RunConfig
    input_set_hash: str
    input_dir: Path
    code_version: str
    spec_version: str
    created_at: str
    status_label: str = STATUS_SYNTHETIC
    lineage: dict = field(default_factory=dict)

    @property
    def data_dir(self) -> Path:
        return self.run_dir / DATA_DIR

    @property
    def results_dir(self) -> Path:
        return self.run_dir / RESULTS_DIR

    @property
    def reports_dir(self) -> Path:
        return self.run_dir / RESULTS_DIR / REPORTS_DIR

    @property
    def scenarios(self) -> tuple[str, ...]:
        return self.config.scenarios

    @property
    def variant(self) -> str:
        return self.config.variant
