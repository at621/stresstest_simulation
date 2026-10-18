"""Property tests of the pure calculation kernels: bounds and identities."""

import numpy as np
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from foundation.matrices import build_matrix
from stress.accounting.kernels import charge
from stress.capital import methodological_floor, output_floor
from stress.cashflows import PROFILE_CODES, remaining, schedules
from stress.cashflows.kernels import contractual_schedule, remaining_maturity
from stress.contracts.errors import Block, BlockingError
from stress.ecl.kernels import ecl, floor_per_exposure
from stress.params.ead import check_ccf, ead
from stress.params.lgd import lgd_from_z
from stress.params.matrix import cumulative, matrix_problems, pd_rises_with_grade, pit_matrix
from stress.params.pd import cumulative_pd, curve_from_conditional, curve_problems, stub_pd
from stress.params.prepay import not_prepaid_share, prepayment_rate
from stress.projection.kernels import stage_flows, stage_of_rank
from stress.scenario.kernels import adverse_weight, compound_index, reverted_z, z_score

TOL = 1e-10
prob = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
open_prob = st.floats(min_value=1e-6, max_value=1 - 1e-6, allow_nan=False)
zs = st.floats(min_value=-5.0, max_value=5.0, allow_nan=False)
rhos = st.floats(min_value=0.0, max_value=0.5, allow_nan=False)


@st.composite
def ttc_matrices(draw):
    n = draw(st.integers(min_value=2, max_value=10))
    low = draw(st.floats(min_value=1e-4, max_value=1e-2))
    ratio = draw(st.floats(min_value=1.3, max_value=3.0))
    pds = np.minimum(low * ratio ** np.arange(n), 0.5)
    pds = np.maximum.accumulate(pds + np.arange(n) * 1e-6)
    stay = draw(st.floats(min_value=0.5, max_value=0.98))
    down = draw(st.floats(min_value=0.1, max_value=0.9))
    decay = draw(st.floats(min_value=0.05, max_value=0.8))
    return build_matrix(pds, stay, down, decay)


# --- R4 -----------------------------------------------------------------------------------------

@pytest.mark.req("SCN-08")
@given(st.lists(st.tuples(st.floats(-2, 2), st.floats(-1, 1), st.floats(0.01, 1)), min_size=1, max_size=5))
def test_z_is_zero_at_the_means_and_linear(coefs):
    drivers = {f"x{i}": {"beta": b, "mean": m, "sd": s} for i, (b, m, s) in enumerate(coefs)}
    at_means = {k: c["mean"] for k, c in drivers.items()}
    assert abs(z_score(at_means, drivers)[0]) <= TOL
    shifted = {k: c["mean"] + c["sd"] for k, c in drivers.items()}
    assert abs(z_score(shifted, drivers)[0] - sum(c["beta"] for c in drivers.values())) <= 1e-9


@pytest.mark.req("SCN-08")
def test_missing_driver_value_blocks():
    with pytest.raises(BlockingError) as err:
        z_score({}, {"gdp": {"beta": 1.0, "mean": 0.0, "sd": 1.0}})
    assert err.value.code == Block.MISSING_SCENARIO_VALUE


@pytest.mark.req("ECL-10")
@given(st.integers(2000, 2100), st.integers(1, 12), zs, zs)
def test_reversion_weights_and_path(year, years, z_adv, z_base):
    last = 2029
    a = adverse_weight(year, last, years)
    assert 0.0 <= a <= 1.0
    assert a == 1.0 if year <= last else a <= adverse_weight(year - 1, last, years)
    assert (a == 0.0) == (year >= last + years)
    z = reverted_z(year, z_adv, z_base, last, years)
    assert min(z_adv, z_base) - 1e-12 <= z <= max(z_adv, z_base) + 1e-12


@pytest.mark.req("SCN-05")
@given(st.lists(st.floats(-0.5, 0.5), min_size=1, max_size=6), st.floats(1, 1000))
def test_index_compounds(changes, start):
    levels = compound_index(changes, start)
    assert np.isclose(levels[-1], start * np.prod([1 + c for c in changes]), rtol=1e-12)


# --- R5 -----------------------------------------------------------------------------------------

