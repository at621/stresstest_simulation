"""Section 5.1-5.5 portfolio targets, plus the section 12.3 tolerances."""

import re

from foundation.transcribe.markdown import Spec, check_transcribed, first, numbers, to_float

RANGE = re.compile(r"(\d+(?:\.\d+)?)%?\s*[–-]\s*(\d+(?:\.\d+)?)(%?)")


def _clean(cell: str) -> str:
    return cell.replace("**", "").strip()


def _amount(cell: str) -> float | None:
    cell = _clean(cell)
    if cell in ("—", "-", ""):
        return None
    return to_float(cell)


def _range(cell: str) -> list[float]:
    match = RANGE.search(cell)
    if not match:
        raise ValueError(f"no range in {cell!r}")
    pct = match.group(3) == "%"
    return [to_float(match.group(1), pct), to_float(match.group(2), pct)]


def portfolio_targets(spec: Spec) -> dict:
    sizes = spec.table("### 5.1")
    portfolios: dict[str, dict] = {}
    totals: dict = {}
    for row in sizes:
        pid = _clean(row["ID"])
        record = {
            "facilities": int(to_float(_clean(row["Facilities"]))),
            "gca": _amount(row["GCA"]),
            "undrawn": _amount(row["Undrawn"]),
            "converted_total": _amount(row["Illustrative GCA + converted commitments"]),
        }
        if pid == "Total":
            totals = record
            continue
        ccf = _clean(row["Test CCF"])
        record["name"] = _clean(row["Portfolio"])
        record["ccf"] = None if ccf in ("—", "") else to_float(ccf.rstrip("%"), True)
        record["purpose"] = _clean(row["Primary test purpose"])
        portfolios[pid] = record
        check_transcribed(record, " ".join(row.values()), f"5.1 {pid}")

    stages: dict[str, dict] = {}
    for row in spec.table("### 5.2"):
        pid = _clean(row["Portfolio"])
        record = {
            "count": {s: int(to_float(_clean(row[f"Stage {s} count"]))) for s in (1, 2, 3)},
            "gca": {s: to_float(_clean(row[f"S{s} GCA"])) for s in (1, 2, 3)},
        }
        stages[pid] = record
        check_transcribed(record["gca"], " ".join(row.values()), f"5.2 {pid}")

    dims = {_clean(r["Dimension"]): r["Synthetic target"] for r in spec.table("### 5.3")}
    countries = {
        c: to_float(v, True) for c, v in re.findall(r"\b([A-Z]{2}) (\d+(?:\.\d+)?)%", dims["Borrower countries"])
    }
    irb_share = {
        p: to_float(v, True) for p, v in re.findall(r"\b(P0\d) (\d+(?:\.\d+)?)%", dims["IRB share"])
    }
    p06_text = dims["P06 counterparties"]
    p06_split = {
        "general_governments": first(r"(\d+%) general governments", p06_text),
        "credit_institutions": first(r"(\d+%) credit institutions", p06_text),
    }
    perimeter = spec.paragraph_containing("total opening IRB GCA target")
    approach_totals = {
        "IRB": first(r"IRB GCA target is €([\d,]+) million", perimeter, percent=False),
        "STA": first(r"STA target is €([\d,]+) million", perimeter, percent=False),
        "AC": first(r"reconcile to \*\*€([\d,]+) million AC\*\*", perimeter, percent=False),
    }
    p06_ac = first(r"All €([\d,]+) million at AC", dims["P06 accounting allocation"], percent=False)

    profiles: dict[str, dict] = {}
    for row in spec.table("### 5.4"):
        pid = _clean(row["Portfolio"])
        profiles[pid] = {
            "performing_pd": _range(row["Performing 12-month PD"]),
            "lgd": _range(row["ECL LGD"]),
            "residual_maturity_years": _range(row["Residual maturity"]),
            "attributes": _clean(row["Additional attributes"]),
        }
        extra = row["Additional attributes"]
        if "LTV" in extra:
            profiles[pid]["ltv"] = _range(extra.split("LTV", 1)[1])
        if "DSCR" in extra:
            dscr = re.search(r"DSCR (\d+(?:\.\d+)?)[–-](\d+(?:\.\d+)?)", extra)
            profiles[pid]["dscr"] = [to_float(dscr.group(1)), to_float(dscr.group(2))]

    syn04 = spec.requirement("SYN-04")
    concentration = {
        p: to_float(v, True) for v, p in re.findall(r"(\d+)% of (P0\d) GCA", syn04)
    }
    top_groups = 10 if "ten largest connected groups" in syn04 else None

    sectors: dict[str, dict] = {}
    collateral: dict[str, list[str]] = {}
    for row in spec.table("### 5.5"):
        pid = _clean(row["Portfolio"])
        design = row["Required design"]
        shares = re.findall(r"\b([A-Z]) (\d+(?:\.\d+)?)%", design)
        if shares:
            sectors[pid] = {s: to_float(v, True) for s, v in shares}
        elif "NACE Rev. 2 L" in design:
            sectors[pid] = {"L": 1.0}
        listed = re.search(r"identify (.+?) collateral separately", design)
        if listed:
            collateral[pid] = [
                c.strip().replace(" ", "_")
                for c in re.split(r",\s*|\s+and\s+", listed.group(1))
                if c.strip()
            ]
        elif "Residential property collateral" in design:
            collateral[pid] = ["residential_property"]

    targets = {
        "source": {"document": spec.path.name, "version": spec.version, "sections": "5.1-5.5"},
        "status": "SYNTHETIC",
        "unit": "EUR_million",
        "currency": "EUR",
        "accounting_category": "AC",
        "nace_version": "NACE Rev. 2",
        "portfolios": portfolios,
        "totals": totals,
        "stages": stages,
        "countries": countries,
        "irb_share": irb_share,
        "approach_totals": approach_totals,
        "p06_counterparties": p06_split,
        "p06_ac_gca": p06_ac,
        "risk_profiles": profiles,
        "concentration_top_groups": {"groups": top_groups, "share_of_gca": concentration},
        "sectors": sectors,
        "collateral_types": collateral,
    }
    check_transcribed(countries, dims["Borrower countries"], "5.3 countries")
    check_transcribed(approach_totals, perimeter, "5.3 approach totals")
    return targets


def tolerances(spec: Spec) -> dict:
    rows = {_clean(r["Item"]): r["Proposed tolerance"] for r in spec.table("### 12.3")}
    prob = rows["Transition row sums and probability identities"]
    rate = rows["PD/LGD/CCF numerical test cases"]
    amount = rows["Individual test-case amounts"]
    aggregate = rows["Aggregate reconciliation"]
    agg_numbers = numbers(aggregate)
    out = {
        "counts": {"kind": "exact"},
        "probability_identity": {"kind": "abs", "abs": numbers(prob)[0]},
        "rate": {"kind": "abs", "abs": numbers(rate)[0]},
        "amount": {"kind": "abs", "abs": numbers(amount)[0]},
        "aggregate": {"kind": "max_abs_rel", "abs": agg_numbers[0], "rel": agg_numbers[1]},
    }
    check_transcribed(out, " ".join(rows.values()), "12.3 tolerances")
    return out
