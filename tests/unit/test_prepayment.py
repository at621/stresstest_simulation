"""The prepayment rate by Z (EAD-11): its level in an average year and its direction.

``test_kernels.py`` holds the share not yet prepaid to its bounds. These hold the rate itself,
which the run takes from the same kernel (the "Z-score and prepayment" control compares them).
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stress.params.prepay import prepayment_rate
from tests.support import tolerance

TOL = tolerance("rate")["abs"]
ttc_rates = st.floats(min_value=1e-3, max_value=1 - 1e-3, allow_nan=False)
sensitivities = st.floats(min_value=0.01, max_value=2.0, allow_nan=False)
zs = st.floats(min_value=-5.0, max_value=5.0, allow_nan=False)
shifts = st.floats(min_value=0.01, max_value=5.0, allow_nan=False)


@pytest.mark.req("EAD-11")
@given(ttc_rates, st.floats(min_value=0.0, max_value=2.0, allow_nan=False))
def test_an_average_year_gives_back_the_ttc_rate(cpr_ttc, v):
    assert abs(float(prepayment_rate(cpr_ttc, v, 0.0)) - cpr_ttc) <= TOL


@pytest.mark.req("EAD-11")
@given(ttc_rates, zs)
def test_zero_sensitivity_keeps_the_ttc_rate(cpr_ttc, z):
    assert abs(float(prepayment_rate(cpr_ttc, 0.0, z)) - cpr_ttc) <= TOL


@pytest.mark.req("EAD-11")
@given(ttc_rates, sensitivities, shifts)
def test_prepayment_falls_when_the_economy_worsens(cpr_ttc, v, shift):
    # v > 0 lowers prepayment when the economy worsens: below the TTC rate for Z < 0, above it for Z > 0.
    worse, better = (float(prepayment_rate(cpr_ttc, v, z)) for z in (-shift, shift))
    assert worse < cpr_ttc < better


@pytest.mark.req("EAD-11")
@given(ttc_rates, sensitivities, zs, zs)
def test_prepayment_never_rises_as_z_falls(cpr_ttc, v, z1, z2):
    low, high = sorted((z1, z2))
    assert float(prepayment_rate(cpr_ttc, v, low)) <= float(prepayment_rate(cpr_ttc, v, high))
    assert 0.0 <= float(prepayment_rate(cpr_ttc, v, low)) <= 1.0
