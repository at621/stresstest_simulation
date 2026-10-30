"""Exercise the optional package against real pipeline contracts, then replay its snapshot."""

import argparse

import numpy as np
import pandas as pd
import pytest
import yaml

from foundation.synth.analysis import build
from stress import cli, params
from stress.contracts.errors import BlockingError
from stress.contracts.run import RunConfig
from stress.validate.sicr import remaining_horizon_diagnostic
from tests import builders
from tests.support import oracle


@pytest.mark.req("MOD-03", "CAP-03", "RPT-05", "OPS-04")
def test_preparation_package_and_replay_use_real_contracts(mini, tmp_path):
    inputs = builders.write(mini, tmp_path / "inputs")
    package = tmp_path / "analysis.yaml"
    package.write_text(yaml.safe_dump(build(inputs)), encoding="utf-8")
    config = RunConfig(str(inputs), ("baseline", "adverse"), "core", analysis=str(package),
                       terminal_treatment="parameters")
    ctx, manifest = cli.execute(config, tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    for name in ("capital", "regulatory_exposure", "climate", "benchmark_selection", "recovery_lgd",
                 "sensitivity", "reverse_stress", "sicr_horizon", "calibration"):
        assert (ctx.results_dir / f"analysis_{name}.parquet").is_file()
    assert (ctx.reports_dir / "analysis_mapped_cells.csv").is_file()
    # Independent bucket-one arithmetic proves the 2029 S1 product override was bypassed.
    slices = pd.read_parquet(ctx.results_dir / "slices.parquet")
    slices = slices.loc[slices.stage.eq(1) & slices.year.eq(2029)]
    fac = pd.read_parquet(ctx.data_dir / "facilities.parquet")
    obl = pd.read_parquet(ctx.data_dir / "obligors.parquet")
    info = fac[["facility_id", "obligor_id", "segment", "gca"]].merge(obl[["obligor_id", "country"]], on="obligor_id")
    rows = slices.merge(info.rename(columns={"gca": "static_gca"}), on="facility_id")
    curve = pd.read_parquet(ctx.results_dir / "pd_curves.parquet")
    curve = curve.loc[curve.valuation_year.eq(2029) & curve.default_bucket.eq(1)]
    rows = rows.merge(curve[["scenario", "segment", "country", "cohort", "m"]],
                      left_on=["scenario", "segment", "country", "grade"],
                      right_on=["scenario", "segment", "country", "cohort"])
    values = pd.read_parquet(ctx.results_dir / "parameters.parquet")
    values = values.loc[values.valuation_year.eq(2029) & values.default_bucket.eq(1)]
    rows = rows.merge(values[["facility_id", "scenario", "fraction", "ead_drawn", "lgd", "discount_factor"]],
                      on=["facility_id", "scenario"])
    expected = rows.gca/rows.static_gca * rows.m * rows.fraction * rows.ead_drawn * rows.lgd * rows.discount_factor
    assert np.allclose(rows.allowance_on, expected, rtol=1e-10, atol=1e-8)
    # Report rates retain rate precision instead of currency rounding.
    recovery = pd.read_parquet(ctx.results_dir / "analysis_recovery_lgd.parquet")
    csv = pd.read_csv(ctx.reports_dir / "analysis_recovery_lgd.csv")
    assert np.allclose(csv.lgd, recovery.lgd, rtol=0, atol=1e-10)
    # Move only the generated pytest input set inside this test's workspace.
    assert inputs.resolve().is_relative_to(tmp_path.resolve())
    inputs.rename(inputs.with_name("unavailable-original-inputs"))
    package.unlink()
    assert cli.cmd_rerun(argparse.Namespace(run=str(ctx.run_dir), runs_dir=str(tmp_path / "replays"))) == 0


@pytest.mark.req("EAD-11")
def test_nonfinite_internal_prepayment_blocks(monkeypatch):
    monkeypatch.setattr(params, "prepayment_rate", lambda *a: np.array([np.nan]))
    schedule = pd.DataFrame({"facility_id": ["F"], "valuation_year": [2026], "period": [1],
                             "fraction": [1.], "bucket_year": [2027], "t": [1.],
                             "opening_balance": [1.], "discount_factor": [1.]})
    port = pd.DataFrame({"facility_id": ["F"], "segment": ["S"], "country": ["DE"],
                         "ttc_lgd": [.5], "undrawn": [0.], "ccf": [np.nan]})
    z = pd.DataFrame({"segment": ["S"], "country": ["DE"], "scenario": ["baseline"], "year": [2027], "z": [0.]})
    ps = {"segments": {"S": {"lgd_w": 0., "cpr_ttc": 0., "cpr_v": 0.}}}
    with pytest.raises(BlockingError, match="non-finite prepayment"):
        params.facility_parameters(schedule, port, z, ps, {}, ["baseline"])


@pytest.mark.req("MIG-07")
def test_remaining_horizon_can_change_the_sicr_line():
    p = oracle("AT-34")["input"]["pd"]
    matrix = np.array([[1-p, 0., p], [0., 1-3*p, 3*p], [0., 0., 1.]])
    port = pd.DataFrame({"facility_id": ["F"], "stage": [1], "segment": ["S"],
                         "origination_rank": [1], "sicr_rank": [3]})
    schedule = pd.DataFrame({"facility_id": ["F", "F"], "valuation_year": [2026, 2027],
                             "remaining_maturity": [2., 1.], "generation": [0, 0]})
    result = remaining_horizon_diagnostic(port, schedule, {"S": matrix}, {"S": {"sicr_k": 3.}})
    assert list(result.remaining_horizon_rank) == [3, 2]
    assert list(result.changed) == [False, True]
