# Assumptions and conflicts (v1 build)

The requirements and the design leave several inputs to the project owner. To deliver a working engine without waiting, Claude Code took the assumptions below. Each one is a proposal: approve it or replace it, and record the answer in the design or the requirements. Code or data that depends on an assumption names it by its A-number. Later improvements add their assumptions here too, with the next free number. The items still waiting on the owner are listed in [architecture.md](architecture.md) §6.

**Status:** all assumptions PROPOSED, none owner-approved. Built on branch `build/v1-engine`, 17 October 2026.

## How to change an assumption

| What | Where | Then |
|---|---|---|
| Parameter values (A2, A19) | `foundation/parameter_set.yaml` | `uv run python -m foundation.synth`, which writes a new `inputs/<hash>/`, then run the engine on it |
| Spec-derived values | the requirements, then `uv run python -m foundation.transcribe` | rebuild the input set |
| Conventions (A6–A11, A15–A17) | the named module | `uv run pytest` |

## Open owner inputs

| # | Owner input | Assumption taken |
|---|---|---|
| A1 | Agreement on D1–D14 | All fourteen design proposals taken as written, including D5 (S2 after 2029 uses the reverted matrices and LGD) and D13 (the √(1−ρ) divisor stays, so Z = 0 is the median year, a little below TTC). |
| A2 | Parameter values N, ρ, k, β, μ, σ, w, CPR_TTC, v, and where they are recorded | Proposed values in `foundation/parameter_set.yaml` (status PROPOSED); O3 copies them into every input set's `parameter_set.yaml`. N = 10 grades on a hand-set master scale 0.02%…18%, chosen so that each §8.7 target sits between two grades inside its §5.4 PD range. ρ: 0.06 consumer, 0.12 SME and corporate, 0.15 mortgages and CRE, 0.20 sovereigns and banks. k: 2.0 consumer, 2.5 most books, 3.0 P06. w: 0.10–0.25. CPR_TTC: 3–10%, 0 for P06. v: 0–0.25. |
| A3 | ParameterRecord key: include the grade slice, or define "cohort" as the slice | Cohort is the slice. Facility records (LGD, prepayment, EAD, DF) carry cohort `performing`, since they are the same for every performing grade slice of a facility. PD records are keyed by the curve (segment, country, grade) instead of `facility_id`, because every facility of a segment, country and grade shares one curve. Storing it per facility would repeat it about 6 million times. |
| A4 | `run_id` out of stored rows or out of the output hashes | Out of the stored rows. The run folder is the run, and `run_id` and the times appear only in `manifest.json`, so a rerun gives identical output hashes. |
| A5 | Country in the `scenarios` key | Yes. The §6.2 common paths are copied to each of the six countries, so Z is per segment, country, year and scenario, as SCN-08 states. |
| A6 | SICR horizon: remaining life at each valuation date, or fixed at opening | Fixed at opening: the facility's residual maturity at end-2026, the same for both lifetime PDs. This keeps MIG-07's "the SICR line is fixed per facility and only rating moves change stage". A replacement restarts with that same maturity. |
| A7 | PD for a stub final bucket | Constant hazard per grade (PD-06): the stub's marginal PD is Σ_j P(in grade j at the stub's start) × (1 − (1 − PD_j)^d). It is also used in O4 and in the R3 SICR line. |
| A8 | Architecture §6 items 2–4; O4 bullet or own schedule | Item 2: LGD-01 and LGD-04 stay as later production requirements and are not built (A12). Item 3: O4 uses the TTC matrix itself, not the PiT matrix at Z = 0. Item 4: the §8.7 opening LGD is the reference (mean) TTC LGD of each segment's generated facilities. O4 uses a bullet schedule, as SYN-PAR-09 and D8 say. |
| A9 | Provision for the undrawn part of a new S3 cohort | The defaulted undrawn stays in the static stock as nominal undrawn (AT-44 needs €2,000m every year). Its off-balance provision is booked once as undrawn flow × CCF × LGD of the default year, then floored like the drawn part. |
| A10 | Oracle values of AT-48, AT-51, AT-52 | They stay OPEN. Their tests prove the rule each case states (stage per SICR line; schedule profiles; Z at the means, the missing-coefficient block, the reversion weights) without numbers. |
| A11 | How a variant changes the repayment profile | Each variant is defined in the parameter set. `annuity` and `linear` apply to the amortising products (mortgage, consumer loan, term loan); revolvers and debt securities stay bullet. `utilisation` raises the P03/P05 accounting CCF to the AT-35 value (75%). `core` is bullet for every facility. |

## Other readings the requirements leave open

