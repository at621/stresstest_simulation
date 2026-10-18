"""Section 12.1 acceptance cases as oracle records: input, expected value, tolerance and the
named wrong answer. Every number is read from the row text by a keyword pattern and checked
against it, so none is typed by hand. The numerical parts of AT-48, AT-51 and AT-52 stay OPEN.
"""

import re

from foundation.transcribe.markdown import (
    WORD_NUMBERS,
    Spec,
    check_transcribed,
    first,
    numbers,
    to_float,
)

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
REQ_ID = re.compile(r"\b([A-Z]{2,4}(?:-[A-Z]{3})?-\d{2})\b")


def _row_map(spec: Spec) -> dict[str, dict[str, str]]:
    rows = {}
    for row in spec.table("### 12.1"):
        rows[row["ID"].strip()] = {"input": row["Test input"], "expected": row["Expected result"]}
    return rows


def _word(pattern: str, text: str) -> float:
    """A number written as a word, such as "three" or "five-sixths"."""
    return WORD_NUMBERS[re.search(pattern, text).group(1).lower()]


def _date(pattern: str, text: str) -> str:
    """An ISO date from a phrase such as "31 December 2026"."""
    day, month, year = re.search(pattern, text).group(1).split()
    return f"{year}-{MONTHS.index(month) + 1:02d}-{int(day):02d}"


def _pcts(text: str) -> list[float]:
    return [to_float(v, True) for v in re.findall(r"(-?\d+(?:\.\d+)?)%", text)]


# Each builder gets (input text, expected text, spec) and returns the record's parts.
# Tolerance names refer to the section 12.3 tolerances in targets.yaml.

def at01(i, e, spec):
    return {
        "input": {"targets": "section 5 (targets.yaml)"},
        "expected": {
            "facilities": int(first(r"([\d,]+) facilities", e, False)),
            "gca_m": first(r"GCA €([\d,]+)m", e, False),
            "undrawn_m": first(r"undrawn €([\d,]+)m", e, False),
            "converted_total_m": first(r"converted total €([\d,]+)m", e, False),
        },
        "tolerance": "aggregate",
        "unit": "EUR_million",
    }


def at02(i, e, spec):
    opening = [to_float(v) for v in re.search(r"= ([\d/]+);", i).group(1).split("/")]
    s1 = _pcts(re.search(r"S1 transitions ([\d%/.]+)", i).group(1))
    s2 = _pcts(re.search(r"S2 transitions ([\d%/.]+)", i).group(1))
    closing = [to_float(v) for v in re.search(r"= ([\d/]+);", e).group(1).split("/")]
    return {
        "input": {"opening": {"S1": opening[0], "S2": opening[1], "S3": opening[2]},
               "transitions": {"S1": {"S1": s1[0], "S2": s1[1], "S3": s1[2]},
                               "S2": {"S1": s2[0], "S2": s2[1], "S3": s2[2]},
                               "S3": {"S3": 1.0}}},
        "expected": {"closing": {"S1": closing[0], "S2": closing[1], "S3": closing[2]},
                  "total": first(r"total ([\d,]+)", e, False)},
        "tolerance": "amount",
        "extra_source": "S3 stays S3 means a transition of one",
        "allow": [1.0],
    }


def at03(i, e, spec):
    return {
        "input": {"exposure": first(r"S3 exposure ([\d.]+)", i, False),
               "opening_allowance": first(r"opening allowance ([\d.]+)", i, False),
               "loss_rate": first(r"loss rate ([\d.]+%)", i)},
        "expected": {"allowance": first(r"remains ([\d.]+)", e, False)},
        "tolerance": "amount",
    }


def at04(i, e, spec):
    return {
        "input": {"flow": first(r"flow ([\d.]+)", i, False), "lgd": first(r"LGD ([\d.]+%)", i)},
        "expected": {"allowance": first(r"allowance ([\d.]+)", e, False), "bookings": 1},
        "tolerance": "amount",
        "allow": [1.0],
    }


def at05(i, e, spec):
    return {
        "input": {"exposure": first(r"exposure ([\d.]+)", i, False),
               "pd": first(r"PD ([\d.]+%)", i), "lgd": first(r"LGD ([\d.]+%)", i),
               "discount_factor": 1},
        "expected": {"provision": first(r"provision ([\d.]+)", e, False)},
        "tolerance": "amount",
        "extra_source": "simplified loss-rate example: no discounting, factor one",
        "allow": [1.0],
    }


