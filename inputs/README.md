# inputs/

Input sets for the run. Each input set is a folder named by its content hash, `inputs/<hash>/`. The one-off steps (O2–O4) write it, and nothing edits it afterwards; a new starting point is a new folder. A run names its input set by hash, and R2 checks every file against it.

| Dataset | Format | Contents | Key |
|---|---|---|---|
| `facilities` | Parquet | Product, segment, IFRS stage, POCI flag, accounting category, drawn balance (GCA with accrued interest), limit, interest rate, fixed/floating, residual maturity, repayment profile, regulatory approach and class, current and origination grade, TTC LGD, DPD, watchlist and forbearance flags with their observation date (`credit_status_date`), default and stage entry dates | facility_id |
| `obligors` | Parquet | Country, counterparty sector, NACE code and version, SME flag, connected group, regulatory default | obligor_id, group_id |
| `commitments` | Parquet | Nominal undrawn, accounting CCF and its source, linked facility, asset category "not applicable" | commitment_id |
| `opening_provisions` | Parquet | On-balance allowance, off-balance provision, overlays with owner and reason, frozen at end-2026 | facility_id |
| `ttc_pd_matrix` | Parquet | One-year probability of moving from each performing grade to each grade or to default, one matrix per reference segment, with the master-scale grade definitions | segment, from, to |
| `scenarios` | YAML | Variable, unit, value type (level, growth, index), year, country, scenario, source, release, completeness and status | scenario, variable, year |
| `parameter_set` | YAML | Z-score weights with driver means and standard deviations, ρ, w, k, CPR_TTC and v per segment, CCFs, terminal rule, qualitative SICR triggers (`sicr_triggers`) | parameter_set_id |

Synthetic input sets are committed to git. Real data is not part of v1.
