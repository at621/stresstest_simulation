"""Definitions shown on the run inputs page. build_page.py checks them against the engine.

Roles: calc = a calculation reads it; check = validated, then unused; report = reports and
optional analyses only; none = must be present, nothing reads it. Backticks become code.
"""

# Parquet columns, grouped for reading: (column, role, definition, rule).
FACILITIES = (
    ("Identity and routing", (
        ("facility_id", "calc", "Unique identifier of one loan, bond or credit line.",
         "Duplicates are rejected: `DUPLICATE_FACILITY`."),
        ("obligor_id", "calc", "The borrower. Joins to `obligors`.",
         "An unknown or rejected obligor rejects the facility: `ORPHAN_FACILITY`."),
        ("entity_id", "none", "Reporting entity that holds the facility.", ""),
        ("portfolio", "calc", ("Reporting portfolio. Free text, not a fixed list. Sets the report rows and "
         "the grid of dynamic volume rates."),
         "A segment must sit in exactly one portfolio, otherwise the run blocks: `PARAMETER_ALIGNMENT`."),
        ("segment", "calc", ("Reference segment. Selects the TTC matrix, the segment parameters and the "
         "macro model."),
         "Needs a matrix and a `segments` entry: `UNKNOWN_SEGMENT`."),
        ("product", "calc", ("Product type: `mortgage`, `consumer_loan`, `term_loan`, `revolver`, "
         "`debt_security` or `guarantee`. The run variant maps it to a repayment profile."),
         "Other values are rejected: `UNKNOWN_PRODUCT`."),
    )),
    ("Accounting", (
        ("ifrs_stage", "calc", "IFRS 9 stage at the snapshot: 1, 2 or 3. Stage 3 takes the original-S3 route.",
         ("Other values: `INVALID_STAGE`. For S1 and S2 it must equal the stage the SICR line and triggers "
         "give back: `STAGE_GRADE_CONFLICT`.")),
        ("poci", "check", "Purchased or originated credit-impaired.",
         "`true` is rejected, because v1 has no POCI treatment: `POCI_NOT_IN_V1`. Blank: `MISSING_FLAG`."),
        ("accounting_category", "check", "Measurement category. The engine covers amortised cost only: `AC`.",
         "Blank: `MISSING_ACCOUNTING_CATEGORY`. Anything else: `NON_AC_ON_BALANCE`."),
        ("currency", "check", "Currency. Only `EUR` is in scope, with no FX conversion.",
         "Blank: `MISSING_CURRENCY`. Anything else: `NON_EUR_CURRENCY`."),
        ("snapshot_date", "check", "Balance-sheet date of the record.",
         "Must equal `horizon.snapshot_date`, otherwise the run blocks: `HORIZON_MISMATCH`."),
        ("regulatory_approach", "report", ("Credit-risk approach: `IRB` or `STA`. Read by the workbook and the "
         "optional capital bridge."), ""),
        ("regulatory_class", "report", ("Regulatory exposure class. An internal product label is not a "
         "regulatory class. Read by the optional capital bridge."), ""),
    )),
    ("Amounts, EUR", (
        ("principal", "check", "Drawn principal.",
         "Not blank: `MISSING_AMOUNT`. A negative amount blocks the run: `NEGATIVE_AMOUNT`."),
        ("accrued_interest", "calc", ("Interest accrued and not yet paid. Added to drawn EAD only when it is "
         "not already inside `gca`."),
         "Not blank, not negative."),
        ("accrued_in_gca", "calc", ("True when `accrued_interest` is already inside `gca`. Stops it being "
         "counted twice."),
         "Blank: `MISSING_FLAG`."),
        ("gca", "calc", ("Gross carrying amount, with accrued interest counted once. The stock that "
         "migrates and carries provisions."),
         ("Must equal principal plus accrued interest when `accrued_in_gca` is true, and principal "
         "otherwise, within €0.01: `GCA_COMPONENTS_MISMATCH`.")),
        ("contractual_limit", "check", "Contractual credit limit.",
         "Principal plus undrawn may exceed it by at most €0.01. A breach blocks the run: `LIMIT_BREACH`."),
    )),
    ("Rate and schedule", (
        ("interest_rate", "calc", ("Annual effective interest rate: the contractual rate of the schedule and "
         "the discount rate of ECL. Held at its snapshot value through the projection."),
         "Required for S1 and S2: `MISSING_RATE`. Must be above −100%: `INVALID_RATE`."),
        ("rate_type", "none", "`fixed` or `floating`. The engine does not reset floating rates.", ""),
        ("residual_maturity", "calc", ("Years from the snapshot to final maturity. Sets the schedule and the "
         "horizon of the SICR line."),
         "Required and above zero for S1 and S2: `INVALID_MATURITY`."),
        ("repayment_profile", "check", ("Contractual profile: `bullet`, `annuity` or `linear`. R5 takes the "
         "profile from the run variant, so this value does not drive the schedule."),
         "For S1 and S2 it must be one of the three: `UNKNOWN_REPAYMENT_PROFILE`."),
        ("origination_date", "report", "Date the facility was granted. Read by the optional NPE backstop.", ""),
    )),
    ("Credit risk", (
        ("current_grade", "calc", "Master-scale grade at the snapshot, or `D`. Starting point of migration.",
         ("Blank: `MISSING_GRADE`. Off the scale: `UNKNOWN_GRADE`. S3 must be D and S1 or S2 must not be: "
         "`STAGE_GRADE_CONFLICT`.")),
        ("origination_grade", "calc", "Grade at origination. With `sicr_k` it fixes the SICR line.",
         "Must be a performing grade: `MISSING_GRADE`, `UNKNOWN_GRADE`."),
        ("ttc_lgd", "calc", "Through-the-cycle LGD, as a decimal. Z moves it each year.",
         "Blank: `MISSING_TTC_LGD`. Outside 0 to 1: `TTC_LGD_OUT_OF_RANGE`."),
        ("collateral_type", "report", ("Collateral type. `residential_property` follows the residential "
         "price index; `office`, `retail`, `industrial` and `residential_rental` follow the CRE index. "
         "Read by the LTV report and the NPE backstop."), ""),
        ("ltv", "report", ("Loan-to-value at the snapshot. Read by the LTV report and the NPE backstop, and "
         "it decides which segments the `lgd_path: trough` option covers."),
         ("A row with no LTV must have no collateral type and status `not_applicable`, otherwise "
         "`MISSING_INPUT` blocks.")),
        ("dscr", "none", "Debt-service coverage ratio.", ""),
    )),
    ("Credit status and history", (
        ("dpd", "calc", ("Days past due at `credit_status_date`. At or above `sicr_triggers.dpd_days` a "
         "performing facility goes to S2 and stays there until default."),
         "Blank: `MISSING_FLAG`. Negative: `INVALID_DPD`."),
        ("watchlist", "calc", ("On the bank's credit watchlist at `credit_status_date`. A performing facility "
         "goes to S2 and stays there until default."),
         "Blank: `MISSING_FLAG`."),
        ("forborne", "calc", ("A forbearance measure in place at `credit_status_date`. A performing facility "
         "goes to S2 and stays there until default."),
         "Blank: `MISSING_FLAG`."),
        ("credit_status_date", "check", "Observation date of `dpd`, `watchlist` and `forborne`.",
         "Required, and not after the snapshot: `INVALID_CREDIT_STATUS_DATE`."),
        ("stage_entry_date", "none", "Date the facility entered its current stage.", ""),
        ("default_date", "report", ("Date of default. Blank unless the facility is in S3. Read by the "
         "optional NPE backstop."), ""),
    )),
)

