"""AT-33: zero EAD gives zero loss and a not-applicable LGD (LGD-12)."""

import pytest

from stress.ecl.kernels import monetary_loss
from stress.params.lgd import loss_weighted_lgd
from tests.support import oracle


@pytest.mark.at("AT-33")
def test_zero_ead():
    case = oracle("AT-33")
    any_lgd = oracle("AT-34")["input"]["lgd"]
    loss, lgd = monetary_loss(case["input"]["ead"], any_lgd)
    assert loss == case["expected"]["loss"]
    assert lgd is None and case["expected"]["lgd"] == "not_applicable"
    _, den, value = loss_weighted_lgd([oracle("AT-34")["input"]["pd"]], [case["input"]["ead"]],
                                      [any_lgd])
    assert den == 0 and value is None
