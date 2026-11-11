"""The off-balance provision of a new S3 cohort (A9): booked once, in the entry year, as
undrawn flow x CCF x LGD of the default year, then floored like the drawn part (ECL-11, EAD-08)."""

import numpy as np
import pytest

from stress.contracts.tables import METHOD_S3_NEW_BOOKING, METHOD_S3_NEW_FLOOR
from tests import builders

COHORT = ["scenario", "facility_id", "slice"]


@pytest.mark.req("ECL-11", "EAD-08")
def test_a_new_s3_cohort_books_its_undrawn_part_once_and_never_releases_it(core_run, full_tables):
    ctx, _ = core_run
    prov = builders.result(ctx, "provisions.parquet")
    slices = builders.result(ctx, "slices.parquet")[[*COHORT, "year", "undrawn", "entry_year"]]
    lgd = builders.result(ctx, "lgd_of_year.parquet")[["scenario", "year", "facility_id", "lgd"]]
    # The core variant overrides no CCF, so each commitment's own accounting CCF applies (A25).
    ccf = full_tables["commitments"].set_index("facility_id")["accounting_ccf"]
    rows = prov[prov["method"].isin([METHOD_S3_NEW_BOOKING, METHOD_S3_NEW_FLOOR])]
    rows = rows.merge(slices, on=[*COHORT, "year"]).merge(lgd, on=["scenario", "year", "facility_id"])
    assert len(rows) == prov["method"].isin([METHOD_S3_NEW_BOOKING, METHOD_S3_NEW_FLOOR]).sum()
    rows["raw"] = (rows["undrawn"] * rows["facility_id"].map(ccf) * rows["lgd"]).where(rows["undrawn"] > 0, 0.0)

    booked = rows[rows["method"] == METHOD_S3_NEW_BOOKING]
    assert (booked["year"] == booked["entry_year"]).all() and not booked.duplicated(COHORT).any(), (
        "one booking per cohort, in its entry year")
    committed = booked[booked["undrawn"] > 0]
    assert set(committed["scenario"]) == {"baseline", "adverse"}, "the case needs defaulted undrawn amounts"
    assert np.allclose(booked["provision_off"], booked["raw"], rtol=1e-12, atol=0), (
        "undrawn flow x CCF x LGD of the default year")
    assert (committed["provision_off"] > 0).all()

    # Afterwards the cohort is re-measured at each year's LGD and never falls below what it carried.
    later = rows[rows["method"] == METHOD_S3_NEW_FLOOR]
    carried = prov.assign(year=prov["year"] + 1).set_index([*COHORT, "year"])["provision_off"]
    prior = carried.reindex(list(zip(*(later[c] for c in [*COHORT, "year"])))).to_numpy()
    assert len(later) and not np.isnan(prior).any(), "every later year follows a year that carried the cohort"
    assert np.allclose(later["provision_off"], np.maximum(later["raw"], prior), rtol=1e-12, atol=0)
    assert (prior > later["raw"]).any(), "the floor has to bind somewhere, or it is not tested"
    assert (later["raw"] > prior).any(), "and somewhere the provision has to rise above it"
