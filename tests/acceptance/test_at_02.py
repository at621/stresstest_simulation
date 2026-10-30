"""AT-02: stage arithmetic, opening balances times transition rows (MIG-01, MIG-02)."""

import pytest

from stress.projection.kernels import stage_flows
from tests import builders
from tests.support import assert_close, oracle, tolerance


@pytest.mark.at("AT-02")
def test_closing_stages_from_transition_rows(reference_runs, core_run):
    case = oracle("AT-02")
    closing, flows = stage_flows(case["input"]["opening"], case["input"]["transitions"],
                                 tolerance("probability_identity")["abs"])
    for stage, expected in case["expected"]["closing"].items():
        assert_close(closing[stage], expected, case["tolerance"], stage)
    assert_close(sum(closing.values()), case["expected"]["total"], case["tolerance"], "total")
    # Closing balances reconcile to all incoming flows (MIG-02).
    for dest in closing:
        assert_close(sum(flows[o][dest] for o in flows), closing[dest], case["tolerance"], dest)
    # The same case through the whole pipeline: R7 moves the opening book with the matrix.
    ctx, _ = reference_runs["core"]
    run = builders.result(ctx, "stage_flows.parquet")
    year = int(run["year"].min())
    mine = run[(run["segment"] == builders.REFERENCE_SEGMENTS["AT-02"]) & (run["year"] == year)]
    assert set(mine["scenario"]) == {"baseline", "adverse"}
    for scenario, rows in mine.groupby("scenario"):
        incoming = rows.groupby("to_stage")["gca"].sum()
        for stage, expected in case["expected"]["closing"].items():
            assert_close(incoming[int(stage[1])], expected, case["tolerance"], f"run {scenario} {stage}")
        assert_close(incoming.sum(), case["expected"]["total"], case["tolerance"], f"run {scenario} total")
    ids = [reference_runs["ids"][f"AT-02/{stage}"] for stage in case["input"]["opening"]]
    slices = builders.result(ctx, "slices.parquet")
    stock = slices[slices["facility_id"].isin(ids) & (slices["year"] == year)]
    for (scenario, stage), gca in stock.groupby(["scenario", "stage"])["gca"].sum().items():
        assert_close(gca, case["expected"]["closing"][f"S{stage}"], case["tolerance"], f"run {scenario} S{stage}")
    # On the real book, closing stages reconcile to all incoming flows every year (MIG-02).
    real, _ = core_run
    incoming = builders.result(real, "stage_flows.parquet").groupby(["scenario", "year", "to_stage"])["gca"].sum()
    stock = builders.result(real, "slices.parquet")
    stock = stock[stock["year"] > stock["year"].min()].groupby(["scenario", "year", "stage"])["gca"].sum()
    assert len(incoming) == len(stock)
    for key, value in incoming.items():
        assert_close(value, stock[key], case["tolerance"], f"real book {key}")
