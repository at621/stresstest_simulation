"""Explicit business-volume assumptions before credit migration.

EXP-01, MIG-02, ACC-01. Dynamic mode relaxes only the static performing-volume constraint.
Defaulted cohorts retain their balances and floors. No fresh origination, sale or write-off
is inferred from a volume percentage; those require distinct accounting/vintage inputs.
"""

import itertools

import numpy as np

from stress.contracts.specification import invalid, mapping, number, text
from stress.contracts.tables import EXPOSURE_MOVEMENTS


def validate_assumptions(specification, mode, portfolio, scenarios, years):
    block = specification.get("balance_sheet", {})
    mapping(block, {"assumptions"}, "balance_sheet")
    if mode == "static":
        if block:
            invalid("balance-sheet assumptions require run.balance_sheet=dynamic")
        return {}
    rows = block.get("assumptions")
    if not isinstance(rows, list) or not rows:
        invalid("dynamic mode requires complete annual balance-sheet assumptions")
    expected = set(itertools.product(scenarios, years, sorted(portfolio.portfolio.unique())))
    result = {}
    fields = {"scenario", "year", "portfolio", "drawn_change", "undrawn_change"}
    for row in rows:
        mapping(row, fields, "volume assumption", fields)
        text(row["scenario"], "volume scenario")
        text(row["portfolio"], "volume portfolio")
        if type(row["year"]) is not int:
            invalid("volume year must be an integer")
        key = (row["scenario"], row["year"], row["portfolio"])
        if key in result:
            invalid(f"duplicate volume assumption {key}")
        result[key] = (number(row["drawn_change"], "drawn change", -1),
                       number(row["undrawn_change"], "undrawn change", -1))
    if set(result) != expected:
        invalid(f"volume coverage: missing {sorted(expected - set(result))[:5]}, "
                f"unexpected {sorted(set(result) - expected)[:5]}")
    return result


def adjust_performing(previous, portfolio, assumptions, scenario, year):
    """Scale performing balances and carried S2 provision in proportion to business volume.

R9 compares the real previous closing provision to the new closing provision, so the ECL
change from volume is included in the charge exactly once. S3 is never scaled.
"""
    out = previous.copy()
    labels = portfolio.set_index("facility_id")["portfolio"]
    keys = out.facility_id.map(labels)
    if keys.isna().any():
        invalid("volume bridge refers to an unknown facility")
    rates = {port: assumptions[(scenario, year, port)] for port in keys.unique()}
    performing = out.stage.lt(3)
    for col, allowance, position in (("gca", "allowance_on", 0), ("undrawn", "provision_off", 1)):
        factor = keys.map(lambda port, position=position: 1.0 + rates[port][position]).where(performing, 1.0)
        out[col] *= factor
        out[allowance] *= factor
        if not np.isfinite(out[[col, allowance]].to_numpy(dtype=float)).all():
            invalid("volume adjustment produced non-finite balances or provisions")
    group = ["facility_id", "stage"]
    before = previous.groupby(group)[["gca", "undrawn"]].sum().add_prefix("opening_")
    after = out.groupby(group)[["gca", "undrawn"]].sum().add_prefix("migration_")
    movement = before.join(after).reset_index()
    movement["gca_change"] = movement.migration_gca - movement.opening_gca
    movement["undrawn_change"] = movement.migration_undrawn - movement.opening_undrawn
    movement["portfolio"] = movement.facility_id.map(labels)
    movement["scenario"] = scenario
    movement["year"] = year
    for col in ("opening_gca", "migration_gca", "gca_change",
                "opening_undrawn", "migration_undrawn", "undrawn_change"):
        movement[col] = movement[col].astype(float)
    return out, EXPOSURE_MOVEMENTS.check(movement, "R7")
