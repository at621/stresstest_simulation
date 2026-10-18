"""AT-41: an end-2029 S1 valuation without its 2030 or terminal input blocks; nothing is set
to zero (ECL-03, ECL-10, PD-02)."""

import pandas as pd
import pytest

from stress.contracts.errors import Block, BlockingError
from stress.contracts.tables import Parameters
from stress.ecl import terminal_s1
from tests import builders
from tests.support import oracle


@pytest.mark.at("AT-41")
def test_missing_terminal_input_blocks(mini, tmp_path):
    case = oracle("AT-41")
    year = case["input"]["valuation_year"]
    # 1. Z is not extended past the valuation year: the 2030 bucket has no parameters.
    mini["parameter_set"]["horizon"]["last_bucket_year"] = year
    ctx, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "BLOCKED"
    assert manifest["blocked"]["code"] == Block.MISSING_TERMINAL_INPUT
    assert not (ctx.results_dir / "provisions.parquet").exists(), "no provision may be written"
    # 2. The interpolation of AT-06 needs the baseline end-of-horizon parameters.
    empty = Parameters(pit=pd.DataFrame(), facility=pd.DataFrame(),
                       pd_curves=pd.DataFrame({"scenario": pd.Series(dtype=str)}),
                       lgd_of_year=pd.DataFrame())
    z = pd.DataFrame({"segment": ["P01"], "country": ["NL"], "scenario": ["adverse"],
                      "year": [year + 1], "adverse_weight": [oracle(case["expected"]["terminal_case"])
                                                             ["expected"]["weights"]["adverse"]]})
    portfolio = pd.DataFrame({"facility_id": ["F1"], "route": ["performing"], "segment": ["P01"],
                              "country": ["NL"]})
    with pytest.raises(BlockingError) as err:
        terminal_s1(empty, z, portfolio, "adverse", year, ("G1",), {"buckets": [1], "last_fraction": [1.0]})
    assert err.value.code == Block.MISSING_TERMINAL_INPUT