@pytest.mark.req("EAD-10")
@settings(max_examples=150)
@given(st.floats(1.0, 1e8), st.floats(-0.05, 0.25), st.integers(1, 360), st.sampled_from(list(PROFILE_CODES)))
def test_schedule_identities(drawn, rate, months, profile):
    maturity = months / 12
    s = contractual_schedule(drawn, rate, maturity, profile)
    assert abs(s.closing_balance[-1]) <= 1e-6
    assert np.isclose(s.principal.sum(), drawn, rtol=1e-9)
    assert (s.opening_balance >= -1e-6).all() and (np.diff(s.opening_balance) <= 1e-6).all()
    assert np.isclose(s.t[-1], maturity) and np.allclose(s.discount_factor, (1 + rate) ** -s.t)
    v = schedules(np.array([drawn]), np.array([rate]), np.array([maturity]), np.array([PROFILE_CODES[profile]]))
    n = int(v[-1][0])
    assert n == len(s.fraction)
    assert np.allclose(v[2][0, :n], s.opening_balance, rtol=1e-12, atol=1e-6)
    assert np.allclose(v[3][0, :n], s.interest, rtol=1e-12, atol=1e-6)


@pytest.mark.req("EXP-05")
@given(st.integers(1, 360), st.integers(0, 4))
def test_like_for_like_replacement(months, elapsed):
    original = months / 12
    rest, generation = remaining_maturity(original, elapsed)
    assert 0 < rest <= original + 1e-12
    assert generation == (0 if elapsed < original - 1e-9 else int(np.floor((elapsed + 1e-9) / original)))
    vec_rest, vec_gen = remaining(np.array([original]), elapsed)
    assert np.isclose(vec_rest[0], rest) and vec_gen[0] == generation


# --- R6 -----------------------------------------------------------------------------------------

@pytest.mark.req("PD-10")
@settings(max_examples=150)
@given(ttc_matrices(), zs, rhos)
def test_pit_matrix_is_valid(ttc, z, rho):
    assert matrix_problems(ttc, TOL) == []
    m = pit_matrix(ttc, z, rho)
    assert matrix_problems(m, TOL) == []
    assert pd_rises_with_grade(m)
    if z < 0:
        assert (m[:-1, -1] >= pit_matrix(ttc, 0.0, rho)[:-1, -1] - 1e-15).all()


@pytest.mark.req("PD-10")
@given(ttc_matrices(), zs)
def test_zero_rho_gives_the_ttc_matrix(ttc, z):
    assert np.allclose(pit_matrix(ttc, z, 0.0), ttc, atol=1e-12)
    assert np.allclose(cumulative(ttc)[:, 0], 1.0)


@pytest.mark.req("PD-03")
@given(st.lists(prob, min_size=1, max_size=40))
def test_probability_identities(q):
    curve = curve_from_conditional(q)
    assert curve_problems(curve, TOL) == []
    assert np.allclose(np.cumsum(curve.m), curve.f, atol=TOL)


@pytest.mark.req("PD-11")
@given(ttc_matrices(), st.lists(zs, min_size=1, max_size=12), rhos)
def test_curves_from_matrix_products(ttc, path, rho):
    matrices = [pit_matrix(ttc, z, rho) for z in path]
    f = cumulative_pd(matrices)
    assert np.allclose(f[:, 0], matrices[0][:-1, -1])
    for g in range(f.shape[0]):
        m = np.diff(np.concatenate([[0.0], f[g]]))
        assert (m >= -TOL).all() and (f[g] <= 1 + TOL).all()


@pytest.mark.req("PD-06")
@given(prob, st.floats(0.0, 1.0))
def test_stub_pd(q, d):
    value = float(stub_pd(q, d))
    assert -TOL <= value <= q + TOL


@pytest.mark.req("LGD-12")
@given(prob, st.floats(0.0, 2.0), zs)
def test_lgd_bounds(lgd_ttc, w, z):
    value = float(lgd_from_z(lgd_ttc, w, z))
    assert 0.0 <= value <= 1.0
    if w > 0 and 0 < lgd_ttc < 1 and z < 0:
        assert value >= lgd_ttc - 1e-12


@pytest.mark.req("EAD-11")
@given(open_prob, st.floats(0.0, 1.0), st.lists(zs, min_size=1, max_size=30))
@example(cpr_ttc=0.9999989999999999, v=1.0, path=[4.0, 0.0])  # the rate rounds to 1.0
def test_not_prepaid_share(cpr_ttc, v, path):
    rates = prepayment_rate(np.full(len(path), cpr_ttc), v, np.array(path))
    sp = not_prepaid_share(rates)
    assert sp[0] == 1.0 and (np.diff(sp) <= 0).all() and ((sp >= 0) & (sp <= 1)).all()
    # SP stays positive wherever the product of the computed factors (1 - CPR) does not
    # underflow. In float64 the probit shift can round to exactly 1 for extreme inputs (CPR_TTC
    # near 1 with a large v x Z): everything is then prepaid, and SP is 0 from the next bucket on.
    with np.errstate(divide="ignore"):
        log_sp = np.concatenate(([0.0], np.cumsum(np.log1p(-rates[:-1]))))
    assert (sp[log_sp > np.log(np.finfo(float).tiny)] > 0).all()


