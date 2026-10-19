"""Stage arithmetic (MIG-01, MIG-02, MIG-07, PD-05).

Opening stage balances times transition probabilities give the flows; closing balances are
the sum of incoming flows. S3 stays S3: no cure, sale or write-off removal (EXP-02).
"""

from collections.abc import Mapping

import numpy as np

STAGES = ("S1", "S2", "S3")


def stage_flows(opening: Mapping[str, float], transitions: Mapping[str, Mapping[str, float]],
                tol: float) -> tuple[dict, dict]:
    """Closing stage balances and the flow matrix from opening balances and transition rows.

    Every row must sum to one within ``tol`` with no negative value (MIG-01); S3 stays S3.
    """
    for origin, row in transitions.items():
        probs = np.array([row.get(s, 0.0) for s in STAGES])
        if (probs < 0).any() or abs(probs.sum() - 1.0) > tol:
            raise ValueError(f"transition row {origin} is not a probability distribution")
    if transitions.get("S3", {"S3": 1.0}).get("S3", 0.0) != 1.0:
        raise ValueError("S3 must stay S3")
    flows = {
        origin: {dest: opening.get(origin, 0.0) * transitions.get(origin, {}).get(dest, 0.0)
                 for dest in STAGES}
        for origin in STAGES
    }
    flows["S3"] = {"S1": 0.0, "S2": 0.0, "S3": opening.get("S3", 0.0)}
    closing = {dest: sum(flows[origin][dest] for origin in STAGES) for dest in STAGES}
    return closing, flows


def aligned_default_flows(opening: Mapping[str, float], pd: Mapping[str, float]) -> dict:
    """PD-05: new default flow per origin stage is opening GCA times that stage's PD, and
    closing S3 is opening S3 plus those flows. The rest stays performing."""
    new = {stage: opening[stage] * pd[stage] for stage in ("S1", "S2")}
    closing_s3 = opening["S3"] + sum(new.values())
    performing = opening["S1"] + opening["S2"] - sum(new.values())
    return {"new_default_flows": new, "closing_s3": closing_s3,
            "closing_performing": performing, "total": closing_s3 + performing}


def stage_of_rank(rank, sicr_rank, default_rank: int, flagged=None):
    """MIG-07 by grade rank: 3 for D, 2 at or beyond the facility's SICR line, else 1. A facility
    with a qualitative trigger (MIG-05, A30) is 2 in every performing grade until it defaults."""
    rank = np.asarray(rank)
    sicr_rank = np.asarray(sicr_rank)
    s2 = rank >= sicr_rank
    if flagged is not None:
        s2 = s2 | np.asarray(flagged, dtype=bool)
    return np.where(rank >= default_rank, 3, np.where(s2, 2, 1))