def at06(i, e, spec):
    adv = _pcts(re.search(r"adverse PD/LGD ([\d.%/]+)", i).group(1))
    base = _pcts(re.search(r"baseline ([\d.%/]+)", i).group(1))
    loss = _pcts(e)
    return {
        "input": {"adverse": {"pd": adv[0], "lgd": adv[1]}, "baseline": {"pd": base[0], "lgd": base[1]},
               "valuation_year": int(first(r"End-(\d{4})", i, False))},
        "expected": {"adverse_loss_rate": loss[0], "baseline_loss_rate": loss[1],
                  "weights": {"adverse": _word(r"([\w-]+) of [\d.]+% plus", e),
                              "baseline": _word(r"plus ([\w-]+) of", e)},
                  "interpolated_loss_rate": loss[2],
                  "bucket_year": int(first(r"Draft's (\d{4})", e, False))},
        "tolerance": "rate",
        "extra_source": i.replace("End-", "End "),
    }


def at07(i, e, spec):
    return {
        "input": {"opening": first(r"from ([\d.]+)", i, False), "closing": first(r"to ([\d.]+)", i, False)},
        "expected": {"charge": first(r"charge ([\d.]+)", e, False)},
        "wrong_answers": [{"value": first(r"not ([\d.]+)", e, False), "why": "expensing the full closing stock"}],
        "tolerance": "amount",
    }


def at08(i, e, spec):
    wrong = numbers(re.search(r"not (.+)$", e).group(1))
    return {
        "input": {"drawn": first(r"Drawn ([\d.]+)", i, False), "undrawn": first(r"undrawn ([\d.]+)", i, False),
               "ccf": first(r"CCF ([\d.]+%)", i)},
        "expected": {"ead_total": first(r"exposure ([\d.]+)", e, False)},
        "wrong_answers": [{"value": wrong[0], "why": "drawn plus full undrawn"},
                       {"value": wrong[1], "why": "full undrawn plus its converted amount (counted twice)"}],
        "tolerance": "amount",
    }


def at10(i, e, spec):
    start = [to_float(v) for v in re.search(r"REA ([\d]+/[\d]+); raw", i).group(1).split("/")]
    raw = [to_float(v) for v in re.search(r"raw stressed REA ([\d]+/[\d]+)", i).group(1).split("/")]
    return {
        "input": {"starting": {"IRB": start[0], "STA": start[1]}, "raw": {"IRB": raw[0], "STA": raw[1]}},
        "expected": {"credit_contribution": first(r"= ([\d.]+)", e, False)},
        "tolerance": "amount",
    }


def at11(i, e, spec):
    m = re.search(r"max\((\d+),\s*(\d+)\) = (\d+)", e)
    return {
        "input": {"utrea": first(r"UTREA ([\d.]+)", i, False), "strea": first(r"STREA ([\d.]+)", i, False),
               "factor": first(r"factor ([\d.]+%)", i)},
        "expected": {"floored_strea": to_float(m.group(2)), "result": to_float(m.group(3))},
        "tolerance": "amount",
        "notes": "The example does not set the transitional rule.",
    }


def at16(i, e, spec):
    return {
        "input": {"annual_changes": _pcts(i), "initial_index": first(r"initial ([\d.]+)", e, False)},
        "expected": {"terminal_index": first(r"index ([\d.]+)", e, False)},
        "wrong_answers": [{"why": "adding annual percentage changes instead of compounding (SCN-05)"}],
        "tolerance": "rate",
    }


def at18(i, e, spec):
    return {
        "input": {"A": {"change": -first(r"falls ([\d.]+)", i, False)},
               "B": {"change": first(r"rises ([\d.]+)", i, False)}},
        "expected": {"A_release_rejected": True, "aggregate_raw_change": first(r"rise ([\d.]+)", e, False)},
        "wrong_answers": [{"why": "checking the no-release rule on the aggregate instead of per exposure"}],
        "tolerance": "amount",
        "extra_source": i + " -" + str(first(r"falls ([\d.]+)", i, False)),
    }


