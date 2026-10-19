"""Section 12.2 calculation and run controls: blocking conditions, parameter alignment,
static balance, reproducibility and version change."""

import numpy as np
import pandas as pd
import pytest

from stress.cli import main
from stress.contracts.errors import Block, BlockingError
from stress.contracts.tables import ROUTE_PERFORMING, ROUTE_S3_ORIGINAL, Parameters
from stress.ecl import performing_ecl
from stress.lineage import compare_outputs
from stress.params.matrix import check_matrix, pit_matrix
from stress.params.pd import check_curve, curve_from_conditional
from stress.projection import check_static
from stress.report import compare_runs
from tests import builders
from tests.support import tolerance


def blocked(mini, tmp_path, **kw):
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs", **kw)
    assert manifest["status"] == "BLOCKED", "the run must block"
    return manifest["blocked"]


@pytest.mark.control("Probability range or transition sum")
def test_probability_range_and_row_sums(mini, tmp_path):
    table = mini["ttc_pd_matrix"]
    cell = (table["segment"] == "P02") & (table["from_grade"] == "G3") & (table["to_grade"] == "G4")
    table.loc[cell, "probability"] = -0.01
    assert blocked(mini, tmp_path)["code"] == Block.INVALID_MATRIX
    bad = pit_matrix(np.array([[0.9, 0.1], [0.0, 1.0]]), -1.0, 0.2)
    bad[0, 0] += 1e-6
    with pytest.raises(BlockingError):
        check_matrix(bad, tolerance("probability_identity")["abs"], "R6", "PiT")


@pytest.mark.control("Rating matrices")
def test_default_must_be_absorbing(mini, tmp_path):
    table = mini["ttc_pd_matrix"]
    d_row = (table["segment"] == "P04") & (table["from_grade"] == "D")
    table.loc[d_row & (table["to_grade"] == "D"), "probability"] = 0.9
    table.loc[d_row & (table["to_grade"] == "G10"), "probability"] = 0.1
    b = blocked(mini, tmp_path)
    assert b["code"] == Block.INVALID_MATRIX and "absorbing" in b["message"]


@pytest.mark.control("PD curve identities and completeness")
def test_pd_curve_identities_block():
    tol = tolerance("probability_identity")["abs"]
    curve = curve_from_conditional([0.02, 0.03])
    check_curve(curve, tol, "R6", "fine")
    broken = type(curve)(q=curve.q, m=curve.m, s=curve.s, f=curve.f[::-1].copy())
    with pytest.raises(BlockingError) as err:
        check_curve(broken, tol, "R6", "decreasing")
    assert err.value.code == Block.PD_IDENTITY


