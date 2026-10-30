"""AT-07: the impairment charge is the change in the allowance stock (ACC-01)."""

import pytest

from stress.accounting.kernels import charge
from tests import builders
from tests.support import assert_close, oracle, within


@pytest.mark.at("AT-07")
def test_charge_is_closing_minus_opening(reference_runs, core_run):
    case = oracle("AT-07")
    value = float(charge(case["input"]["opening"], case["input"]["closing"]))
    assert_close(value, case["expected"]["charge"], case["tolerance"], "charge")
    for wrong in case["wrong_answers"]:
        assert not within(value, wrong["value"], case["tolerance"]), wrong["why"]
    # The same case through the whole pipeline: R8 raises the stock, R9 charges the change.
    ctx, _ = reference_runs["core"]
    charges = builders.result(ctx, "charges.parquet")
    mine = charges[(charges["facility_id"] == reference_runs["ids"]["AT-07"])
                   & (charges["year"] == charges["year"].min())]
    assert len(mine) == 2  # baseline and adverse
    for row in mine.itertuples(index=False):
        assert_close(row.opening_on, case["input"]["opening"], case["tolerance"], "run opening")
        assert_close(row.closing_on, case["input"]["closing"], case["tolerance"], "run closing")
        assert_close(row.charge_on, case["expected"]["charge"], case["tolerance"], "run charge")
        for wrong in case["wrong_answers"]:
            assert not within(row.charge_on, wrong["value"], case["tolerance"]), wrong["why"]
    # On the real book, three years of charges add up to the change in the stock.
    real, _ = core_run
    charges = builders.result(real, "charges.parquet")
    total = (charges["charge_on"] + charges["charge_off"]).groupby(charges["scenario"]).sum()
    slices = builders.result(real, "slices.parquet")
    stock = (slices["allowance_on"] + slices["provision_off"]).groupby([slices["scenario"], slices["year"]]).sum()
    assert set(total.index) == {"baseline", "adverse"}
    for scenario, value in total.items():
        assert_close(value, stock[scenario].iloc[-1] - stock[scenario].iloc[0], case["tolerance"], scenario)
