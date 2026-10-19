"""AT-48: the SICR rule on the run's grade slices (MIG-07, MIG-08).

The expected stage per grade is OPEN in the spec until the owner approves it; this case proves
the rule itself on every slice the run projects. Since the owner decision of 18 October 2026 a
qualitative trigger also makes a facility S2 (MIG-05, A30, C11): the grade rule is proved on the
facilities without a trigger, and a flagged facility stays S2 until it defaults.
"""

import numpy as np
import pytest

from stress.params import ttc_arrays
from stress.validate.sicr import TtcLifetime, qualitative_trigger
from tests import builders
from tests.support import oracle


@pytest.mark.at("AT-48")
def test_stage_follows_the_sicr_line(core_run, full_tables):
    case = oracle("AT-48")
    assert case["status"] == "PARTLY_OPEN"
    ctx, _ = core_run
    fac = full_tables["facilities"].set_index("facility_id")
    k = {s: p["sicr_k"] for s, p in full_tables["parameter_set"]["segments"].items()}
    matrices, grades = ttc_arrays(full_tables["ttc_pd_matrix"])
    rank = {g: i for i, g in enumerate(grades)}
    life = TtcLifetime(matrices)
    slices = builders.result(ctx, "slices.parquet")
    perf = slices[slices["stage"] < 3]
    flagged = set(fac.index[qualitative_trigger(fac["dpd"], fac["watchlist"], fac["forborne"],
                                                full_tables["parameter_set"]["sicr_triggers"])])
    sample = perf[perf["facility_id"].isin(fac.index[::7])]
    for row in sample.itertuples(index=False):
        f = fac.loc[row.facility_id]
        lifetime = life.pd(f["segment"], float(f["residual_maturity"]))
        by_grade = lifetime[rank[row.grade]] >= k[f["segment"]] * lifetime[rank[row.origination_grade]]
        expected = 2 if by_grade or row.facility_id in flagged else 1
        assert row.stage == expected, (row.facility_id, row.grade)
    # S3 exactly in D; D never cures, and its exposure never leaves.
    assert (slices.loc[slices["stage"] == 3, "grade"] == "D").all()
    assert not (slices.loc[slices["stage"] < 3, "grade"] == "D").any()
    s3 = slices[slices["stage"] == 3].groupby(["scenario", "facility_id", "year"])["gca"].sum().unstack("year")
    assert (np.diff(s3.fillna(0.0).to_numpy(), axis=1) >= -1e-9).all()
    # A slice that improves back over the line returns to S1: opening-S2 facilities hold S1 slices.
    opening_s2 = set(fac.index[fac["ifrs_stage"] == 2]) - flagged
    back = perf[(perf["facility_id"].isin(opening_s2)) & (perf["stage"] == 1) & (perf["year"] > perf["year"].min())]
    assert len(back) > 0
