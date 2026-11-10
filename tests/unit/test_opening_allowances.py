"""SYN-PAR-09: the opening allowances of the performing book, held to their rule without O4's code.

``test_foundation.py`` checks the Stage 3 leg. Here the S1 and S2 legs are rebuilt from the input
set's own tables (PD curve from powers of the TTC matrix, TTC LGD, the TTC prepayment rate, a
bullet schedule at the facility's rate and maturity), and tied to two things O4 does not write:
O2's lifetime PD and the engine's own end-2026 valuation.
"""

import numpy as np
import pandas as pd
import pytest

from foundation.matrices import lifetime_pd
from foundation.synth.allowances import _fractions, marginal_pd
from stress.contracts.tables import MODEL_LGD, MODEL_PD
from tests import builders
from tests.support import CURRENT_INPUT_SET, INPUTS_DIR, tolerance

WHOLE = 1e-9  # a maturity this close to a whole number of years has no part-year bucket


def matrices_by_segment(tables: dict) -> dict[str, np.ndarray]:
    """Each segment's TTC matrix in rank order, D last."""
    out = {}
    for segment, cells in tables["ttc_pd_matrix"].groupby("segment"):
        size = int(cells["from_rank"].max())
        m = np.zeros((size, size))
        m[cells["from_rank"].to_numpy() - 1, cells["to_rank"].to_numpy() - 1] = cells["probability"]
        out[str(segment)] = m
    return out


class Powers:
    """Whole-year powers of one TTC matrix, each computed once."""

    def __init__(self, matrix: np.ndarray):
        self.matrix = matrix
        self._known: dict[int, np.ndarray] = {}

    def __getitem__(self, years: int) -> np.ndarray:
        if years not in self._known:
            self._known[years] = np.linalg.matrix_power(self.matrix, years)
        return self._known[years]


def default_buckets(powers: Powers, grade: int, maturity: float) -> tuple[np.ndarray, np.ndarray]:
    """Marginal TTC PD and time in years of each default bucket to maturity, for a start grade.
    A whole year is the rise of the cumulative PD, read from powers of the matrix. A final part
    year of d takes 1 - (1 - PD)^d per grade, on the grades reached by then (PD-06)."""
    years = int(np.floor(maturity + WHOLE))
    part = maturity - years
    marginal = list(np.diff([powers[k][grade, -1] for k in range(years + 1)]))
    t = list(range(1, years + 1))
    if part > WHOLE:
        marginal.append(powers[years][grade, :-1] @ (1.0 - (1.0 - powers.matrix[:-1, -1]) ** part))
        t.append(maturity)
    return np.array(marginal), np.array(t, dtype=float)


def ttc_valuation(tables: dict) -> pd.DataFrame:
    """The end-2026 allowance of every performing facility by SYN-PAR-09: S1 the first bucket, S2
    the whole life; the drawn part on balance, the undrawn part times its CCF off balance."""
    powers = {segment: Powers(matrix) for segment, matrix in matrices_by_segment(tables).items()}
    cpr = {segment: float(body["cpr_ttc"]) for segment, body in builders.segments(tables).items()}
    grades = list(tables["parameter_set"]["master_scale"]["grades"])
    commitments = tables["commitments"].set_index("facility_id")
    facilities = tables["facilities"]
    rows = []
    for f in facilities[facilities["ifrs_stage"] < 3].itertuples(index=False):
        marginal, t = default_buckets(powers[f.segment], grades.index(f.current_grade), f.residual_maturity)
        if f.ifrs_stage == 1:
            marginal, t = marginal[:1], t[:1]
        not_prepaid = (1.0 - cpr[f.segment]) ** np.arange(len(t))
        loss = marginal * f.ttc_lgd * (1.0 + f.interest_rate) ** -t
        converted = 0.0
        if f.facility_id in commitments.index:
            line = commitments.loc[f.facility_id]
            converted = float(line["nominal_undrawn"] * line["accounting_ccf"]) if line["nominal_undrawn"] > 0 else 0.0
        rows.append({"facility_id": f.facility_id, "stage": f.ifrs_stage, "buckets": len(t),
                     "part_year": bool(t[-1] % 1 > WHOLE),
                     "on": float(np.sum(loss * f.gca * not_prepaid)), "off": float(np.sum(loss * converted))})
    return pd.DataFrame(rows).set_index("facility_id")


