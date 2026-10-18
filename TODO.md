# TODO

## Loan-level ECL and term-structure table

**Goal.** Two tables for every loan, built from a sealed run:

1. **Loan summary**, one row per loan, scenario and valuation date: the loan's stage, its 12-month ECL, its lifetime ECL, PD, LGD, remaining maturity and discount rate. It sits next to the provision the run actually booked.
2. **Term structure**, one row per loan, scenario, valuation date and default bucket: the PD, LGD, EAD and discount factor of each year to maturity, plus that bucket's share of the ECL.

All the inputs exist already. The task joins tables and recomputes ECL; it adds no new modelling.

### Where each column comes from

| Column | Source | Note |
|---|---|---|
| stage, grade | `slices.parquet` | At the 2026 snapshot each loan has one slice. From 2027 on, a loan can be spread over several grade slices. |
| origination grade, SICR rank | input `facilities` (`run.data("facilities")`) | Shows why the loan is S1 or S2 |
| PD: q, m, S, F per bucket | `pd_curves.parquet` | Stored per segment, country and grade, not per loan. Join on the loan's grade. q is the conditional PD, m the marginal PD, S the survival and F the cumulative PD. |
| LGD per bucket | `parameters.parquet` | Point-in-time, from the Z of the bucket year. No recovery discounting (LGD-12). |
| EAD drawn and undrawn per bucket | `parameters.parquet` | Conditional on default. Prepayment is already applied. |
| discount factor per bucket | `parameters.parquet` / `cf_schedule.parquet` | DF = (1 + r)^-t, from the default date back to the valuation date |
| discount rate r | input `facilities`, `interest_rate` | Used as the EIR and held fixed for the loan's whole life, floating-rate loans included. This is not written to any results table. |
| remaining maturity, t, fraction, period end | `cf_schedule.parquet` | The final bucket can be a part-year stub |
| booked provision | `provisions.parquet` | Raw and constrained values, with the method used |

### How the ECL is computed (same as R8, `src/stress/ecl/`)

- Bucket term: `m[k] × EAD[k] × LGD[k] × DF[k]`. Drawn EAD goes to the on-balance allowance and undrawn EAD to the off-balance provision.
- 12-month ECL: bucket 1 only. When the first bucket is a stub, it covers only the stub.
- Lifetime ECL: the sum of all buckets up to maturity.
- Report both for every performing loan, whatever its stage. The booked provision uses the 12-month ECL for S1 and the lifetime ECL for S2.

### Caveats to show in the output

- **End-2029 S1.** The engine books the interpolated 2030 loss rate there (ECL-05, AT-06), not `m[1] × LGD[1]`. The recomputed 12-month ECL at 2029 will therefore differ from the booked provision. Show both and flag the difference; don't silently swap one for the other.
- **S3 loans** (331 at the snapshot). PD = 1. The allowance is `GCA × LGD of the year`, floored at the prior allowance (ECL-11). There is no 12-month or lifetime split and no term structure.
- **Raw vs constrained.** Floors can lift the booked value above the raw one. Keep both.

### Open decisions (owner)

- [ ] **Valuation dates.** The 2026 snapshot only, or every date from 2026 to 2029? From 2027 on, a loan can sit in several grades, so we'd need one row per slice or a GCA-weighted blend. Recommendation: 2026 first, with per-slice rows if later dates are wanted.
- [ ] **S3 loans.** Include them in the summary with stage 3 and their allowance, or leave them out? Recommendation: include them in the summary, but not in the term structure.
- [ ] **One-off or permanent.** A notebook that reads a sealed run, with no engine change. Or a new output of every run, which goes through `/improve` with tests, gate, compare and `change-reviewer`. Recommendation: the notebook first.
- [ ] **Format and location** of the export (CSV, Parquet, Excel). Never write into `runs/`, `inputs/` or a new root folder.

### Steps

- [ ] Settle the open decisions above.
- [ ] Create a branch off `main` for this work.
- [ ] Notebook `notebooks/02_loan_term_structure.ipynb`: open a sealed run with `nb.open_run(...)` and read the tables through `run.table(...)` and `run.data(...)`.
- [ ] Build the term-structure table: parameters joined to the PD curves by segment, country, scenario, valuation date, grade, bucket and fraction, plus the rate and maturity.
- [ ] Build the loan summary: stage, 12-month and lifetime ECL (on and off balance), 12-month PD (m[1]), lifetime PD (F at maturity), LGD and DF of bucket 1, remaining maturity, rate, and the booked provision.
- [ ] Controls, each recomputed from the run's own tables (no hand-typed expected values):
  - [ ] S1 loans, 2026–2028: the recomputed 12-month ECL equals `raw_on` / `raw_off` in `provisions.parquet`.
  - [ ] S2 loans: the recomputed lifetime ECL equals `raw_on` / `raw_off`.
  - [ ] The bucket terms summed by segment, stage and bucket equal `ecl_buckets.parquet`.
  - [ ] On every PD curve, `F + S = 1` and F never decreases.
  - [ ] Every rate is consistent with its DF: `DF = (1 + r)^-t`.
- [ ] Export the two tables.
- [ ] Add the notebook to the table in `notebooks/README.md`.
- [ ] `uv run ruff check`. Clear the notebook outputs before committing.
- [ ] If it becomes permanent: run it through `/improve`, then update `README.md` and `docs/runbook.md`.

## Part-year PD bucket: build it in the curves or in ECL?

**Question.** When a facility's last period is shorter than a year, its PD for that part-year is `1 − (1 − PD)^d` (PD-06). Today R6 builds it while creating the PD curves. It may belong in the ECL calculation (R8) instead, so that the curves hold full years only. The design doesn't say which step owns it: its R6 PD curve shows full-year buckets only, and PD-06 gives just the formula.

