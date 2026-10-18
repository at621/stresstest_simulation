"""O3–O4: generate the synthetic portfolio and freeze opening allowances, written to inputs/<hash>/.

O3: seeded generator hitting every section 5 target exactly, with current and origination
grades chosen so the stage rule returns each facility's opening stage (SYN-PAR-08).
O4: end-2026 allowances from the generator's own formula, frozen as opening_provisions
(SYN-PAR-09). Writes a new file set and never edits an old one.

``uv run python -m foundation.synth`` runs O2, O3 and O4 and writes one hashed input set.
"""

from datetime import date
from pathlib import Path

import numpy as np
import yaml

from foundation import matrices as o2
from foundation.synth import config as cfg
from foundation.synth.allowances import opening_allowances
from foundation.synth.generate import Generator
from foundation.synth.inputset import write_input_set

GENERATOR_VERSION = "0.1.0"


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


def scenario_document(scenarios: dict, spec_version: str) -> dict:
    """The scenarios dataset: every section 6.2 value for every country, with its unit,
    value type, source and SYNTHETIC status (SCN-01, SCN-02, SCN-04)."""
    source = f"requirements v{spec_version} section 6.2 (illustrative common paths)"
    release = "2026-10-17"
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
    starting = [
        {"variable": var, "country": country, "year": scenarios["starting_year"],
         "value": float(v["value"]), "unit": v["unit"], "value_type": v["value_type"]}
        for var, v in scenarios["starting_values"].items() for country in scenarios["countries"]
    ]
    return {
        "scenario_set_id": f"SYN-SCN-{spec_version}",
        "source": source,
        "release": release,
        "revision": 1,
        "status": scenarios["status"],
        "scenarios": [
            {"id": s, "label": s.capitalize(), "status": scenarios["status"],
             "source_type": scenarios["source_type"]}
            for s in scenarios["paths"]
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
    segments = {}
    for seg, sp in params["segments"].items():
        portfolio = cal["segments"][seg]["portfolio"]
        segments[seg] = {
            "portfolio": portfolio,
            "z_drivers": {
                d: {"beta": b, **params["driver_moments"][d]} for d, b in sp["betas"].items()
            },
            "rho": sp["rho"], "sicr_k": sp["sicr_k"], "lgd_w": sp["lgd_w"],
            "cpr_ttc": sp["cpr_ttc"], "cpr_v": sp["cpr_v"],
            "ccf": targets["portfolios"][portfolio]["ccf"],
        }
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
        "segments": segments,
        "terminal_rule": terminal,
        "conventions": params["conventions"],
        "tolerances": targets["tolerances"],
        "variants": variants,
    }


def build(spec_dir: Path, params_path: Path, out_root: Path, seed: int = cfg.SEED) -> Path:
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

    # O3: the portfolio.
    snapshot = date.fromisoformat(param_doc["horizon"]["snapshot_date"])
    facilities, obligors, commitments = Generator(
        targets, spec["calibration"], plan, param_doc, matrices, snapshot, seed).run()

    # O4: frozen opening allowances.
    provisions = opening_allowances(facilities, commitments, matrices, param_doc, grades,
                                    param_doc["horizon"]["snapshot_date"])

    tables = {
        "facilities": facilities, "obligors": obligors, "commitments": commitments,
        "opening_provisions": provisions, "ttc_pd_matrix": o2.matrix_table(matrices, grades),
    }
    documents = {
        "scenarios": scenario_document(spec["scenarios"], targets["source"]["version"]),
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
