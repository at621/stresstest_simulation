"""AT-05: simplified S1 loss-rate provision (ECL-02)."""

import pytest

from stress.ecl.kernels import s1_loss_rate_provision
from tests.support import assert_close, oracle


@pytest.mark.at("AT-05")
def test_s1_provision_from_next_year_pd_and_lgd():
    case = oracle("AT-05")
    i = case["input"]
    value = s1_loss_rate_provision(i["exposure"], i["pd"], i["lgd"], i["discount_factor"])
    assert_close(value, case["expected"]["provision"], case["tolerance"], "provision")
