"""R9: the allowance bridge ignores float rounding and still catches a real break."""

import pandas as pd
import pytest

from stress import accounting
from stress.contracts.errors import Block, BlockingError
from tests.support import tolerance

# Adjacent floats near this closing amount are 1.9e-9 apart, so the charge rounds on the way back.
OPENING, CLOSING = 886049.29, 11828376.6
FACILITY = "F1"


def _slices(allowance: float) -> pd.DataFrame:
    return pd.DataFrame({"facility_id": [FACILITY], "slice": ["G5"], "stage": [2],
                         "allowance_on": [allowance], "provision_off": [0.0]})


def _bridge() -> pd.DataFrame:
    portfolio = pd.DataFrame({"facility_id": [FACILITY], "overlay_amount": [0.0]})
    return accounting.stock_to_flow(_slices(OPENING), _slices(CLOSING), portfolio, "adverse", 2027,
                                    tolerance("aggregate"))


@pytest.mark.req("ACC-01")
def test_float_rounding_does_not_block_a_correct_run():
    assert abs(OPENING + (CLOSING - OPENING) - CLOSING) > 0, "the pair must round"
    assert _bridge()["charge_on"].iloc[0] == CLOSING - OPENING


@pytest.mark.req("ACC-02")
def test_a_movement_outside_the_charge_still_blocks(monkeypatch):
    gap = 2 * tolerance("aggregate")["abs"]
    monkeypatch.setattr(accounting, "charge", lambda opening, closing: closing - opening + gap)
    with pytest.raises(BlockingError) as caught:
        _bridge()
    assert caught.value.code == Block.NOT_PERMITTED_MOVEMENT
