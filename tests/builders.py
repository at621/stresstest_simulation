"""Input sets built by the tests.

``full_input_set`` runs O2-O4 into a temporary folder (deterministic, so it has the same hash
as the committed set). ``mini`` takes a few facilities of every segment and stage from it;
tests then change one field to plant a defect and write the result as a new hashed input set.
"""

import json
from pathlib import Path

import pandas as pd
import yaml
from scipy.special import ndtri

from foundation.synth import build
from foundation.synth.inputset import FILES, write_input_set
from stress.cli import execute
from stress.contracts.inputs import SCENARIO_UNITS
from stress.contracts.run import RunConfig
from tests.support import ROOT, SPEC_DIR, oracle

PARAMS = ROOT / "foundation" / "parameter_set.yaml"
TABLES = ("facilities", "obligors", "commitments", "opening_provisions", "ttc_pd_matrix")
DOCUMENTS = ("scenarios", "parameter_set")
# Cases that read a whole segment or rewrite grade rows; the others share P03.
REFERENCE_SEGMENTS = {"AT-02": "P01", "AT-29": "P02", "AT-25": "P04", "AT-06": "P05"}


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


def _grade(tables: dict, value: float) -> str:
    """The grade whose master-scale PD neighbours ``value`` from above, which keeps PD rising."""
    scale = tables["parameter_set"]["master_scale"]
    return next(g for g, p in zip(scale["grades"], scale["ttc_pd"]) if p >= value)


def _set_row(tables: dict, segment: str, grade: str, cells: dict[str, float]) -> None:
    """Replace one grade's row of a segment's TTC matrix."""
    m = tables["ttc_pd_matrix"]
    row = (m["segment"] == segment) & (m["from_grade"] == grade)
    m.loc[row, "probability"] = m.loc[row, "to_grade"].map(cells).fillna(0.0)


def _pd_row(tables: dict, segment: str, value: float) -> str:
    """A grade of the segment that stays put or defaults with one-year PD ``value``."""
    grade = _grade(tables, value)
    _set_row(tables, segment, grade, {grade: 1.0 - value, "D": value})
    return grade


def _stage_book(name: str, opening: dict, grades: dict) -> dict:
    """One facility per stage of a case's opening book, alone in the case's segment. The S2
    facility originated in the S1 grade, whose SICR line it is over."""
    common = {"segment": REFERENCE_SEGMENTS[name], "lgd": oracle("AT-34")["input"]["lgd"]}
    return {
        f"{name}/S1": {**common, "gca": opening["S1"], "grade": grades["S1"]},
        f"{name}/S2": {**common, "gca": opening["S2"], "stage": 2, "grade": grades["S2"],
                       "origination": grades["S1"]},
        f"{name}/S3": {**common, "gca": opening["S3"], "stage": 3},
    }


def _transition_book(t: dict) -> dict:
    """AT-02: two grades carry the S1 and S2 transition rows; D is S3."""
    i = oracle("AT-02")["input"]
    rows = i["transitions"]
    grades = {stage: _grade(t, rows[stage]["S3"]) for stage in ("S1", "S2")}
    labels = {**grades, "S3": "D"}
    for stage, grade in grades.items():
        _set_row(t, REFERENCE_SEGMENTS["AT-02"], grade, {labels[to]: p for to, p in rows[stage].items()})
    return _stage_book("AT-02", i["opening"], grades)


def _default_book(t: dict) -> dict:
    """AT-29: two grades carry the origin-stage PDs."""
    i = oracle("AT-29")["input"]
    grades = {stage: _pd_row(t, REFERENCE_SEGMENTS["AT-29"], p) for stage, p in i["pd"].items()}
    return _stage_book("AT-29", i["opening"], grades)


def _curve_book(t: dict) -> dict:
    """AT-25 and AT-39: survivors move down a chain of grades whose one-year PDs are the
    conditional PDs in order, so the start grade's PD curve is the case's."""
    q = oracle("AT-25")["input"]["conditional_pd"]
    i = oracle("AT-39")["input"]
    segment = REFERENCE_SEGMENTS["AT-25"]
    grades = t["parameter_set"]["master_scale"]["grades"]
    first = grades.index(_grade(t, q[0]))
    chain = grades[first:first + len(q)]
    for grade, following, p in zip(chain, chain[1:] + chain[-1:], q):
        _set_row(t, segment, grade, {following: 1.0 - p, "D": p})
    common = {"segment": segment, "grade": chain[0], "gca": i["ead"], "lgd": i["lgd"], "rate": i["eir"],
              "maturity": i["remaining_life_years"]}
    return {"AT-39/S1": common, "AT-39/S2": {**common, "stage": 2, "watchlist": True}}


