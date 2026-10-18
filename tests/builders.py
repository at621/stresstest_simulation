"""Input sets built by the tests.

``full_input_set`` runs O2-O4 into a temporary folder (deterministic, so it has the same hash
as the committed set). ``mini`` takes a few facilities of every segment and stage from it;
tests then change one field to plant a defect and write the result as a new hashed input set.
"""

import json
from pathlib import Path

import pandas as pd
import yaml

from foundation.synth import build
from foundation.synth.inputset import FILES, write_input_set
from stress.cli import execute
from stress.contracts.run import RunConfig
from tests.support import ROOT, SPEC_DIR

PARAMS = ROOT / "foundation" / "parameter_set.yaml"
TABLES = ("facilities", "obligors", "commitments", "opening_provisions", "ttc_pd_matrix")
DOCUMENTS = ("scenarios", "parameter_set")


def full_input_set(root: Path) -> Path:
    return build(SPEC_DIR, PARAMS, root)


def load(input_dir: Path) -> dict:
    out = {name: pd.read_parquet(input_dir / FILES[name]) for name in TABLES}
    for name in DOCUMENTS:
        with (input_dir / FILES[name]).open(encoding="utf-8") as fh:
            out[name] = yaml.safe_load(fh)
    out["_meta"] = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    return out


def mini(tables: dict, per_cell: int = 2) -> dict:
    """A few facilities per segment and stage, plus one revolver per book with commitments."""
    fac = tables["facilities"].sort_values("facility_id")
    picked = fac.groupby(["segment", "ifrs_stage"], sort=True).head(per_cell)
    revolvers = fac[fac["facility_id"].isin(tables["commitments"]["facility_id"])]
    picked = pd.concat([picked, revolvers.groupby("portfolio").head(1)]).drop_duplicates("facility_id")
    ids = set(picked["facility_id"])
    out = {
        "facilities": picked.sort_values("facility_id").reset_index(drop=True),
        "obligors": tables["obligors"][tables["obligors"]["obligor_id"].isin(set(picked["obligor_id"]))]
        .reset_index(drop=True),
        "commitments": tables["commitments"][tables["commitments"]["facility_id"].isin(ids)].reset_index(drop=True),
        "opening_provisions": tables["opening_provisions"][tables["opening_provisions"]["facility_id"].isin(ids)]
        .reset_index(drop=True),
        "ttc_pd_matrix": tables["ttc_pd_matrix"].copy(),
        "scenarios": json.loads(json.dumps(tables["scenarios"])),
        "parameter_set": json.loads(json.dumps(tables["parameter_set"])),
        "_meta": tables["_meta"],
    }
    return out


def copy_tables(tables: dict) -> dict:
    out = {}
    for name, value in tables.items():
        out[name] = value.copy() if isinstance(value, pd.DataFrame) else json.loads(json.dumps(value))
    return out


def write(tables: dict, root: Path) -> Path:
    meta = {k: tables["_meta"][k] for k in ("status", "spec_version", "parameter_set_id", "generator")}
    return write_input_set(root, {n: tables[n] for n in TABLES},
                           {n: tables[n] for n in DOCUMENTS}, meta)


def reference_set(tables: dict, at34: dict, at42: dict) -> tuple[dict, dict[str, str]]:
    """Two P03 S1 revolvers carrying the AT-34 and AT-42 inputs, valued at end-2026.

    The P03 matrix gives each facility's grade exactly the case's one-year PD, and rho = 0,
    w = 0 and no prepayment make the PiT matrix, LGD and EAD equal their TTC inputs, so the
    run's first bucket reproduces the case. All values come from the two oracles.
    """
    t = copy_tables(tables)
    fac = t["facilities"]
    p03 = fac[(fac["segment"] == "P03") & (fac["ifrs_stage"] == 1)].sort_values("facility_id").head(2)
    grades = t["parameter_set"]["master_scale"]["grades"]
    pds = t["parameter_set"]["master_scale"]["ttc_pd"]
    cases = {"AT-34": at34["input"], "AT-42": at42["input"]}
    ids = {}
    m = t["ttc_pd_matrix"]
    for (name, case), row in zip(cases.items(), p03.itertuples(index=False)):
        # The grade whose master-scale PD neighbours the case PD from above keeps PD rising.
        grade = next(g for g, p in zip(grades, pds) if p >= case["pd"])
        rate = case.get("eir", 0.0) if "eir" in case else 1.0 / case["discount_factor"] - 1.0
        i = fac.index[fac["facility_id"] == row.facility_id][0]
        fac.loc[i, ["principal", "gca", "contractual_limit"]] = [case["drawn"], case["drawn"],
                                                                case["drawn"] + case["undrawn"]]
        fac.loc[i, ["accrued_interest", "interest_rate", "residual_maturity"]] = [0.0, rate, 1.0]
        fac.loc[i, ["ttc_lgd", "current_grade", "origination_grade", "product"]] = [
            case["lgd"], grade, grade, "revolver"]
        cell = (m["segment"] == "P03") & (m["from_grade"] == grade)
        d = cell & (m["to_grade"] == "D")
        stay = cell & (m["to_grade"] == grade)
        m.loc[stay, "probability"] += float(m.loc[d, "probability"].iloc[0]) - case["pd"]
        m.loc[d, "probability"] = case["pd"]
        ids[name] = row.facility_id
    keep = set(ids.values())
    t["facilities"] = fac[fac["facility_id"].isin(keep)].reset_index(drop=True)
    t["obligors"] = t["obligors"][t["obligors"]["obligor_id"].isin(set(t["facilities"]["obligor_id"]))]
    template = t["commitments"].iloc[0]
    t["commitments"] = pd.DataFrame([
        {**template.to_dict(), "commitment_id": f"CREF{n}", "facility_id": fid,
         "nominal_undrawn": cases[name]["undrawn"], "accounting_ccf": cases[name]["ccf"]}
        for n, (name, fid) in enumerate(ids.items(), start=1)
    ])
    provisions = t["opening_provisions"]
    t["opening_provisions"] = provisions[provisions["facility_id"].isin(keep)].reset_index(drop=True)
    seg = t["parameter_set"]["segments"]["P03"]
    seg.update({"rho": 0.0, "lgd_w": 0.0, "cpr_ttc": 0.0, "cpr_v": 0.0})
    return t, ids


def run(input_dir: Path, runs_dir: Path, scenarios=("baseline", "adverse"), variant: str = "core",
        mode: str = "synthetic"):
    config = RunConfig(inputs=input_dir.as_posix(), scenarios=tuple(scenarios), variant=variant, mode=mode)
    return execute(config, runs_dir)


def result(ctx, name: str) -> pd.DataFrame:
    return pd.read_parquet(ctx.results_dir / name)


def report(ctx, name: str) -> pd.DataFrame:
    return pd.read_csv(ctx.reports_dir / name)
