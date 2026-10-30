"""Independent identities for the optional synthetic bridges."""

import pandas as pd
import pytest

from stress.capital.assessment import capital_bridge
from stress.contracts.errors import BlockingError
from stress.ecl.climate import climate_assessment
from stress.report.assessment import mapped_cells
from tests.support import oracle


@pytest.mark.req("CAP-03", "CAP-04")
def test_capital_bridge_floors_and_explicit_missing_inputs():
    amount = oracle("AT-34")["input"]["drawn"]
    slices = pd.DataFrame([{"scenario": "adverse", "year": y, "facility_id": "F", "grade": "G1",
                               "gca": amount, "undrawn": amount} for y in (2026, 2027)])
    port = pd.DataFrame([{"facility_id": "F", "regulatory_approach": "IRB", "regulatory_class": "corporate"}])
    charges = pd.DataFrame([{"scenario": "adverse", "year": 2027, "charge_on": amount/10, "charge_off": 0.}])
    weights = [{"scenario": "adverse", "year": y, "regulatory_approach": "IRB", "regulatory_class": "corporate",
                    "grade": "G1", "regulatory_ccf": 0., "standardised_ccf": 1.,
                    "risk_weight": .5, "standardised_risk_weight": 1., "model_version": "test"}
               for y in (2026, 2027)]
    bridge = {"scenario": "adverse", "year": 2027, "opening_cet1": amount, "other_pnl": 0., "tax_rate": 0.,
                  "distributions": 0., "irb_shortfall_change": 0., "npl_deduction_change": 0.,
                  "other_cet1_change": 0., "other_utrea": 0., "other_strea": 0., "output_floor_factor": 1.}
    result, detail = capital_bridge({"weights": weights, "bridge": [bridge]}, slices, port, charges)
    assert result.iloc[0].cet1 == amount - amount/10
    assert result.iloc[0].total_rea == 2*amount
    assert result.iloc[0].cet1_ratio == pytest.approx(.45)
    assert detail.regulatory_ead.eq(amount).all()
    assert detail.standardised_ead.eq(2*amount).all()
    with pytest.raises(BlockingError):
        capital_bridge({"weights": [{k: v for k, v in w.items() if k != "regulatory_ccf"}
                                     for w in weights], "bridge": [bridge]}, slices, port, charges)


@pytest.mark.req("ECL-11")
def test_climate_separate_flood_window_and_insurance_bridge():
    amount = oracle("AT-34")["input"]["drawn"]
    port = pd.DataFrame([{"facility_id": "F", "accounting_category": "AC", "product": "mortgage",
                             "gca": amount, "stage": 1, "opening_allowance_on": 0.}])
    identity = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
    row = {"facility_id": "F", "channel": "flood", "scenario": "adverse", "year": 2027,
               "nace_code": "NA_household", "energy_bucket": "D", "geolocation": "synthetic-DE",
               "flood_category": "high", "model_version": "test", "reference_transition": identity,
               "shock_transition": identity, "reference_loss_rates": [0., .2, .5],
               "shock_loss_rates": [.1, .2, .5], "insurance_recovery": 0.}
    result = climate_assessment([row], port)
    assert result.iloc[0].incremental_before_insurance == amount*.1
    assert result.iloc[0].incremental_after_insurance == amount*.1
    with pytest.raises(BlockingError):
        climate_assessment([{**row, "year": 2028}], port)
    with pytest.raises(BlockingError):
        climate_assessment([{**row, "insurance_recovery": amount}], port)
    with pytest.raises(BlockingError):
        climate_assessment([{**row, "scenario": "baseline"}], port)
    with pytest.raises(BlockingError):
        climate_assessment([{**row, "reference_loss_rates": [.2, .2, .5]}], port)


@pytest.mark.req("RPT-05")
def test_mapping_blocks_duplicates_empty_selections_and_unknown_fields():
    table = pd.DataFrame([{"scenario": "adverse", "year": 2027, "gca": 1.}])
    cell = {"sheet": "demo", "row": "r1", "column": "c1", "table": "dimensions", "measure": "gca",
                "filters": {"scenario": "adverse", "year": 2027}}
    spec = {"version": "test", "cells": [cell]}
    assert mapped_cells(spec, {"dimensions": table}).iloc[0].value == 1.
    for cells in ([cell, cell], [{**cell, "filters": {"year": 2050}}],
                  [{**cell, "measure": "not_a_column"}]):
        with pytest.raises(BlockingError):
            mapped_cells({**spec, "cells": cells}, {"dimensions": table})
