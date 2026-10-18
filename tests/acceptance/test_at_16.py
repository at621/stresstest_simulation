"""AT-16: property price shocks compound into an index (SCN-05)."""

import pytest

from stress.scenario.kernels import compound_index
from tests.support import assert_close, oracle, spec_yaml, within


@pytest.mark.at("AT-16")
def test_terminal_index_compounds():
    case = oracle("AT-16")
    i = case["input"]
    levels = compound_index(i["annual_changes"], i["initial_index"])
    assert_close(levels[-1], case["expected"]["terminal_index"], case["tolerance"], "index")
    added = i["initial_index"] * (1 + sum(i["annual_changes"]))
    assert not within(added, case["expected"]["terminal_index"], case["tolerance"]), (
        case["wrong_answers"][0]["why"])
    # SCN-05 states every adverse index level, residential and CRE, not only the last one.
    scenarios = spec_yaml("scenarios.yaml")
    expected = scenarios["expected_indices"]["adverse"]
    for change_var, index_var in scenarios["index_of"].items():
        path = scenarios["paths"]["adverse"][change_var]
        start = scenarios["starting_values"][index_var]["value"]
        got = compound_index([path[y] / 100 for y in sorted(path)], start)
        for level, year in zip(got, sorted(path)):
            assert_close(level, expected[index_var][year], case["tolerance"], f"{index_var} {year}")