def at21(i, e, spec):
    return {
        "input": {"scope": i},
        "expected": {"currency": "EUR", "fx_movement": 0},
        "tolerance": "counts",
        "allow": [0.0],
    }


def at22(i, e, spec):
    return {
        "input": {"allocation": "section 5.3 (targets.yaml)"},
        "expected": {"ac_gca_m": first(r"AC GCA €([\d,]+)m", e, False),
                  "p06_ac_gca_m": first(r"P06 AC €([\d,]+)m", e, False),
                  "fvoci_fvpl_gca_m": 0,
                  "stage_totals": "section 5.2", "approach_totals": "section 5.3"},
        "tolerance": "aggregate",
        "unit": "EUR_million",
        "allow": [0.0],
    }


def at25(i, e, spec):
    return {
        "input": {"conditional_pd": _pcts(i)},
        "expected": {"marginal_pd": _pcts(re.search(r"Marginal PDs ([^;]+)", e).group(1)),
                  "cumulative_pd": _pcts(re.search(r"cumulative PDs ([^;]+)", e).group(1)),
                  "terminal_survival": first(r"terminal survival ([\d.]+%)", e)},
        "wrong_answers": [{"why": "summing conditional PDs to obtain cumulative PD (PD-03)"}],
        "tolerance": "rate",
    }


def at28(i, e, spec):
    return {
        "input": {"annual_pd": first(r"PD ([\d.]+%)", i), "fraction": first(r"interval ([\d.]+) years", i, False)},
        "expected": {"stub_pd": first(r"= ([\d.]+%)$", e)},
        "tolerance": "rate",
    }


def at29(i, e, spec):
    gca = [to_float(v) for v in re.search(r"GCA ([\d/]+);", i).group(1).split("/")]
    pds = _pcts(re.search(r"PDs ([\d.%/]+)", i).group(1))
    flows = [to_float(v) for v in re.search(r"flows ([\d]+) and ([\d]+)", e).groups()]
    return {
        "input": {"opening": {"S1": gca[0], "S2": gca[1], "S3": gca[2]}, "pd": {"S1": pds[0], "S2": pds[1]}},
        "expected": {"new_default_flows": {"S1": flows[0], "S2": flows[1]},
                  "closing_s3": first(r"closing S3 ([\d,]+)", e, False),
                  "closing_performing": first(r"performing total ([\d,]+)", e, False),
                  "total": first(r"total GCA ([\d,]+)", e, False)},
        "tolerance": "amount",
    }


def at33(i, e, spec):
    return {
        "input": {"ead": 0, "recovery": 0},
        "expected": {"lgd": "not_applicable", "loss": 0},
        "tolerance": "amount",
        "allow": [0.0],
    }


def at34(i, e, spec):
    ead = numbers(re.search(r"drawn/undrawn/total ([\d,/ ]+);", e).group(1))
    return {
        "input": {"drawn": first(r"Drawn ([\d,]+)", i, False), "undrawn": first(r"undrawn ([\d,]+)", i, False),
               "ccf": first(r"CCF ([\d.]+%)", i), "pd": first(r"PD ([\d.]+%)", i),
               "lgd": first(r"LGD ([\d.]+%)", i), "discount_factor": first(r"DF ([\d.]+)", i, False)},
        "expected": {"ead_drawn": ead[0], "ead_undrawn": ead[1], "ead_total": ead[2],
                  "ecl_on": first(r"ECL ([\d,]+) on-balance", e, False),
                  "ecl_off": first(r"([\d,]+) off-balance", e, False),
                  "ecl_total": first(r"= ([\d,]+)$", e, False)},
        "tolerance": "amount",
    }


def at35(i, e, spec):
    return {
        "input": {"base_case": "AT-34", "ccf_from": first(r"from ([\d.]+%)", i), "ccf_to": first(r"to ([\d.]+%)", i)},
        "expected": {"ead_from": first(r"EAD rises from ([\d,]+)", e, False),
                  "ead_to": first(r"EAD rises from [\d,]+ to ([\d,]+)", e, False),
                  "ecl_from": first(r"ECL rises from ([\d,]+)", e, False),
                  "ecl_to": first(r"ECL rises from [\d,]+ to ([\d,]+)", e, False),
                  "nominal_unchanged": True, "in_core_run": False},
        "tolerance": "amount",
    }


