"""Separate climate provision projection from supplied stage transitions and loss rates.

Stage-1 loss rates represent 12-month ECL, stage-2 lifetime ECL, stage-3 LGD.
These are already stressed model outputs, not multipliers applied again to core ECL.
"""

import numpy as np
import pandas as pd

from stress.contracts.checks import number, required
from stress.contracts.errors import BlockingError


def climate_assessment(rows: list[dict], portfolio: pd.DataFrame) -> pd.DataFrame:
    if not rows:
        raise BlockingError("climate", "MISSING_INPUT", "empty climate population")
    port = portfolio.set_index("facility_id")
    groups, out = {}, []
    for row in rows:
        required(row, ("facility_id", "channel", "scenario", "year", "nace_code", "energy_bucket",
                       "geolocation", "flood_category", "model_version", "reference_transition",
                       "shock_transition", "reference_loss_rates", "shock_loss_rates",
                       "insurance_recovery"), "climate")
        if row["channel"] not in ("transition", "flood") or row["scenario"] != "adverse":
            raise BlockingError("climate", "INVALID_INPUT", "climate requires transition/flood on adverse macro stress")
        for name in ("nace_code", "energy_bucket", "geolocation", "flood_category", "model_version"):
            if not isinstance(row[name], str) or not row[name].strip():
                raise BlockingError("climate", "MISSING_INPUT", f"missing {name}")
        groups.setdefault((row["facility_id"], row["channel"], row["scenario"]), []).append(row)
    for (fid, channel, scenario), group in sorted(groups.items()):
        years = [r["year"] for r in group]
        expected = [2027] if channel == "flood" else [2027, 2028, 2029]
        if sorted(years) != expected:
            raise BlockingError("climate", "INVALID_HORIZON", f"{channel} requires years {expected} once")
        if fid not in port.index:
            raise BlockingError("climate", "MISSING_INPUT", "climate facility not in accepted portfolio")
        facility = port.loc[fid]
        if facility.accounting_category != "AC" or facility.gca <= 0:
            raise BlockingError("climate", "INVALID_SCOPE", "climate requires on-balance AC exposure")
        if (facility["product"] != "mortgage"
                and facility.get("counterparty_sector") != "non_financial_corporations"):
            raise BlockingError("climate", "INVALID_SCOPE", "climate requires NFC or house purchase exposure")
        state = np.eye(3)[int(facility.stage)-1] * facility.gca
        states = {leg: state.copy() for leg in ("reference", "shock")}
        cohorts = {leg: [(state[2], float(facility.opening_allowance_on))] if state[2] else []
                   for leg in states}
        previous_increment = 0.
        for row in sorted(group, key=lambda r: r["year"]):
            totals = {}
            for leg, incoming in states.items():
                try:
                    matrix = np.asarray(row[leg+"_transition"], dtype=float)
                    rates = np.asarray(row[leg+"_loss_rates"], dtype=float)
                except (ValueError, TypeError) as exc:
                    raise BlockingError("climate", "INVALID_INPUT", "non-numeric climate model output") from exc
                if (matrix.shape != (3, 3) or rates.shape != (3,) or not np.isfinite(matrix).all()
                        or not np.isfinite(rates).all() or (matrix < 0).any() or (matrix > 1).any()
                        or (rates < 0).any() or (rates > 1).any()
                        or not np.allclose(matrix.sum(axis=1), 1, rtol=0, atol=1e-10)
                        or not np.array_equal(matrix[2], [0., 0., 1.])):
                    raise BlockingError("climate", "INVALID_MATRIX", "invalid transition/loss-rate bundle")
                new_default = float(incoming[:2] @ matrix[:2, 2])
                states[leg] = incoming @ matrix
                # Each default cohort carries its own previous allowance floor, including original S3.
                cohorts[leg].append((new_default, new_default*rates[2]))
                cohorts[leg] = [(gca, max(floor, gca*rates[2])) for gca, floor in cohorts[leg]]
                totals[leg] = float(states[leg][:2] @ rates[:2] + sum(a for _, a in cohorts[leg]))
            incremental = totals["shock"] - totals["reference"]
            insurance = number(row["insurance_recovery"], "insurance_recovery", 0)
            if insurance > max(0., incremental) + 1e-10:
                raise BlockingError("climate", "INVALID_INPUT", "insurance exceeds incremental provision")
            after_insurance = incremental-insurance
            out.append({k: row[k] for k in ("facility_id", "channel", "scenario", "year", "nace_code",
                                           "energy_bucket", "geolocation", "flood_category", "model_version")}
                       | {"gca": float(facility.gca), "reference_provision": totals["reference"],
                          "shock_provision": totals["shock"], "incremental_before_insurance": incremental,
                          "insurance_recovery": insurance, "incremental_after_insurance": after_insurance,
                          "incremental_charge_after_insurance": after_insurance-previous_increment,
                          "basis": "SYNTHETIC_EXTERNAL_CLIMATE_MODEL"})
            previous_increment = after_insurance
    result = pd.DataFrame(out)
    if (result.groupby(["channel", "scenario", "year"])["incremental_after_insurance"].sum() < -1e-8).any():
        raise BlockingError("climate", "INVALID_INPUT", "climate cannot offset the aggregate macro stress")
    return result