OBLIGORS = (
    ("Identity", (
        ("obligor_id", "calc", "Unique identifier of one borrower.",
         "Duplicates are rejected, and so are their facilities: `DUPLICATE_OBLIGOR`."),
        ("group_id", "report", "Connected-client group. Read by the concentration report.", ""),
        ("entity_id", "none", "Reporting entity.", ""),
        ("snapshot_date", "check", "Balance-sheet date of the record.",
         "Must equal `horizon.snapshot_date`: `HORIZON_MISMATCH`."),
    )),
    ("Counterparty", (
        ("country", "calc", "Country of domicile. Selects the scenario path and Z of each facility.",
         "Blank, or a country with no scenario values, rejects the facility: `UNMAPPED_COUNTRY`."),
        ("counterparty_sector", "check", ("Counterparty sector, such as `households` or "
         "`non_financial_corporations`. Also labels reports."),
         "`central_bank` is rejected, because v1 has no zero-loss route: `CENTRAL_BANK_NOT_IN_V1`."),
        ("sme_flag", "none", "SME borrower.", ""),
        ("regulatory_default", "check", "Regulatory default status of the borrower.",
         "Must be true exactly when the facility is in S3: `DEFAULT_STAGE_CONFLICT`. Blank: `MISSING_FLAG`."),
    )),
    ("Industry", (
        ("nace_code", "report", ("NACE section, for corporates. Read by reports, and by `assignments` "
         "selectors in a run specification."), ""),
        ("nace_version", "report", "Version of the NACE classification. Read by the dimensions report.", ""),
        ("principal_activity", "none", "Description of the main activity.", ""),
    )),
)

