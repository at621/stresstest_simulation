"""O3–O4: generate the synthetic portfolio and freeze opening allowances, written to inputs/<hash>/.

O3: seeded generator hitting every section 5 target exactly, with current and origination
grades chosen so the stage rule returns each facility's opening stage (SYN-PAR-08).
O4: end-2026 allowances from the generator's own formula, frozen as opening_provisions
(SYN-PAR-09). Writes a new file set and never edits an old one.

``uv run python -m foundation.synth`` runs O2, O3 and O4 and writes one hashed input set.
"""

import re
from datetime import date
from math import isfinite
from pathlib import Path

import numpy as np
import yaml

from foundation import matrices as o2
from foundation.synth import config as cfg
from foundation.synth.allowances import opening_allowances
from foundation.synth.generate import Generator
from foundation.synth.inputset import MATRIX_DIR, write_input_set

GENERATOR_VERSION = "0.3.0"
SCENARIO_LIBRARY = Path(__file__).resolve().parents[1] / "scenarios.yaml"  # every scenario's description; those beyond section 6.2


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def spec_inputs(spec_dir: Path) -> dict:
    return {
        "targets": _load(spec_dir / "targets.yaml"),
        "scenarios": _load(spec_dir / "scenarios.yaml"),
        "calibration": _load(spec_dir / "calibration_targets.yaml"),
        "AT-35": _load(spec_dir / "oracles" / "AT-35.yaml"),
        "AT-52": _load(spec_dir / "oracles" / "AT-52.yaml"),
    }


def library_scenarios(scenarios: dict, library: dict) -> dict:
    """The paths of the scenarios ``foundation/scenarios.yaml`` adds to section 6.2: for each
    scenario and country, every variable with every year, the country's own path where it has one.
    A section 6.2 scenario takes only its label and description from the library. Anything
    incomplete, unknown or not a finite number is refused."""
    entries = _mapping(library.get("scenarios"), "the scenarios of foundation/scenarios.yaml")
    for name in scenarios["paths"]:
        if name not in entries:
            raise ValueError(f"foundation/scenarios.yaml does not describe the section 6.2 scenario {name}")
    variables, years = set(scenarios["variables"]), list(scenarios["years"])
    added = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError(f"scenario {name!r} needs a lower-case identifier")
        _mapping(entry, f"scenario {name}")
        section = name in scenarios["paths"]
        extra = set(entry) - ({"label", "description"} if section else {"label", "description", "paths", "by_country"})
        if extra:
            reason = "a section 6.2 scenario takes its paths from section 6.2" if section else "unknown fields"
            raise ValueError(f"scenario {name}: {reason}: {sorted(extra)}")
        for field in ("label", "description"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"scenario {name} needs a {field}")
        if section:
            continue
        if "paths" not in entry:
            raise ValueError(f"scenario {name} needs paths")
        common = _mapping(entry["paths"], f"scenario {name}: paths")
        own = _mapping(entry.get("by_country", {}), f"scenario {name}: by_country")
        if set(own) - set(scenarios["countries"]):
            raise ValueError(f"scenario {name} names unknown countries {sorted(set(own) - set(scenarios['countries']))}")
        added[name] = {}
        for country in scenarios["countries"]:
            given = {**common, **_mapping(own.get(country, {}), f"scenario {name}: by_country {country}")}
            if set(given) != variables:
                raise ValueError(f"scenario {name} in {country}: missing {sorted(variables - set(given))}, "
                                 f"unknown {sorted(set(given) - variables)}")
            for var, path in given.items():
                if set(_mapping(path, f"scenario {name}: {var} in {country}")) != set(years):
                    raise ValueError(f"scenario {name}: {var} in {country} needs the years {years}")
                for year, value in path.items():
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                        raise ValueError(f"scenario {name}: {var} in {country} {year} is {value!r}, not a finite number")
            added[name][country] = given
    return added