### What the code does now

- **R6 builds it.** `pd_curves` (`src/stress/params/__init__.py:142-161`) adds a row per grade for every part-year length that facilities need, marked by `fraction < 1`. It applies each grade's part-year PD to the grade spread at the start of the bucket: `m = Σⱼ P[n][g, j] × (1 − (1 − PDⱼ)^d)`. In run `20261017T2304Z-core-b559d9dd` these are 214,720 of the 252,720 rows in `pd_curves.parquet`.
- **R8 only looks them up** (`_curve_arrays`, `src/stress/ecl/__init__.py:94`).
- **Except at end-2029 S1.** `terminal_s1` applies the same rule inside R8 (`src/stress/ecl/__init__.py:191-193`). So the rule lives in two steps.

### Things to find out

- R8 can't compute the part-year PD from the curve table alone. It needs each grade's spread at the start of the bucket, `P[n][g, j]`, and the curve table holds only its D column. Either R6 passes those spreads (or the PiT matrices of every year) to R8, or R8 recomputes them.
- A simpler rule from the curve alone, `S[n] × (1 − (1 − q[n+1])^d)`, applies the part-year rule to the grade-averaged PD instead of to each grade. It gives slightly higher part-year PDs, so it changes results and needs the owner's agreement and a design update first.
- Everything that reads `pd_curves` and may rely on the part-year rows: the loan term-structure task above (it joins on `fraction`), `notebooks/01_full_run_walkthrough.ipynb`, `notebooks/02_annual_pd_calculation.ipynb`, and the tests `test_at_41`, `test_at_42`, `test_at_50`, `test_run_controls` and `test_terminal_s1`.

### Open decision (owner)

- [ ] Keep the part-year PD in R6, or move it to R8. If R8: exact (pass the grade spreads) or the simpler rule (changes results)? Recommendation: decide once the points above are worked out.

### Steps

- [ ] Create a branch off `main` for this work.
- [ ] Work out the points under "Things to find out" and bring them to the owner.
- [ ] Settle the decision above. If it departs from the design, agree it first and update the design with it.
- [ ] If moving: run it through `/improve`. Keeping the formula must reproduce the last run (`stress compare`); the simpler rule must show its effect with `stress compare` output.
- [ ] Record where the part-year PD is built in `docs/assumptions.md`, and update the loan term-structure task above if its join changes.

## End-2029 Stage 1: why a loss-rate blend instead of the PD curve?

**Question.** At end-2029 the engine books Stage 1 from a blend of 2029 loss rates (PD × LGD) instead of from the PD curve, as it does in every other year. Understand why, check it against the EBA draft, and decide whether it stays.

### What the code does now

- **2026–2028 year-ends:** 12-month ECL = `m[1] × EAD[1] × LGD[1] × DF[1]`, with m from the PD curve.
- **End-2029, S1 only** (`terminal_s1`, `src/stress/ecl/__init__.py:157`): `rate = a × PD_adv × LGD_adv + (1 − a) × PD_base × LGD_base` with `a = 5/6`, then `× EAD[1] × DF[1]`. PD is each grade's 2029 one-year PD (bucket 1 of the end-2028 curve) and LGD is the 2029 LGD.
- **Baseline:** `a = 1`, so it gets its own 2029 loss rate, which is what the curve gives anyway. Only adverse differs.
- **End-2029 S2:** uses the curve, with the reverted 2030+ matrices and LGD. So at end-2029 a facility's S1 and S2 provisions rest on two different views of 2030.

### Where it comes from

- ECL-10: end-2029 S1 uses the interpolated 2030 loss rate. ECL-05: interpolating the product PD × LGD is not the same as interpolating PD and LGD separately. AT-06 is the oracle: adverse 6% / 40%, baseline 2% / 30% → 5/6 × 2.4% + 1/6 × 0.6% = 2.1%.
- ECL-10 calls itself "the project's reading of ECL-03–ECL-05 and SYN-PAR-04". ECL-03 and ECL-04 cite the draft at [S3 ¶55, ¶123–125, Boxes 4–9].
- Design decision D5 ("Parameters after 2029") already notes that AT-06 pins only the first year and that the S2 choice awaits the owner's sign-off.
- `docs/assumptions.md` A27: with a part-year first bucket, the part-year rule is applied to each scenario's 2029 PD before the blend (see the part-year task above).

### Things to find out

- Read the draft paragraphs above. Confirm that it prescribes a loss-rate blend for the end-2029 S1 provision, and that the blend uses the 2029 PD and LGD, as the engine does.
- Size of the effect: recompute adverse end-2029 S1 from the curve (`m[1]` and LGD from the reverted 2030 Z) and compare it with the booked blend, by segment. This only reads a sealed run.
- Whether S1 and S2 using different views of 2030 makes a facility's end-2029 provision jump when it changes stage, and whether that is acceptable.
- The loan term-structure task above already flags that its recomputed end-2029 12-month ECL will differ from the booked provision for this reason.

### Open decisions (owner)

- [ ] Keep the loss-rate blend for end-2029 S1, as ECL-10 and AT-06 prescribe, or use the curve as in every other year. Changing it departs from the requirements and the design: it needs the owner's agreement, and AT-06 would change with it.
- [ ] The S2 choice in design decision D5 (reverted matrices and LGD), still awaiting sign-off.

### Steps

- [ ] Work out the points under "Things to find out" and bring them to the owner. No engine change is needed for this.
- [ ] Settle the decisions above and record the answers in the design (D5) and, if the method changes, in the requirements.
- [ ] If the method changes: create a branch off `main`, run it through `/improve`, and show the effect with `stress compare` output.