@pytest.mark.control("PD curve identities and completeness")
def test_missing_curve_bucket_blocks_the_ecl(core_run, full_tables):
    # R8 never reads a missing whole-year PD as zero, the one behind a part-year bucket included.
    ctx, _ = core_run
    curves = builders.result(ctx, "pd_curves.parquet")
    facility = builders.result(ctx, "parameters.parquet")
    params = Parameters(pit=builders.result(ctx, "pit_matrices.parquet"), pd_curves=curves,
                        facility=facility, lgd_of_year=builders.result(ctx, "lgd_of_year.parquet"))
    fac = full_tables["facilities"].merge(full_tables["obligors"][["obligor_id", "country"]], on="obligor_id")
    portfolio = fac.assign(route=np.where(fac["ifrs_stage"] < 3, ROUTE_PERFORMING, ROUTE_S3_ORIGINAL))
    grades = tuple(full_tables["parameter_set"]["master_scale"]["grades"])
    scenario = "baseline"
    year = int(full_tables["parameter_set"]["horizon"]["snapshot_year"])
    performing_ecl(params, portfolio, scenario, year, grades)  # the intact tables price
    part = facility[(facility["scenario"] == scenario) & (facility["valuation_year"] == year)
                    & (facility["fraction"] < 1.0) & (facility["default_bucket"] > 2)].iloc[0]
    where = portfolio.set_index("facility_id").loc[part["facility_id"]]
    curve = ((curves["segment"] == where["segment"]) & (curves["country"] == where["country"])
             & (curves["scenario"] == scenario) & (curves["valuation_year"] == year))
    last = int(curves.loc[curve, "default_bucket"].max())
    gaps = {
        "a middle bucket of one grade": (curve & (curves["cohort"] == grades[0])
                                         & (curves["default_bucket"] == 2), "has gaps"),
        "the whole year behind a part-year bucket": (curve & (curves["cohort"] == grades[0])
                                                     & (curves["default_bucket"] == int(part["default_bucket"])),
                                                     "has gaps"),
        "the last bucket of every grade": (curve & (curves["default_bucket"] == last), "too short"),
    }
    for what, (drop, reason) in gaps.items():
        broken = Parameters(pit=params.pit, pd_curves=curves[~drop], facility=facility,
                            lgd_of_year=params.lgd_of_year)
        with pytest.raises(BlockingError) as err:
            performing_ecl(broken, portfolio, scenario, year, grades)
        assert err.value.code == Block.PARAMETER_ALIGNMENT and reason in str(err.value), what
    unknown = curves.copy()
    unknown.loc[curve & (unknown["cohort"] == grades[0]), "cohort"] = "not a grade"
    broken = Parameters(pit=params.pit, pd_curves=unknown, facility=facility, lgd_of_year=params.lgd_of_year)
    with pytest.raises(BlockingError) as err:
        performing_ecl(broken, portfolio, scenario, year, grades)
    assert err.value.code == Block.PARAMETER_ALIGNMENT and "unknown grade" in str(err.value)


@pytest.mark.control("Parameter alignment")
def test_parameter_alignment(core_run):
    ctx, _ = core_run
    params = builders.result(ctx, "parameters.parquet")
    key = ["facility_id", "scenario", "valuation_year", "cohort", "default_bucket", "basis"]
    assert not params.duplicated(key).any()
    assert set(params["basis"]) == {"accounting"}
    # Every ECL bucket term shares scenario, valuation date, bucket and basis with its PD.
    curves = builders.result(ctx, "pd_curves.parquet")
    assert set(curves["basis"]) == set(params["basis"])
    assert set(curves["valuation_year"]) == set(params["valuation_year"])
    buckets = builders.result(ctx, "ecl_buckets.parquet")
    prov = builders.result(ctx, "provisions.parquet")
    perf = prov[prov["stage"] < 3].groupby(["scenario", "year"])["allowance_on"].sum()
    by_bucket = buckets.groupby(["scenario", "valuation_year"])["ecl_on"].sum()
    assert np.allclose(perf.to_numpy(), by_bucket.to_numpy(), rtol=1e-9)


@pytest.mark.control("S3 parameter use")
def test_s3_bypasses_performing_pd(core_run, full_tables):
    ctx, _ = core_run
    s3_ids = set(full_tables["facilities"].loc[full_tables["facilities"]["ifrs_stage"] == 3, "facility_id"])
    params = builders.result(ctx, "parameters.parquet")
    assert not s3_ids & set(params["facility_id"]), "defaulted exposures get no performing parameters"
    prov = builders.result(ctx, "provisions.parquet")
    lgd = builders.result(ctx, "lgd_of_year.parquet").set_index(["facility_id", "scenario", "year"])["lgd"]
    booked = prov[prov["method"] == "s3_new_booking"]
    slices = builders.result(ctx, "slices.parquet").set_index(["scenario", "year", "facility_id", "slice"])
    gca = slices.loc[list(zip(booked["scenario"], booked["year"], booked["facility_id"], booked["slice"])), "gca"]
    expected = gca.to_numpy() * lgd.loc[list(zip(booked["facility_id"], booked["scenario"], booked["year"]))].to_numpy()
    assert np.allclose(booked["allowance_on"].to_numpy(), expected, rtol=1e-12), "flow x LGD, never x PD"


