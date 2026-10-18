"""ParameterRecord store under the MOD-06 key; a duplicate or missing key blocks (MOD-05, MOD-06).

R6 applies no adjustment or methodological constraint in v1, so every record's final value is
its raw value; ``adjustment`` is 0 and ``constraint`` is "none". The S3 floor is a provision
constraint and lives in R8, which keeps raw and constrained values.
"""

import pandas as pd

from stress.contracts.tables import PARAMETERS, PD_CURVES, TableSpec

STEP = "R6"
NO_CONSTRAINT = "none"


def source_version(parameter_set: dict, engine_version: str) -> str:
    return f"{parameter_set['parameter_set_id']}|engine {engine_version}"


def finalise(df: pd.DataFrame, spec: TableSpec, version: str) -> pd.DataFrame:
    df = df.copy()
    df["source_version"] = version
    if spec is PARAMETERS:
        df["adjustment"] = 0.0
        df["constraint"] = NO_CONSTRAINT
    checked = spec.check(df, STEP)
    return checked.sort_values(list(spec.key), kind="mergesort").reset_index(drop=True)


def finalise_parameters(df: pd.DataFrame, version: str) -> pd.DataFrame:
    return finalise(df, PARAMETERS, version)


def finalise_pd_curves(df: pd.DataFrame, version: str) -> pd.DataFrame:
    return finalise(df, PD_CURVES, version)
