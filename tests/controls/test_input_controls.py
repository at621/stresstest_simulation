"""Section 12.2 input controls: R3 rejects the defective record with a reason code, logs it
in rejections.parquet, and the record never reaches a total."""

import numpy as np
import pandas as pd
import pytest

from tests import builders


def run_with(mini, tmp_path):
    ctx, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    return ctx, builders.result(ctx, "rejections.parquet")


def first(mini, **where):
    fac = mini["facilities"]
    mask = np.ones(len(fac), dtype=bool)
    for col, value in where.items():
        mask &= fac[col] == value
    return fac.index[mask][0]


def reasons(rejections, record_id):
    return set(rejections.loc[rejections["record_id"] == record_id, "reason_code"])


@pytest.mark.control("Duplicate facility")
def test_duplicate_facility_rejected(mini, tmp_path):
    dup = mini["facilities"].iloc[[0]]
    mini["facilities"] = pd.concat([mini["facilities"], dup], ignore_index=True)
    fid = dup["facility_id"].iloc[0]
    ctx, rej = run_with(mini, tmp_path)
    rows = rej[(rej["record_id"] == fid) & (rej["reason_code"] == "DUPLICATE_FACILITY")]
    assert len(rows) == 2, "both copies are rejected; neither reaches a total"
    slices = builders.result(ctx, "slices.parquet")
    assert fid not in set(slices["facility_id"])
    start = builders.report(ctx, "starting_point_reconciliation.csv")
    cells = start[start["stage"] != "all"]
    assert (cells["loaded_count"] == cells["accepted_count"] + cells["rejected_count"]).all()


@pytest.mark.control("Currency and accounting scope")
def test_currency_and_accounting_scope(mini, tmp_path):
    fac = mini["facilities"]
    usd, fvoci, blank = fac.index[:3]
    fac.loc[usd, "currency"] = "USD"
    fac.loc[fvoci, "accounting_category"] = "FVOCI"
    fac.loc[blank, "currency"] = None
    com = mini["commitments"]
    com.loc[com.index[0], "asset_category"] = "AC"
    ids = fac.loc[[usd, fvoci, blank], "facility_id"].tolist()
    _, rej = run_with(mini, tmp_path)
    assert "NON_EUR_CURRENCY" in reasons(rej, ids[0])
    assert "NON_AC_ON_BALANCE" in reasons(rej, ids[1])
    assert "MISSING_CURRENCY" in reasons(rej, ids[2])
    assert "OFF_BALANCE_CATEGORY" in reasons(rej, com["commitment_id"].iloc[0])


@pytest.mark.control("Country or taxonomy mapping")
def test_unmapped_country(mini, tmp_path):
    obl = mini["obligors"]
    obl.loc[obl.index[0], "country"] = "XX"
    fids = mini["facilities"].loc[mini["facilities"]["obligor_id"] == obl["obligor_id"].iloc[0], "facility_id"]
    _, rej = run_with(mini, tmp_path)
    for fid in fids:
        assert "UNMAPPED_COUNTRY" in reasons(rej, fid)


@pytest.mark.control("Grade and stage")
def test_grade_must_explain_stage(mini, tmp_path):
    fac = mini["facilities"]
    missing = first(mini, ifrs_stage=1, segment="P01")
    conflict = first(mini, ifrs_stage=2, segment="P05")
    fac.loc[missing, "origination_grade"] = None
    fac.loc[conflict, "origination_grade"] = fac.loc[conflict, "current_grade"]  # no SICR left
    fac.loc[conflict, ["dpd", "watchlist", "forborne"]] = [0, False, False]  # and no trigger
    _, rej = run_with(mini, tmp_path)
    assert "MISSING_GRADE" in reasons(rej, fac.loc[missing, "facility_id"])
    assert "STAGE_GRADE_CONFLICT" in reasons(rej, fac.loc[conflict, "facility_id"])


@pytest.mark.control("Grade and stage")
def test_credit_status_must_be_complete_and_explain_stage(mini, tmp_path):
    # MIG-05 with the owner decision of 18 October 2026: a missing flag is never read as "no
    # trigger", each flag carries its observation date (section 4.2), and a flag on a facility
    # reported S1 is a stage the rule cannot explain.
    fac = mini["facilities"]
    snapshot = pd.Timestamp(fac["snapshot_date"].iloc[0])
    s1 = fac.index[fac["ifrs_stage"] == 1]
    no_dpd, no_watchlist, no_forborne, negative = s1[:4]
    undated = first(mini, ifrs_stage=1, segment="P03")
    later = first(mini, ifrs_stage=1, segment="P04")
    flagged = first(mini, ifrs_stage=1, segment="P05")
    assert len({no_dpd, no_watchlist, no_forborne, negative, undated, later, flagged}) == 7
    fac["dpd"] = fac["dpd"].astype("Int64")
    fac["watchlist"] = fac["watchlist"].astype(object)
    fac["forborne"] = fac["forborne"].astype(object)
    fac.loc[no_dpd, "dpd"] = pd.NA
    fac.loc[no_watchlist, "watchlist"] = None
    fac.loc[no_forborne, "forborne"] = None
    fac.loc[negative, "dpd"] = -1
    fac.loc[undated, "credit_status_date"] = None
    fac.loc[later, "credit_status_date"] = (snapshot + pd.Timedelta(days=1)).date().isoformat()
    fac.loc[flagged, "forborne"] = True
    _, rej = run_with(mini, tmp_path)
    for gone in (no_dpd, no_watchlist, no_forborne):
        assert "MISSING_FLAG" in reasons(rej, fac.loc[gone, "facility_id"])
    assert "INVALID_DPD" in reasons(rej, fac.loc[negative, "facility_id"])
    assert "INVALID_CREDIT_STATUS_DATE" in reasons(rej, fac.loc[undated, "facility_id"])
    assert "INVALID_CREDIT_STATUS_DATE" in reasons(rej, fac.loc[later, "facility_id"])
    assert "STAGE_GRADE_CONFLICT" in reasons(rej, fac.loc[flagged, "facility_id"])