def _mapping(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{where} must be a mapping")
    return value


def scenario_document(scenarios: dict, spec_version: str, library: dict) -> dict:
    """The scenarios dataset: every section 6.2 value for every country, then the values of the
    scenarios the library adds, each with its unit, value type, source and SYNTHETIC status, and
    every scenario with its label and description (SCN-01, SCN-02, SCN-04)."""
    source = f"requirements v{spec_version} section 6.2 (illustrative common paths)"
    release = "2026-10-17"
    added = library_scenarios(scenarios, library)
    values = []
    for scenario, variables in scenarios["paths"].items():
        for var, path in variables.items():
            meta = scenarios["variables"][var]
            for country in scenarios["countries"]:
                for year in sorted(path):
                    values.append({
                        "scenario": scenario, "variable": var, "country": country, "year": int(year),
                        "value": float(path[year]), "unit": meta["unit"],
                        "value_type": meta["value_type"], "source": source, "release": release,
                        "completeness": "complete", "status": scenarios["status"],
                    })
    for scenario, countries in added.items():
        for var, meta in scenarios["variables"].items():
            for country in scenarios["countries"]:
                path = countries[country][var]
                for year in sorted(path):
                    values.append({
                        "scenario": scenario, "variable": var, "country": country, "year": int(year),
                        "value": float(path[year]), "unit": meta["unit"],
                        "value_type": meta["value_type"], "source": library["source"],
                        "release": library["release"], "completeness": "complete",
                        "status": scenarios["status"],
                    })
    starting = [
        {"variable": var, "country": country, "year": scenarios["starting_year"],
         "value": float(v["value"]), "unit": v["unit"], "value_type": v["value_type"]}
        for var, v in scenarios["starting_values"].items() for country in scenarios["countries"]
    ]
    return {
        "scenario_set_id": f"SYN-SCN-{spec_version}",
        "source": f"{source}; {library['source']}",
        "release": library["release"],
        "revision": 2,
        "status": scenarios["status"],
        "scenarios": [
            {"id": s, "label": library["scenarios"][s]["label"],
             "description": " ".join(library["scenarios"][s]["description"].split()),
             "status": scenarios["status"], "source_type": scenarios["source_type"]}
            for s in [*scenarios["paths"], *added]
        ],
        "variables": [{"id": var, **meta} for var, meta in scenarios["variables"].items()],
        "starting_values": starting,
        "index_of": scenarios["index_of"],
        "values": values,
    }


def parameter_document(params: dict, spec: dict) -> dict:
    """The parameter_set dataset: the proposed values plus the values the spec fixes."""
    targets, scen, cal = spec["targets"], spec["scenarios"], spec["calibration"]
    years = list(scen["years"])
    weights = spec["AT-52"]["expected"]["adverse_weights"]
    zero_year = min(int(y) for y, w in weights.items() if w == 0)
    portfolios = {}
    for portfolio, body in params["portfolios"].items():
        segments = {}
        for seg, sp in body["segments"].items():
            if cal["segments"][seg]["portfolio"] != portfolio:
                raise ValueError(f"segment {seg} is in portfolio {portfolio}, the spec says "
                                 f"{cal['segments'][seg]['portfolio']}")
            segments[seg] = {
                "pd_model": sp["pd_model"], "lgd_model": sp["lgd_model"], "prepayment_model": sp["prepayment_model"],
                "ttc_matrix": f"{MATRIX_DIR}/{seg}.parquet",
                "asset_correlation": sp["asset_correlation"], "sicr_k": sp["sicr_k"], "cpr_ttc": sp["cpr_ttc"],
                "ccf": targets["portfolios"][portfolio]["ccf"],
            }
        portfolios[portfolio] = {"segments": segments}
    variants = {}
    ccf_to = spec["AT-35"]["input"]["ccf_to"]
    for name, v in params["variants"].items():
        variants[name] = {
            "label": v["label"], "repayment_profile": v["repayment_profile"],
            "ccf": {seg: (ccf_to if value == "AT-35" else value) for seg, value in v["ccf"].items()},
        }
    terminal = dict(params["terminal_rule"])
    last_bucket_year = terminal.pop("last_bucket_year")
    terminal.update({"last_scenario_year": max(years), "reversion_years": zero_year - max(years)})
    return {
        "parameter_set_id": params["parameter_set_id"],
        "version": params["version"],
        "status": params["status"],
        "spec_version": targets["source"]["version"],
        "horizon": {
            "snapshot_date": f"{scen['starting_year']}-12-31",
            "snapshot_year": scen["starting_year"],
            "projection_years": years,
            "last_bucket_year": last_bucket_year,
        },
        "master_scale": params["master_scale"],
        "portfolios": portfolios,
        "terminal_rule": terminal,
        "conventions": params["conventions"],
        "sicr_triggers": params["sicr_triggers"],
        "tolerances": targets["tolerances"],
        "variants": variants,
    }


def segment_settings(param_doc: dict) -> dict:
    """The parameter set's segments by segment, with their portfolio, for O3 and O4."""
    return {seg: {**settings, "portfolio": portfolio}
            for portfolio, body in param_doc["portfolios"].items() for seg, settings in body["segments"].items()}


def build(spec_dir: Path, params_path: Path, out_root: Path, seed: int = cfg.SEED,
          scenarios_path: Path = SCENARIO_LIBRARY) -> Path:
    spec = spec_inputs(spec_dir)
    params = _load(params_path)
    targets = spec["targets"]
    tol = targets["tolerances"]["probability_identity"]["abs"]
    grades = list(params["master_scale"]["grades"])
    pds = np.array(params["master_scale"]["ttc_pd"], dtype=float)

    # O2: matrices and the calibration grade mix.
    matrices = o2.build_matrices(params)
    longest = int(max(r["residual_maturity_years"][1] for r in targets["risk_profiles"].values()))
    for seg, m in matrices.items():
        problems = o2.matrix_problems(m, tol)
        if problems or not o2.lifetime_monotone(m, longest):
            raise ValueError(f"TTC matrix {seg} is invalid: {problems or 'lifetime PD not monotone'}")
    plan = o2.calibration_plan(pds, spec["calibration"], targets["risk_profiles"])
    param_doc = parameter_document(params, spec)
    working = {**param_doc, "segments": segment_settings(param_doc)}

    # O3: the portfolio.
    snapshot = date.fromisoformat(param_doc["horizon"]["snapshot_date"])
    facilities, obligors, commitments = Generator(
        targets, spec["calibration"], plan, working, matrices, snapshot, seed).run()

    # O4: frozen opening allowances.
    provisions = opening_allowances(facilities, commitments, matrices, working, grades,
                                    param_doc["horizon"]["snapshot_date"])

    tables = {
        "facilities": facilities, "obligors": obligors, "commitments": commitments,
        "opening_provisions": provisions, "ttc_pd_matrix": o2.matrix_table(matrices, grades),
    }
    documents = {
        "scenarios": scenario_document(spec["scenarios"], targets["source"]["version"], _load(scenarios_path)),
        "parameter_set": param_doc,
    }
    meta = {
        "status": "SYNTHETIC",
        "spec_version": targets["source"]["version"],
        "parameter_set_id": param_doc["parameter_set_id"],
        "parameter_set_status": param_doc["status"],
        "generator": {"name": "foundation.synth", "version": GENERATOR_VERSION, "seed": seed},
        "calibration_plan": {seg: {str(s): {grades[r - 1]: w for r, w in mix.items()}
                                   for s, mix in stages.items()} for seg, stages in plan.items()},
    }
    return write_input_set(out_root, tables, documents, meta)
