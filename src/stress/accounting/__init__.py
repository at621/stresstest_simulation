"""R9 stock to flow: charge = closing − opening allowance, on- and off-balance separately.
FX movement fixed at zero; overlays tracked by risk and year.

ACC-01–ACC-04.
"""

import logging

import numpy as np
import pandas as pd

from stress.accounting.kernels import FX_MOVEMENT, charge
from stress.contracts.errors import Block, BlockingError
from stress.contracts.tables import CHARGES

STEP = "R9"
LOG = logging.getLogger("stress.R9")
RELEASE_EPS = 1e-9  # EUR


def stock_to_flow(opening: pd.DataFrame, closing: pd.DataFrame, portfolio: pd.DataFrame,
                  scenario: str, year: int) -> pd.DataFrame:
    """Charges per facility from the slices at the previous and this year-end.

    The only movement in the bridge is the charge: no write-offs, transfers or sales are
    permitted in the static projection, FX is zero (EUR only) and the opening overlays are
    carried unchanged, so no overlay is counted twice (ACC-02, ACC-04).
    """
    no_release(opening, closing, year)
    before = opening.groupby("facility_id")[["allowance_on", "provision_off"]].sum()
    after = closing.groupby("facility_id")[["allowance_on", "provision_off"]].sum()
    ids = portfolio["facility_id"]
    before = before.reindex(ids).fillna(0.0)
    after = after.reindex(ids).fillna(0.0)
    overlay = portfolio.set_index("facility_id")["overlay_amount"].reindex(ids).fillna(0.0)
    out = pd.DataFrame({
        "scenario": scenario, "year": year, "facility_id": ids.to_numpy(),
        "opening_on": before["allowance_on"].to_numpy(),
        "closing_on": after["allowance_on"].to_numpy(),
        "opening_off": before["provision_off"].to_numpy(),
        "closing_off": after["provision_off"].to_numpy(),
        "overlay_opening": overlay.to_numpy(), "overlay_closing": overlay.to_numpy(),
        "fx_movement": FX_MOVEMENT, "other_movement": 0.0,
    })
    out["charge_on"] = charge(out["opening_on"], out["closing_on"])
    out["charge_off"] = charge(out["opening_off"], out["closing_off"])
    LOG.info("%s %d: charge EUR %.1fm on-balance, %.1fm off-balance; FX movement zero; "
             "no S3 slice released provision", scenario, year, out["charge_on"].sum() / 1_000_000,
             out["charge_off"].sum() / 1_000_000)
    bridge = (out["opening_on"] + out["charge_on"] + out["fx_movement"] + out["other_movement"]
              - out["closing_on"])
    if (bridge.abs() > RELEASE_EPS).any():
        raise BlockingError(STEP, Block.NOT_PERMITTED_MOVEMENT, "allowance bridge does not close")
    return CHARGES.check(out, STEP).sort_values(list(CHARGES.key)).reset_index(drop=True)


def no_release(opening: pd.DataFrame, closing: pd.DataFrame, year: int) -> None:
    """REG-05 and AT-18: no S3 exposure or cohort releases provision, checked per slice."""
    prev = opening[opening["stage"] == 3].set_index(["facility_id", "slice"])
    curr = closing[closing["stage"] == 3].set_index(["facility_id", "slice"])
    joined = prev[["allowance_on", "provision_off"]].join(
        curr[["allowance_on", "provision_off"]], rsuffix="_now", how="left")
    if joined[["allowance_on_now", "provision_off_now"]].isna().any().any():
        raise BlockingError(STEP, Block.NOT_PERMITTED_MOVEMENT,
                            f"an S3 slice disappeared in {year}: no cure, sale or write-off removal")
    drop = np.maximum(joined["allowance_on"] - joined["allowance_on_now"],
                      joined["provision_off"] - joined["provision_off_now"])
    if (drop > RELEASE_EPS).any():
        key = drop.idxmax()
        raise BlockingError(STEP, Block.S3_RELEASE, f"S3 slice {key} releases provision in {year}")
