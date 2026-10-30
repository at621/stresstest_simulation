"""Synthetic capital bridge from explicit regulatory model outputs, not accounting CCFs.

Risk weights are versioned external model inputs. This is not a CRR risk-weight calculator.
"""

import numpy as np
import pandas as pd

from stress.capital import methodological_floor, output_floor
from stress.contracts.checks import number, required
from stress.contracts.errors import BlockingError


def capital_bridge(spec: dict, slices: pd.DataFrame, portfolio: pd.DataFrame,
                   charges: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required(spec, ("weights", "bridge"), "capital")
    keys = ["scenario", "year", "regulatory_approach", "regulatory_class", "grade"]
    for row in spec["weights"]:
        required(row, (*keys, "regulatory_ccf", "standardised_ccf", "risk_weight", "standardised_risk_weight",
                       "model_version"), "regulatory model output")
        number(row["regulatory_ccf"], "regulatory_ccf", 0, 1)
        number(row["standardised_ccf"], "standardised_ccf", 0, 1)
        for field in ("risk_weight", "standardised_risk_weight"):
            number(row[field], field, 0)
        if not row["model_version"]:
            raise BlockingError("capital", "MISSING_INPUT", "empty risk weight model version")
    weights = pd.DataFrame(spec["weights"])
    if weights.empty or weights.duplicated(keys).any():
        raise BlockingError("capital", "DUPLICATE_KEY", "empty or duplicate regulatory model outputs")
    detail = slices.merge(portfolio[["facility_id", "regulatory_approach", "regulatory_class"]],
                          on="facility_id", validate="many_to_one")
    detail = detail.merge(weights, on=keys, how="left", validate="many_to_one", indicator=True)
    if not detail["_merge"].eq("both").all():
        raise BlockingError("capital", "MISSING_INPUT", "regulatory weights do not cover every slice")
    if not detail.regulatory_approach.isin(["IRB", "STA"]).all():
        raise BlockingError("capital", "INVALID_INPUT", "unsupported regulatory approach")
    detail = detail.drop(columns="_merge")
    detail["regulatory_ead"] = detail.gca + detail.undrawn * detail.regulatory_ccf
    detail["raw_rea"] = detail.regulatory_ead * detail.risk_weight
    detail["standardised_ead"] = detail.gca + detail.undrawn * detail.standardised_ccf
    detail["standardised_rea"] = detail.standardised_ead * detail.standardised_risk_weight
    grouped = detail.groupby(["scenario", "year", "regulatory_approach"])["raw_rea"].sum()
    sta = detail.groupby(["scenario", "year"])["standardised_rea"].sum()
    losses = (charges.assign(charge_total=charges.charge_on + charges.charge_off)
              .groupby(["scenario", "year"])["charge_total"].sum())
    bridge = {}
    fields = ("scenario", "year", "other_pnl", "tax_rate", "distributions", "irb_shortfall_change",
              "npl_deduction_change", "other_cet1_change", "other_utrea", "other_strea",
              "output_floor_factor")
    for row in spec["bridge"]:
        required(row, fields, "capital bridge")
        key = (row["scenario"], row["year"])
        if key in bridge:
            raise BlockingError("capital", "DUPLICATE_KEY", "duplicate capital bridge period")
        for field in fields[2:]:
            number(row[field], field)
        for field in ("tax_rate", "output_floor_factor"):
            number(row[field], field, 0, 1)
        for field in ("distributions", "other_utrea", "other_strea"):
            number(row[field], field, 0)
        bridge[key] = row
    if set(bridge) != set(losses.index):
        raise BlockingError("capital", "MISSING_INPUT", "bridge periods must match all charge periods")
    out = []
    for scenario in sorted(detail.scenario.unique()):
        start = int(detail.loc[detail.scenario.eq(scenario), "year"].min())
        starting = grouped.loc[(scenario, start)].to_dict()
        previous = None
        for year in sorted(y for s, y in bridge if s == scenario):
            row = bridge[scenario, year]
            if previous is None:
                required(row, ("opening_cet1",), "first capital period")
                previous = number(row["opening_cet1"], "opening_cet1", 0)
            elif "opening_cet1" in row and not np.isclose(row["opening_cet1"], previous, rtol=1e-10, atol=.01):
                raise BlockingError("capital", "RECONCILIATION", "opening CET1 differs from preceding close")
            opening = previous
            raw = grouped.loc[(scenario, year)].to_dict()
            if set(raw) != set(starting):
                raise BlockingError("capital", "MISSING_INPUT", "regulatory approaches changed")
            credit = methodological_floor(starting, raw)["credit_contribution"]
            ut = credit + row["other_utrea"]
            st = float(sta.loc[(scenario, year)]) + row["other_strea"]
            total = output_floor(ut, st, row["output_floor_factor"])["result"]
            if total <= 0:
                raise BlockingError("capital", "INVALID_INPUT", "total REA must be positive")
            charge = float(losses.loc[(scenario, year)])
            # Symmetric tax is an explicit synthetic convention; no automatic DTA recognition model.
            profit = (row["other_pnl"] - charge) * (1 - row["tax_rate"])
            previous = (opening + profit - row["distributions"] - row["irb_shortfall_change"]
                        - row["npl_deduction_change"] + row["other_cet1_change"])
            out.append({**row, "opening_cet1": opening, "credit_charge": charge,
                        "profit_after_tax": profit, "raw_credit_rea": sum(raw.values()),
                        "floored_credit_rea": credit, "utrea": ut, "strea": st,
                        "total_rea": total, "cet1": previous, "cet1_ratio": previous/total,
                        "basis": "SYNTHETIC_EXTERNAL_RISK_WEIGHTS"})
    return pd.DataFrame(out), detail