COMMITMENTS = (
    ("All columns", (
        ("commitment_id", "check", "Unique identifier of one undrawn commitment.",
         "Duplicates block the run: `DUPLICATE_COMMITMENT`."),
        ("facility_id", "calc", ("The linked facility. At most one commitment per facility, so a conversion "
         "is never counted twice."),
         ("Unknown facility: `ORPHAN_COMMITMENT`. A second commitment blocks the run: "
         "`DUPLICATE_COMMITMENT`.")),
        ("nominal_undrawn", "calc", "Undrawn nominal amount, EUR. Before conversion to EAD.",
         ("Not blank. Negative blocks the run. Above zero on a term product is rejected: "
         "`UNDRAWN_ON_TERM_PRODUCT`.")),
        ("accounting_ccf", "calc", ("Accounting credit conversion factor. Converts undrawn to EAD, unless the "
         "run variant overrides it for the segment."),
         ("Missing on a positive undrawn blocks the run: `MISSING_CCF`. Outside 0 to 1 blocks the run: "
         "`CCF_OUT_OF_RANGE`. Must match `segments.<id>.ccf`: `CCF_MISMATCH`.")),
        ("ccf_source", "none", "Where the CCF comes from.", ""),
        ("currency", "check", "Currency. Only `EUR`.", "Blank: `MISSING_CURRENCY`. Other: `NON_EUR_CURRENCY`."),
        ("asset_category", "check", "Measurement category of an off-balance item. Always `not_applicable`.",
         "Anything else is rejected: `OFF_BALANCE_CATEGORY`."),
        ("provision_classification", "none", "Accounting class of the off-balance provision.", ""),
        ("snapshot_date", "check", "Balance-sheet date of the record.",
         "Must equal `horizon.snapshot_date`: `HORIZON_MISMATCH`."),
    )),
)

OPENING_PROVISIONS = (
    ("All columns", (
        ("facility_id", "calc", "The facility. Exactly one row per facility.",
         ("No row: `MISSING_OPENING_PROVISION`. Two rows: `DUPLICATE_OPENING_PROVISION`. Unknown facility: "
         "`ORPHAN_OPENING_PROVISION`.")),
        ("allowance_on", "calc", ("Opening on-balance allowance, EUR. The opening side of the first charge. "
         "A run never recomputes it."),
         "Not blank. Negative blocks the run: `NEGATIVE_AMOUNT`."),
        ("provision_off", "calc", "Opening off-balance provision, EUR. Zero when there is no commitment.",
         "Not blank. Negative blocks the run: `NEGATIVE_AMOUNT`."),
        ("overlay_amount", "report", ("Management overlay, EUR. Shown as an unchanged stock in the charge "
         "tables. It is not added to ECL or to the charge."),
         "Not blank. Negative blocks the run: `NEGATIVE_AMOUNT`."),
        ("overlay_risk", "none", "Risk the overlay addresses.", ""),
        ("overlay_owner", "none", "Owner of the overlay.", ""),
        ("overlay_reason", "none", "Reason for the overlay.", ""),
        ("method", "none", "How the opening allowance was calculated.", ""),
        ("frozen", "none", "True when the opening amount is frozen. Every run treats it as frozen.", ""),
        ("currency", "check", "Currency. Only `EUR`.", "Blank: `MISSING_CURRENCY`. Other: `NON_EUR_CURRENCY`."),
        ("snapshot_date", "check", "Balance-sheet date of the record.",
         "Must equal `horizon.snapshot_date`: `HORIZON_MISMATCH`."),
    )),
)

TTC_PD_MATRIX = (
    ("All columns", (
        ("segment", "calc", "Segment the matrix belongs to. Each segment has one complete matrix.",
         "11 × 11 cells per segment on this scale: `INVALID_MATRIX`."),
        ("from_grade", "calc", "Grade at the start of the year.",
         "Must match `master_scale.grades`, and the scale must end with `D`."),
        ("to_grade", "calc", "Grade at the end of the year.", "Same labels as `from_grade`."),
        ("probability", "calc", ("One-year through-the-cycle probability of moving from `from_grade` to "
         "`to_grade`, as a decimal."),
         "Not blank or negative. Each row sums to 1 within 1e-10. D is absorbing. PD rises with the grade."),
        ("from_rank", "calc", "Position of `from_grade`: 1 to N for performing grades, N+1 for D.",
         "Must run 1 to N+1 with no gaps, and agree across segments."),
        ("to_rank", "calc", "Position of `to_grade`, on the same numbering.", ""),
        ("master_scale_pd", "none", "Master-scale one-year PD of `from_grade`.", ""),
    )),
)

MEANINGS = {
    "facilities": "one loan, bond or credit line",
    "obligors": "one borrower",
    "commitments": "the undrawn part of one facility",
    "opening_provisions": "the frozen opening provision of one facility",
    "ttc_pd_matrix": "one cell of a one-year rating matrix",
}