def at36(i, e, spec):
    return {
        "input": {"drawn": first(r"drawn ([\d.]+)", i, False), "undrawn": first(r"undrawn ([\d.]+)", i, False),
               "transfer": first(r"transfer ([\d.]+)", i, False), "ccf": first(r"CCF ([\d.]+%)", i)},
        "expected": {"drawn": first(r"Drawn ([\d.]+)", e, False), "undrawn": first(r"undrawn ([\d.]+)", e, False),
                  "limit": first(r"limit remains ([\d,]+)", e, False),
                  "ead_total": first(r"EAD ([\d.]+)", e, False)},
        "wrong_answers": [{"why": "counting the transferred amount again as undrawn"}],
        "tolerance": "amount",
    }


def at37(i, e, spec):
    return {
        "input": {"principal": first(r"Principal ([\d.]+)", i, False),
               "accrued_interest": first(r"accrued interest ([\d.]+)", i, False),
               "gca": first(r"GCA ([\d.]+)", i, False), "accrued_in_gca": True, "undrawn": 0},
        "expected": {"ead_drawn": first(r"EAD ([\d.]+)", e, False)},
        "wrong_answers": [{"value": first(r"not ([\d.]+)", e, False), "why": "adding accrued interest twice"}],
        "tolerance": "amount",
        "allow": [0.0],
    }


def at38(i, e, spec):
    return {
        "input": {"drawn": first(r"Drawn ([\d.]+)", i, False), "undrawn": first(r"undrawn ([\d.]+)", i, False),
               "accounting_ccf": first(r"accounting CCF ([\d.]+%)", i),
               "regulatory_ccf": first(r"regulatory CCF ([\d.]+%)", i), "other_adjustments": 0},
        "expected": {"accounting_ead": first(r"Accounting EAD ([\d.]+)", e, False),
                  "regulatory_ead": first(r"regulatory EAD ([\d.]+)", e, False),
                  "ccf_bridge": first(r"bridge \+([\d.]+)", e, False)},
        "wrong_answers": [{"why": "applying both CCFs sequentially to the same exposure (EAD-04)"}],
        "tolerance": "amount",
        "allow": [0.0],
    }


def at39(i, e, spec):
    return {
        "input": {"pd_curve": "AT-25", "ead": first(r"EAD ([\d,]+)", i, False), "lgd": first(r"LGD ([\d.]+%)", i),
               "eir": first(r"EIR ([\d.]+%)", i),
               "remaining_life_years": _word(r"remaining life (\w+) years", i)},
        "expected": {"s1_ecl": first(r"ECL ([\d.]+);", e, False),
                  "s2_ecl": first(r"lifetime ECL ([\d.]+)", e, False),
                  "s2_ecl_displayed": first(r"rounded to ([\d.]+)", e, False)},
        "wrong_answers": [{"value": first(r"not ([\d.]+)", e, False), "why": "summing conditional PDs"}],
        "tolerance": "amount",
    }


def at40(i, e, spec):
    return {
        "input": {"ead": first(r"EAD ([\d.]+)", i, False), "marginal_pd": first(r"marginal PD ([\d.]+%)", i),
               "lgd": first(r"LGD ([\d.]+%)", i), "eir": first(r"EIR ([\d.]+%)", i), "buckets": 1},
        "expected": {"undiscounted_ecl": first(r"= ([\d.]+) /", e, False),
                  "discount_divisor": first(r"/ ([\d.]+) =", e, False),
                  "ecl": first(r"= [\d.]+ / [\d.]+ = ([\d.]+)", e, False)},
        "wrong_answers": [{"why": "reapplying default-to-recovery discounting"}],
        "tolerance": "rate",
        "allow": [1.0],
    }


def at41(i, e, spec):
    return {
        "input": {"valuation_year": int(first(r"End-(\d{4})", i, False)),
               "missing": re.search(r"required (\S+) input", i).group(1) + " input"},
        "expected": {"blocked": True, "terminal_case": "AT-06"},
        "wrong_answers": [{"why": "setting next-year PD or ECL to zero"}],
        "tolerance": "counts",
        "extra_source": i.replace("End-", "End "),
    }


