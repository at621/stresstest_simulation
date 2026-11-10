# inputs/

Input sets for the run. Each input set is a folder named by its content hash, `inputs/<hash>/`. The one-off steps (O2–O4) write it, and nothing edits it afterwards; a new starting point is a new folder. A run names its input set by hash, and R2 checks every file against it.

A set holds four tables, one TTC matrix file per segment under `matrices/`, and two YAML documents. Two segments may name the same matrix file when their matrices are equal; no committed set does.

| Dataset | Format | Contents | Key |
|---|---|---|---|
| `facilities` | Parquet | Portfolio, segment, product, IFRS stage, POCI flag, accounting category, drawn balance (GCA with accrued interest), limit, interest rate, fixed/floating, residual maturity, repayment profile, regulatory approach and class, current and origination grade, TTC LGD, DPD, watchlist and forbearance flags with their observation date (`credit_status_date`), origination, stage entry and default dates, collateral type, LTV and DSCR | facility_id |
| `obligors` | Parquet | Country, counterparty sector, NACE code and version, SME flag, connected group, regulatory default | obligor_id |
| `commitments` | Parquet | Nominal undrawn, accounting CCF and its source, linked facility, asset category "not applicable" | commitment_id |
| `opening_provisions` | Parquet | On-balance allowance, off-balance provision, overlays with owner and reason, frozen at end-2026 | facility_id |
| `matrices/<segment>` | Parquet | One file per segment, at the path the segment's `ttc_matrix` names in the parameter set, for example `matrices/P01.parquet`. One-year probability of moving from each grade to each grade or to default, with each grade's rank and master-scale PD | from_grade, to_grade |
| `scenarios` | YAML | Variable, unit, value type (level, growth, index, cumulative_change, pp_change or bp_shock), year, country, scenario, source, release, completeness and status; each scenario's label and description. The section 6.2 paths, plus the synthetic scenarios of `foundation/scenarios.yaml` | scenario, variable, country, year |
| `parameter_set` | YAML | The horizon, the master scale, and the portfolios with their segments. Each segment names its PD, LGD and prepayment model and its TTC matrix file, and states its ρ, k, CPR_TTC and CCF. Also the terminal rule, conventions, tolerances, variants and the qualitative SICR triggers (`sicr_triggers`). The models' coefficients are not in it: the Z-score weights with driver means and standard deviations, w and v sit in the model functions in `src/stress/models/` (A42) | parameter_set_id |

Each set also holds `manifest.json`, with every file's SHA-256, each table's row count, the control totals R2 checks and the generator that wrote the set, and `approval.json`, the owner's approval record. The set hash covers the tables, the matrix files and the two documents, not these two files.

The table describes the form a set has had since 6 November 2026 (A42). Older sets that are still committed hold one `ttc_pd_matrix.parquet` for all segments and keep the coefficients in the parameter set, and the engine blocks on them at R2.

Synthetic input sets are committed to git. Real data is not part of v1.