@pytest.mark.req("EAD-04")
@given(st.floats(0, 1e8), st.floats(0, 1e8), prob)
def test_ead_bounds(drawn, undrawn, c):
    e = ead(drawn, undrawn, c)
    assert drawn - 1e-6 <= float(e.total) <= drawn + undrawn + 1e-6


@pytest.mark.req("EAD-04")
def test_ccf_contract_blocks():
    with pytest.raises(BlockingError):
        check_ccf([np.nan], [100.0])
    with pytest.raises(BlockingError):
        check_ccf([1.2], [100.0])
    check_ccf([np.nan], [0.0])  # no undrawn amount: the CCF is not applicable


# --- R7-R10 -------------------------------------------------------------------------------------

@pytest.mark.req("MIG-02")
@given(st.floats(0, 1e6), st.floats(0, 1e6), st.floats(0, 1e6), st.lists(prob, min_size=6, max_size=6))
def test_stage_flows_conserve_the_book(s1, s2, s3, raw):
    r = np.array(raw).reshape(2, 3) + 1e-9
    r = r / r.sum(axis=1, keepdims=True)
    rows = {"S1": dict(zip(("S1", "S2", "S3"), r[0])), "S2": dict(zip(("S1", "S2", "S3"), r[1])),
            "S3": {"S3": 1.0}}
    closing, _ = stage_flows({"S1": s1, "S2": s2, "S3": s3}, rows, TOL)
    assert np.isclose(sum(closing.values()), s1 + s2 + s3, rtol=1e-12, atol=1e-6)
    assert closing["S3"] >= s3 - 1e-6


@pytest.mark.req("MIG-07")
def test_stage_of_rank():
    stages = stage_of_rank(np.array([1, 3, 4, 11]), np.array([4, 4, 4, 4]), 11)
    assert stages.tolist() == [1, 1, 2, 3]


@pytest.mark.req("MIG-05")
def test_stage_of_rank_with_a_qualitative_trigger():
    ranks, line = np.array([1, 3, 4, 11]), np.array([4, 4, 4, 4])
    flagged = np.array([True, True, False, True])
    # A flag makes every performing grade S2; D stays S3; without a flag the grade decides.
    assert stage_of_rank(ranks, line, 11, flagged).tolist() == [2, 2, 2, 3]
    unflagged = stage_of_rank(ranks, line, 11, np.zeros(4, dtype=bool))
    assert unflagged.tolist() == stage_of_rank(ranks, line, 11).tolist()


@pytest.mark.req("ECL-07")
@given(st.lists(st.tuples(st.floats(0, 1e6), st.floats(0, 1e6)), min_size=1, max_size=20))
def test_floor_never_releases(pairs):
    raw, prior = (np.array(x) for x in zip(*pairs))
    constrained, released = floor_per_exposure(raw, prior)
    assert (constrained >= prior).all() and (constrained >= raw).all()
    assert (released == (raw < prior)).all()


@pytest.mark.req("ECL-08")
@given(st.lists(st.tuples(prob, st.floats(0, 1e6), prob, prob), min_size=1, max_size=30))
def test_ecl_is_a_sum_of_products(terms):
    m, e, lgd, df = (np.array(x) for x in zip(*terms))
    assert np.isclose(ecl(m, e, lgd, df), float(np.sum(m * e * lgd * df)))
    assert ecl(m * 0, e, lgd, df) == 0.0


@pytest.mark.req("ACC-01")
@given(st.lists(st.floats(0, 1e6), min_size=1, max_size=10), st.lists(st.floats(0, 1e6), min_size=1, max_size=10))
def test_charge_is_the_stock_change(a, b):
    n = min(len(a), len(b))
    assert np.isclose(charge(a[:n], b[:n]).sum(), sum(b[:n]) - sum(a[:n]), atol=1e-6)


@pytest.mark.req("CAP-03")
@given(st.floats(0, 1e6), st.floats(0, 1e6), st.floats(0, 1e6), st.floats(0, 1e6))
def test_methodological_floor(si, ss, ri, rs):
    out = methodological_floor({"IRB": si, "STA": ss}, {"IRB": ri, "STA": rs})
    assert out["floored"]["IRB"] >= si and out["floored"]["STA"] >= ss
    assert out["credit_contribution"] >= ri + rs - 1e-9


@pytest.mark.req("CAP-04")
@given(st.floats(0, 1e6), st.floats(0, 1e6), prob)
def test_output_floor(utrea, strea, factor):
    assert output_floor(utrea, strea, factor)["result"] >= utrea