@pytest.fixture(scope="module", params=["generated", "committed"])
def book(request, full_tables):
    """The book O2-O4 build now, and the committed one, which a run reads on every system (A36)."""
    return full_tables if request.param == "generated" else builders.load(INPUTS_DIR / CURRENT_INPUT_SET)


@pytest.mark.req("SYN-PAR-09")
def test_performing_opening_allowances_are_the_ttc_valuation(book):
    expected = ttc_valuation(book)
    frozen = book["opening_provisions"].set_index("facility_id").loc[expected.index]
    lifetime = expected[expected["stage"] == 2]
    assert (lifetime["buckets"] > 1).any() and lifetime["part_year"].any(), (
        "S2 needs a later bucket and a part-year bucket to prove prepayment, discounting and PD-06")
    assert (expected.groupby("stage")["off"].max() > 0).all(), "each stage needs an undrawn commitment"
    assert np.allclose(frozen["allowance_on"], expected["on"], rtol=1e-9, atol=0)
    assert np.allclose(frozen["provision_off"], expected["off"], rtol=1e-9, atol=0)


@pytest.mark.req("SYN-PAR-09", "PD-06")
def test_marginal_pds_add_up_to_the_lifetime_pd(full_tables):
    """O4's buckets against O2's lifetime PD, for every grade and every maturity in the book: the
    whole years telescope and the part year takes the constant hazard."""
    tol = tolerance("probability_identity")["abs"]
    performing = full_tables["facilities"][full_tables["facilities"]["ifrs_stage"] < 3]
    part_years = 0
    for segment, matrix in matrices_by_segment(full_tables).items():
        for maturity in sorted(set(performing.loc[performing["segment"] == segment, "residual_maturity"])):
            fractions = _fractions(maturity)
            part_years += fractions[-1] < 1.0
            assert abs(fractions.sum() - maturity) <= WHOLE
            lifetime = lifetime_pd(matrix, maturity)
            for rank in range(1, matrix.shape[0]):
                total = marginal_pd(matrix, rank, fractions).sum()
                assert abs(total - lifetime[rank - 1]) <= tol, (segment, maturity, rank)
    assert part_years, "the book needs a maturity with a part year"


@pytest.mark.req("SYN-PAR-09")
def test_the_engine_values_an_average_year_as_the_generator_did(core_run, full_tables):
    """Where the first year's baseline Z is 0, the PiT matrix and the LGD are the TTC ones (PD-10,
    LGD-12), and the first bucket is not yet prepaid. The engine's own end-2026 S1 valuation is then
    the frozen O4 allowance, facility by facility, on and off balance."""
    ctx, _ = core_run
    z = builders.result(ctx, "drivers.parquet")
    first_year = int(full_tables["parameter_set"]["horizon"]["projection_years"][0])
    z = z[(z["scenario"] == "baseline") & (z["year"] == first_year) & z["model"].isin([MODEL_PD, MODEL_LGD])]
    average = z.groupby(["segment", "country"])["z"].apply(
        lambda values: bool((values.abs() <= tolerance("rate")["abs"]).all()))
    average = set(average[average].index)
    assert average, "no segment has Z = 0 in the first baseline year, so this identity proves nothing"
    facts = full_tables["facilities"].merge(full_tables["obligors"][["obligor_id", "country"]], on="obligor_id")
    facts = facts.set_index("facility_id")
    engine = builders.result(ctx, "provisions.parquet")
    engine = engine[(engine["scenario"] == "baseline") & (engine["year"] == engine["year"].min())
                    & (engine["stage"] == 1)].set_index("facility_id")
    assert engine.index.is_unique
    of = facts.loc[engine.index]
    # A first bucket shorter than a year is left out: O4 takes the constant hazard, R8 pro rata (A7).
    kept = np.array([pair in average for pair in zip(of["segment"], of["country"])]) \
        & (of["residual_maturity"].to_numpy() >= 1.0)
    engine = engine[kept]
    frozen = full_tables["opening_provisions"].set_index("facility_id").loc[engine.index]
    rel = tolerance("aggregate")["rel"]
    assert len(engine), "no S1 facility with a whole first year in those segments"
    assert np.allclose(engine["allowance_on"], frozen["allowance_on"], rtol=rel, atol=0)
    assert np.allclose(engine["provision_off"], frozen["provision_off"], rtol=rel, atol=0)
