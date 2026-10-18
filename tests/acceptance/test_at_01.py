"""AT-01: the synthetic input set hits the section 5 portfolio targets."""

import pytest

from tests.support import assert_close, eur, oracle, spec_yaml


@pytest.mark.at("AT-01")
def test_portfolio_targets(full_tables):
    case = oracle("AT-01")
    e = case["expected"]
    fac = full_tables["facilities"]
    com = full_tables["commitments"]
    obl = full_tables["obligors"]
    tol = case["tolerance"]
    assert len(fac) == e["facilities"]
    assert_close(fac["gca"].sum(), eur(e["gca_m"]), tol, "GCA")
    assert_close(com["nominal_undrawn"].sum(), eur(e["undrawn_m"]), tol, "undrawn")
    converted = fac["gca"].sum() + (com["nominal_undrawn"] * com["accounting_ccf"]).sum()
    assert_close(converted, eur(e["converted_total_m"]), tol, "converted total")

    targets = spec_yaml("targets.yaml")
    joined = fac.merge(obl, on="obligor_id")
    undrawn = com.merge(fac[["facility_id", "portfolio"]], on="facility_id")
    for portfolio, t in targets["portfolios"].items():
        book = joined[joined["portfolio"] == portfolio]
        assert len(book) == t["facilities"], portfolio
        total = book["gca"].sum()
        assert_close(total, eur(t["gca"]), tol, f"{portfolio} GCA")
        assert_close(undrawn.loc[undrawn["portfolio"] == portfolio, "nominal_undrawn"].sum(),
                     eur(t["undrawn"]), tol, f"{portfolio} undrawn")
        stages = targets["stages"][portfolio]
        for stage in (1, 2, 3):
            part = book[book["ifrs_stage"] == stage]
            assert len(part) == stages["count"][stage], (portfolio, stage)
            assert_close(part["gca"].sum(), eur(stages["gca"][stage]), tol, f"{portfolio} S{stage}")
        for country, share in targets["countries"].items():
            assert_close(book.loc[book["country"] == country, "gca"].sum(), share * total, tol,
                         f"{portfolio} {country}")
        irb = book.loc[book["regulatory_approach"] == "IRB", "gca"].sum()
        assert_close(irb, targets["irb_share"][portfolio] * total, tol, f"{portfolio} IRB")
        for section, share in targets["sectors"].get(portfolio, {}).items():
            if len(targets["sectors"][portfolio]) > 1:
                assert_close(book.loc[book["nace_code"] == section, "gca"].sum(), share * total, tol,
                             f"{portfolio} NACE {section}")
    p06 = joined[joined["portfolio"] == "P06"]
    for sector, share in targets["p06_counterparties"].items():
        assert_close(p06.loc[p06["counterparty_sector"] == sector, "gca"].sum(),
                     share * p06["gca"].sum(), tol, f"P06 {sector}")
    # SYN-04: the ten largest connected groups hold the target share, without double counting.
    top = targets["concentration_top_groups"]
    assert not fac["facility_id"].duplicated().any()
    for portfolio, share in top["share_of_gca"].items():
        book = joined[joined["portfolio"] == portfolio]
        groups = book.groupby("group_id")["gca"].sum().sort_values(ascending=False)
        assert_close(groups.head(top["groups"]).sum(), share * book["gca"].sum(), tol, f"{portfolio} top groups")
