"""Tables the pipeline steps hand to each other. A step gets another step's output only as one
of these tables, never by importing that step.

Each table has a key; ``TableSpec.check`` blocks on a missing column, a missing key value or a
duplicate key (MOD-06). Amounts are unrounded EUR; rounding happens only in R10.
"""

from dataclasses import dataclass

import pandas as pd

from stress.contracts.errors import Block, BlockingError


@dataclass(frozen=True)
class TableSpec:
    name: str
    filename: str  # under runs/<run_id>/results/, empty if the table is not written
    key: tuple[str, ...]
    columns: tuple[str, ...]  # non-key columns

    @property
    def all_columns(self) -> tuple[str, ...]:
        return self.key + self.columns

    def check(self, df: pd.DataFrame, step: str) -> pd.DataFrame:
        missing = [c for c in self.all_columns if c not in df.columns]
        if missing:
            raise BlockingError(step, Block.MISSING_COLUMN, f"{self.name} lacks columns {missing}")
        if len(df) and df[list(self.key)].isna().any().any():
            raise BlockingError(step, Block.MISSING_KEY, f"{self.name} has a row with a missing key")
        dup = df.duplicated(list(self.key))
        if dup.any():
            first = df.loc[dup, list(self.key)].iloc[0].to_dict()
            raise BlockingError(step, Block.DUPLICATE_KEY, f"{self.name} has duplicate key {first}")
        return df[list(self.all_columns)]


# --- R3 -----------------------------------------------------------------------------------------

REJECTIONS = TableSpec(
    "rejections", "rejections.parquet",
    key=("record_type", "record_id", "row", "reason_code"),  # row: position in the input file
    columns=("detail", "step"),
)

# One row per accepted facility, joined with its obligor, commitment and opening provision.
PORTFOLIO = TableSpec(
    "portfolio", "",
    key=("facility_id",),
    columns=(
        "obligor_id", "group_id", "portfolio", "segment", "country", "counterparty_sector",
        "nace_code", "product", "currency", "accounting_category", "route", "stage", "gca",
        "principal", "accrued_interest", "accrued_in_gca",
        "undrawn", "ccf", "commitment_id", "interest_rate", "rate_type", "residual_maturity",
        "repayment_profile", "regulatory_approach", "regulatory_class", "current_grade",
        "current_rank", "origination_grade", "origination_rank", "ttc_lgd", "sicr_rank",
        "opening_allowance_on", "opening_provision_off", "overlay_amount",
    ),
)

ROUTE_PERFORMING = "performing"
ROUTE_S3_ORIGINAL = "s3_original"

# --- R4 -----------------------------------------------------------------------------------------

Z_SCORES = TableSpec(
    "drivers", "drivers.parquet",
    key=("segment", "country", "scenario", "year"),
    columns=("z", "z_source", "adverse_weight"),
)
Z_SOURCE_PATH = "scenario_path"
Z_SOURCE_REVERSION = "reversion"
Z_SOURCE_FLAT = "flat"

DRIVER_CONTRIBUTIONS = TableSpec(
    "driver_contributions", "driver_contributions.parquet",
    key=("segment", "country", "scenario", "year", "driver"),
    columns=("value", "mean", "sd", "beta", "contribution"),
)

INDICES = TableSpec(
    "indices", "indices.parquet",
    key=("scenario", "country", "variable", "year"),
    columns=("annual_change", "index"),
)

# --- R5 -----------------------------------------------------------------------------------------

# Schedule row, written only by R5: one row per facility, valuation date and period to
# maturity. Contractual only; the same in every scenario. At each valuation year-end the
# schedule restarts from the static stock balance (EAD-05, EAD-11).
SCHEDULE = TableSpec(
    "cf_schedule", "cf_schedule.parquet",
    key=("facility_id", "valuation_year", "period"),
    columns=(
        "period_end", "bucket_year", "fraction", "t", "opening_balance", "interest", "principal",
        "closing_balance", "discount_factor", "profile", "generation", "remaining_maturity",
    ),
)

# --- R6 -----------------------------------------------------------------------------------------

PIT_MATRICES = TableSpec(
    "pit_matrices", "pit_matrices.parquet",
    key=("segment", "country", "scenario", "year", "from_grade", "to_grade"),
    columns=("probability", "z"),
)

# PD ParameterRecords. Every facility of a segment, country and grade shares one curve, so the
# record is keyed by the curve (segment, country) instead of facility_id; cohort is the grade
# slice. Curves hold whole years only: R8 takes the part of a final bucket that the maturity
# covers (assumption A7).
PD_CURVES = TableSpec(
    "pd_curves", "pd_curves.parquet",
    key=("segment", "country", "scenario", "valuation_year", "cohort", "default_bucket", "basis"),
    columns=("bucket_year", "q", "m", "s", "f", "source_version"),
)

# Facility ParameterRecords under the MOD-06 key (run_id is the run folder itself, so it is
# kept out of the rows and the output hashes). Cohort "performing" covers every performing
# grade slice of the facility. R6 applies no adjustment or constraint in v1: final = raw.
PARAMETER_RECORD_KEY = ("facility_id", "scenario", "valuation_year", "cohort", "default_bucket",
                        "basis")
