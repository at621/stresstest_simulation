# Input and run specification, version 1

This is the current operational reference for the configurable engine. It covers the base
input set, run options, experiment YAML, model selection and output interpretation together.
The locked requirements v1.3 remain the historical acceptance baseline. Their unresolved
conflicts are listed below; this reference does not grant regulatory or model approval.

## Running and precedence

Run a complete specification:

```
uv run stress run --specification docs/examples/configurable-projection.yaml
```

Or use the original command without a specification:

```
uv run stress run --inputs inputs/57bf340df85d5a54 --scenarios baseline,adverse --variant core
```

With `--specification`, calculation flags must be placed in `run`, not on the command line.
`--runs-dir` (default `runs`) and `--quiet` are execution options and may accompany either
form. Relative `run.inputs` and `run.analysis` paths are relative to the specification file.
The Python API can supply omitted settings through `RunConfig`; supplied YAML settings take
precedence. The CLI disallows this ambiguity.

Only ingestion reads the new file. Its preflight resolves run settings before R1 assigns
the run identity. R2 captures those exact bytes, verifies the input-set binding, applies
the experiment in memory and preserves the original seven files unchanged. A replay reads
the sealed base input set, specification and optional analysis; it does not need the original
paths. Changing a specification creates a different run identity and requires a new run.

## Required specification envelope

| Field | Type / requirement |
|---|---|
| `schema_version` | Integer `1` |
| `status` | `SYNTHETIC`; regulatory execution is unavailable |
| `source` | Nonempty description of the source/authoring basis |
| `version` | Nonempty version identifier |
| `input_set_hash` | Full hash in the base input set's `manifest.json` |
| `run` | Mapping of the run options below |

Optional top-level sections are `scenarios`, `additional_values`, `segments`,
`assignments`, `reporting`, `terminal_policies`, and `balance_sheet`. Unknown top-level or
extension fields block. Names and classifications are case-sensitive. YAML is data; no
expressions, executable model paths or scripts are evaluated.

## Run options

| Field | Default | Meaning / allowed values |
|---|---|---|
| `inputs` | Required for a standalone specification | Immutable input-set directory |
| `scenarios` | `[baseline, adverse]` | Nonempty unique list of available scenario identifiers |
| `variant` | `core` | A variant defined in the base parameter set |
| `mode` | `synthetic` | `regulatory` is recognised and blocks |
| `balance_sheet` | `static` | `static` or `dynamic` |
| `terminal_treatment` | `z` | `z` or `parameters` |
| `s2_treatment` | `repriced` | `repriced` or `held` |
| `horizon_runoff` | `contractual` | `contractual` or `replaced`; replaced supports bullet schedules only |
| `lgd_path` | `annual` | `annual` or `trough` |
| `analysis` | Omitted | Optional versioned preparation analysis YAML |

The horizon and snapshot belong to the base parameter set, not a second set of run defaults.
Non-baseline runs still require `baseline`, which anchors lifetime/terminal calculations.

## Base input set: seven datasets

Five Parquet tables plus two YAML documents are mandatory. `manifest.json` contains file
hashes and control totals; its combined hash names the directory. `approval.json` is separate
owner evidence. An approval of the base set does not approve experiment overrides.

Amounts are EUR, probabilities/rates decimal fractions, dates ISO `YYYY-MM-DD`. Booleans are
strictly parsed. Each table field can carry a `<field>__status` companion: supplied, estimated,
zero, missing or not_applicable. Missing is not zero. Nullable at ingestion does not mean
optional for a calculation that requires that value. The executable column/type/nullability
definitions are `src/stress/contracts/inputs.py`; R3 enforces scope and applicability.

