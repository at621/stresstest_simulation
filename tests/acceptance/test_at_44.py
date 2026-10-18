"""AT-44: the static books hold in every projected year (EXP-01, EAD-05, REG-02)."""

import pytest

from tests import builders
from tests.support import assert_close, eur, oracle


@pytest.mark.at("AT-44")
def test_static_books_each_year(core_run, full_tables):
    case = oracle("AT-44")
    e = case["expected"]
    tol = case["tolerance"]
    ctx, _ = core_run
    slices = builders.result(ctx, "slices.parquet")
    fac = full_tables["facilities"][["facility_id", "portfolio"]]
    ccf = full_tables["commitments"].set_index("facility_id")["accounting_ccf"]
    slices = slices.merge(fac, on="facility_id")
    slices["converted"] = slices["undrawn"] * slices["facility_id"].map(ccf).fillna(0.0)
    years = sorted(slices["year"].unique())
    assert len(years) == 4  # the opening year and the three projected years
    for (scenario, year), part in slices.groupby(["scenario", "year"]):
        where = f"{scenario} {year}"
        assert_close(part["gca"].sum(), eur(e["gca_m"]), tol, f"GCA {where}")
        assert_close(part["undrawn"].sum(), eur(e["undrawn_m"]), tol, f"undrawn {where}")
        assert_close(part["converted"].sum(), eur(e["converted_commitments_m"]), tol, f"converted {where}")
        assert_close(part["gca"].sum() + part["converted"].sum(), eur(e["total_m"]), tol, f"total {where}")
        for book in ("P03", "P05"):
            b = part[part["portfolio"] == book]
            assert_close(b["gca"].sum() + b["converted"].sum(), eur(e[f"{book}_total_m"]), tol, f"{book} {where}")