# parameter_set.yaml: path, role, type, definition, allowed values. <id> stands for any key.
PARAMETER_PATHS = (
    ("parameter_set_id", "none", "text", "Identifier of the parameter set. Copied to run reports.", "Required"),
    ("version", "none", "text", "Version of the parameter set.", "Required"),
    ("status", "none", "text", "Approval status. Reported, not enforced.", "`PROPOSED` today"),
    ("spec_version", "none", "text", "Requirements version. The package step copies it to the manifest.",
     "Optional"),
    ("horizon.snapshot_date", "check", "date", "Balance-sheet date. All four tables must carry it.", "ISO date"),
    ("horizon.snapshot_year", "calc", "integer", "Year of the opening position.", ""),
    ("horizon.projection_years", "calc", "list", "Years the run projects.",
     "Last entry must equal `terminal_rule.last_scenario_year`"),
    ("horizon.last_bucket_year", "calc", "integer", "Last year to which Z is extended.", ""),
    ("master_scale.grades", "check", "list", "Performing grades, best first.",
     "Must match the matrix grades"),
    ("master_scale.default_grade", "none", "text", "Label of the default grade. The engine fixes it at `D`.", ""),
    ("master_scale.ttc_pd", "report", "list", ("One-year TTC PD of each grade. Read only by the calibration "
     "and challenge diagnostics."), "One value per grade"),
    ("terminal_rule.method", "none", "text", "Name of the reversion method. A label, not a selector.", ""),
    ("terminal_rule.baseline", "none", "text", ("Treatment of baseline after the horizon. Baseline stays flat "
     "in the code."), ""),
    ("terminal_rule.s1_end_of_horizon", "none", "text", ("End-2029 S1 convention. Chosen by "
     "`run.terminal_treatment`, not by this value."), ""),
    ("terminal_rule.last_scenario_year", "calc", "integer", ("Last year with scenario values. Reversion "
     "starts after it."), "Must equal the last projection year"),
    ("terminal_rule.reversion_years", "calc", "integer", "Years Z takes to reach the baseline 2029 level.",
     "Overridden per scenario by `terminal_policies`"),
    ("conventions.sicr_horizon", "none", "text", "SICR uses the residual maturity at opening.", ""),
    ("conventions.stub_pd", "none", "text", "Part-year PD convention in the SICR test.", ""),
    ("conventions.default_buckets", "none", "text", "Default buckets end at calendar year-ends.", ""),
    ("conventions.new_s3_undrawn", "none", "text", "New S3 off-balance flow uses CCF and LGD.", ""),
    ("conventions.opening_allowance_matrix", "none", "text", "O4 builds opening allowances from the TTC matrix.",
     ""),
    ("conventions.opening_allowance_schedule", "none", "text", ("O4 builds opening allowances on a bullet "
     "schedule."), ""),
    ("sicr_triggers.enabled", "calc", "list", "Qualitative triggers switched on.",
     "Any of `dpd`, `watchlist`, `forborne`"),
    ("sicr_triggers.dpd_days", "calc", "integer", "Days past due that trigger S2.", "Positive whole number"),
    ("sicr_triggers.hold", "check", "text", "How long a trigger holds.", "Only `until_default`"),
    ("sicr_triggers.definitions.<id>", "check", "text", "Source definition of a trigger.",
     "Required for each enabled trigger"),
    ("sicr_triggers.source", "check", "text", "Where the flags come from.", "Not empty"),
    ("tolerances.counts.kind", "none", "text", "Counts must match exactly.", ""),
    ("tolerances.probability_identity.kind", "none", "text", "Type of tolerance.", ""),
    ("tolerances.probability_identity.abs", "check", "number", ("Absolute limit for probability identities and "
     "matrix row sums."), ""),
    ("tolerances.rate.kind", "none", "text", "Type of tolerance.", ""),
    ("tolerances.rate.abs", "none", "number", "Limit for rates. No check reads it.", ""),
    ("tolerances.amount.kind", "none", "text", "Type of tolerance.", ""),
    ("tolerances.amount.abs", "check", "number", "Limit for amounts per facility, in EUR.", ""),
    ("tolerances.aggregate.kind", "none", "text", "Type of tolerance.", ""),
    ("tolerances.aggregate.abs", "check", "number", "Absolute limit for portfolio and book totals, in EUR.", ""),
    ("tolerances.aggregate.rel", "check", "number", "Relative limit for the same totals. The larger limit applies.",
     ""),
    ("variants.<id>.label", "none", "text", "Description of the variant.", ""),
    ("variants.<id>.repayment_profile.<id>", "calc", "text", ("Repayment profile by product. `default` covers "
     "products not listed."), "`bullet`, `annuity`, `linear`"),
    ("variants.<id>.ccf.<id>", "calc", "number", "CCF override by segment. Empty means the commitments' own CCF.",
     "0 to 1"),
)

