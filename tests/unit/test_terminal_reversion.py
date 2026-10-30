"""Independent endpoint/linearity checks of the draft terminal alternative."""

import numpy as np
import pytest

from stress.params import PitBook
from stress.params.matrix import pit_matrix
from tests.support import oracle


@pytest.mark.req("REG-06", "ECL-10")
def test_parameter_reversion_is_linear_in_transition_probabilities():
    p = oracle("AT-34")["input"]["pd"]
    ttc = np.array([[1 - p, p], [0., 1.]])
    last = oracle("AT-41")["input"]["valuation_year"]
    z = {("S", "DE", scenario, year): value for scenario, value in
         [("baseline", 0.), ("adverse", -1.)] for year in range(last, last + 7)}
    segments = {"S": {"rho": p}}
    rule = {"last_scenario_year": last, "reversion_years": 6}
    book = PitBook({"S": ttc}, segments, z, 1e-10, terminal_rule=rule)
    bad = pit_matrix(ttc, -1., p)
    for offset in range(1, 7):
        weight = (6 - offset) / 6
        expected = weight * bad + (1 - weight) * ttc
        assert np.allclose(book.get("S", "DE", "adverse", last + offset), expected)
    assert np.allclose(book.get("S", "DE", "baseline", last + 6), ttc)