def _terminal_book(t: dict) -> dict:
    """AT-06: one driver scaled so that Z of the valuation year is 0 on baseline and -1 on
    adverse. The TTC PD and LGD are then the baseline's, and rho and w reach the adverse ones."""
    i = oracle("AT-06")["input"]
    adverse, baseline = i["adverse"], i["baseline"]
    segment = REFERENCE_SEGMENTS["AT-06"]
    params = t["parameter_set"]["segments"][segment]
    driver = next(iter(params["z_drivers"]))
    x = {v["scenario"]: v["value"] * SCENARIO_UNITS[v["unit"]] for v in t["scenarios"]["values"]
         if v["variable"] == driver and v["year"] == i["valuation_year"]}
    params["z_drivers"] = {driver: {"beta": 1.0, "mean": x["baseline"], "sd": x["baseline"] - x["adverse"]}}
    params["rho"] = float(ndtri(adverse["pd"]) - ndtri(baseline["pd"])) ** 2
    params["lgd_w"] = float(ndtri(adverse["lgd"]) - ndtri(baseline["lgd"]))
    return {"AT-06": {"segment": segment, "grade": _pd_row(t, segment, baseline["pd"]),
                      "gca": oracle("AT-34")["input"]["drawn"], "lgd": baseline["lgd"]}}


def _reference_book(t: dict) -> dict:
    """Every reference facility, by case. A case that names no PD or LGD takes AT-34's."""
    case = {n: oracle(f"AT-{n}")["input"] for n in ("03", "04", "05", "07", "08", "18", "34", "37", "40", "42")}
    base = case["34"]
    grade = _pd_row(t, "P03", base["pd"])
    at18 = {}
    for name in ("A", "B"):
        change = case["18"][name]["change"]
        opening = abs(change) * 4  # any positive allowance
        at18[f"AT-18/{name}"] = {"segment": "P03", "stage": 3, "gca": (opening + change) / base["lgd"],
                                 "lgd": base["lgd"], "opening": opening}
    return {
        "AT-34": {"segment": "P03", "grade": grade, "gca": base["drawn"], "undrawn": base["undrawn"],
                  "ccf": base["ccf"], "lgd": base["lgd"], "rate": 1.0 / base["discount_factor"] - 1.0},
        "AT-42": {"segment": "P03", "grade": _pd_row(t, "P03", case["42"]["pd"]), "gca": case["42"]["drawn"],
                  "undrawn": case["42"]["undrawn"], "ccf": case["42"]["ccf"], "lgd": case["42"]["lgd"],
                  "rate": case["42"]["eir"]},
        "AT-04": {"segment": "P03", "grade": grade, "gca": case["04"]["flow"] / base["pd"],
                  "lgd": case["04"]["lgd"]},
        "AT-05": {"segment": "P03", "grade": _pd_row(t, "P03", case["05"]["pd"]), "gca": case["05"]["exposure"],
                  "lgd": case["05"]["lgd"], "rate": 1.0 / case["05"]["discount_factor"] - 1.0},
        "AT-08": {"segment": "P03", "grade": grade, "gca": case["08"]["drawn"], "undrawn": case["08"]["undrawn"],
                  "ccf": case["08"]["ccf"], "lgd": base["lgd"]},
        "AT-37": {"segment": "P03", "grade": grade, "gca": case["37"]["gca"], "lgd": base["lgd"],
                  "principal": case["37"]["principal"], "accrued": case["37"]["accrued_interest"],
                  "accrued_in_gca": case["37"]["accrued_in_gca"]},
        "AT-40": {"segment": "P03", "grade": _pd_row(t, "P03", case["40"]["marginal_pd"]),
                  "gca": case["40"]["ead"], "lgd": case["40"]["lgd"], "rate": case["40"]["eir"],
                  "maturity": float(case["40"]["buckets"])},
        "AT-03": {"segment": "P03", "stage": 3, "gca": case["03"]["exposure"], "lgd": case["03"]["loss_rate"],
                  "opening": case["03"]["opening_allowance"]},
        "AT-07": {"segment": "P03", "stage": 3, "gca": case["07"]["closing"] / base["lgd"], "lgd": base["lgd"],
                  "opening": case["07"]["opening"]},
        **at18, **_transition_book(t), **_default_book(t), **_curve_book(t), **_terminal_book(t),
    }