SEGMENT_FIELDS = (
    ("portfolio", "none", "text", "Portfolio of the segment. A description: membership comes from `facilities`.",
     "Required by the file format"),
    ("z_drivers.<variable>.beta", "calc", "number", "Weight of the driver: Z = Σ beta × (x − mean) / sd.",
     "Finite"),
    ("z_drivers.<variable>.mean", "calc", "number", "Mean used to standardise the driver.", "Finite"),
    ("z_drivers.<variable>.sd", "calc", "number", "Standard deviation used to standardise the driver.",
     "Above 0"),
    ("rho", "calc", "number", "How strongly Z shifts the matrix: C_PiT = Φ(Φ⁻¹(C_TTC) − √ρ × Z).", "0 ≤ ρ < 1"),
    ("sicr_k", "calc", "number", ("SICR multiple. A grade is S2 when its lifetime TTC PD is at least k times "
     "the lifetime PD at the origination grade."), "Above 0"),
    ("lgd_w", "calc", "number", "How strongly Z moves LGD: LGD = Φ(Φ⁻¹(LGD_TTC) − w × Z).", "0 or more"),
    ("cpr_ttc", "calc", "number", "Through-the-cycle annual prepayment rate.", "0 to 1"),
    ("cpr_v", "calc", "number", "How strongly Z moves prepayment: CPR = Φ(Φ⁻¹(CPR_TTC) + v × Z).", "0 or more"),
    ("ccf", "check", "number or null", "Expected accounting CCF. Commitments must match it. Null means no check.",
     "0 to 1, or null"),
    ("macro_model", "calc", "text", "Named model that replaces `z_drivers`. Set in a run specification.", "Optional"),
    ("template_class", "report", "text", "Reporting class of the segment. P01 to P06 have built-in labels.",
     "Optional; a new segment in a static run needs one"),
)

SCENARIO_TOP = (
    ("scenario_set_id", "none", "text", "Identifier of the scenario set.", "Required"),
    ("source", "none", "text", "Source of the set.", "Required"),
    ("release", "none", "text", "Release date of the set.", "Required"),
    ("revision", "none", "integer", "Revision number.", "Required"),
    ("status", "check", "text", "Status of the set.", "Must be `SYNTHETIC`: `SCENARIO_PROVENANCE`"),
    ("scenarios", "calc", "list", "The scenarios in the set. Fields below.", "Required"),
    ("variables", "none", "list", ("List of variables with `id`, `label`, `unit` and `value_type`. The key must "
     "exist. The engine works from `values`."), "Required"),
    ("values", "calc", "list", "One row per scenario, variable, country and year. Fields below.", "Required"),
    ("starting_values", "calc", "list", ("Levels at the snapshot year. Read for the price indices listed in "
     "`index_of`."), "Needed for each index"),
    ("index_of", "calc", "mapping", "Maps an annual price change to the index it compounds into.", "Optional"),
)

SCENARIO_RECORD = (
    ("id", "calc", "text", "Name used in `run.scenarios`, such as `baseline`.", ("Must exist if requested: "
     "`UNKNOWN_SCENARIO`")),
    ("label", "none", "text", "Display name.", ""),
    ("status", "check", "text", "Status of the scenario.", "Must be `SYNTHETIC`: `SCENARIO_PROVENANCE`"),
    ("source_type", "check", "text", "Origin of the scenario, such as `synthetic`.", ("A synthetic scenario must "
     "be labelled `SYNTHETIC`")),
)

SCENARIO_VALUE = (
    ("scenario", "calc", "text", "Scenario the value belongs to.", "Unique with variable, country and year"),
    ("variable", "calc", "text", "Variable name. Models and `z_drivers` refer to it.", ""),
    ("country", "calc", "text", "Country code. A facility's country must appear here.", ""),
    ("year", "calc", "integer", "Year of the value.", ""),
    ("value", "calc", "number", "The value, in `unit`. Blank means missing.", "Finite"),
    ("unit", "calc", "text", "Unit. R2 converts to decimals: `percent` × 0.01; `decimal` and `index` × 1.",
     "`percent`, `decimal`, `index`"),
    ("value_type", "check", "text", "Kind of value. Checked against the list. It does not transform the value.",
     "`level`, `growth`, `index`, `cumulative_change`, `pp_change`, `bp_shock`"),
    ("source", "none", "text", "Source of the value.", "Required"),
    ("release", "none", "text", "Release of the value.", "Required"),
    ("completeness", "none", "text", "Completeness label.", "Required"),
    ("status", "check", "text", "Status of the value.", "Must be `SYNTHETIC`"),
)

