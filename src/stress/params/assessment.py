"""Explicit synthetic preparation analyses; never substitutes into a regulatory run.

Benchmark bundles follow the June-2026 draft coverage rule by pivot and parameter family.
Recovery assumptions are supplied inputs; this module does not generate contractual flows.
"""

import numpy as np
import pandas as pd
from scipy.special import ndtr, ndtri

from stress.contracts.checks import number, required
from stress.contracts.errors import BlockingError
from stress.params.lgd import lgd_from_z

FAMILIES = {
    "pd_tr": ("tr11", "tr12", "tr13", "tr21", "tr22", "tr23"),
    "lgd_lr": ("lr11", "lr12", "lr13", "lr21", "lr22", "lr23"),
}


def benchmark_selection(rows: list[dict]) -> pd.DataFrame:
    """Choose whole model/benchmark parameter bundles, not an opportunistic scalar mix."""
    if not rows:
        raise BlockingError("analysis", "MISSING_INPUT", "empty benchmark population")
    stable, seen = {}, set()
    for row in rows:
        required(row, ("exposure_id", "country", "pivot", "family", "scenario", "year", "gca",
                       "model_available", "route"), "benchmark row")
        if row["family"] not in FAMILIES or row["route"] not in ("ordinary", "sovereign", "central_bank"):
            raise BlockingError("analysis", "INVALID_INPUT", "unknown benchmark family or route")
        if not isinstance(row["model_available"], bool):
            raise BlockingError("analysis", "INVALID_INPUT", "model_available must be boolean")
        if row["model_available"]:
            required(row, ("model_parameters", "model_version"), "eligible model")
            required(row["model_parameters"], FAMILIES[row["family"]], "eligible complete family")
            for name in FAMILIES[row["family"]]:
                number(row["model_parameters"][name], name, 0, 1)
        number(row["gca"], "gca", 0)
        identity = tuple(row[k] for k in ("exposure_id", "country", "pivot", "family"))
        key = identity + (row["scenario"], row["year"])
        if key in seen:
            raise BlockingError("analysis", "DUPLICATE_KEY", "duplicate benchmark exposure")
        seen.add(key)
        choice = (row["model_available"], row["route"], row["gca"], row.get("model_version"),
                  row.get("benchmark_version"))
        if identity in stable and stable[identity] != choice:
            raise BlockingError("analysis", "UNSTABLE_SELECTION", "model choice changes across scenarios/years")
        stable[identity] = choice
    groups = {}
    for row in rows:
        key = tuple(row[k] for k in ("country", "pivot", "family", "scenario", "year"))
        groups.setdefault(key, []).append(row)
    populations = {}
    periods = {(r["scenario"], r["year"]) for r in rows}
    for key, group in groups.items():
        pivot, period = key[:3], key[3:]
        population = frozenset(r["exposure_id"] for r in group)
        populations.setdefault(pivot, {})[period] = population
    for pivot, views in populations.items():
        if set(views) != periods or len(set(views.values())) != 1:
            raise BlockingError("analysis", "UNSTABLE_SELECTION", f"pivot population changes: {pivot}")
    out = []
    for key, group in groups.items():
        total = sum(r["gca"] for r in group)
        if total <= 0:
            raise BlockingError("analysis", "INVALID_INPUT", "zero pivot exposure")
        coverage = sum(r["gca"] for r in group if r["model_available"]) / total
        for row in group:
            source = ("zero_loss" if row["route"] == "central_bank" else
                      "model" if row["route"] == "ordinary" and coverage >= .10
                      and row["model_available"] else "benchmark")
            names = FAMILIES[row["family"]]
            if source == "zero_loss":
                values = {n: (1. if n in ("tr11", "tr22") else 0.) for n in names}
                version = "central-bank-zero-loss"
            else:
                required(row, (source + "_parameters", source + "_version"), "selected source")
                values = row[source + "_parameters"]
                required(values, names, "complete parameter family")
                version = row[source + "_version"]
                if not isinstance(version, str) or not version.strip():
                    raise BlockingError("analysis", "MISSING_INPUT", "empty selected source version")
            for name in names:
                number(values[name], name, 0, 1)
            if row["family"] == "pd_tr":
                for origin in (1, 2):
                    if not np.isclose(sum(values[f"tr{origin}{j}"] for j in (1, 2, 3)), 1., atol=1e-10, rtol=0):
                        raise BlockingError("analysis", "INVALID_MATRIX", "transition row must sum to one")
            for name in names:
                out.append({**dict(zip(("country", "pivot", "family", "scenario", "year"), key)),
                            "exposure_id": row["exposure_id"], "gca": row["gca"],
                            "model_coverage": coverage, "source": source, "source_version": version,
                            "parameter": name, "value": values[name]})
    return pd.DataFrame(out)


