"""The shape R2 requires of the two YAML documents of an input set.

Every section a step of this run reads must be there and hold the kind of value that step
calculates with: a mapping, a list, text, a whole number or a number. A boolean is never a number
and text is never a number, so ``value: true`` is not 1.0 and ``abs: "0.01"`` is not a tolerance. A
year, and the number of reversion years, is a whole number as YAML reads one: ``2027``, not
``"2027"`` and not ``2027.0``. A wrong shape blocks here with a block code, and no later step meets
a value it cannot read.

What no step of this run reads is not checked: ``variables`` and ``conventions``, which are records
for people. Of the variants, the one the run uses must be complete. The others are read in two
places only, and are checked for just that: a segment that a specification creates inherits the
``ccf`` override of every variant (R2), and the effective specification lists every variant by name
(R10). So every variant's name is text, every variant is a mapping, and a ``ccf`` that is there and
not null maps segments to numbers. An unused variant may lack ``repayment_profile`` or have a null
``ccf``.

Whether the values fit together stays where it was checked: a segment's settings, the triggers and
the variant of the run at R3, the horizon against the terminal rule and the scenario values a model
needs at R4.

Section 4.2, DAT-02, SCN-01, SCN-02, SYN-PAR-06.
"""

from datetime import date
from math import isfinite

from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import PARAMETER_SET, SCENARIO_UNITS, SCENARIOS

STEP = "R2"


def _wrong(file: str, message: str):
    raise BlockingError(STEP, Block.BAD_VALUE_TYPE, f"{file}: {message}")


def _shown(value) -> str:
    return f"{value!r}" if isinstance(value, (str, bool, int, float, type(None))) else type(value).__name__


def _mapping(value, file: str, where: str, required=(), lacking=Block.MISSING_PARAMETER) -> dict:
    if not isinstance(value, dict):
        _wrong(file, f"{where} must be a mapping, not {_shown(value)}")
    missing = [key for key in required if key not in value]
    if missing:
        raise BlockingError(STEP, lacking, f"{file}: {where} lacks {missing}")
    return value


def _list(value, file: str, where: str) -> list:
    if not isinstance(value, list) or not value:
        _wrong(file, f"{where} must be a nonempty list, not {_shown(value)}")
    return value


def is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _text(value, file: str, where: str) -> None:
    if not is_text(value):
        _wrong(file, f"{where} must be text, not {_shown(value)}")


def _whole(value, file: str, where: str, minimum: int | None = None) -> None:
    if not is_whole(value) or (minimum is not None and value < minimum):
        floor = "" if minimum is None else f" of {minimum} or more"
        _wrong(file, f"{where} must be a whole number{floor}, not {_shown(value)}")


def _number(value, file: str, where: str, minimum: float | None = None, maximum: float | None = None) -> None:
    if not is_number(value) or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        bounds = ("" if minimum is None else f" from {minimum:g}") + ("" if maximum is None else f" to {maximum:g}")
        _wrong(file, f"{where} must be a number{bounds}, not {_shown(value)}")


# --- scenarios.yaml -----------------------------------------------------------------------------

def scenarios(doc: dict) -> None:
    """The lists of the Scenarios file. Each entry of ``values`` is checked as it is read."""
    file = SCENARIOS.filename
    names = []
    for n, scenario in enumerate(_list(doc["scenarios"], file, "scenarios")):
        _mapping(scenario, file, f"scenario {n}", ("id",), Block.MISSING_COLUMN)
        _text(scenario["id"], file, f"the id of scenario {n}")
        names.append(scenario["id"])
    if len(set(names)) != len(names):
        raise BlockingError(STEP, Block.DUPLICATE_KEY, f"{file}: a scenario id appears twice")
    _list(doc["values"], file, "values")
    if "index_of" in doc:
        for change, index in _mapping(doc["index_of"], file, "index_of").items():
            _text(change, file, "a variable in index_of")
            _text(index, file, f"index_of.{change}")
    if "starting_values" in doc:
        if not isinstance(doc["starting_values"], list):
            _wrong(file, f"starting_values must be a list, not {_shown(doc['starting_values'])}")
        for n, start in enumerate(doc["starting_values"]):
            _mapping(start, file, f"starting value {n}", ("variable", "country", "value"), Block.MISSING_COLUMN)
            _text(start["variable"], file, f"the variable of starting value {n}")
            _text(start["country"], file, f"the country of starting value {n}")
            _number(start["value"], file, f"the value of starting value {n}")
            if "unit" in start and start["unit"] not in SCENARIO_UNITS:
                raise BlockingError(STEP, Block.SCENARIO_WITHOUT_UNIT,
                                    f"{file}: starting value {n} has an unknown unit {start['unit']!r}")


def scenario_value(value: dict, n: int) -> None:
    """The typed fields of one entry of ``values``, once its fields and unit are known to be there.
    A value may be null: that is a missing value, with a status of its own (DAT-02)."""
    file = SCENARIOS.filename
    where = f"scenario value {n} ({value.get('variable')})"
    for name in ("scenario", "variable", "country"):
        _text(value[name], file, f"{name} of {where}")
    _whole(value["year"], file, f"year of {where}")
    raw = value["value"]
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, (int, float))):
        _wrong(file, f"value of {where} must be a number or null, not {_shown(raw)}")


