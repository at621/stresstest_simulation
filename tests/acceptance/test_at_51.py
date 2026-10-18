"""AT-51: contractual schedules for bullet, annuity and linear profiles, with a stub (EAD-10).

The schedule values are OPEN in the spec until the owner approves them; the case proves the
profile rules, which need no oracle number.
"""

import numpy as np
import pytest

from stress.cashflows import PROFILE_CODES, schedules
from stress.cashflows.kernels import annuity_payment, contractual_schedule, drawn_measure
from tests.support import oracle, tolerance


@pytest.mark.at("AT-51")
def test_schedule_profiles(full_tables):
    case = oracle("AT-51")
    assert case["status"] == "PARTLY_OPEN"
    tol = tolerance("amount")["abs"]
    fac = full_tables["facilities"]
    # Real facilities: one whole-year and one stub maturity per profile, from the input set.
    whole = fac[(fac["residual_maturity"] % 1 == 0) & (fac["residual_maturity"] > 1)].iloc[0]
    stub = fac[(fac["residual_maturity"] % 1 > 0) & (fac["residual_maturity"] > 2)].iloc[0]
    for f in (whole, stub):
        d = drawn_measure(f["principal"], f["accrued_interest"], bool(f["accrued_in_gca"]), f["gca"])
        assert abs(d - f["gca"]) <= tol, "accrued interest counted once"
        m, r = float(f["residual_maturity"]), float(f["interest_rate"])
        frac = m - np.floor(m)
        for profile in case["input"]["profiles"]:
            s = contractual_schedule(d, r, m, profile)
            assert abs(s.closing_balance[-1]) <= tol and abs(s.principal.sum() - d) <= tol
            assert np.isclose(s.t[-1], m)
            if frac > 0:
                assert np.isclose(s.fraction[-1], frac), "stub of fraction d in the final period"
            full_years = s.fraction == 1.0
            if profile == "bullet":
                assert np.allclose(s.balance, d), "balance flat at D until M"
            if profile == "annuity":
                payments = s.payment[full_years][:-1] if frac == 0 else s.payment[full_years]
                assert np.allclose(payments, annuity_payment(d, r, m)), "constant payment"
            if profile == "linear":
                principal = s.principal[full_years][:-1] if frac == 0 else s.principal[full_years]
                assert np.allclose(principal, d / m), "principal D / M each year"
            # The vectorised R5 builder gives the same schedule.
            v = schedules(np.array([d]), np.array([r]), np.array([m]), np.array([PROFILE_CODES[profile]]))
            n = int(v[-1][0])
            assert np.allclose(v[2][0, :n], s.opening_balance) and np.allclose(v[4][0, :n], s.principal)