def recovery_lgd(rows: list[dict]) -> pd.DataFrame:
    """Net recovery at its supplied date, discounted to default exactly once."""
    allocations, collateral_values, seen, out = {}, {}, set(), []
    fields = ("facility_id", "ead", "eir", "collateral_id", "collateral_value", "allocation",
              "haircut", "cost", "recovery_years", "unsecured_recovery", "model_version")
    for row in rows:
        required(row, fields, "recovery")
        if row["facility_id"] in seen:
            raise BlockingError("analysis", "DUPLICATE_KEY", "duplicate recovery facility")
        seen.add(row["facility_id"])
        ead = number(row["ead"], "ead", 0)
        rate = number(row["eir"], "eir")
        if ead <= 0 or rate <= -1:
            raise BlockingError("analysis", "INVALID_INPUT", "ead must be positive and eir > -1")
        value = number(row["collateral_value"], "collateral_value", 0)
        allocation = number(row["allocation"], "allocation", 0, 1)
        haircut = number(row["haircut"], "haircut", 0, 1)
        cost = number(row["cost"], "cost", 0)
        time = number(row["recovery_years"], "recovery_years", 0)
        unsecured = number(row["unsecured_recovery"], "unsecured_recovery", 0)
        cid = row["collateral_id"]
        if cid in collateral_values and collateral_values[cid] != value:
            raise BlockingError("analysis", "INVALID_INPUT", "shared collateral values disagree")
        collateral_values[cid] = value
        allocations[cid] = allocations.get(cid, 0.) + allocation
        if allocations[cid] > 1 + 1e-10:
            raise BlockingError("analysis", "INVALID_INPUT", "shared collateral allocated more than once")
        recovery = min(ead, max(0., value * allocation * (1 - haircut) + unsecured - cost))
        pv = recovery / (1 + rate)**time
        out.append({"facility_id": row["facility_id"], "model_version": row["model_version"],
                    "net_recovery": recovery, "present_value": pv,
                    "lgd": max(0., min(1., 1 - pv / ead))})
    return pd.DataFrame(out)


def reverse_threshold(loss, target: float, lower: float, upper: float, iterations: int = 50) -> dict:
    """Bracket a breach of a user-named internal loss limit for a monotone severity model."""
    for name, value in (("target", target), ("lower", lower), ("upper", upper)):
        number(value, name, 0)
    if upper <= lower:
        raise BlockingError("analysis", "INVALID_INPUT", "reverse-stress bracket must increase")
    left, right = number(loss(lower), "loss"), number(loss(upper), "loss")
    if left >= target:
        return {"status": "ALREADY_BREACHED", "severity": lower, "loss": left}
    if right < target:
        return {"status": "NOT_REACHED", "severity": upper, "loss": right}
    for _ in range(iterations):
        mid = (lower + upper) / 2
        value = number(loss(mid), "loss")
        if value < left - 1e-8 or value > right + 1e-8:
            raise BlockingError("analysis", "NON_MONOTONE", "loss is not monotone within the bracket")
        if value >= target:
            upper, right = mid, value
        else:
            lower, left = mid, value
    return {"status": "BREACHED", "severity": upper, "loss": right}


def calibration_diagnostics(ps: dict) -> pd.DataFrame:
    """Independent Gaussian quadrature, explicitly conditional on Z being standard normal."""
    nodes, weights = np.polynomial.hermite.hermgauss(64)
    out = []
    for segment, settings in ps["segments"].items():
        rho = settings["rho"]
        for grade, p in zip(ps["master_scale"]["grades"], ps["master_scale"]["ttc_pd"]):
            cycle = float(np.dot(weights, ndtr(ndtri(p) - np.sqrt(2*rho)*nodes)) / np.sqrt(np.pi))
            analytic = float(ndtr(ndtri(p) / np.sqrt(1+rho)))
            out.append({"segment": segment, "grade": grade, "anchor_pd": p,
                        "cycle_pd_quadrature": cycle, "cycle_pd_analytic": analytic,
                        "difference": cycle-analytic, "cycle_to_anchor": cycle/p,
                        "assumption": "Z standard normal; diagnostic, not empirical calibration"})
    return pd.DataFrame(out)


def challenge_analysis(spec: dict, portfolio: pd.DataFrame, ps: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One-year PD x accounting EAD x LGD sensitivity, not lifetime ECL or capital depletion."""
    required(spec, ("severity_grid", "loss_limit_eur", "lower", "upper", "limit_name"), "challenge")
    if not spec["severity_grid"] or not spec["limit_name"]:
        raise BlockingError("analysis", "MISSING_INPUT", "challenge requires grid and named internal limit")
    perf = portfolio.loc[portfolio.stage.ne(3)]
    if perf.empty:
        raise BlockingError("analysis", "MISSING_INPUT", "challenge needs performing exposures")
    anchors = dict(zip(ps["master_scale"]["grades"], ps["master_scale"]["ttc_pd"]))
    p = perf.current_grade.map(anchors).to_numpy(float)
    rho = perf.segment.map(lambda s: ps["segments"][s]["rho"]).to_numpy(float)
    w = perf.segment.map(lambda s: ps["segments"][s]["lgd_w"]).to_numpy(float)
    ccf = perf.ccf.where(perf.undrawn.gt(0), 0.).to_numpy(float)
    exposure = perf.gca.to_numpy(float) + perf.undrawn.to_numpy(float)*ccf
    if not np.isfinite(p).all() or not np.isfinite(exposure).all():
        raise BlockingError("analysis", "MISSING_INPUT", "challenge exposure or anchor missing")

    def loss(severity):
        pd = ndtr(ndtri(p) + np.sqrt(rho)*severity)
        lgd = lgd_from_z(perf.ttc_lgd.to_numpy(float), w, -severity)
        return float(np.sum(exposure*pd*lgd))

    grid = []
    for severity in spec["severity_grid"]:
        number(severity, "severity", 0)
        grid.append({"severity": severity, "loss": loss(severity), "z": -severity,
                     "basis": "ONE_YEAR_PD_EAD_LGD_DIAGNOSTIC"})
    reverse = reverse_threshold(loss, spec["loss_limit_eur"], spec["lower"], spec["upper"])
    reverse.update(limit_name=spec["limit_name"], loss_limit_eur=spec["loss_limit_eur"],
                   basis="ONE_YEAR_PD_EAD_LGD_DIAGNOSTIC")
    return pd.DataFrame(grid), pd.DataFrame([reverse])