@pytest.mark.control("Grade and stage")
def test_trigger_settings_are_required(mini, tmp_path):
    del mini["parameter_set"]["sicr_triggers"]
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "BLOCKED" and manifest["blocked"]["code"] == "MISSING_PARAMETER"


@pytest.mark.control("Grade and stage")
@pytest.mark.parametrize("defect", ["undefined trigger", "unknown trigger", "zero days", "definitions not a mapping",
                                    "empty source", "unsupported hold"])
def test_incomplete_trigger_settings_block_in_r3(mini, tmp_path, defect):
    settings = mini["parameter_set"]["sicr_triggers"]
    if defect == "undefined trigger":
        del settings["definitions"]["watchlist"]
    elif defect == "unknown trigger":
        settings["enabled"] = [*settings["enabled"], "arrears_flag"]
    elif defect == "zero days":
        settings["dpd_days"] = 0
    elif defect == "definitions not a mapping":
        settings["definitions"] = "see the credit policy"
    elif defect == "empty source":
        settings["source"] = " "
    else:
        settings["hold"] = "probation"
    _, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    blocked = manifest["blocked"]
    assert manifest["status"] == "BLOCKED" and blocked["code"] == "MISSING_PARAMETER" and blocked["step"] == "R3", defect


@pytest.mark.control("Cash-flow inputs")
def test_cash_flow_inputs(mini, tmp_path):
    fac = mini["facilities"]
    perf = fac.index[fac["ifrs_stage"] < 3][:3]
    fac.loc[perf[0], "residual_maturity"] = 0.0
    fac.loc[perf[1], "interest_rate"] = None
    fac.loc[perf[2], "interest_rate"] = -1.5
    _, rej = run_with(mini, tmp_path)
    assert "INVALID_MATURITY" in reasons(rej, fac.loc[perf[0], "facility_id"])
    assert "MISSING_RATE" in reasons(rej, fac.loc[perf[1], "facility_id"])
    assert "INVALID_RATE" in reasons(rej, fac.loc[perf[2], "facility_id"])


@pytest.mark.control("EAD/CCF contract")
def test_ead_ccf_contract(mini, tmp_path):
    """EAD-04 and EAD-09: these defects block the run; R3 logs every record behind the block."""
    com = mini["commitments"]
    assert len(com) >= 2
    com.loc[com.index[0], "accounting_ccf"] = None
    com.loc[com.index[1], "accounting_ccf"] = 1.2
    dup = com.iloc[[1]].assign(commitment_id="CDUP")
    mini["commitments"] = pd.concat([com, dup], ignore_index=True)
    fac = mini["facilities"]
    term = first(mini, product="term_loan")
    fac.loc[term, "contractual_limit"] = fac.loc[term, "principal"] / 2  # limit breach
    ctx, manifest = builders.run(builders.write(mini, tmp_path / "in"), tmp_path / "runs")
    assert manifest["status"] == "BLOCKED" and manifest["blocked"]["step"] == "R3"
    rej = builders.result(ctx, "rejections.parquet")
    assert "MISSING_CCF" in reasons(rej, com["commitment_id"].iloc[0])
    assert {"CCF_OUT_OF_RANGE", "DUPLICATE_COMMITMENT"} <= reasons(rej, com["commitment_id"].iloc[1])
    assert "LINKED_RECORD_REJECTED" in reasons(rej, com["facility_id"].iloc[0])
    assert "LIMIT_BREACH" in reasons(rej, fac.loc[term, "facility_id"])
    assert not (ctx.results_dir / "provisions.parquet").exists()


@pytest.mark.req("DAT-02", "OPS-07")
def test_missing_flag_is_never_a_default(mini, tmp_path):
    fac = mini["facilities"]
    fac["poci"] = fac["poci"].astype(object)
    fac.loc[fac.index[0], "poci"] = None
    ctx, rej = run_with(mini, tmp_path)
    assert "MISSING_FLAG" in reasons(rej, fac["facility_id"].iloc[0])
    summary = (ctx.reports_dir / "summary.md").read_text(encoding="utf-8")
    assert "DATA GAP" in summary, "rejected records stay visible (OPS-07)"


@pytest.mark.control("LGD rule")
def test_lgd_rule(mini, tmp_path):
    fac = mini["facilities"]
    fac.loc[fac.index[0], "ttc_lgd"] = None
    fac.loc[fac.index[1], "ttc_lgd"] = 1.3
    ctx, rej = run_with(mini, tmp_path)
    assert "MISSING_TTC_LGD" in reasons(rej, fac["facility_id"].iloc[0])
    assert "TTC_LGD_OUT_OF_RANGE" in reasons(rej, fac["facility_id"].iloc[1])
    params = builders.result(ctx, "parameters.parquet")
    assert params["lgd"].between(0.0, 1.0).all(), "every final LGD stays in [0, 1]"
