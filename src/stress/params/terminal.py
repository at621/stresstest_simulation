"""Buckets after 2029 from the reverted Z (ECL-10, SYN-PAR-04).

R4 extends Z past the last scenario year by the terminal rule. Here every bucket a facility
needs is looked up; a missing terminal year blocks the calculation and is never zero (AT-41).
"""

from collections.abc import Iterable

import pandas as pd

from stress.contracts.errors import Block, BlockingError

STEP = "R6"


def z_lookup(z: pd.DataFrame) -> dict[tuple[str, str, str, int], float]:
    keys = zip(z["segment"], z["country"], z["scenario"], z["year"].astype(int))
    return dict(zip(keys, z["z"].astype(float)))


def require_years(lookup: dict, segment: str, country: str, scenario: str,
                  years: Iterable[int]) -> None:
    missing = [y for y in years if (segment, country, scenario, int(y)) not in lookup]
    if missing:
        raise BlockingError(
            STEP, Block.MISSING_TERMINAL_INPUT,
            f"no Z for {segment}/{country}/{scenario} in years {missing[:5]}"
            + (" ..." if len(missing) > 5 else ""),
        )
