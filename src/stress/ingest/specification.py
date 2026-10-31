"""Read and apply a versioned experiment without changing its immutable base input set.

R2 has a preflight before R1 so run identity contains resolved settings. R2 then captures
the same bytes, rather than reading an editable file a second time. OPS-01, SCN-01.
"""

import copy
import hashlib
from pathlib import Path

import pandas as pd
import yaml

from stress.contracts.inputs import SCENARIO_UNITS, SCENARIO_VALUE_TYPES
from stress.contracts.specification import (
    invalid,
    mapping,
    number,
    text,
    validate_document,
)


class SpecificationLoader(yaml.SafeLoader):
    """Reject duplicate YAML settings rather than silently keeping the last one."""


def _unique_mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            invalid("specification mapping keys must be strings")
        if key in result:
            invalid(f"duplicate specification key {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


SpecificationLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def resolve(config):
    if not config.specification:
        return config
    path = Path(config.specification).resolve()
    try:
        raw = path.read_bytes()
        doc = validate_document(yaml.load(raw, Loader=SpecificationLoader))
    except (OSError, yaml.YAMLError) as exc:
        invalid(f"cannot read specification: {exc}")
    digest = hashlib.sha256(raw).hexdigest()
    if config.specification_hash and config.specification_hash != digest:
        invalid("specification hash differs from the sealed run")
    # On replay the verified data/ snapshot and analysis path supersede original paths.
    replay = bool(config.specification_hash)
    for name, value in doc["run"].items():
        if replay and name in ("inputs", "analysis"):
            continue
        if name in ("inputs", "analysis"):
            value = str((path.parent / value).resolve())
        if name == "scenarios":
            value = tuple(value)
        setattr(config, name, value)
    if not config.inputs:
        invalid("run.inputs or --inputs is required")
    config.specification_hash = digest
    config._specification_document = doc
    config._specification_bytes = raw
    return config


def apply(loaded, ctx):
    doc = ctx.config._specification_document
    if not doc:
        return
    if doc["input_set_hash"] != ctx.input_set_hash:
        invalid("specification belongs to another input set")
    loaded.specification = copy.deepcopy(doc)
    (ctx.data_dir / "specification.yaml").write_bytes(ctx.config._specification_bytes)
    ctx.lineage["specification"] = {
        "sha256": ctx.config.specification_hash, "source": doc["source"],
        "version": doc["version"], "status": doc["status"],
    }
    apply_scenarios(loaded, doc.get("scenarios", {}))
    add_values(loaded, doc.get("additional_values", []))
    apply_segments(loaded, doc.get("segments", {}), doc.get("assignments", []))
    loaded.parameter_set["macro_models"] = copy.deepcopy(doc.get("models", {}))
    selected = {s.get("macro_model") for s in loaded.parameter_set["segments"].values()
                if s.get("macro_model")}
    if set(doc.get("models", {})) - selected:
        invalid("a supplied macro model is not assigned to any segment")
    policies = doc.get("terminal_policies", {})
    names = {row["id"] for row in loaded.scenario_meta["scenarios"]}
    for name, policy in policies.items():
        mapping(policy, {"method", "years"}, f"terminal policy {name}", ("method",))
        if name not in names or name == "baseline":
            invalid(f"terminal policy refers to unknown or baseline scenario {name}")
        if policy["method"] not in ("reversion", "flat"):
            invalid(f"unknown terminal policy for {name}")
        if policy["method"] == "reversion":
            years = number(policy.get("years"), f"{name} reversion years", 1)
            if not years.is_integer():
                invalid("reversion years must be whole years")
        elif "years" in policy:
            invalid("flat terminal policy does not take years")
    loaded.parameter_set["terminal_policies"] = copy.deepcopy(policies)
    reporting = mapping(doc.get("reporting", {}), {"template_classes"}, "reporting")
    classes = reporting.get("template_classes", {})
    if not isinstance(classes, dict):
        invalid("template_classes must be a mapping")
    for segment, label in classes.items():
        if segment not in loaded.parameter_set["segments"]:
            invalid(f"reporting refers to unknown segment {segment}")
        loaded.parameter_set["segments"][segment]["template_class"] = text(label, "template class")


def apply_scenarios(loaded, definitions):
    values = loaded.scenario_values.copy()
    known = {s["id"] for s in loaded.scenario_meta["scenarios"]}
    countries = sorted(values.country.unique())
    for name, definition in definitions.items():
        text(name, "scenario identifier")
        mapping(definition, {"inherits", "narrative", "overrides", "values"}, f"scenario {name}",
                ("narrative",))
        text(definition["narrative"], f"{name} narrative")
        if name in known:
            invalid(f"scenario {name} already exists; choose a new immutable identifier")
        if "inherits" in definition:
            parent = text(definition["inherits"], "inherited scenario")
            if parent not in known:
                invalid(f"scenario {name} inherits unknown scenario {parent}")
            rows = values[values.scenario == parent].copy()
            rows["scenario"] = name
            edits = definition.get("overrides", [])
            if "values" in definition:
                invalid("use overrides with inherits, or values without inherits")
        else:
            rows = values.iloc[:0].copy()
            edits = definition.get("values")
            if "overrides" in definition:
                invalid("overrides require an explicit inherited scenario")
        if not isinstance(edits, list) or (not edits and "inherits" not in definition):
            invalid(f"scenario {name} requires a list of paths")
        seen = set()
        for edit in edits:
            mapping(edit, {"variable", "country", "year", "value", "unit", "value_type"},
                    f"scenario {name} path", ("variable", "country", "year", "value", "unit", "value_type"))
            text(edit["variable"], "variable")
            for field in ("country", "unit", "value_type"):
                text(edit[field], f"scenario path {field}")
            if type(edit["year"]) is not int:
                invalid("scenario year must be an integer")
            if edit["unit"] not in SCENARIO_UNITS or edit["value_type"] not in SCENARIO_VALUE_TYPES:
                invalid("scenario has an unsupported unit or value type")
            raw = number(edit["value"], f"{name}/{edit['variable']}")
            selected = countries if edit["country"] == "*" else [edit["country"]]
            for country in selected:
                if country not in countries:
                    invalid(f"unknown scenario country {country}")
                key = (edit["variable"], country, edit["year"])
                if key in seen:
                    invalid(f"duplicate scenario path {name}/{key}")
                seen.add(key)
                match = ((rows.variable == edit["variable"]) & (rows.country == country)
                         & (rows.year == edit["year"]))
                rows = rows.loc[~match]
                rows = pd.concat([rows, pd.DataFrame([{
                    "scenario": name, "variable": edit["variable"], "country": country,
                    "year": edit["year"], "value": raw * SCENARIO_UNITS[edit["unit"]],
                    "raw_value": raw, "unit": edit["unit"], "value_type": edit["value_type"],
                    "status": "SYNTHETIC", "completeness": "complete", "value_status": "supplied",
                }])], ignore_index=True)
        values = pd.concat([values, rows], ignore_index=True)
        loaded.scenario_meta["scenarios"].append({
            "id": name, "label": name, "status": "SYNTHETIC", "source_type": "synthetic",
            "narrative": definition["narrative"], "inherits": definition.get("inherits"),
        })
        known.add(name)
    loaded.scenario_values = values


def apply_segments(loaded, definitions, assignments):
    segments = loaded.parameter_set["segments"]
    allowed = {"inherits", "portfolio", "macro_model", "template_class", "z_drivers",
               "rho", "sicr_k", "lgd_w", "cpr_ttc", "cpr_v", "ccf"}
    for name, definition in definitions.items():
        text(name, "segment")
        mapping(definition, allowed, f"segment {name}")
        validate_segment_overrides(name, definition)
        if name not in segments:
            parent = text(definition.get("inherits"), "inherited segment")
            if parent not in segments:
                invalid(f"new segment {name} needs an existing matrix/parameter parent")
            segments[name] = copy.deepcopy(segments[parent])
            matrix = loaded.ttc_pd_matrix[loaded.ttc_pd_matrix.segment == parent].copy()
            matrix["segment"] = name
            loaded.ttc_pd_matrix = pd.concat([loaded.ttc_pd_matrix, matrix], ignore_index=True)
        elif "inherits" in definition:
            invalid("existing segments cannot be reparented")
        segments[name].update({k: copy.deepcopy(v) for k, v in definition.items() if k != "inherits"})
        for field in ("portfolio", "macro_model", "template_class"):
            if field in definition:
                text(definition[field], f"{name}.{field}")
    facilities = loaded.facilities.data
    original = facilities.copy()
    obligors = loaded.obligors.data.set_index("obligor_id")
    used = set()
    for assignment in assignments:
        mapping(assignment, {"where", "segment", "portfolio"}, "assignment", ("where", "segment"))
        where = mapping(assignment["where"], {"facility_id", "portfolio", "segment", "country", "nace_code"},
                        "assignment.where")
        text(assignment["segment"], "assigned segment")
        if not where or assignment["segment"] not in segments:
            invalid("assignment needs a selector and a configured segment")
        mask = pd.Series(True, index=facilities.index)
        for field, value in where.items():
            text(value, f"assignment {field}")
            actual = (original.obligor_id.map(obligors[field]) if field in ("country", "nace_code")
                      else original[field])
            mask &= actual.eq(value)
        ids = set(facilities.loc[mask, "facility_id"])
        if not ids or used & ids:
            invalid("assignment matches no facility or overlaps an earlier assignment")
        used |= ids
        facilities.loc[mask, "segment"] = assignment["segment"]
        if "portfolio" in assignment:
            facilities.loc[mask, "portfolio"] = text(assignment["portfolio"], "portfolio")
    # CCF here is an input alignment expectation, not an effective risk-parameter override.
    # A changed expectation must never silently remove commitments from an experiment.
    expectations = {name: d["ccf"] for name, d in definitions.items() if d.get("ccf") is not None}
    if expectations:
        commitments = loaded.commitments.data
        segment_of = facilities.set_index("facility_id")["segment"]
        expected = commitments.facility_id.map(segment_of).map(expectations)
        tolerance = loaded.parameter_set["tolerances"]["probability_identity"]["abs"]
        mismatch = expected.notna() & ((commitments.accounting_ccf - expected).abs() > tolerance)
        if mismatch.any():
            invalid("segment ccf differs from supplied commitments; use a named variant for a CCF sensitivity")


def validate_segment_overrides(name, definition):
    if "z_drivers" in definition:
        drivers = definition["z_drivers"]
        if not isinstance(drivers, dict) or not drivers:
            invalid(f"{name}.z_drivers must be a nonempty mapping")
        for driver, coefficients in drivers.items():
            text(driver, "driver name")
            mapping(coefficients, {"beta", "mean", "sd"}, f"{name}.{driver}", ("beta", "mean", "sd"))
            for field in ("beta", "mean", "sd"):
                number(coefficients[field], f"{name}.{driver}.{field}")
            if coefficients["sd"] <= 0:
                invalid("driver sd must be positive")
    for field in ("rho", "sicr_k", "lgd_w", "cpr_ttc", "cpr_v", "ccf"):
        if field not in definition or (field == "ccf" and definition[field] is None):
            continue
        value = number(definition[field], f"{name}.{field}", 0)
        if ((field == "rho" and value >= 1) or (field == "sicr_k" and value <= 0)
                or (field in ("ccf", "cpr_ttc") and value > 1)):
            invalid(f"{name}.{field} outside its allowed domain")


def add_values(loaded, additions):
    """Supply lag history or new driver paths; never overwrite a value in a named scenario."""
    values = loaded.scenario_values
    names = {s["id"] for s in loaded.scenario_meta["scenarios"]}
    countries = set(values.country)
    keys = set(zip(values.scenario, values.variable, values.country, values.year))
    rows = []
    fields = {"scenario", "variable", "country", "year", "value", "unit", "value_type"}
    for addition in additions:
        mapping(addition, fields, "additional scenario value", fields)
        for field in ("scenario", "variable", "country", "unit", "value_type"):
            text(addition[field], f"additional value {field}")
        if type(addition["year"]) is not int:
            invalid("additional scenario year must be an integer")
        if addition["unit"] not in SCENARIO_UNITS or addition["value_type"] not in SCENARIO_VALUE_TYPES:
            invalid("additional value has unknown unit or value type")
        raw = number(addition["value"], "additional value")
        selected_names = sorted(names) if addition["scenario"] == "*" else [addition["scenario"]]
        selected_countries = sorted(countries) if addition["country"] == "*" else [addition["country"]]
        for scenario in selected_names:
            for country in selected_countries:
                if scenario not in names or country not in countries:
                    invalid("additional value has an unknown scenario or country")
                key = (scenario, addition["variable"], country, addition["year"])
                if key in keys:
                    invalid(f"additional value would overwrite existing path {key}")
                keys.add(key)
                rows.append({"scenario": scenario, "variable": addition["variable"], "country": country,
                             "year": addition["year"], "value": raw * SCENARIO_UNITS[addition["unit"]],
                             "raw_value": raw, "unit": addition["unit"], "value_type": addition["value_type"],
                             "status": "SYNTHETIC", "completeness": "complete", "value_status": "supplied"})
    if rows:
        loaded.scenario_values = pd.concat([values, pd.DataFrame(rows)], ignore_index=True)