| # | Topic | Assumption |
|---|---|---|
| A12 | LGD-01, LGD-04 | Not built: LGD-12 uses no collateral or recovery data. The collateral fields (LTV, DSCR, type) are generated and kept as data. |
| A13 | Reference LGD (§8.7) | The generator draws each facility's TTC LGD from a beta distribution on the §5.4 LGD range, with the §8.7 value as its mean. |
| A14 | New S3 cohort after its entry year | Raw = GCA × LGD of the year; allowance = max(raw, prior), so it never falls below the booking (ECL-11, D6). |
| A15 | Replacement timing (EXP-05) | A facility that matures is replaced at its maturity date by one with the starting residual maturity. At each valuation year-end the contractual schedule restarts from the static stock balance (EAD-05, EAD-11). |
| A16 | End-2026 valuation | The engine also values the opening date with its own formula, as a diagnostic next to the frozen O4 allowances (starting-point report). Charges always start from the frozen allowances. |
| A17 | Rejection or block | The rule follows each requirement's own wording. **Block the run:** the EAD-04 and EAD-09 defects (missing or out-of-range CCF on a positive undrawn amount, negative amount, duplicate commitment, unexplained limit breach), and every dataset-level defect (matrix, scenario, parameter set, hash). R3 first writes every defective record to `rejections.parquet`, then the run is sealed with status BLOCKED. **Reject the record and continue:** the defects the requirements say "reject" (duplicate facility, currency and accounting scope) or "block the facility or calculation" (EAD-10 cash-flow inputs, SYN-PAR-08 grade and stage, LGD-12 missing TTC LGD). A rejected facility takes its commitment and opening provision with it, and the other way round. Rejected records stay visible as a DATA GAP line in the summary and the manifest (OPS-07). |
| A18 | Scenario units | The input set keeps the §6.2 values in percent with unit `percent`; R2 converts every value to a decimal fraction by its unit. |
| A19 | Z-score driver moments | Rough long-run euro-area moments: GDP growth 1.5% ± 3%, unemployment 6.5% ± 2%, residential prices 2.5% ± 8%, CRE prices 2% ± 10%, reference rate 2.5% ± 1.5%. The §6.2 adverse path then gives Z ≈ −1.3 in 2027–2028 and the baseline ≈ +0.1. A first, tighter set (GDP σ 2%) gave Z ≈ −2 and a cumulative adverse charge of 7.6% of GCA, which was judged implausibly severe. |
| A20 | Adverse without baseline | Blocks (BASELINE_REQUIRED): adverse Z reverts toward baseline 2029, and the end-2029 S1 interpolation needs baseline parameters. |
| A21 | Terminal horizon | Z is extended to 2060 (`terminal_rule.last_bucket_year`). A facility needing a later bucket blocks (AT-41). |
| A22 | P06 split | Government and bank facility counts follow 60/40 within each stage; GCA is raked to exactly 60/40. |
| A23 | Obligors and groups | All facilities of an obligor share its country, sector, current grade, stage and default status (SYN-01, PD-01). The origination grade is per facility. The ten largest groups in P04 and P05 are built from performing obligors. |
| A24 | Overlays | The v1 data has no overlays (explicit zero, with not-applicable owner and reason). R9 carries opening overlays unchanged, so none is counted twice. |
| A25 | CCF source | Each commitment carries its accounting CCF. It must equal the parameter set's segment CCF, otherwise it is rejected as CCF_MISMATCH. Variant overrides apply in R6. |
| A26 | Rounding | Report CSVs round EUR to cents and rates to 10 decimals; `summary.md` shows EUR millions to one decimal. All results Parquet files stay unrounded. |
| A27 | End-2029 S1 with a stub first bucket | The constant-hazard stub is applied to each scenario's 2029 PD before the loss-rate interpolation. |
| A28 | Run log and Excel report | `run.log` sits next to `manifest.json`, outside `results/`. It carries times, so the manifest hashes it for integrity, but it is not an output a rerun must reproduce. `stress_report.xlsx` is an output: its document and zip-entry times are fixed to the snapshot date so a rerun gives the same bytes, and it leaves out the run ID, which is in the manifest. It is written in EUR millions with engine values and Excel formulas; Excel recalculates on open. |

## Conflicts between documents

The design leads. Where another document disagrees, the build follows the design, or both readings where it can, and the conflict is listed here for resolution.

| # | Conflict | Resolution in the build |
|---|---|---|
| C1 | Design O4 says O4 uses "the facility's own schedule (D8)", but D8 and SYN-PAR-09 say a bullet schedule. | Bullet (A8). The design's O4 sentence should be corrected. |
| C2 | SYN-PAR-09 says "PD curves from the TTC matrix (Z = 0)", but under PD-10 the PiT matrix at Z = 0 is not the TTC matrix (architecture §6 item 3). | TTC matrix (A8). |
| C3 | MOD-06's key has no parameter name and includes run_id. The design's ParameterRecord has one value per record. | Records are wide per key, with one column per parameter and raw = final in v1. run_id is implied by the run folder (A3, A4). |
| C4 | Design D1 counts "up to 4 S3 cohorts" per facility, but MIG-03 keeps each new cohort's origin stage. | Up to seven S3 slices: the original, plus one per entry year and origin stage. |
| C5 | Design R1 "blocks on a synthetic scenario labelled official", but scenarios enter only through R2. | R1 blocks regulatory mode. The provenance control runs on the loaded scenarios (R4) and blocks the run there. |
| C6 | MIG-07 fixes the SICR line per facility; PD-06 forbids using "the original full-life PD as though it were the current remaining-life PD". | Both lifetime PDs use the same opening horizon (A6). The owner should confirm. |
| C7 | The workspace setup wants `"onFailure": "block"` on the hooks after the CLI upgrade; the terminal CLI here is 2.1.263. | Not added yet: an older CLI may reject the unknown key and drop the deny rules with it. Add it after upgrading to 2.1.295 or later. |

## Results that need the owner's eye

- **First-year charge from O4.** O4 values the opening book at TTC. The engine's baseline at Z ≈ 0 is the median year (A1, D13), so baseline 2027 releases €5m, while adverse 2027 charges €344m. The starting-point report shows the frozen O4 allowance next to the engine's own end-2026 view for each scenario.
- **S3 build-up.** With no cures, sales or write-offs (EXP-02), S3 grows from €364m to €717m in the baseline and €1,360m in the adverse by end-2029.