SCENARIO_START = (
    ("variable", "calc", "text", "Variable or index name, such as `cre_price_index`. Only index rows are read.", ""),
    ("country", "calc", "text", "Country code.", ""),
    ("year", "none", "integer", "Year of the level: the snapshot year.", ""),
    ("value", "calc", "number", "The level.", ""),
    ("unit", "none", "text", "Unit of the level.", ""),
    ("value_type", "none", "text", "Kind of value.", ""),
)

MANIFEST = (
    ("input_set_hash", "calc", "text", ("SHA-256 over the sorted file hashes. The folder is named by its first "
     "16 characters."), "Mismatch blocks: `INPUT_HASH_MISMATCH`"),
    ("files.<file>.sha256", "calc", "text", "Hash of each of the seven datasets.", "Any change blocks at R2"),
    ("files.<file>.rows", "none", "integer", "Row count of a table. Null for the YAML files.", ""),
    ("control_totals", "calc", "mapping", ("Row counts and totals of GCA, undrawn, allowance and provision, by "
     "portfolio and stage."), "Must match the loaded data: `CONTROL_TOTAL_MISMATCH`"),
    ("spec_version", "calc", "text", "Requirements version. Part of the run identity.", ""),
    ("status", "report", "text", "Data status. Copied to the run manifest.", ""),
    ("parameter_set_id", "report", "text", "Parameter set in this input set. Copied to the run manifest.", ""),
    ("parameter_set_status", "none", "text", "Status of the parameter set when the set was built.", ""),
    ("generator", "report", "mapping", "What built the set. Copied to the run manifest.", ""),
    ("calibration_plan", "none", "mapping", "Grade plan the generator used, by segment.", ""),
)

APPROVAL = (
    ("input_set_hash", "check", "text", "Input set the record belongs to.", ("Mismatch blocks: "
     "`INPUT_HASH_MISMATCH`")),
    ("status", "report", "text", "Approval state. Shown in `analysis_readiness.csv`.",
     "`APPROVED` or `PENDING_OWNER_APPROVAL`"),
    ("approved_by", "report", "text or null", "Approver.", "Required when `APPROVED`"),
    ("approved_on", "report", "date or null", "Approval date.", "ISO date; required when `APPROVED`"),
)

# Run specification: field, required, type, definition, allowed values.
SPEC_TOP = (
    ("schema_version", "Yes", "integer", "Version of this file format.", "`1`"),
    ("status", "Yes", "text", "Status of the file.", "`SYNTHETIC` only"),
    ("source", "Yes", "text", "Who wrote it and on what basis.", "Not empty"),
    ("version", "Yes", "text", "Version of this experiment.", "Not empty"),
    ("input_set_hash", "Yes", "text", "Full hash from the input set's `manifest.json`.", "Must match"),
    ("run", "Yes", "mapping", "Run settings. See below.", ""),
    ("scenarios", "No", "mapping", "New scenarios, by name.", ""),
    ("additional_values", "No", "list", "New driver paths or lag history.", ""),
    ("models", "No", "mapping", "Macro models, by name.", ""),
    ("segments", "No", "mapping", "Links, overrides and new segments, by segment name.", ""),
    ("assignments", "No", "list", "Moves facilities to another segment or portfolio.", ""),
    ("reporting", "No", "mapping", "Reporting labels.", ""),
    ("terminal_policies", "No", "mapping", "How each scenario fades after 2029.", ""),
    ("balance_sheet", "No", "mapping", "Volume rates for a dynamic run.", ""),
)

SPEC_RUN = (
    ("inputs", "Yes", "path", "Input-set folder. Relative to the specification file.", ""),
    ("scenarios", "No", "list", "Scenarios to run. Must include `baseline`.", "Default `[baseline, adverse]`"),
    ("variant", "No", "text", "Variant from the parameter set.", "Default `core`"),
    ("mode", "No", "text", "Run mode. `regulatory` is recognised and blocks.", "Default `synthetic`"),
    ("balance_sheet", "No", "text", "Static book, or volumes changed by `balance_sheet.assumptions`.",
     "`static` (default), `dynamic`"),
    ("terminal_treatment", "No", "text", "Revert Z, or revert the parameters, after 2029.",
     "`z` (default), `parameters`"),
    ("s2_treatment", "No", "text", "Reprice S2 each year-end, or hold it once booked.",
     "`repriced` (default), `held`"),
    ("horizon_runoff", "No", "text", "Contractual run-off, or replacement inside the horizon. Bullet only.",
     "`contractual` (default), `replaced`"),
    ("lgd_path", "No", "text", "LGD from each year's Z, or from the worst Z for property-secured books.",
     "`annual` (default), `trough`"),
    ("analysis", "No", "path", "Optional analysis file. Relative to the specification file.", ""),
)

