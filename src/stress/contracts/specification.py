"""Version 1 experiment contract. Financial equations belong to the pipeline steps.

OPS-01, SCN-01, MOD-01. Unknown fields fail closed rather than silently doing nothing.
"""

from math import isfinite

from stress.contracts.errors import Block, BlockingError

ENVELOPE_FIELDS = {"schema_version", "status", "source", "version", "input_set_hash", "run"}
# What a specification can change beyond the settings of its ``run`` section, which the command
# line can give as well: scenarios, values, segments, assignments, reporting classes, terminal
# policies and volumes.
CHANGE_FIELDS = {"scenarios", "segments", "assignments", "reporting", "balance_sheet",
                 "terminal_policies", "additional_values"}
TOP_FIELDS = ENVELOPE_FIELDS | CHANGE_FIELDS
RUN_FIELDS = {"inputs", "scenarios", "variant", "mode", "terminal_treatment", "analysis",
              "s2_treatment", "horizon_runoff", "lgd_path", "balance_sheet"}
STEP = "R2"  # a specification is read by the R2 preflight and applied by R2


def invalid(message: str):
    """Block on specification data. The step is R2's; ``cli.step`` gives a block that a later step
    raises on specification data that step's own name."""
    raise BlockingError(STEP, Block.INVALID_SPECIFICATION, message)


def changes_the_run(document: dict) -> bool:
    """Whether a specification holds more than run settings: such a run is named for it (R1)."""
    return any(document.get(name) for name in CHANGE_FIELDS)


def mapping(value, allowed: set[str], where: str, required=()) -> dict:
    if not isinstance(value, dict):
        invalid(f"{where} must be a mapping")
    extra = set(value) - allowed
    missing = set(required) - set(value)
    if extra or missing:
        invalid(f"{where}: unknown {sorted(extra)}, missing {sorted(missing)}")
    return value


def number(value, where, lower=None, upper=None) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        invalid(f"{where} must be finite numeric data")
    if (lower is not None and value < lower) or (upper is not None and value > upper):
        invalid(f"{where} outside [{lower}, {upper}]")
    return float(value)


def text(value, where) -> str:
    if not isinstance(value, str) or not value.strip():
        invalid(f"{where} must be a nonempty string")
    return value


def validate_document(doc: dict) -> dict:
    mapping(doc, TOP_FIELDS, "specification",
            ("schema_version", "status", "source", "version", "input_set_hash", "run"))
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        invalid("schema_version must be 1")
    if doc["status"] != "SYNTHETIC":
        invalid("specifications currently require SYNTHETIC status")
    for field in ("source", "version", "input_set_hash"):
        text(doc[field], field)
    run = mapping(doc["run"], RUN_FIELDS, "run")
    if "scenarios" in run:
        names = run["scenarios"]
        if not isinstance(names, list) or not names:
            invalid("run.scenarios must be a nonempty list")
        for name in names:
            text(name, "scenario identifier")
        if len(set(names)) != len(names):
            invalid("run.scenarios has duplicates")
    for name, value in run.items():
        if name != "scenarios":
            text(value, f"run.{name}")
    for name in ("scenarios", "segments", "reporting", "balance_sheet", "terminal_policies"):
        if name in doc and not isinstance(doc[name], dict):
            invalid(f"{name} must be a mapping")
    if "assignments" in doc and not isinstance(doc["assignments"], list):
        invalid("assignments must be a list")
    if "additional_values" in doc and not isinstance(doc["additional_values"], list):
        invalid("additional_values must be a list")
    return doc


def terminal_weight(parameter_set: dict, scenario: str, year: int) -> float:
    """One scenario's terminal policy, shared by Z and optional parameter reversion."""
    rule = parameter_set["terminal_rule"]
    policy = parameter_set.get("terminal_policies", {}).get(scenario, {})
    if policy.get("method") == "flat":
        return 1.0
    years = policy.get("years", rule["reversion_years"])
    return max(0.0, min(1.0, (years - (year - rule["last_scenario_year"])) / years))
