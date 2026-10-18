"""Qualitative SICR triggers (MIG-05; owner decision of 18 October 2026, assumption A30): 30+
days past due, watchlist and forbearance each make a performing facility S2 whatever its grade,
and a flag holds the facility in S2 until it defaults (option (a))."""

import numpy as np
import pytest

from stress.params import ttc_arrays
from stress.validate.sicr import TtcLifetime, qualitative_trigger
from tests import builders


def _settings(full_tables) -> dict:
    return dict(full_tables["parameter_set"]["sicr_triggers"])


@pytest.mark.req("MIG-05")
def test_each_trigger_alone(full_tables):
    settings = _settings(full_tables)
    days = int(settings["dpd_days"])
    dpd = np.array([0, days - 1, days, 0, 0])
    watchlist = np.array([False, False, False, True, False])
    forborne = np.array([False, False, False, False, True])
    assert qualitative_trigger(dpd, watchlist, forborne, settings).tolist() == [
        False, False, True, True, True]


@pytest.mark.req("MIG-05")
def test_a_switched_off_trigger_is_ignored(full_tables):
    settings = _settings(full_tables) | {"enabled": ["dpd"]}
    days = int(settings["dpd_days"])
    flags = qualitative_trigger(np.array([days, 0, 0]), np.array([False, True, False]),
                                np.array([False, False, True]), settings)
    assert flags.tolist() == [True, False, False]


@pytest.mark.req("MIG-05")
def test_a_flag_holds_the_facility_in_s2_until_default(core_run, full_tables):
    ctx, _ = core_run
    fac = full_tables["facilities"]
    flagged = fac.loc[qualitative_trigger(fac["dpd"], fac["watchlist"], fac["forborne"], _settings(full_tables))
                      & (fac["ifrs_stage"] < 3), "facility_id"]
    assert len(flagged) > 0
    slices = builders.result(ctx, "slices.parquet")
    held = slices[slices["facility_id"].isin(set(flagged))]
    assert (held.loc[held["grade"] != "D", "stage"] == 2).all(), "a flagged facility never returns to S1"
    assert (held["stage"] == 3).any(), "a flagged facility still defaults"
    # The flag, not the grade, sets the stage: some flagged slices sit above the SICR line.
    matrices, grades = ttc_arrays(full_tables["ttc_pd_matrix"])
    rank = {g: i for i, g in enumerate(grades)}
    k = {s: p["sicr_k"] for s, p in full_tables["parameter_set"]["segments"].items()}
    life = TtcLifetime(matrices)
    facts = fac.set_index("facility_id")
    above = 0
    for row in held[held["grade"] != "D"].drop_duplicates(["facility_id", "grade"]).itertuples(index=False):
        f = facts.loc[row.facility_id]
        pd_life = life.pd(f["segment"], float(f["residual_maturity"]))
        above += pd_life[rank[row.grade]] < k[f["segment"]] * pd_life[rank[f["origination_grade"]]]
    assert above > 0