SPEC_SCENARIO = (
    ("narrative", "Yes", "text", "What the scenario represents.", "Not empty"),
    ("inherits", "One of two", "text", "Existing scenario to copy.", "Must already exist"),
    ("overrides", "No", "list", "Cells that replace inherited values. Path fields below.", "Needs `inherits`"),
    ("values", "One of two", "list", "A complete path, with no parent. Path fields below.", "No `inherits`"),
)

SPEC_PATH = (
    ("variable", "Yes", "text", "Variable name.", ""),
    ("country", "Yes", "text", "Country code, or `'*'` for all countries.", "A known country"),
    ("year", "Yes", "integer", "Year.", ""),
    ("value", "Yes", "number", "The value.", "Finite"),
    ("unit", "Yes", "text", "Unit of the value.", "`percent`, `decimal`, `index`"),
    ("value_type", "Yes", "text", "Kind of value.", "As in `scenarios.yaml`"),
    ("scenario", "`additional_values` only", "text", "Scenario, or `'*'` for all.", "Cannot overwrite a value"),
)

SPEC_MODEL = (
    ("kind", "Yes", "text", "Model type.", "`linear`, `polynomial`, `supplied`"),
    ("source", "Yes", "text", "Source of the model.", "Not empty"),
    ("version", "Yes", "text", "Model version.", "Not empty"),
    ("drivers.<variable>", "`linear`", "mapping", "`beta`, `mean` and `sd`. Z = Σ beta × (x − mean) / sd.",
     "sd above 0"),
    ("terms.<name>.variable", "`polynomial`", "text", "Variable the term reads.", ""),
    ("terms.<name>.mean, sd, beta", "`polynomial`", "number", "Coefficients of the term.", "sd above 0"),
    ("terms.<name>.lag", "No", "integer", "Years of lag. A lag needs history values.", "0 or more; default 0"),
    ("terms.<name>.power", "No", "integer", "Power of the standardised term.", "1, 2 or 3; default 1"),
    ("intercept", "No", "number", "Constant added to Z. For `polynomial`.", "Default 0"),
    ("values[]", "`supplied`", "list", ("Rows of `scenario`, `country`, `year`, `z`. One for every combination in "
     "the run, including countries with no exposure."), "Finite, unique"),
)

SPEC_SEGMENT = (
    ("inherits", "New segment", "text", "Existing segment to copy, with its matrix and parameters.",
     "Not on an existing segment"),
    ("macro_model", "No", "text", "Model to link.", "Must be in `models`"),
    ("template_class", "New static segment", "text", "Reporting class.", "Not empty"),
    ("portfolio", "No", "text", "Description only. Use `assignments` to move facilities.", ""),
    ("z_drivers", "No", "mapping", "Replaces the base drivers. Each needs exactly `beta`, `mean`, `sd`.", "sd above 0"),
    ("rho, sicr_k, lgd_w, cpr_ttc, cpr_v", "No", "number", "Override the base values.", "As in the parameter set"),
    ("ccf", "No", "number or null", "An expectation checked against commitments. Not an override.",
     "A mismatch blocks"),
)

SPEC_ASSIGNMENT = (
    ("where", "Yes", "mapping", ("Exact matches on `facility_id`, `portfolio`, `segment`, `country` or `nace_code`. "
     "All must hold."), "Must match a facility, and no earlier assignment"),
    ("segment", "Yes", "text", "Segment to move to.", "Must be configured"),
    ("portfolio", "No", "text", "Reporting portfolio to move to.", "A segment keeps one portfolio"),
)

SPEC_OTHER = (
    ("reporting.template_classes.<segment>", "No", "text", "Reporting class of a segment.", "A known segment"),
    ("terminal_policies.<scenario>.method", "Yes", "text", ("`flat` holds the 2029 Z. `reversion` moves it to "
     "baseline."), "Not for `baseline`"),
    ("terminal_policies.<scenario>.years", "For `reversion`", "integer", "Years of reversion.", ("1 or more; "
     "not with `flat`")),
    ("balance_sheet.assumptions[].scenario, year, portfolio", "Yes", "key", ("One row for each selected scenario, "
     "projection year and portfolio."), "Complete grid"),
    ("balance_sheet.assumptions[].drawn_change", "Yes", "number", "Annual change in performing drawn balance.",
     "−1 or more"),
    ("balance_sheet.assumptions[].undrawn_change", "Yes", "number", "Annual change in performing undrawn balance.",
     "−1 or more"),
)