| Dataset | Key | Fields |
|---|---|---|
| `facilities.parquet` | `facility_id` | `facility_id`, `obligor_id`, `entity_id`, `portfolio`, `segment`, `product`, `ifrs_stage`, `poci`, `accounting_category`, `currency`, `principal`, `accrued_interest`, `accrued_in_gca`, `gca`, `contractual_limit`, `interest_rate`, `rate_type`, `residual_maturity`, `repayment_profile`, `regulatory_approach`, `regulatory_class`, `current_grade`, `origination_grade`, `ttc_lgd`, `dpd`, `watchlist`, `forborne`, `credit_status_date`, `origination_date`, `stage_entry_date`, `default_date`, `collateral_type`, `ltv`, `dscr`, `snapshot_date` |
| `obligors.parquet` | `obligor_id` | `obligor_id`, `group_id`, `entity_id`, `country`, `counterparty_sector`, `nace_code`, `nace_version`, `principal_activity`, `sme_flag`, `regulatory_default`, `snapshot_date` |
| `commitments.parquet` | `commitment_id` | `commitment_id`, `facility_id`, `currency`, `nominal_undrawn`, `accounting_ccf`, `ccf_source`, `asset_category`, `provision_classification`, `snapshot_date` |
| `opening_provisions.parquet` | `facility_id` | `facility_id`, `currency`, `allowance_on`, `provision_off`, `overlay_amount`, `overlay_risk`, `overlay_owner`, `overlay_reason`, `method`, `frozen`, `snapshot_date` |
| `matrices/<segment>.parquet`, one per segment, at the path its `ttc_matrix` names | `from_grade`, `to_grade` | Keys plus `probability`, `from_rank`, `to_rank`, `master_scale_pd` |
| `scenarios.yaml` | scenario, variable, country, year | Structure below |
| `parameter_set.yaml` | `parameter_set_id` | Structure below |

Supported products: `mortgage`, `consumer_loan`, `term_loan`, `revolver`, `debt_security`,
`guarantee`. On-balance scope is AC/EUR; commitments are a separate off-balance dataset.
Stages are 1/2/3; approaches IRB/STA. Performing grades share a master scale, followed by D.
Matrices are complete, nonnegative, stochastic, default-absorbing and increasing in default
probability with grade. A segment must belong to exactly one reporting portfolio.

New portfolios can supply these same tables and reuse the existing calculations. Freeze
prepared files without synthetic generation:

```
uv run python -m foundation.synth package --source <prepared-directory> --out inputs
```

This preserves supplied exposures and opening provisions, generates hashes/control totals,
and records pending owner approval. Financial validation still runs at R2/R3. It does not
estimate opening provisions, create new product logic or approve data. The original six-book
synthetic generator remains available and its Python design constants remain generator inputs.

## Base scenario and parameter documents

`scenarios.yaml` requires `scenario_set_id`, `source`, `release`, `revision`, `status`,
`scenarios`, `variables`, `values`. Scenario records include `id`, `label`, `status`,
`source_type`. Each value requires `scenario`, `variable`, `country`, `year`, `value`, `unit`,
`value_type`, `source`, `release`, `completeness`, `status`. `starting_values` supply property
index levels; `index_of` maps annual price-change variables to their index variables.

Units: `decimal` and `index` multiply by 1, `percent` by 0.01. Value types: `level`, `growth`,
`index`, `cumulative_change`, `pp_change`, `bp_shock`. The engine does not infer economic
transformations from those labels: supply the variable in the model's declared scale.
For example a one-percentage-point change is `1` percent or `0.01` decimal. A 100bp shock
is likewise `0.01` decimal, not `100` decimal. Annual price changes compound.

`parameter_set.yaml` requires:

- `parameter_set_id`, `version`, `status` (existing values remain PROPOSED).
- `horizon`: `snapshot_date`, `snapshot_year`, `projection_years`, `last_bucket_year`.
- `master_scale`: `grades`, `default_grade`, `ttc_pd`.
- `portfolios`: per portfolio its `segments`, and per segment exactly `pd_model`, `lgd_model`,
  `prepayment_model`, `ttc_matrix`, `asset_correlation`, `sicr_k`, `cpr_ttc` and `ccf`. A model
  is named `<portfolio>.<function>`, a function in `src/stress/models/` of the segment's own
  portfolio that holds its coefficients (A42); `ttc_matrix` names a file of the input set under
  `matrices/`. Any other setting, such as `z_drivers`, `rho`, `lgd_w` or `cpr_v`, blocks at R2.