@pytest.mark.control("Missing scenario value")
def test_missing_scenario_value_blocks(mini, tmp_path):
    values = mini["scenarios"]["values"]
    mini["scenarios"]["values"] = [v for v in values if not (
        v["scenario"] == "adverse" and v["variable"] == "gdp_growth" and v["country"] == "IT" and v["year"] == 2028)]
    assert blocked(mini, tmp_path)["code"] == Block.MISSING_SCENARIO_VALUE


@pytest.mark.control("Missing mandatory benchmark")
def test_regulatory_mode_blocks(mini_tables, tmp_path, capsys):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    code = main(["run", "--inputs", inputs.as_posix(), "--mode", "regulatory", "--runs-dir", str(tmp_path / "runs")])
    assert code == 2 and "REGULATORY_MODE" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists() or not any((tmp_path / "runs").iterdir())


@pytest.mark.control("Scenario provenance")
def test_synthetic_scenario_labelled_official_blocks(mini, tmp_path):
    mini["scenarios"]["scenarios"][1]["status"] = "OFFICIAL"
    assert blocked(mini, tmp_path)["code"] == Block.SCENARIO_PROVENANCE


@pytest.mark.control("Static balance")
def test_static_balance(core_run):
    ctx, _ = core_run
    slices = builders.result(ctx, "slices.parquet")
    tol = tolerance("aggregate")
    for (scenario, year), part in slices.groupby(["scenario", "year"]):
        prev = slices[(slices["scenario"] == scenario) & (slices["year"] == slices["year"].min())]
        check_static(prev, part, tol)
    grown = slices[slices["year"] == slices["year"].max()].copy()
    grown.loc[grown.index[0], "gca"] += 10 * tol["abs"]
    with pytest.raises(BlockingError) as err:
        check_static(slices[slices["year"] == slices["year"].min()], grown, tol)
    assert err.value.code == Block.STATIC_BALANCE


@pytest.mark.control("Reproducibility")
def test_rerun_reproduces_every_output(mini_tables, tmp_path, capsys):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "in")
    ctx, first = builders.run(inputs, tmp_path / "runs")
    assert main(["rerun", "--run", ctx.run_dir.as_posix()]) == 0
    assert "reproduced" in capsys.readouterr().out
    _, second = builders.run(inputs, tmp_path / "runs")
    assert compare_outputs(first, second) == [] and first["outputs_digest"] == second["outputs_digest"]


@pytest.mark.control("Version change")
def test_version_change_difference_report(mini, mini_tables, tmp_path):
    base_ctx, base = builders.run(builders.write(builders.copy_tables(mini_tables), tmp_path / "a"), tmp_path / "ra")
    mini["parameter_set"]["segments"]["P05"]["lgd_w"] *= 2
    new_ctx, new = builders.run(builders.write(mini, tmp_path / "b"), tmp_path / "rb")
    assert base["input_set_hash"] != new["input_set_hash"]
    diff = compare_runs(base_ctx.run_dir, new_ctx.run_dir)
    p05 = diff[(diff["portfolio"] == "P05") & (diff["scenario"] == "adverse")]
    assert (p05["closing_on_diff"].abs() > 0).any(), "the impacted book shows a quantified difference"
    assert isinstance(diff, pd.DataFrame) and {"closing_on_base", "closing_on_new"} <= set(diff.columns)


@pytest.mark.control("Z-score and prepayment")
def test_missing_prepayment_rate_blocks(mini, tmp_path):
    mini["parameter_set"]["segments"]["P01"]["cpr_ttc"] = None
    b = blocked(mini, tmp_path)
    assert b["code"] == Block.MISSING_PARAMETER and "cpr_ttc" in b["message"]