def at42(i, e, spec):
    return {
        "input": {"segment": re.match(r"(P0\d)", i).group(1), "stage": 1,
               "valuation_date": _date(r"valuation (\d+ December \d{4})", i),
               "default_bucket_end": _date(r"default bucket (\d+ December \d{4})", i),
               "pd": first(r"bucket ([\d.]+%)", i), "lgd": first(r"LGD ([\d.]+%)", i),
               "drawn": first(r"drawn ([\d,]+)", i, False), "undrawn": first(r"undrawn ([\d,]+)", i, False),
               "ccf": first(r"CCF ([\d.]+%)", i), "profile": "bullet", "prepayment_rate": 0,
               "eir": first(r"EIR ([\d.]+%)", i)},
        "expected": {"ead_total": first(r"EAD ([\d,]+)", e, False),
                  "ecl": first(r"ECL ([\d,.]+),", e, False),
                  "ecl_displayed": first(r"displayed as ([\d,.]+)", e, False)},
        "tolerance": "amount",
        "allow": [0.0, 1.0],
    }


def at44(i, e, spec):
    return {
        "input": {"books": "section 5.1", "configuration": "section 8.7 fixed-CCF core"},
        "expected": {"gca_m": first(r"GCA €([\d,]+)m", e, False),
                  "undrawn_m": first(r"undrawn €([\d,]+)m", e, False),
                  "converted_commitments_m": first(r"converted commitments €([\d,]+)m", e, False),
                  "total_m": first(r"total €([\d,]+)m", e, False),
                  "P03_total_m": first(r"P03 €([\d,]+)m", e, False),
                  "P05_total_m": first(r"P05 €([\d,]+)m", e, False)},
        "tolerance": "aggregate",
        "unit": "EUR_million",
    }


def at45(i, e, spec):
    return {
        "input": {"matrices": "every TTC matrix (PD-09)"},
        "expected": {"row_sum_tolerance": first(r"within (1e-\d+)", e, False), "negative_cells": 0,
                  "default_absorbing": True, "invalid_matrix_blocked": True},
        "tolerance": "probability_identity",
        "allow": [0.0],
    }


def at46(i, e, spec):
    return {
        "input": {"matrices": "TTC matrix and PiT shifts for several Z values"},
        "expected": {"row_sum_tolerance": first(r"within (1e-\d+)", e, False), "pd_rises_with_grade": True},
        "tolerance": "probability_identity",
    }


def at47(i, e, spec):
    return {
        "input": {"z": "lowered, everything else fixed"},
        "expected": {"pd_rises_as_z_falls": True},
        "tolerance": "rate",
    }


def at48(i, e, spec):
    return {
        "input": {"origination_grade": "supplied by the case", "k": "supplied", "matrix": "TTC"},
        "expected": {"rule": "S2 exactly when lifetime PD >= k x lifetime PD at origination grade; "
                          "S3 in D; S1 otherwise; returns to S1 when improving back over the line; "
                          "D never cures",
                  "stage_per_grade": "OPEN"},
        "tolerance": "counts",
        "status": "PARTLY_OPEN",
        "open": ["Expected stage per grade: OPEN until approved by the project owner"],
    }


def at49(i, e, spec):
    return {
        "input": {"lgd_ttc_boundaries": [0, 1], "lgd_ttc_interior": "an interior value",
               "z": {"zero": 0, "negative": "Z < 0"}},
        "expected": {"z_zero_returns_ttc_within": first(r"within (1e-\d+)", e, False),
                  "boundaries_pass_through": True, "interior_rises_as_z_falls": True,
                  "interior_below_one": True},
        "tolerance": "rate",
        "allow": [0.0, 1.0],
    }


def at50(i, e, spec):
    return {
        "input": {"prepayment_rate": "positive", "undrawn": "positive"},
        "expected": {"sp_first_bucket": 1, "ead_drawn": "B[k] x SP[k]", "undrawn_prepaid": False,
                  "survival_unchanged_by_prepayment": True, "zero_rate_gives_contractual_balance": True},
        "tolerance": "rate",
        "allow": [1.0],
    }


