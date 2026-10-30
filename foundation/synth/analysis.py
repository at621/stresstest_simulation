"""Generate a deliberately uncalibrated preparation package without altering an input set.

python -m foundation.synth.analysis --inputs inputs/<hash> --out docs/examples/preparation.yaml
All example risk weights, transitions, loss rates and balance-sheet inputs below are synthetic.
"""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

BENCHMARKS = Path(__file__).resolve().parents[2] / "docs" / "benchmarks" / "eba-2025-published.yaml"


def build(input_dir: Path) -> dict:
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = (input_dir / name).resolve()
        if (not path.is_relative_to(input_dir.resolve())
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]):
            raise ValueError(f"input hash mismatch: {name}")
    f = pd.read_parquet(input_dir / "facilities.parquet")
    ps = yaml.safe_load((input_dir / "parameter_set.yaml").read_text(encoding="utf-8"))
    if manifest.get("status") != "SYNTHETIC":
        raise ValueError("example generator accepts only synthetic input sets")
    first = f.loc[f["product"].eq("mortgage") & f.ifrs_stage.eq(1)].iloc[0]
    scales = list(ps["master_scale"]["grades"]) + ["D"]
    years = [int(ps["horizon"]["snapshot_year"]), *map(int, ps["horizon"]["projection_years"])]
    scenarios = ["baseline", "adverse"]
    weights = []
    for scenario in scenarios:
        for year in years:
            for approach, category in sorted(set(zip(f.regulatory_approach, f.regulatory_class))):
                for i, grade in enumerate(scales):
                    # Illustrative class/grade inputs, expressly not CRR formulas or approved weights.
                    weight = (i+1)/len(scales) * (1. + .05*(year-years[0])*(scenario == "adverse"))
                    weights.append({"scenario": scenario, "year": year, "regulatory_approach": approach,
                                    "regulatory_class": category, "grade": grade, "regulatory_ccf": .5,
                                    "standardised_ccf": .5,
                                    "risk_weight": float(weight), "standardised_risk_weight": 1.,
                                    "model_version": "synthetic-demonstration-1"})
    bridge = []
    for scenario in scenarios:
        for year in years[1:]:
            row = {"scenario": scenario, "year": year, "other_pnl": 0., "tax_rate": 0.,
                   "distributions": 0., "irb_shortfall_change": 0., "npl_deduction_change": 0.,
                   "other_cet1_change": 0., "other_utrea": 0., "other_strea": 0.,
                   "output_floor_factor": .75}
            if year == years[1]:
                row["opening_cet1"] = float(f.gca.sum()*.15)
            bridge.append(row)
    benchmark = []
    for scenario in scenarios:
        for year in years[1:]:
            for family in ("pd_tr", "lgd_lr"):
                for identifier, gca, model in (("demo_model", .05, True), ("demo_benchmark", .95, False)):
                    values = ({"tr11": .95, "tr12": .04, "tr13": .01, "tr21": .05, "tr22": .90, "tr23": .05}
                              if family == "pd_tr" else
                              {"lr11": .01, "lr12": .10, "lr13": .50, "lr21": .01, "lr22": .10, "lr23": .50})
                    benchmark.append({"exposure_id": identifier, "country": "DE", "pivot": "demo_corporate",
                                      "family": family, "scenario": scenario, "year": year, "gca": gca,
                                      "model_available": model, "route": "ordinary", "model_version": "demo-1",
                                      "benchmark_version": "demo-1", "model_parameters": values.copy(),
                                      "benchmark_parameters": values.copy()})
    reference = [[.95, .04, .01], [.05, .90, .05], [0., 0., 1.]]
    climate = []
    for scenario in ["adverse"]:
        for channel in ("transition", "flood"):
            for year in ([2027] if channel == "flood" else years[1:]):
                climate.append({"facility_id": str(first.facility_id), "channel": channel, "scenario": scenario,
                                "year": year, "nace_code": "NA_household", "energy_bucket": "D",
                                "geolocation": "synthetic-DE-location", "flood_category": "high",
                                "model_version": "synthetic-stage-model-1", "reference_transition": reference,
                                "shock_transition": [[.90, .08, .02], [.03, .87, .10], [0., 0., 1.]],
                                "reference_loss_rates": [.005, .10, .40], "shock_loss_rates": [.01, .15, .50],
                                "insurance_recovery": 0.})
    return {"schema_version": 1, "input_set_hash": manifest["input_set_hash"], "status": "SYNTHETIC",
            "version": "demo-1", "source": "June 2026 EBA draft preparation; invented demonstration inputs",
            "benchmarks": benchmark,
            "recoveries": [{"facility_id": str(first.facility_id), "ead": float(first.gca),
                            "eir": float(first.interest_rate), "collateral_id": "synthetic-property-1",
                            "collateral_value": float(first.gca), "allocation": 1., "haircut": .30,
                            "cost": float(first.gca*.05), "recovery_years": 2., "unsecured_recovery": 0.,
                            "model_version": "synthetic-recovery-1"}],
            "capital": {"weights": weights, "bridge": bridge}, "climate": climate,
            "template_mapping": {"version": "illustrative-layout-1", "cells": [
                {"sheet": "DEMO_CREDIT", "row": "total", "column": f"gca_{s}_{y}", "table": "dimensions",
                 "measure": "gca", "filters": {"scenario": s, "year": y}} for s in scenarios for y in years]},
            # Unsecured 35% in the third year is footnote 75 of the draft and 2019-2026 is paragraph 563.
            # Every other factor is an illustration: replace them from Article 47c before any use.
            "npe_backstop": {"version": "illustrative-calendar-1", "scope_from": "2019-04-26",
                             "scope_to": "2026-12-31",
                             "source": "unsecured year 3 from draft footnote 75; other factors illustrative",
                             "calendar": [{"from_year": 1, "unsecured": 0., "secured": 0.},
                                          {"from_year": 3, "unsecured": .35, "secured": 0.},
                                          {"from_year": 4, "unsecured": 1., "secured": .25}]},
            "plausibility": yaml.safe_load(BENCHMARKS.read_text(encoding="utf-8")),
            "challenge": {"severity_grid": [0., 1., 2., 3., 4.], "loss_limit_eur": float(f.gca.sum()*.05),
                          "lower": 0., "upper": 6., "limit_name": "illustrative one-year loss budget"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    doc = build(args.inputs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(doc, stream, sort_keys=False)
    print(f"wrote SYNTHETIC preparation package: {args.out}")


if __name__ == "__main__":
    main()