- `terminal_rule`: `method`, `baseline`, `last_scenario_year`, `reversion_years`,
  `s1_end_of_horizon`. Supported execution is the existing linear reversion/flat-baseline
  convention with the selectable treatment above; arbitrary method strings are not plugins.
- `conventions`: recorded legacy `sicr_horizon`, `stub_pd`, `default_buckets`, `new_s3_undrawn`,
  `opening_allowance_matrix`, `opening_allowance_schedule`. These describe fixed implemented
  conventions rather than arbitrary executable strategy selectors; see conflicts below.
- `tolerances`: the existing named `abs`/`rel` probability, amount and aggregate tolerances.
- `variants`: each named variant has `label`, `repayment_profile` (product/default to bullet,
  annuity or linear), and `ccf` (segment overrides).
- `sicr_triggers`: `enabled`, `dpd_days`, `hold`, `definitions`, `source`. Supported hold is
  until_default; configured DPD/watchlist/forborne flags are observed at `credit_status_date`.

Core parameter domains: `0 <= asset_correlation < 1`, positive `sicr_k`, nonnegative LGD and
prepayment model sensitivities, `0 <= cpr_ttc <= 1`; CCF in [0,1] when applicable. Each linear
driver in a model has finite `beta`, `mean` and positive `sd`. Shared grade scale and
independently validated matrix rows remain required whichever model supplies the score.

## New scenarios and supplementary history

`scenarios` maps each new name to a nonempty `narrative` and either:

- `inherits: <existing-name>` with optional `overrides`, or
- a complete `values` list without inheritance.

Every path row has `variable`, `country`, integer `year`, finite `value`, `unit`, `value_type`.
`country: '*'` explicitly applies the row to all countries of the base set. Inheritance is
recorded in the effective specification. Overrides replace only the named cells; all others
come from the parent. Duplicate expanded keys, unknown parents and names already present in
the base set block. New scenarios may inherit earlier definitions in the same YAML mapping.

`additional_values` is a list with the same fields plus `scenario`. Both `scenario: '*'`
and `country: '*'` are supported. It supplies new driver variables or lag history, including
history for baseline. It cannot overwrite an existing value. Supply annual observations for
every model dependency; there is no automatic interpolation or missing-history imputation.

## Portfolio and sector assignment

`segments` maps a segment name to overrides of `portfolio`, `template_class`, `pd_model`,
`lgd_model`, `prepayment_model`, `asset_correlation`, `sicr_k`, `cpr_ttc`, `ccf`. A new segment
requires `inherits: <existing-segment>`, which explicitly copies its TTC matrix, models and
parameter defaults. Its models must stay those of its parent's portfolio, even when `portfolio`
reports it elsewhere.
Existing segments cannot be reparented. Supply a genuinely new matrix through the base input
set when copying is not the intended modelling assumption.

`portfolio` in segment settings is descriptive metadata; use `assignments.portfolio` to
change facility membership. `ccf` is a nullable alignment expectation for the supplied
commitments, not an effective CCF override. A conflicting specification expectation blocks
the whole run. Use a named base variant's CCF settings for a sensitivity, or package updated
commitment data. Coefficients are not specification data: point the segment at another model
of its portfolio instead. Unknown fields and invalid domains block.

`assignments` contains rows with `where`, `segment` and optional `portfolio`. Selectors are
exact matches on `facility_id`, `portfolio`, `segment`, borrower `country` or `nace_code`.
All predicates in a selector must match. Empty, unmatched or overlapping assignments block.
The assignment changes segmentation only; exposure amounts and opening provisions are retained.

