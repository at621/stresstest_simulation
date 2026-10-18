"""AT-21: every monetary item is EUR and FX movements are zero (SCP-06, ACC-02)."""

import pytest

from tests import builders
from tests.support import oracle


@pytest.mark.at("AT-21")
def test_currency_scope(full_tables, core_run):
    case = oracle("AT-21")
    currency = case["expected"]["currency"]
    for name in ("facilities", "commitments", "opening_provisions"):
        assert set(full_tables[name]["currency"]) == {currency}, name
    # Scenarios carry rates and indices only: no exchange-rate variable and no FX unit.
    variables = {v["id"] for v in full_tables["scenarios"]["variables"]}
    assert not any("fx" in v or "exchange" in v for v in variables)
    ctx, _ = core_run
    charges = builders.result(ctx, "charges.parquet")
    assert (charges["fx_movement"] == case["expected"]["fx_movement"]).all()
    start = builders.report(ctx, "starting_point_reconciliation.csv")
    assert set(start["currency_check"].dropna()) == {"EUR only"}
