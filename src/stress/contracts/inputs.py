"""Schema of the seven input datasets of an input set (inputs/<hash>/) and its manifest.

The one-off steps O2-O4 write these files; R2 reads them, and nothing else does. Amounts are
EUR, rates and probabilities decimal fractions, dates ISO 8601 strings. A field may have a
companion ``<field>__status`` column; without one, R2 infers the status from the value.
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

import pandas as pd

from stress.contracts.status import USABLE_STATUSES, ValueStatus

# --- vocabularies -----------------------------------------------------------------------------

CURRENCY = "EUR"
ON_BALANCE_CATEGORY = "AC"
OFF_BALANCE_CATEGORY = "not_applicable"
EXCLUDED_ON_BALANCE_CATEGORIES = ("FVOCI", "FVPL")

PRODUCTS = ("mortgage", "consumer_loan", "term_loan", "revolver", "debt_security", "guarantee")
# Fully drawn products: U = 0 and CCF not applicable (EAD-03).
TERM_PRODUCTS = ("mortgage", "consumer_loan", "term_loan", "debt_security")
REPAYMENT_PROFILES = ("bullet", "annuity", "linear")
STAGES = (1, 2, 3)
DEFAULT_GRADE = "D"
CENTRAL_BANK_SECTOR = "central_bank"
APPROACHES = ("IRB", "STA")


# --- dataset specs ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Column:
    name: str
    kind: str  # str, float, int, bool, date
    nullable: bool = False  # may the value be missing or not applicable at load time
    description: str = ""


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    filename: str
    key: tuple[str, ...]
    columns: tuple[Column, ...] = field(default_factory=tuple)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def column(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(name)


FACILITIES = DatasetSpec(
    name="facilities",
    filename="facilities.parquet",
    key=("facility_id",),
    columns=(
        Column("facility_id", "str"),
        Column("obligor_id", "str"),
        Column("entity_id", "str"),
        Column("portfolio", "str", description="Reporting portfolio identifier; not a fixed enumeration"),
        Column("segment", "str", description="section 8.7 reference segment, one TTC matrix each"),
        Column("product", "str"),
        Column("ifrs_stage", "int"),
        Column("poci", "bool"),
        Column("accounting_category", "str", nullable=True),
        Column("currency", "str", nullable=True),
        Column("principal", "float", description="drawn principal, EUR"),
        Column("accrued_interest", "float", description="EUR"),
        Column("accrued_in_gca", "bool"),
        Column("gca", "float", description="gross carrying amount, accrued interest counted once"),
        Column("contractual_limit", "float"),
        Column("interest_rate", "float", nullable=True, description="annual EIR"),
        Column("rate_type", "str", description="fixed or floating"),
        Column("residual_maturity", "float", nullable=True, description="years from snapshot"),
        Column("repayment_profile", "str", description="contractual: bullet, annuity, linear"),
        Column("regulatory_approach", "str"),
        Column("regulatory_class", "str"),
        Column("current_grade", "str", nullable=True, description="master-scale grade or D"),
        Column("origination_grade", "str", nullable=True),
        Column("ttc_lgd", "float", nullable=True),
        Column("dpd", "int"),
        Column("watchlist", "bool"),
        Column("forborne", "bool"),
        Column("credit_status_date", "date", description="observation date of dpd, watchlist, forborne"),
        Column("origination_date", "date"),
        Column("stage_entry_date", "date"),
        Column("default_date", "date", nullable=True),
        Column("collateral_type", "str", nullable=True),
        Column("ltv", "float", nullable=True),
        Column("dscr", "float", nullable=True),
        Column("snapshot_date", "date"),
    ),
)

OBLIGORS = DatasetSpec(
    name="obligors",
    filename="obligors.parquet",
    key=("obligor_id",),
    columns=(
        Column("obligor_id", "str"),
        Column("group_id", "str", description="connected-client group"),
        Column("entity_id", "str"),
        Column("country", "str", nullable=True, description="country of domicile"),
        Column("counterparty_sector", "str"),
        Column("nace_code", "str", nullable=True),
        Column("nace_version", "str", nullable=True),
        Column("principal_activity", "str", nullable=True),
        Column("sme_flag", "bool"),
        Column("regulatory_default", "bool"),
        Column("snapshot_date", "date"),
    ),
)

COMMITMENTS = DatasetSpec(
    name="commitments",
    filename="commitments.parquet",
    key=("commitment_id",),
    columns=(
        Column("commitment_id", "str"),
        Column("facility_id", "str", description="linked facility"),
        Column("currency", "str", nullable=True),
        Column("nominal_undrawn", "float", description="EUR"),
        Column("accounting_ccf", "float", nullable=True),
        Column("ccf_source", "str"),
        Column("asset_category", "str", description='always "not_applicable" (SCP-06)'),
        Column("provision_classification", "str"),
        Column("snapshot_date", "date"),
    ),
)

OPENING_PROVISIONS = DatasetSpec(
    name="opening_provisions",
    filename="opening_provisions.parquet",
    key=("facility_id",),
    columns=(
        Column("facility_id", "str"),
        Column("currency", "str", nullable=True),
        Column("allowance_on", "float", description="on-balance allowance, EUR"),
        Column("provision_off", "float", description="off-balance provision, EUR"),
        Column("overlay_amount", "float"),
        Column("overlay_risk", "str", nullable=True),
        Column("overlay_owner", "str", nullable=True),
        Column("overlay_reason", "str", nullable=True),
        Column("method", "str"),
        Column("frozen", "bool"),
        Column("snapshot_date", "date"),
    ),
)

# One TTC matrix file per segment, at the path its ``ttc_matrix`` names in the parameter set,
# for example matrices/P01.parquet. R2 reads each one and adds the segment to its rows.
MATRIX_DIR = "matrices"
TTC_MATRIX = DatasetSpec(
    name="ttc_matrix",
    filename=f"{MATRIX_DIR}/<segment>.parquet",
    key=("from_grade", "to_grade"),
    columns=(
        Column("from_grade", "str"),
        Column("to_grade", "str"),
        Column("probability", "float"),
        Column("from_rank", "int", description="1..N for performing grades, N+1 for D"),
        Column("to_rank", "int"),
        Column("master_scale_pd", "float", description="master-scale one-year PD of from_grade"),
    ),
)

# The two YAML datasets have nested structure; R2 checks their top-level keys and value fields.
SCENARIOS = DatasetSpec(name="scenarios", filename="scenarios.yaml", key=("scenario", "variable", "year"))
PARAMETER_SET = DatasetSpec(name="parameter_set", filename="parameter_set.yaml", key=("parameter_set_id",))

# The files every input set has; the matrix files come on top, one per segment.
DATASETS = (FACILITIES, OBLIGORS, COMMITMENTS, OPENING_PROVISIONS, SCENARIOS, PARAMETER_SET)
TABLE_DATASETS = (FACILITIES, OBLIGORS, COMMITMENTS, OPENING_PROVISIONS)

SCENARIO_TOP_KEYS = (
    "scenario_set_id", "source", "release", "revision", "status", "scenarios", "variables", "values",
)
SCENARIO_VALUE_FIELDS = (
    "scenario", "variable", "country", "year", "value", "unit", "value_type", "source", "release",
    "completeness", "status",
)
SCENARIO_UNITS = {"percent": 0.01, "decimal": 1.0, "index": 1.0}
SCENARIO_VALUE_TYPES = ("level", "growth", "index", "cumulative_change", "pp_change", "bp_shock")
SYNTHETIC = "SYNTHETIC"

PARAMETER_SET_TOP_KEYS = (
    "parameter_set_id", "version", "status", "horizon", "master_scale", "portfolios", "terminal_rule",
    "conventions", "tolerances", "variants", "sicr_triggers",
)
# What each segment states in the parameter set, under portfolios.<portfolio>.segments.<segment>:
# where its three models and its TTC matrix live, and its own settings. The models hold their
# coefficients themselves (src/stress/models/).
MODEL_SETTINGS = {"pd": "pd_model", "lgd": "lgd_model", "prepayment": "prepayment_model"}
SEGMENT_PARAMETERS = (*MODEL_SETTINGS.values(), "ttc_matrix", "asset_correlation", "sicr_k", "cpr_ttc", "ccf")
def inside_set(name) -> bool:
    """Whether a file name stays inside its input set: a plain relative path with forward slashes,
    no drive, no root and no ``..``, read the same way on every system."""
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        return False
    posix, windows = PurePosixPath(name), PureWindowsPath(name)
    return not (posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root
                or ".." in posix.parts or str(posix) != name)


# The engine's own name for a setting where it differs from the parameter set's.
ENGINE_NAMES = {"asset_correlation": "rho"}


def segments_of(parameter_set: dict) -> dict[str, dict]:
    """The segments of a parameter set by segment, each with its portfolio and its settings under
    the engine's names. ``model_portfolio`` is the portfolio the segment's models must belong to: the
    one it is filed under here, which a run specification never changes, even when it reports the
    segment, or a new segment inherited from it, under another portfolio. A setting the file lacks stays absent: R3 blocks on it (MISSING_PARAMETER).
    Raises TypeError for a wrong shape and ValueError for a setting the parameter set does not have."""
    portfolios = parameter_set.get("portfolios")
    if not isinstance(portfolios, dict) or not portfolios:
        raise TypeError("portfolios must be a nonempty mapping of portfolio to segments")
    out = {}
    for portfolio, body in portfolios.items():
        if not isinstance(body, dict) or set(body) != {"segments"} or not isinstance(body["segments"], dict):
            raise TypeError(f"portfolio {portfolio} must hold only a mapping of segments")
        for segment, settings in body["segments"].items():
            if not isinstance(settings, dict):
                raise TypeError(f"segment {segment} must be a mapping")
            unknown = sorted(set(settings) - set(SEGMENT_PARAMETERS))
            if unknown:
                raise ValueError(f"segment {segment}: {unknown} not a parameter-set setting; a segment names "
                                 f"its models, whose coefficients live in src/stress/models/")
            if segment in out:
                raise ValueError(f"segment {segment} is in two portfolios")
            out[segment] = {"portfolio": portfolio, "model_portfolio": portfolio,
                            **{ENGINE_NAMES.get(k, k): v for k, v in settings.items()}}
    return out

INPUT_MANIFEST = "manifest.json"
APPROVAL_FILE = "approval.json"


# --- typed tables after R2 --------------------------------------------------------------------

@dataclass
class TypedTable:
    """A loaded table plus the status of every value (same shape as ``data``)."""

    name: str
    data: pd.DataFrame
    status: pd.DataFrame

    def usable(self, column: str) -> pd.Series:
        return self.status[column].isin([str(s) for s in USABLE_STATUSES])

    def has_status(self, column: str, status: ValueStatus) -> pd.Series:
        return self.status[column] == str(status)


@dataclass
class LoadedInputs:
    """Everything R2 read from the input set. No later step reads a file."""

    input_set_hash: str
    manifest: dict
    facilities: TypedTable
    obligors: TypedTable
    commitments: TypedTable
    opening_provisions: TypedTable
    ttc_pd_matrix: pd.DataFrame
    scenario_values: pd.DataFrame  # one row per scenario, variable, country, year; decimal values
    scenario_meta: dict
    parameter_set: dict
    load_controls: dict
    analysis: dict = field(default_factory=dict)
    approval: dict = field(default_factory=dict)
    specification: dict = field(default_factory=dict)