For sector stress, assign the affected NACE population to a dedicated segment and point it
at a model of its portfolio that reads a supplied driver such as `manufacturing_gva`. Other sectors keep their models.
This is explicit segmentation, not an inferred relation between an arbitrary NACE code and GDP.

`reporting.template_classes` maps segment identifiers to nonempty reporting labels. It can
also be supplied as `segments.<id>.template_class`. Legacy P01–P06 mappings remain defaults;
new static-run segments need explicit mappings. These labels are not an approved FINREP mapping.

## Segment models

Each segment has a PD, an LGD and a prepayment model, each a function in
`src/stress/models/<portfolio>.py` that holds its coefficients and whose docstring describes it.
The parameter set names them; a specification may point a segment at another model of the same
portfolio and role, for example `segments: {P02: {pd_model: p02.pd_nonlinear}}`. Names outside
the registry, models of another role or portfolio, and coefficients in YAML block at R2
(`UNKNOWN_MODEL`, `MISSING_PARAMETER`). The inline `models:` section is no longer accepted.

The model functions are built from three forms in `stress.models.forms`:

| Form | Data in the function | Equation / interpretation |
|---|---|---|
| `linear` | drivers: variable to `{beta, mean, sd}` | Z = sum beta × (value − mean) / sd |
| `polynomial` | intercept and terms | Z = intercept + sum beta × ((lagged value − mean) / sd)^power |
| `supplied` | scores by scenario and year | Z taken as given, the same in every country |

Each polynomial term has `variable`, `mean`, `sd`, `beta`, optional integer `lag` (default 0,
nonnegative), and `power` (default 1; 1, 2 or 3). Coefficients and outputs must be finite. A
supplied score must cover every scenario and projection year of the run. R4 scores every
configured segment's three models across the base scenario countries.

Each model's Z drives its own parameter: the PD model's the matrix, the LGD model's the LGD and
the prepayment model's prepayment. The models each segment ran with, their location,
sensitivity and the first line of their description are in `segment_models.csv`; terms and
their contributions are in `driver_contributions.csv`, by model.
The effective specification retains lag, power, coefficients, inherited assumptions and
external-score data. This is model execution, not estimation or bank validation.