def at51(i, e, spec):
    return {
        "input": {"profiles": ["bullet", "annuity", "linear"], "stub": "one facility with a stub final period"},
        "expected": {"bullet": "balance flat at D until M", "annuity": "constant payment, closing balance 0 at M",
                  "linear": "principal D / M each year", "stub": "fraction d in the final period",
                  "accrued_interest": "counted once", "schedule_values": "OPEN"},
        "tolerance": "amount",
        "status": "PARTLY_OPEN",
        "open": ["Schedule values: OPEN until approved by the project owner"],
        "allow": [0.0],
    }


def at52(i, e, spec):
    ecl10 = spec.requirement("ECL-10")
    weights_text = re.search(r"adverse weights a\(t\) of ([^f]+?) for (\d{4})–(\d{4}) and (\d+) from (\d{4})", ecl10)
    fractions = re.findall(r"(\d+)/(\d+)|\b(0)\b", weights_text.group(1))
    weights = [int(a) / int(b) if a else 0.0 for a, b, zero in fractions]
    first_year, last_year = int(weights_text.group(2)), int(weights_text.group(3))
    flat_from = int(weights_text.group(5))
    years = list(range(first_year, last_year + 1))
    return {
        "input": {"drivers": "supplied by the case", "coefficients": "supplied, one case with a missing coefficient"},
        "expected": {"z_at_means": 0, "missing_coefficient_blocks": True,
                  "adverse_weights": dict(zip(years, weights)),
                  "weight_from": {"year": flat_from, "weight": to_float(weights_text.group(4))},
                  "baseline": "flat at its 2029 value",
                  "z_values": "OPEN"},
        "tolerance": "rate",
        "status": "PARTLY_OPEN",
        "open": ["Z values: OPEN until approved by the project owner"],
        "extra_source": ecl10,
        "allow": [0.0],
    }


BUILDERS = {
    "AT-01": at01, "AT-02": at02, "AT-03": at03, "AT-04": at04, "AT-05": at05, "AT-06": at06,
    "AT-07": at07, "AT-08": at08, "AT-10": at10, "AT-11": at11, "AT-16": at16, "AT-18": at18,
    "AT-21": at21, "AT-22": at22, "AT-25": at25, "AT-28": at28, "AT-29": at29, "AT-33": at33,
    "AT-34": at34, "AT-35": at35, "AT-36": at36, "AT-37": at37, "AT-38": at38, "AT-39": at39,
    "AT-40": at40, "AT-41": at41, "AT-42": at42, "AT-44": at44, "AT-45": at45, "AT-46": at46,
    "AT-47": at47, "AT-48": at48, "AT-49": at49, "AT-50": at50, "AT-51": at51, "AT-52": at52,
}


def oracles(spec: Spec, tolerances: dict) -> dict[str, dict]:
    rows = _row_map(spec)
    missing = sorted(set(rows) - set(BUILDERS))
    if missing:
        raise ValueError(f"acceptance cases without a transcription rule: {missing}")
    out = {}
    for at_id, builder in BUILDERS.items():
        if at_id not in rows:
            raise ValueError(f"{at_id} is not in section 12.1")
        i, e = rows[at_id]["input"], rows[at_id]["expected"]
        parts = builder(i, e, spec)
        source = " ".join([i, e, parts.pop("extra_source", "")])
        allow = parts.pop("allow", [])
        allowed_text = source + " " + " ".join(repr(a) for a in allow)
        for part in ("input", "expected", "wrong_answers"):
            check_transcribed(parts.get(part, []), allowed_text, f"{at_id} {part}")
        tol_name = parts.pop("tolerance")
        refs = sorted(set(REQ_ID.findall(i + " " + e)) - {at_id})
        record = {
            "id": at_id,
            "status": parts.pop("status", "TRANSCRIBED"),
            "source": {"document": spec.path.name, "version": spec.version, "section": "12.1"},
            "source_text": {"input": i, "expected": e},
            "references": refs,
            "unit": parts.pop("unit", "EUR"),
            "input": parts.pop("input"),
            "expected": parts.pop("expected"),
            "tolerance": {"name": tol_name, **tolerances[tol_name]},
            "wrong_answers": parts.pop("wrong_answers", []),
        }
        if "open" in parts:
            record["open"] = parts.pop("open")
        if "notes" in parts:
            record["notes"] = parts.pop("notes")
        if parts:
            raise ValueError(f"{at_id}: unused parts {sorted(parts)}")
        out[at_id] = record
    return out
