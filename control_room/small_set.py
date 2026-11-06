"""The small dataset, a tenth of the large one, for a Heroku dyno too small for the full book:

    uv run python control_room/small_set.py

It keeps a tenth of the facilities in each portfolio and opening stage, at least one of each, with
their obligors, commitments and opening provisions. The rating matrices, scenarios and parameter set
stay as they are. `foundation.synth package` freezes the result as a new inputs/<hash>/, so only the
one-off step writes an input set and the full book is not touched. `BOOKS` in server.py names both
sets. The sample cannot meet the requirements' exact targets (docs/assumptions.md A41).
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from server import BOOKS, ROOT

from stress.contracts.inputs import (
    COMMITMENTS,
    DATASETS,
    FACILITIES,
    MATRIX_DIR,
    OBLIGORS,
    OPENING_PROVISIONS,
)

FULL = ROOT / "inputs" / BOOKS["large"]
SHARE = 10
CELL = ["portfolio", "ifrs_stage"]
SPREAD = ["segment", "current_grade", "gca", "facility_id"]


def chosen(facilities: pd.DataFrame) -> pd.Series:
    """The kept facility IDs: the middle of each equal band of a cell ranked by segment, rating and
    size, so the sample keeps all three. A cell of two still leaves one, so no portfolio loses a
    stage; a segment can (P06_CI keeps only Stage 1)."""
    kept = []
    for _, cell in facilities.sort_values(SPREAD).groupby(CELL):
        count = max(1, round(len(cell) / SHARE))
        places = ((np.arange(count) + 0.5) * len(cell) / count).astype(int)
        kept.append(cell["facility_id"].iloc[places])
    return pd.concat(kept)


def write_sample(source: Path, target: Path) -> None:
    """The files of `source`, with the four tables cut down to the kept facilities."""
    for spec in DATASETS:
        shutil.copyfile(source / spec.filename, target / spec.filename)
    shutil.copytree(source / MATRIX_DIR, target / MATRIX_DIR)
    facilities = pd.read_parquet(source / FACILITIES.filename)
    ids = chosen(facilities)
    owners = facilities.loc[facilities["facility_id"].isin(ids), "obligor_id"]
    for spec, key, values in ((FACILITIES, "facility_id", ids), (COMMITMENTS, "facility_id", ids),
                              (OPENING_PROVISIONS, "facility_id", ids), (OBLIGORS, "obligor_id", owners)):
        table = pd.read_parquet(source / spec.filename)
        table[table[key].isin(values)].to_parquet(target / spec.filename, index=False)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="stress-small-set-") as temp:
        write_sample(FULL, Path(temp))
        return subprocess.run([sys.executable, "-m", "foundation.synth", "package", "--source", temp, "--out", "inputs"],
                              cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