`terminal_policies.<scenario>` optionally chooses `method: flat` (hold its last score) or
`method: reversion` with positive integer `years` (revert towards baseline's last score).
Default is the base terminal rule. Baseline stays flat. The same scenario-specific weights
feed parameter reversion, terminal S1 valuation and the template replica. A run still needs
baseline. The legacy trough-LGD option changes LGD's score alone when explicitly selected.

## Dynamic exposure assumptions

Set `run.balance_sheet: dynamic` and provide `balance_sheet.assumptions`, a complete list
with `scenario`, integer `year`, `portfolio`, `drawn_change`, `undrawn_change` for each selected
scenario × projection year × accepted portfolio. Explicit zeros mean no volume change.
Changes are finite decimal rates, at least −1; duplicate, missing and unexpected keys block.

Each year, before credit migration:

```
performing drawn after volume = prior performing drawn × (1 + drawn_change)
performing undrawn after volume = prior performing undrawn × (1 + undrawn_change)
```

S1 and S2 grade proportions are retained during the volume adjustment. Existing S2 allowance
is scaled for the held-S2 alternative. S3 cohorts and their provisions are not scaled or
removed. R7 then migrates the adjusted performing exposures; R8 measures ECL on the resulting
slices; R9 compares against the actual previous closing provision. Volume-related releases
or charges therefore enter P&L once. No write-off or non-P&L movement is manufactured.

`exposure_movements.parquet/csv` retains opening exposure, change and migration-opening
exposure per facility/stage/year/scenario. The stage report reconciles outflows to opening
stocks plus volume changes; `dynamic_books.csv` reconciles the whole book cumulatively.
The original `static_books.csv` and EBA template replica are emitted only in static mode.

This is an externally specified volume forecast for the existing facility prototypes.
Growth is **not** a fresh loan vintage: it retains grade mix, maturity/replacement convention,
interest rate and product profile. No automatic contractual-stock runoff, new-origination
cohort, sales, cures, write-offs or endogenous lending model is inferred. Rates cannot create
exposure where that component is zero. Post-valuation lifetime EAD retains the chosen
contractual/prepayment convention and does not assume future growth of the current cohort.

Facility ParameterRecords remain on the opening-facility reference basis; R8 scales drawn
and undrawn separately to each current slice. In dynamic runs `ead_profile.csv` reports the
current performing-exposure-scaled profile. LTV uses current total facility GCA over the
original collateral value adjusted by scenario prices; no new collateral is inferred from
volume growth. Core LGD still uses its statistical model. Workbook stage/default/coverage
ratios use each scenario's own GCA. Summary average cost of risk uses opening GCA.

## Optional preparation analysis

The separate analysis YAML is referenced by `run.analysis`, bound to the same input hash,
and captured with the run. Required envelope: `schema_version: 1`, `status: SYNTHETIC`,
`source`, `version`, `input_set_hash`. Allowed sections:

| Section | Shape / role |
|---|---|
| `benchmarks` | Rows of supplied model/benchmark bundles; selection diagnostic, not core substitution |
| `recoveries` | Rows of supplied recoveries, costs, allocation and timing; LGD diagnostic |
| `capital` | `weights` and `bridge` inputs; supplied regulatory outputs, not CRR estimation |
| `climate` | Separate transition/flood projection rows; does not overwrite macro losses |
| `template_mapping` | Versioned long-cell export; not an official EBA workbook |
| `challenge` | Severity/reverse one-year loss diagnostic |
| `npe_backstop` | Supplied coverage calendar; no implicit regulatory calendar |
| `plausibility` | Published comparison data; no automatic calibration or approval |

The existing runnable preparation example in `docs/examples/README.md` supplies illustrative
values for the following fields. Actual inputs are copied into `effective_specification.json`.
Omitted analyses are reported NOT_PROVIDED. Incomplete supplied sections block. Adding a
crisis requires matching rows for any optional analysis whose contract covers all scenarios.

| Section | Input fields and domains |
|---|---|
| `benchmarks[]` | `exposure_id`, `country`, `pivot`, `family` (`pd_tr` or `lgd_lr`), `scenario`, integer `year`, nonnegative EUR `gca`, boolean `model_available`, `route` (`ordinary`, `sovereign`, `central_bank`). Eligible models require `model_parameters`, `model_version`; the selected fallback needs `benchmark_parameters`, `benchmark_version`. Transition family keys: `tr11`, `tr12`, `tr13`, `tr21`, `tr22`, `tr23`; loss family: `lr11`, `lr12`, `lr13`, `lr21`, `lr22`, `lr23`. All rates in [0,1]. Opening population/GCA must remain fixed across periods for selection. |
| `recoveries[]` | Unique `facility_id`, positive EUR `ead`, `eir > -1`, `collateral_id`, nonnegative EUR `collateral_value`, `allocation` and `haircut` in [0,1], nonnegative EUR `cost` and `unsecured_recovery`, nonnegative `recovery_years`, `model_version`. Shared collateral values must agree and allocations sum to at most 1. Single supplied recovery date; not a workout cash-flow model. |
| `capital.weights[]` | Unique `scenario`, `year`, `regulatory_approach` (IRB/STA), `regulatory_class`, `grade`; `regulatory_ccf` and `standardised_ccf` in [0,1], nonnegative `risk_weight` and `standardised_risk_weight`, nonempty `model_version`. Must cover all projected and opening slices. |
| `capital.bridge[]` | One row per charge period: `scenario`, `year`, EUR `other_pnl`, `distributions`, `irb_shortfall_change`, `npl_deduction_change`, `other_cet1_change`, `other_utrea`, `other_strea`; `tax_rate` and `output_floor_factor` in [0,1]. Distributions and other REA are nonnegative. First period needs nonnegative EUR `opening_cet1`; any later supplied opening must equal preceding closing. Tax is the existing symmetric synthetic convention. |
| `climate[]` | `facility_id`, `channel` (`transition` or `flood`), `scenario: adverse`, `year`, `nace_code`, `energy_bucket`, `geolocation`, `flood_category`, `model_version`, `reference_transition`, `shock_transition`, `reference_loss_rates`, `shock_loss_rates`, nonnegative EUR `insurance_recovery`. Transition matrices are 3×3 stochastic with absorbing S3; loss-rate vectors have 3 entries in [0,1]. Transition requires 2027–2029; flood requires 2027. Insurance cannot exceed positive incremental provision. This separate fixed-exposure diagnostic does not inherit dynamic core volumes. |
| `template_mapping` | Nonempty `version`, `cells[]` with unique `sheet`, `row`, `column` destinations; each has `table`, numeric `measure`, `filters` mapping exact dimension values. Matching rows are summed; empty selections block. Available tables are the generated analysis tables, including `dimensions`, `concentration`, `sicr_attribution`, `ecl_bridge`, `ltv`, `maturity`, static `template_replica` and supplied optional analyses. This exports long cells rather than filling an official workbook. |
| `challenge` | Nonempty nonnegative `severity_grid`, nonnegative EUR `loss_limit_eur`, nonnegative `lower` and `upper` severity bounds with lower < upper, nonempty `limit_name`. Runs a separate one-year anchor-PD/EAD/LGD diagnostic, not the selected macro model or dynamic path. |
| `npe_backstop` | `version`, `source`, ISO `scope_from`/`scope_to`, `calendar[]`: integer `from_year >= 1`, `unsecured`, `secured` factors in [0,1]. Unique periods start at 1; factors cannot decrease. Uses on-balance S3, original/default dates and supplied collateral data. No statutory calendar is embedded. Dynamic growth does not supply the missing legal modification-event classification. |
| `plausibility` | `version`, `source`, `sources` mapping source IDs to references, `rows[]` with `measure`, `scope` (portfolio or `Total`), finite `published` value, `source` ID. Supported measures: `credit_loss_rate`, `first_year_loss_share`, `s2_share_start`, `s2_share_end`, `s3_share_start`, `s3_share_end`, `gdp_cumulative`, `unemployment_rise`, `residential_price_cumulative`, `cre_price_cumulative`. Compares the named `adverse` scenario only; it does not infer which new crisis should replace that comparison. |

These legacy preparation sections validate their required fields and financial domains;
unlike the new experiment sections, they do not universally reject every extra nested key.
Do not treat extra metadata as a calculation switch. Recovery, benchmark and challenge
outputs are diagnostics, not replacements for core losses. The standalone climate and NPE
conventions require a separate production assessment before use with a business-volume forecast.

## Effective record and unresolved methodology

Every run writes `results/reports/effective_specification.json`: resolved run settings,
base input hash, parameter values, scenario paths/metadata, experiment sections, optional
analysis and known conflicts. This record is deterministic on replay. The raw base datasets
remain in `data/`, and the envelope/schema fields above are the authoring contract.

The following remain explicit, not silently fixed by a new configuration interface:

- C9: implementation follows the owner's divisor-free matrix shift; locked PD-10 text differs.
- C10: projected fractional ECL is pro rata; opening/SICR constant-hazard treatment differs.
- C11: qualitative SICR flags are enabled despite the older locked wording.
- C13–C16: S3 timing, S2 holding, in-horizon runoff and collateral/LGD interpretation decisions.
- Proposed parameters and AT-48/51/52 numerical oracles require owner sign-off.
- Final EBA package, official scenarios/benchmarks, bank validation, CRR/NPE inputs and
  approved official mappings remain production dependencies. Static is necessary for the
  exercise but does not itself establish compliance. Dynamic is an internal sensitivity.
