"""AT-34: drawn/undrawn EAD and the on/off-balance ECL split (EAD-02, EAD-08)."""

import pytest

from stress.ecl.kernels import ecl_split
from stress.params.ead import ead
from tests import builders
from tests.support import assert_close, oracle


@pytest.mark.at("AT-34")
def test_ead_and_ecl_split(reference_runs):
    case = oracle("AT-34")
    i, e = case["input"], case["expected"]
    result = ead(i["drawn"], i["undrawn"], i["ccf"])
    assert_close(result.drawn, e["ead_drawn"], case["tolerance"], "drawn")
    assert_close(result.undrawn, e["ead_undrawn"], case["tolerance"], "undrawn")
    assert_close(result.total, e["ead_total"], case["tolerance"], "total")
    on, off = ecl_split([i["pd"]], [result.drawn], [result.undrawn], [i["lgd"]],
                        [i["discount_factor"]])
    assert_close(on, e["ecl_on"], case["tolerance"], "on-balance")
    assert_close(off, e["ecl_off"], case["tolerance"], "off-balance")
    assert_close(on + off, e["ecl_total"], case["tolerance"], "total ECL")
    # The same case through the whole pipeline: R6 splits the EAD, R8 the provision.
    ctx, _ = reference_runs["core"]
    fid = reference_runs["ids"]["AT-34"]
    params = builders.result(ctx, "parameters.parquet")
    start = int(params["valuation_year"].min())
    first = params[(params["facility_id"] == fid) & (params["valuation_year"] == start)
                   & (params["default_bucket"] == 1)]
    assert len(first) == 2  # baseline and adverse
    for row in first.itertuples(index=False):
        assert_close(row.ead_drawn, e["ead_drawn"], case["tolerance"], "run drawn")
        assert_close(row.ead_undrawn, e["ead_undrawn"], case["tolerance"], "run undrawn")
        assert_close(row.ead_total, e["ead_total"], case["tolerance"], "run total")
    prov = builders.result(ctx, "provisions.parquet")
    mine = prov[(prov["facility_id"] == fid) & (prov["year"] == start)]
    assert len(mine) == 2
    for row in mine.itertuples(index=False):
        assert_close(row.allowance_on, e["ecl_on"], case["tolerance"], "run on-balance")
        assert_close(row.provision_off, e["ecl_off"], case["tolerance"], "run off-balance")
        assert_close(row.allowance_on + row.provision_off, e["ecl_total"], case["tolerance"], "run total ECL")