def reference_set(tables: dict) -> tuple[dict, dict[str, str]]:
    """Facilities carrying the oracle inputs, valued at end-2026, with the ids they got by case.

    The TTC matrix gives each facility's grade exactly the case's PD or transitions, and rho = 0,
    w = 0 and no prepayment make the PiT matrix, LGD and EAD equal their TTC inputs, so the run
    reproduces the case. Cases that read a whole segment or rewrite grade rows have a segment of
    their own (REFERENCE_SEGMENTS); AT-06 alone keeps a rho and a w. All values come from oracles.
    """
    t = copy_tables(tables)
    for segment in ("P03", *REFERENCE_SEGMENTS.values()):
        t["parameter_set"]["segments"][segment].update({"rho": 0.0, "lgd_w": 0.0, "cpr_ttc": 0.0, "cpr_v": 0.0})
    book = _reference_book(t)
    fac, prov = t["facilities"], t["opening_provisions"]
    template = t["commitments"].iloc[0]
    facilities, provisions, commitments, ids = [], [], [], {}
    for n, (name, case) in enumerate(book.items(), start=1):
        fid = ids[name] = f"FREF{n:02d}"
        stage = case.get("stage", 1)
        undrawn = case.get("undrawn", 0.0)
        # S1 and S2 clone an S1 facility, which has no trigger and a performing obligor; S3 an S3 one.
        source = fac[(fac["segment"] == case["segment"]) & (fac["ifrs_stage"] == (3 if stage == 3 else 1))]
        row = source.head(1).assign(
            facility_id=fid, ifrs_stage=stage, gca=case["gca"], principal=case.get("principal", case["gca"]),
            accrued_interest=case.get("accrued", 0.0), accrued_in_gca=case.get("accrued_in_gca", True),
            contractual_limit=case["gca"] + undrawn, interest_rate=case.get("rate", 0.0),
            residual_maturity=case.get("maturity", 1.0), ttc_lgd=case["lgd"],
            watchlist=case.get("watchlist", False), product="revolver" if undrawn else "term_loan")
        if stage < 3:
            row = row.assign(current_grade=case["grade"], origination_grade=case.get("origination", case["grade"]))
        facilities.append(row)
        provisions.append(prov[prov["facility_id"] == source["facility_id"].iloc[0]].assign(
            facility_id=fid, allowance_on=case.get("opening", 0.0), provision_off=0.0, overlay_amount=0.0))
        if undrawn:
            commitments.append({**template.to_dict(), "commitment_id": f"CREF{n}", "facility_id": fid,
                                "nominal_undrawn": undrawn, "accounting_ccf": case["ccf"]})
    t["facilities"] = pd.concat(facilities, ignore_index=True)
    t["obligors"] = t["obligors"][t["obligors"]["obligor_id"].isin(set(t["facilities"]["obligor_id"]))]
    t["commitments"] = pd.DataFrame(commitments)
    t["opening_provisions"] = pd.concat(provisions, ignore_index=True)
    return t, ids


def capital_case(starting: dict[str, float], raw: dict[str, float], strea: float = 0.0, factor: float = 0.0) -> tuple:
    """One unit of exposure per approach, with risk weights that give the case's REA: ``starting``
    at the snapshot and ``raw`` a year later. Charges and CET1 movements are zero."""
    keys = {"scenario": "adverse", "regulatory_class": "corporate", "grade": "G1"}
    approaches = sorted(starting)
    slices = pd.DataFrame([{"scenario": "adverse", "year": year, "facility_id": a, "grade": "G1", "gca": 1.0,
                            "undrawn": 0.0} for year in (2026, 2027) for a in approaches])
    portfolio = pd.DataFrame([{"facility_id": a, "regulatory_approach": a, "regulatory_class": "corporate"}
                              for a in approaches])
    charges = pd.DataFrame([{"scenario": "adverse", "year": 2027, "charge_on": 0.0, "charge_off": 0.0}])
    weights = [{**keys, "year": year, "regulatory_approach": a, "regulatory_ccf": 0.0, "standardised_ccf": 0.0,
                "risk_weight": float(table[a]), "standardised_risk_weight": strea / len(approaches),
                "model_version": "test"}
               for year, table in ((2026, starting), (2027, raw)) for a in approaches]
    period = {"scenario": "adverse", "year": 2027, "opening_cet1": 1.0, "other_pnl": 0.0, "tax_rate": 0.0,
              "distributions": 0.0, "irb_shortfall_change": 0.0, "npl_deduction_change": 0.0,
              "other_cet1_change": 0.0, "other_utrea": 0.0, "other_strea": 0.0, "output_floor_factor": factor}
    return {"weights": weights, "bridge": [period]}, slices, portfolio, charges


def run(input_dir: Path, runs_dir: Path, scenarios=("baseline", "adverse"), variant: str = "core",
        mode: str = "synthetic"):
    config = RunConfig(inputs=input_dir.as_posix(), scenarios=tuple(scenarios), variant=variant, mode=mode)
    return execute(config, runs_dir)


def result(ctx, name: str) -> pd.DataFrame:
    return pd.read_parquet(ctx.results_dir / name)


def report(ctx, name: str) -> pd.DataFrame:
    return pd.read_csv(ctx.reports_dir / name)
