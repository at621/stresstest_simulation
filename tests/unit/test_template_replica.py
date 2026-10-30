"""R10: the draft's template provisions rebuilt from reported parameters (Boxes 3-9)."""

import numpy as np
import pandas as pd
import pytest

from stress.contracts.errors import BlockingError
from stress.contracts.tables import SLICE_S3_ORIGINAL
from stress.report.template import TEMPLATE_CLASS, template_replica
from tests import builders
from tests.support import oracle, tolerance

YEARS = [2027, 2028, 2029]
PORTFOLIO = pd.DataFrame({"facility_id": ["S", "M", "O"], "segment": ["P03", "P03", "P03"]})


def row(scenario, year, facility, name, stage, gca, allowance):
    return {"scenario": scenario, "year": year, "facility_id": facility, "slice": name, "stage": stage,
            "gca": gca, "allowance_on": allowance}


def slices(scenario="adverse") -> pd.DataFrame:
    rows = []
    for year in (2026, *YEARS):
        step = year - 2026
        rows += [row(scenario, year, "S", "G1", 1, 100.0, 1.0), row(scenario, year, "M", "G5", 2, 50.0, 5.0),
                 row(scenario, year, "O", SLICE_S3_ORIGINAL, 3, 20.0, 8.0)]
        if step:
            rows.append(row(scenario, year, "S", f"S3_{year}_from_S1", 3, 0.0, 0.0))
    return pd.DataFrame(rows)


def flows(scenario="adverse", year=2027, s1s2=9.0, s2s1=5.0, s1s3=2.0, s2s3=4.0) -> pd.DataFrame:
    out = [(1, 2, s1s2), (2, 1, s2s1), (1, 3, s1s3), (2, 3, s2s3)]
    return pd.DataFrame([{"scenario": scenario, "year": year, "segment": "P03", "from_stage": a, "to_stage": b,
                          "gca": v} for a, b, v in out])


def lgd(scenario="adverse") -> pd.DataFrame:
    return pd.DataFrame([{"scenario": scenario, "year": y, "facility_id": f, "lgd": 0.5}
                         for y in YEARS for f in ("S", "M", "O")])


def z() -> pd.DataFrame:
    return pd.DataFrame({"segment": ["P03"], "country": ["DE"], "scenario": ["adverse"], "year": [2030],
                         "adverse_weight": [5 / 6]})


@pytest.mark.req("RPT-05")
def test_boxes_rebuild_the_template_lines_from_parameters():
    both = pd.concat([slices(), slices("baseline")], ignore_index=True)
    moved = pd.concat([flows(year=y) for y in YEARS] + [flows("baseline", y) for y in YEARS], ignore_index=True)
    rates = pd.concat([lgd(), lgd("baseline")], ignore_index=True)
    out = template_replica(both, moved, rates, z(), PORTFOLIO, YEARS, tolerance("aggregate"))
    first = out[(out["scenario"] == "adverse") & (out["year"] == 2027)].iloc[0]
    assert first["template_class"] == TEMPLATE_CLASS["P03"]
    assert first["tr12"] == pytest.approx(0.09) and first["pd12m_s1"] == pytest.approx(0.02)
    assert first["tr21"] == pytest.approx(0.1) and first["pd12m_s2"] == pytest.approx(0.08)
    assert first["lgd_s1"] == pytest.approx(0.5) and first["lrlt_s2"] == pytest.approx(0.1)
    next_rate = 0.02 * 0.5
    assert first["prov_s1_s1"] == pytest.approx(100 * (1 - 0.09 - 0.02) * next_rate)  # Box 5
    assert first["prov_s2_s1"] == pytest.approx(50 * 0.1 * next_rate)  # Box 4
    assert first["prov_s1_s2"] == pytest.approx(100 * 0.09 * 0.1)  # Box 6
    assert first["prov_s1_s3"] == pytest.approx(100 * 0.02 * 0.5)  # Box 8
    later = out[(out["scenario"] == "adverse") & (out["year"] == 2028)].iloc[0]
    assert later["template_s3_new"] == pytest.approx(2 * (first["prov_s1_s3"] + first["prov_s2_s3"]))
    assert first["old_s3_box_9"] == pytest.approx(max(20 * 0.5, 8.0))  # Box 9


@pytest.mark.req("ECL-05")
def test_end_of_horizon_blends_the_two_loss_rates_as_boxes_4_and_5_write_them():
    case = oracle("AT-06")
    i = case["input"]
    book = pd.concat([slices(), slices("baseline")], ignore_index=True)
    # An S1 stock of 100 turns each scenario's PD into a flow; the LGD comes through the table.
    moved = pd.concat([flows("adverse", y, s1s3=100 * i["adverse"]["pd"]) for y in YEARS]
                      + [flows("baseline", y, s1s3=100 * i["baseline"]["pd"]) for y in YEARS], ignore_index=True)
    rates = pd.concat([lgd().assign(lgd=i["adverse"]["lgd"]), lgd("baseline").assign(lgd=i["baseline"]["lgd"])],
                      ignore_index=True)
    weights = z().assign(adverse_weight=case["expected"]["weights"]["adverse"])
    out = template_replica(book, moved, rates, weights, PORTFOLIO, YEARS, tolerance("aggregate"))
    rate = out[(out["scenario"] == "adverse") & (out["year"] == 2029)]["loss_rate_s1_next"].iloc[0]
    assert rate == pytest.approx(case["expected"]["interpolated_loss_rate"], abs=case["tolerance"]["abs"])
    base = out[(out["scenario"] == "baseline") & (out["year"] == 2029)]["loss_rate_s1_next"].iloc[0]
    assert base == pytest.approx(case["expected"]["baseline_loss_rate"], abs=case["tolerance"]["abs"])


@pytest.mark.req("RPT-05")
def test_a_segment_without_a_terminal_weight_blocks():
    with pytest.raises(BlockingError, match="terminal weight"):
        template_replica(slices(), pd.concat([flows(year=y) for y in YEARS]), lgd(), z().assign(segment="P05"),
                         PORTFOLIO, YEARS, tolerance("aggregate"))


@pytest.mark.req("RPT-05")
def test_replica_of_a_full_run_ties_to_the_engine(core_run):
    ctx, _ = core_run
    out = builders.report(ctx, "analysis_template_replica.csv")
    assert set(out["segment"]) == set(TEMPLATE_CLASS)
    assert out["template_class"].notna().all()
    # S2 is the engine's own coverage on the template's flows, so it must close exactly.
    assert np.allclose(out["template_s2"], out["engine_s2"], rtol=1e-7, atol=1.0)
    new = out[out["engine_s3_new"] > 0]
    assert (new["gap_s3_new"].abs() < 0.05).all(), "new S3 is flow x LGD in both"
    totals = out.groupby(["scenario", "year"])[["template_s1", "engine_s1"]].sum()
    assert (totals["template_s1"] > totals["engine_s1"]).all(), "the template carries no discount factor"