# --- parameter_set.yaml -------------------------------------------------------------------------

def parameter_set(doc: dict, variant: str) -> None:
    """Every section of the Parameters file that this run reads, but ``portfolios``, whose tree
    ``segments_of`` reads, and ``sicr_triggers``, which R3 checks with the rule it serves (MIG-05).
    Every variant is checked for what is read of all of them, and ``variant``, the one the run uses,
    for being complete; R3 blocks one the file does not have."""
    file = PARAMETER_SET.filename
    for name in ("parameter_set_id", "version", "status"):
        if not (is_text(doc[name]) or is_number(doc[name])):
            _wrong(file, f"{name} must be text or a number, not {_shown(doc[name])}")

    horizon = _mapping(doc["horizon"], file, "horizon",
                       ("snapshot_date", "snapshot_year", "projection_years", "last_bucket_year"))
    snapshot = horizon["snapshot_date"]
    try:
        if not isinstance(snapshot, date):
            date.fromisoformat(snapshot)
    except (TypeError, ValueError):
        _wrong(file, f"horizon.snapshot_date must be a date written YYYY-MM-DD, not {_shown(snapshot)}")
    _whole(horizon["snapshot_year"], file, "horizon.snapshot_year")
    years = horizon["projection_years"]
    if not isinstance(years, list) or not years or not all(is_whole(year) for year in years):
        _wrong(file, f"horizon.projection_years must be a nonempty list of whole numbers, not {_shown(years)}")
    _whole(horizon["last_bucket_year"], file, "horizon.last_bucket_year")

    scale = _mapping(doc["master_scale"], file, "master_scale", ("grades", "ttc_pd"))
    grades = _list(scale["grades"], file, "master_scale.grades")
    for grade in grades:
        _text(grade, file, "a grade in master_scale.grades")
    if len(set(grades)) != len(grades):
        _wrong(file, "master_scale.grades names a grade twice")
    anchors = scale["ttc_pd"]
    if not isinstance(anchors, list) or len(anchors) != len(grades):
        _wrong(file, "master_scale.ttc_pd must be a list with one PD per grade")
    for grade, anchor in zip(grades, anchors):
        _number(anchor, file, f"master_scale.ttc_pd of {grade}", 0.0, 1.0)

    rule = _mapping(doc["terminal_rule"], file, "terminal_rule", ("last_scenario_year", "reversion_years"))
    _whole(rule["last_scenario_year"], file, "terminal_rule.last_scenario_year")
    _whole(rule["reversion_years"], file, "terminal_rule.reversion_years", 1)

    tolerances = _mapping(doc["tolerances"], file, "tolerances", ("probability_identity", "amount", "aggregate"))
    for name, limits in (("probability_identity", ("abs",)), ("amount", ("abs",)), ("aggregate", ("abs", "rel"))):
        tolerance = _mapping(tolerances[name], file, f"tolerances.{name}", limits)
        for limit in limits:
            _number(tolerance[limit], file, f"tolerances.{name}.{limit}", 0.0)

    variants = doc["variants"]
    if not isinstance(variants, dict) or not variants:
        _wrong(file, f"variants must be a nonempty mapping of variant to settings, not {_shown(variants)}")
    for name, settings in variants.items():
        _text(name, file, "a variant's name")
        _mapping(settings, file, f"variants.{name}")
        # No ccf, or a null one, means no override. One that is there maps segments to numbers.
        if settings.get("ccf") is not None:
            for segment, ccf in _mapping(settings["ccf"], file, f"variants.{name}.ccf").items():
                _text(segment, file, f"a segment in variants.{name}.ccf")
                _number(ccf, file, f"variants.{name}.ccf.{segment}", 0.0, 1.0)
    if variant in variants:
        settings = _mapping(variants[variant], file, f"variants.{variant}", ("repayment_profile",))
        for product, profile in _mapping(settings["repayment_profile"], file,
                                         f"variants.{variant}.repayment_profile").items():
            _text(product, file, f"a product in variants.{variant}.repayment_profile")
            _text(profile, file, f"variants.{variant}.repayment_profile.{product}")
        # R6 reads the ccf of the run's own variant as a mapping: no ccf is no override, null is not.
        if "ccf" in settings:
            _mapping(settings["ccf"], file, f"variants.{variant}.ccf")


def segments(settings_by_segment: dict) -> None:
    """A segment's ``ccf`` is null, where it has no commitments to check, or a number from 0 to 1.
    R3 checks the other settings: each must be there, finite and in its domain."""
    file = PARAMETER_SET.filename
    for segment, settings in settings_by_segment.items():
        ccf = settings.get("ccf")
        if ccf is not None:
            _number(ccf, file, f"segment {segment}: ccf (null where not applicable)", 0.0, 1.0)