ANALYSIS_TOP = (
    ("schema_version", "Yes", "integer", "Version of this file format.", "`1`"),
    ("status", "Yes", "text", "Status of the file.", "`SYNTHETIC` only"),
    ("source", "Yes", "text", "Source of the inputs.", "Not empty"),
    ("version", "Yes", "text", "Version of the inputs.", "Not empty"),
    ("input_set_hash", "Yes", "text", "Input set the file belongs to.", "Must match"),
)

ANALYSIS_SECTIONS = (
    ("benchmarks[]", "Selection diagnostic. Does not replace core results.",
     ("`exposure_id`, `country`, `pivot`, `family` (`pd_tr` or `lgd_lr`), `scenario`, `year`, `gca` (EUR, 0 or more), "
     "`model_available` (boolean), `route` (`ordinary`, `sovereign`, `central_bank`). Eligible models need "
     "`model_parameters` and `model_version`; a chosen fallback needs `benchmark_parameters` and "
     "`benchmark_version`. Transition keys: `tr11`, `tr12`, `tr13`, `tr21`, `tr22`, `tr23`. Loss keys: `lr11`, "
     "`lr12`, `lr13`, `lr21`, `lr22`, `lr23`. All rates 0 to 1.")),
    ("recoveries[]", "Recovery LGD diagnostic.",
     ("`facility_id` (unique), `ead` (EUR, above 0), `eir` (above −1), `collateral_id`, `collateral_value` (EUR), "
     "`allocation` and `haircut` (0 to 1), `cost` and `unsecured_recovery` (EUR), `recovery_years`, "
     "`model_version`. Shared collateral must agree, and allocations sum to at most 1.")),
    ("capital.weights[]", "Supplied regulatory outputs for the capital bridge.",
     ("`scenario`, `year`, `regulatory_approach` (IRB or STA), `regulatory_class`, `grade` (unique together), "
     "`regulatory_ccf` and `standardised_ccf` (0 to 1), `risk_weight` and `standardised_risk_weight` (0 or more), "
     "`model_version`. Must cover every opening and projected slice.")),
    ("capital.bridge[]", "One row per charge period.",
     ("`scenario`, `year`, `other_pnl`, `distributions`, `irb_shortfall_change`, `npl_deduction_change`, "
     "`other_cet1_change`, `other_utrea`, `other_strea` (EUR), `tax_rate` and `output_floor_factor` (0 to 1). "
     "The first period also needs `opening_cet1`.")),
    ("climate[]", "Separate diagnostic. Does not change macro losses.",
     ("`facility_id`, `channel` (`transition` or `flood`), `scenario: adverse`, `year`, `nace_code`, "
     "`energy_bucket`, `geolocation`, `flood_category`, `model_version`, `reference_transition`, "
     "`shock_transition`, `reference_loss_rates`, `shock_loss_rates`, `insurance_recovery` (EUR).")),
    ("template_mapping", "Long-cell export. Not an official EBA workbook.",
     "`version`, `cells[]`: unique `sheet`, `row`, `column`, plus `table`, numeric `measure` and `filters`."),
    ("challenge", "One-year severity and reverse-stress diagnostic.",
     "`severity_grid`, `loss_limit_eur`, `lower`, `upper` (lower below upper), `limit_name`."),
    ("npe_backstop", "Coverage calendar for the backstop diagnostic.",
     ("`version`, `source`, `scope_from`, `scope_to`, `calendar[]`: `from_year` (1 or more), `unsecured`, "
     "`secured` (0 to 1, never decreasing).")),
    ("plausibility", "Comparison with published data. Adverse only.",
     "`version`, `source`, `sources` (ID to reference), `rows[]`: `measure`, `scope`, `published`, `source`."),
)

CLI_OPTIONS = (
    ("--specification", "Run specification. When used, calculation settings must be in the file."),
    ("--inputs", "Input-set folder, `inputs/<hash>`."),
    ("--scenarios", "Comma-separated scenarios. Default `baseline,adverse`."),
    ("--variant", "`core` (default), `annuity`, `linear` or `utilisation`."),
    ("--balance-sheet", "`static` or `dynamic`."),
    ("--terminal-treatment", "`z` or `parameters`."),
    ("--s2-treatment", "`repriced` or `held`."),
    ("--horizon-runoff", "`contractual` or `replaced`."),
    ("--lgd-path", "`annual` or `trough`."),
    ("--analysis", "Optional analysis file."),
    ("--mode", "`synthetic` (default). `regulatory` blocks."),
    ("--runs-dir", "Where run folders go. Default `runs`. Allowed with `--specification`."),
    ("--quiet", "Warnings only on the console. Allowed with `--specification`."),
)