PARAMETERS = TableSpec(
    "parameters", "parameters.parquet",
    key=PARAMETER_RECORD_KEY,
    columns=(
        "fraction", "bucket_year", "t", "z", "lgd", "prepayment_rate", "not_prepaid_share",
        "balance", "discount_factor", "undrawn", "ccf", "ead_drawn", "ead_undrawn", "ead_total",
        "adjustment", "constraint", "source_version",
    ),
)
COHORT_PERFORMING = "performing"
BASIS_ACCOUNTING = "accounting"

# LGD of the year y for the S3 allowance and the end-2029 interpolation (ECL-11, ECL-10).
# It also carries each facility's accounting CCF as the run applies it (variant included),
# NaN where no undrawn amount makes it applicable, for S3 slices and the reports.
LGD_OF_YEAR = TableSpec(
    "lgd_of_year", "lgd_of_year.parquet",
    key=("facility_id", "scenario", "year"),
    columns=("z", "lgd", "ccf"),
)

# --- R7 -----------------------------------------------------------------------------------------

# Facility slice: the projection state. One row per facility and slice (grade G1..GN,
# S3_orig, S3_new_<year>_S<origin stage>). Stage is derived from the grade (MIG-07).
SLICES = TableSpec(
    "slices", "slices.parquet",
    key=("scenario", "year", "facility_id", "slice"),
    columns=(
        "stage", "grade", "origination_grade", "entry_year", "origin_stage", "gca", "undrawn",
        "allowance_on", "provision_off", "generation", "replaced",
    ),
)
SLICE_S3_ORIGINAL = "S3_orig"


def new_s3_slice(entry_year: int, origin_stage: int) -> str:
    return f"S3_new_{entry_year}_S{origin_stage}"


STAGE_FLOWS = TableSpec(
    "stage_flows", "stage_flows.parquet",
    key=("scenario", "year", "segment", "from_stage", "to_stage"),
    columns=("portfolio", "gca", "undrawn"),
)

GRADE_FLOWS = TableSpec(
    "grade_flows", "grade_flows.parquet",
    key=("scenario", "year", "segment", "country", "from_grade", "to_grade"),
    columns=("gca",),
)

# --- R8 -----------------------------------------------------------------------------------------

PROVISIONS = TableSpec(
    "provisions", "provisions.parquet",
    key=("scenario", "year", "facility_id", "slice"),
    columns=(
        "stage", "method", "raw_on", "raw_off", "allowance_on", "provision_off", "floor_binding",
        "masked_on", "masked_off",
    ),
)
METHOD_S1 = "s1_12m"
METHOD_S1_TERMINAL = "s1_terminal_interpolated"
METHOD_S2 = "s2_lifetime"
METHOD_S3_ORIGINAL = "s3_original_floor"
METHOD_S3_NEW_BOOKING = "s3_new_booking"
METHOD_S3_NEW_FLOOR = "s3_new_floor"

# ECL per default bucket, summed from facility and slice results (ECL-09).
ECL_BUCKETS = TableSpec(
    "ecl_buckets", "ecl_buckets.parquet",
    key=("scenario", "valuation_year", "segment", "stage", "default_bucket"),
    columns=("ecl_on", "ecl_off"),
)

# --- R9 -----------------------------------------------------------------------------------------

CHARGES = TableSpec(
    "charges", "charges.parquet",
    key=("scenario", "year", "facility_id"),
    columns=(
        "opening_on", "closing_on", "charge_on", "opening_off", "closing_off", "charge_off",
        "overlay_opening", "overlay_closing", "fx_movement", "other_movement",
    ),
)


# --- bundles handed from step to step ----------------------------------------------------------

@dataclass
class RoutedPortfolio:
    portfolio: pd.DataFrame  # PORTFOLIO
    rejections: pd.DataFrame  # REJECTIONS
    grades: tuple[str, ...]  # performing master-scale grades G1..GN, in rank order
    reconciliation: pd.DataFrame  # starting point against the input-set control totals


@dataclass
class Drivers:
    z: pd.DataFrame  # Z_SCORES, scenario years plus terminal years
    contributions: pd.DataFrame  # DRIVER_CONTRIBUTIONS
    indices: pd.DataFrame  # INDICES


@dataclass
class Parameters:
    pit: pd.DataFrame  # PIT_MATRICES
    pd_curves: pd.DataFrame  # PD_CURVES
    facility: pd.DataFrame  # PARAMETERS
    lgd_of_year: pd.DataFrame  # LGD_OF_YEAR


@dataclass
class YearProjection:
    slices: pd.DataFrame  # SLICES before provisions
    stage_flows: pd.DataFrame  # STAGE_FLOWS
    grade_flows: pd.DataFrame  # GRADE_FLOWS


@dataclass
class YearProvisions:
    slices: pd.DataFrame  # SLICES with allowance_on and provision_off
    provisions: pd.DataFrame  # PROVISIONS
    ecl_buckets: pd.DataFrame  # ECL_BUCKETS
