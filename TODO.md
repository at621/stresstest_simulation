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

Settled by the owner on 18 October 2026: all four recommendations confirmed, as used on branch `todo/loan-term-structure`.

- [x] **Valuation dates.** The 2026 snapshot only, or every date from 2026 to 2029? From 2027 on, a loan can sit in several grades, so we'd need one row per slice or a GCA-weighted blend. Recommendation: 2026 first, with per-slice rows if later dates are wanted. *Used: the export holds 2026 (`EXPORT_YEARS = [2026]`). The tables are built per slice, so adding a later year to `EXPORT_YEARS` gives one row per slice. The controls always cover 2026–2029.*
- [x] **S3 loans.** Include them in the summary with stage 3 and their allowance, or leave them out? Recommendation: include them in the summary, but not in the term structure. *Used as recommended.*
- [x] **One-off or permanent.** A notebook that reads a sealed run, with no engine change. Or a new output of every run, which goes through `/improve` with tests, gate, compare and `change-reviewer`. Recommendation: the notebook first. *Used: notebook.*
- [x] **Format and location** of the export (CSV, Parquet, Excel). Never write into `runs/`, `inputs/` or a new root folder. *Used: both tables as Parquet (unrounded, every column) and the loan summary also as CSV, in `notebooks/output/<run_id>/`, which git ignores.*

### Steps

- [x] Settle the open decisions above (confirmed by the owner, 18 October 2026).
- [x] Create a branch off `main` for this work.
- [x] Notebook `notebooks/04_loan_term_structure.ipynb` (02 was already taken): open a sealed run with `nb.open_run(...)` and read the tables through `run.table(...)` and `run.data(...)`.
- [x] Build the term-structure table: parameters joined to the PD curves by segment, country, scenario, valuation date, grade, bucket and fraction, plus the rate and maturity. (With the part-year item, the curves hold whole years: the join drops `fraction`, and a part-year bucket takes `d × m`.)
- [x] Build the loan summary: stage, 12-month and lifetime ECL (on and off balance), 12-month PD (m[1]), lifetime PD (F at maturity), LGD and DF of bucket 1, remaining maturity, rate, and the booked provision.
- [x] Controls, each recomputed from the run's own tables (no hand-typed expected values). All pass on run `20261018T1959Z-core-36ace84d`, both scenarios, every valuation date:
  - [x] S1 loans, 2026–2028: the recomputed 12-month ECL equals `raw_on` / `raw_off` in `provisions.parquet`.
  - [x] S2 loans: the recomputed lifetime ECL equals `raw_on` / `raw_off`.
  - [x] The bucket terms summed by segment, stage and bucket equal `ecl_buckets.parquet`.
  - [x] On every PD curve, `F + S = 1` and F never decreases.
  - [x] Every rate is consistent with its DF: `DF = (1 + r)^-t`.
  - [x] Added: every performing slice's stage follows from the SICR line, rebuilt by hand from the TTC matrix (MIG-07).
  - [x] Added: end-2029 S1 equals the loss-rate blend recomputed from `pd_curves`, `lgd_of_year` and the terminal weights in `drivers`, both scenarios; in the baseline it also equals the curve.
  - [x] Added: one event basis per scenario and valuation date, the same in `parameters` and `pd_curves`.
- [x] Export the two tables.
- [x] Add the notebook to the table in `notebooks/README.md`.
- [x] `uv run ruff check`. Clear the notebook outputs before committing.
- [ ] If it becomes permanent: run it through `/improve`, then update `README.md` and `docs/runbook.md`.

## Part-year PD bucket: build it in the curves or in ECL?

**Question.** When a facility's last period is shorter than a year, its PD for that part-year is `1 − (1 − PD)^d` (PD-06). Until 18 October 2026 R6 built it while creating the PD curves. It may belong in the ECL calculation (R8) instead, so that the curves hold full years only. The design doesn't say which step owns it: its R6 PD curve shows full-year buckets only, and PD-06 gives just the formula.

### What the code did until 18 October 2026

- **R6 builds it.** `pd_curves` (`src/stress/params/__init__.py:142-161`) adds a row per grade for every part-year length that facilities need, marked by `fraction < 1`. It applies each grade's part-year PD to the grade spread at the start of the bucket: `m = Σⱼ P[n][g, j] × (1 − (1 − PDⱼ)^d)`. In run `20261017T2304Z-core-b559d9dd` these are 214,720 of the 252,720 rows in `pd_curves.parquet`.
- **R8 only looks them up** (`_curve_arrays`, `src/stress/ecl/__init__.py:94`).
- **Except at end-2029 S1.** `terminal_s1` applies the same rule inside R8 (`src/stress/ecl/__init__.py:191-193`). So the rule lives in two steps.

### Things to find out

- R8 can't compute the part-year PD from the curve table alone. It needs each grade's spread at the start of the bucket, `P[n][g, j]`, and the curve table holds only its D column. Either R6 passes those spreads (or the PiT matrices of every year) to R8, or R8 recomputes them.
- A simpler rule from the curve alone, `S[n] × (1 − (1 − q[n+1])^d)`, applies the part-year rule to the grade-averaged PD instead of to each grade. It gives slightly higher part-year PDs, so it changes results and needs the owner's agreement and a design update first.
- Everything that reads `pd_curves` and may rely on the part-year rows: the loan term-structure task above (it joins on `fraction`), `notebooks/01_full_run_walkthrough.ipynb`, `notebooks/02_annual_pd_calculation.ipynb`, and the tests `test_at_41`, `test_at_42`, `test_at_50`, `test_run_controls` and `test_terminal_s1`.

### Findings (18 October 2026, run `20261018T1959Z-core-36ace84d`)

- **What R8 would need for the exact rule.** R8 already receives the PiT matrices in its `Parameters` bundle (`pit_matrices`), but only for 2027–2036. To get `P[n][g, j]` it would have to multiply them again, as R6 does for the curves, and rely on Z staying flat after 2036 for longer maturities (buckets run to 2060). The alternative is a new contract table of grade spreads at the start of each part-year from R6. Either way, R8 would take on matrix work that today belongs to R6 alone (`params/CLAUDE.md`: "PD comes only from the matrices").
- **The simpler rule gives *lower* part-year PDs, not higher.** `1 − (1 − x)^d` is convex in x for d < 1. Applying it per grade and then averaging, as R6 does, therefore gives at least as much as applying it to the grade average. The effect is tiny:
  - The part-year m falls by at most 0.00041.
  - S2 provisions fall by 0.02–0.03% in every scenario and year (−€0.02m to −€0.05m).
  - The cumulative charge moves by −€0.02m (baseline) and −€0.03m (adverse).
  - The two rules agree exactly when the part-year is bucket 1 (n = 0), so S1, including end-2029 S1, is unaffected.
- **"Two steps" apply one formula.** The end-2029 S1 use in `terminal_s1` is that n = 0 case: one-year PD per grade, then `1 − (1 − PD)^d`. It is the same number R6 would give for a part-year bucket 1, so the two steps cannot disagree.
- **Readers of the part-year rows.**
  - Rely on them: R8 `_curve_arrays`, `notebooks/02_annual_pd_calculation.ipynb` section 5 (rebuilds every part-year row and compares it with `pd_curves`), and `notebooks/04_loan_term_structure.ipynb` (joins on the exact `fraction`).
  - Read full-year rows only: the R10 reports (`pd_curves.csv`, `portfolio_pd.csv`), `notebooks/01_full_run_walkthrough.ipynb`, `test_terminal_s1`.
  - Would not notice a move: `test_at_41` (empty curves), `test_at_50` and `test_run_controls` (compare whole tables or basis sets), `test_at_42` (bucket 1 without a `fraction` filter, so moving the part-year rows out only simplifies it).
- **Found on the way.** `pd_curves` holds 520 part-year rows whose fraction equals another row's to 10 decimals but not exactly (for example 0.25 and 0.25 + 1e-16, from replacement dates). Their m differs by at most 1e-16. R8 keys part-year rows on the fraction rounded to 10 decimals and keeps the last one, so results are unaffected. Rounding the fraction once in R5 would remove these rows without changing any result.
- **Recommendation: keep the part-year PD in R6.** It is exact, needs no new contract, and the simpler rule would change results by a negligible amount in the direction opposite to the one this item assumed. Then record in `docs/assumptions.md` (A7) that R6 builds the part-year rows and R8 looks them up, applying the same rule itself only for end-2029 S1 with n = 0 (A27).

### Open decision (owner)

- [x] Keep the part-year PD in R6, or move it to R8. If R8: exact (pass the grade spreads) or the simpler rule (changes results)? Recommendation: keep it in R6 (findings above). *Settled by the owner on 18 October 2026: the part-year is captured by the maturity in the ECL calculation, pro rata. The curves hold whole years, and R8 takes `d × m[n+1]` (end-2029 S1: `d × PD`). This departs from PD-06's constant-hazard wording; see C10 in `docs/assumptions.md`.*

### Steps

- [x] Create a branch off `main` for this work (`todo/part-year-pd`).
- [x] Work out the points under "Things to find out" and bring them to the owner (findings above, 18 October 2026).
- [x] Settle the decision above. If it departs from the design, agree it first and update the design with it. (Agreed by the owner; the design's R6 PD curve and R8 text are updated. PD-06's text is the owner's to change, C10.)
- [x] If moving: run it through `/improve`. Keeping the formula must reproduce the last run (`stress compare`); the simpler rule must show its effect with `stress compare` output. (`stress compare` from `20261018T2152Z-core-fdcada28` to `20261018T2212Z-core-e1cf1ab2`: S2 provisions −0.09% to −0.29%, S1 at most −0.05%, S3 unchanged; cumulative charge −€0.14m baseline, −€0.34m adverse; `pd_curves.parquet` 252,720 → 38,000 rows.)
- [x] Record where the part-year PD is built in `docs/assumptions.md`, and update the loan term-structure task above if its join changes. (A7, A27 and C10 updated. The loan term-structure notebook now joins the curves on whole buckets and takes `d × m` for a part-year bucket. That needs this branch, which merges `todo/loan-term-structure`.)
- [ ] Owner: amend PD-06 (and add a note to PD-02) as C10 proposes, then O1 retranscribes `docs/spec/` and the owner signs it off (GOV-03).
- [ ] At the next input-set rebuild: rename or split the parameter-set convention `stub_pd: constant_hazard_by_grade`, which now describes O4 and the R3 SICR line only (A7).

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
- Design decision D5 ("Parameters after 2029") already notes that AT-06 pins only the first year and that the S2 choice awaits the owner's sign-off. (Signed off on 18 October 2026; see below.)
- `docs/assumptions.md` A27: with a part-year first bucket, the part-year rule is applied to each scenario's 2029 PD before the blend (see the part-year task above).

### Things to find out

- Read the draft paragraphs above. Confirm that it prescribes a loss-rate blend for the end-2029 S1 provision, and that the blend uses the 2029 PD and LGD, as the engine does.
- Size of the effect: recompute adverse end-2029 S1 from the curve (`m[1]` and LGD from the reverted 2030 Z) and compare it with the booked blend, by segment. This only reads a sealed run.
- Whether S1 and S2 using different views of 2030 makes a facility's end-2029 provision jump when it changes stage, and whether that is acceptable.
- The loan term-structure task above already flags that its recomputed end-2029 12-month ECL will differ from the booked provision for this reason.

### Findings (18 October 2026, run `20261018T1959Z-core-36ace84d`)

**The draft.** The draft note was downloaded from the URL in requirements §15 (S3): "2027 EU-wide stress test – Draft Methodological Note", 11 June 2026, 210 pages. The requirements had not checked it before ("Direct access to the two draft PDFs was unavailable").
- **End-2029 S1: the engine follows the draft.**
  - Box 4 (new S1, pp. 52–53) and Box 5 (existing S1, pp. 53–54) write the adverse 2029 provision as `… × (5/6 × PD-12M-S1Adv(2029) × LGD S1Adv(2029) + 1/6 × PD-12M-S1Base(2029) × LGD S1Base(2029))`. That is a blend of loss-rate products, using each scenario's 2029 PD and LGD for the missing 2030 values.
  - The baseline uses its own 2029 product, "given that PD-12M-S1Base is the same in 2029 and in 2030". That is the engine's rule, with a = 1.
  - The draft has no numerical example. The AT-06 numbers are the project's own, and correct: 2.1%, against 2.04% if PD and LGD were interpolated separately.
- **The citations hold.**
  - ¶55 (p. 28): forward-looking parameters for S1/S2, same-year parameters for S3.
  - ¶123–125 (pp. 49–51): perfect foresight, flat macro variables for S3 after 2029, the 6-year reversion for S1/S2, and time slices after the horizon.
  - Boxes 4–9 are the provisioning boxes.
  - Box 1 (p. 26) restates the 6-year reversion and could be added to the citations. The §15 note that the references are unverified can now be updated by the owner (step below).
- **S2 after 2029 differs from the draft's wording (D5).**
  - ¶124 (p. 50): "The path of each of the credit risk parameters for S1 and S2 exposures is assumed to linearly revert to those observed at the end of the baseline scenario over 6 years following the end of the adverse scenario." The parameters are "stage transition probabilities/PDs and the corresponding loss rates across stages", and the paragraph opens "Notwithstanding these assumptions on macroeconomic variables".
  - ¶125 has the time slices after the horizon follow that path.
  - The engine instead reverts Z linearly (ECL-10) and derives the matrices and LGD from it. Through Φ that path is not linear in the parameters: the PDs of 2030–2034 come out below the linear path. P03 IT G7: 2030 3.36% vs 3.43%, 2032 2.70% vs 2.83%.
  - For the end-2029 S1 provision, Boxes 4–5 simplify ¶124 to a blend of loss-rate products (Box 4: "Hence"; Box 5: "For simplification"). The engine follows the boxes for S1 and its own Z reading for S2.
- **Discounting.** The draft's S1 formulas carry no discount factor. The engine's `× EAD × DF` comes from ECL-08 (DESIGN), not from the draft.

**Size of the effect, adverse (the baseline blend equals the curve).**

| End-2029 S1, EUR m | P01 | P02 | P03 | P04 | P05 | P06_CI | P06_GG | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Booked: loss-rate blend | 2.10 | 0.92 | 10.71 | 8.61 | 12.50 | 0.53 | 0.10 | 35.48 |
| Curve: m[1] and LGD from the reverted 2030 Z | 1.95 | 0.90 | 10.41 | 8.30 | 12.25 | 0.49 | 0.10 | 34.41 |
| PD and LGD interpolated separately (AT-06's wrong answer) | 2.05 | 0.92 | 10.63 | 8.51 | 12.44 | 0.53 | 0.10 | 35.17 |

- The blend books €1.06m (+3.1%) more than the curve, from +1.9% (P02) to +8.6% (P06_CI). That is 0.14% of the adverse closing provisions (€774.6m).
- S2 with the draft's linear parameter reversion instead of Z reversion has the matrices `a × M_adv(2029) + (1 − a) × M_base(2029)` and LGD alike after 2029, with EAD and prepayment as now. Adverse S2 would rise by €1.04m (+0.5%) at end-2027, €1.40m (+1.0%) at end-2028 and €1.81m (+1.6%) at end-2029. That is +€1.8m on the cumulative adverse charge, the most in P06_CI (+5.7%) and P01 (+2.8%). This was measured from the sealed run with R6's own `pd_curves` function; nothing in the repository changed.

**Jump at a stage change.**
- An adverse slice that moves from S1 to S2 at end-2029 goes from the 12-month blend to the lifetime curve: 2.6 times the provision on aggregate (€35.5m → €93.6m for the S1 book).
- Of that step, the switch between the two views of 2030 is −1.8%. The S2 view of the 2030 bucket is the lower one, so it slightly offsets the step and never adds to it.
- The baseline has no such switch.
- The jump is therefore almost entirely 12-month against lifetime, which IFRS 9 intends. The difference in views is small and, if anything, errs low for S2. Adopting the draft's linear reversion for S2 would move its 2030 view toward the S1 blend.

**Loan term-structure task.** Its notebook (`notebooks/04_loan_term_structure.ipynb`, branch `todo/loan-term-structure`) recomputes the blend and checks that it equals the booked value. It shows the curve gap by segment in section 6.

**Recommendation.**
- Keep the loss-rate blend for end-2029 S1: it is the draft's own formula (Boxes 4–5).
- For D5's S2 choice, the owner picks one of two:
  - (i) sign off Z reversion as the project's reading and record the ¶124 wording as a conflict in `docs/assumptions.md`, with the size above (+1.6% of adverse S2);
  - (ii) follow ¶124 and revert the matrices and LGD linearly after 2029. That departs from "one Z drives matrix, LGD and prepayment" after the horizon, and goes through `/improve` with a design update.
- With the effect this small, (i) is enough for v1.

### Open decisions (owner)

- [x] Keep the loss-rate blend for end-2029 S1, as ECL-10 and AT-06 prescribe, or use the curve as in every other year. Changing it departs from the requirements and the design: it needs the owner's agreement, and AT-06 would change with it. Recommendation: keep it (the draft's Boxes 4–5). *Settled by the owner on 18 October 2026: keep the blend.*
- [x] The S2 choice in design decision D5 (reverted matrices and LGD), still awaiting sign-off. Recommendation: sign off Z reversion and record the ¶124 difference as a conflict (findings above). *Settled by the owner on 18 October 2026: Z reversion signed off; the ¶124 difference is conflict C8 in `docs/assumptions.md`.*

### Steps

- [x] Work out the points under "Things to find out" and bring them to the owner. No engine change is needed for this. (Findings above, 18 October 2026.)
- [x] Settle the decisions above and record the answers in the design (D5) and, if the method changes, in the requirements. (D5 updated; the method does not change.)
- [x] If the method changes: create a branch off `main`, run it through `/improve`, and show the effect with `stress compare` output. (Not needed: the method stays.)
- [ ] Owner: update requirements §15, whose note says the draft's paragraph references are unverified (they were checked on 18 October 2026, C8), and consider adding the draft's Box 1 (p. 26) to the citations of ECL-04 and ECL-10. `docs/spec/` is the owner's to edit; O1 then retranscribes it (GOV-03).

## Baseline 2027 releases provisions: O4 and the engine measure PD differently

**Problem.** Baseline 2027 shows a charge of −€5.0m: provisions fall from €278.6m to €273.6m, while 2028 and 2029 charge €32.0m and €33.6m. The release is not a credit effect. The frozen opening allowances (O4) and the engine measure PD in two different ways, and the gap between them lands in the first projected year.

### What the numbers show (run `20261017T2304Z-core-b559d9dd`, baseline, EUR m)

| Step | Amount |
|---|---:|
| Frozen opening allowances (O4) | 278.6 |
| Engine's own end-2026 valuation (`starting_point_reconciliation.csv`) | 238.2 |
| One-off gap between the two methods | −40.4 |
| 2027 charge on the engine's own basis (238.2 → 273.6) | +35.4 |
| Reported 2027 charge | −5.0 |

- The whole gap is in S1 and S2: S1 is 34.3 frozen against 22.7 on the engine's basis, S2 119.8 against 91.0. S3 is 124.5 in both.
- S2 provisions fall from 119.8 to 80.6 in 2027, while S2 GCA grows from 1,368.6 to 1,466.2.
- Adverse 2027 (343.5) starts from the same opening, so its first-year charge is understated too. The adverse-minus-baseline difference is largely unaffected.

### Cause

- O4 values the opening book with the TTC matrix itself (SYN-PAR-09, A8, C2), so Z = 0 there means an average year.
- The engine shifts the matrix with `Φ((Φ⁻¹(C) − √ρ·Z) / √(1−ρ))` (`src/stress/params/matrix.py:29`). Because of the √(1−ρ) divisor, Z = 0 is the median year, below the TTC average (design D13, A1).
- The design calls this "a little below TTC", but the gap is large. A grade with a 0.80% TTC PD and ρ = 0.15 gets ≈0.45% at Z = 0, and ≈0.42% at the baseline 2027 Z of +0.06. Low-PD grades roughly halve: P06 S1 is 0.76 frozen against 0.22 on the engine's basis.
- The code does what the design says, and `docs/assumptions.md` already lists the result under "Results that need the owner's eye" (see also A16). What needs deciding is the design choice.

### Options

1. **Drop the √(1−ρ) divisor**, the alternative D13 names. Z = 0 then gives back the TTC matrix exactly, as the LGD rule does. O4 and the engine agree, and C2 goes away. PDs rise in both scenarios (the 0.80% grade above: adverse 2027 ≈1.9% → ≈2.8%), so the adverse gets noticeably harsher and the Z-score moments (A19) need another look.
2. **Keep the engine and rebuild O4 with the engine's PiT matrix at Z = 0**, which gives a new input set. The opening falls to about €238m and baseline 2027 becomes about +€35m, with closing provisions unchanged. But the opening PDs then sit well below the §8.7 targets.
3. **Report only.** Split the 2027 charge into the one-off gap and the year's charge in the stock-to-flow report. No result changes, and nothing is fixed.

Recommendation: option 1.

### Things to find out

- Size of option 1 before deciding: its effect on the adverse cumulative charge and the S3 build-up, and whether A19 or ρ need retuning. A first, tighter A19 set gave 7.6% of GCA and was judged too severe.
- A separate pattern to check after the fix: in baseline, S2 coverage keeps falling after 2027 (5.5% → 4.4% → 3.6%) while the S2 book grows. It may be the worst S2 grades defaulting out each year, but it has not been checked.

### Findings (18 October 2026)

**Size of option 1.** Measured with an experimental run: the engine with the √(1−ρ) divisor dropped in memory, written to a scratch folder outside the repository, against run `20261018T1959Z-core-36ace84d`. That run is the `main` code and reproduces `20261017T2304Z-core-b559d9dd` exactly. No repository file changed, and the experimental run is not a result.

| EUR m | Baseline now | Baseline option 1 | Adverse now | Adverse option 1 |
|---|---:|---:|---:|---:|
| Engine's own end-2026 view (O4: 278.6) | 238.2 | 267.3 | 439.9 | 495.0 |
| 2027 charge | −5.0 | +38.9 | 343.5 | 439.5 |
| Cumulative charge 2027–2029 | 60.6 | 129.7 | 496.0 | 634.9 |
| Cumulative charge, % of GCA | 0.55% | 1.18% | 4.51% | 5.77% |
| Closing provisions 2029 | 339.2 | 408.3 | 774.6 | 913.5 |
| S3 GCA 2029 | 716.5 | 845.9 | 1,360.4 | 1,601.0 |

- The baseline 2027 release disappears. The gap between O4 and the engine's opening view falls from −40.4 to −11.3. What is left comes from the baseline Z sitting at or slightly above 0 (0.00 to +0.25 across segments in 2027–2029), which also moves LGD and prepayment. Where the baseline 2027 Z is exactly 0.00 (P04, P05, P06_GG), the engine's end-2026 S1 valuation equals O4 to the cent.
- The adverse cumulative charge rises by €138.9m (+28%), and the adverse-minus-baseline difference by €69.8m (435.4 → 505.2). S3 GCA at end-2029 rises by €240.6m in the adverse and €129.4m in the baseline.
- A19 and ρ: Z itself is unchanged. At 5.8% of GCA the adverse sits between today's 4.5% and the 7.6% of the first, tighter A19 set that was judged too severe. Nothing forces a retune; whether 5.8% is plausible is the owner's judgement.
- The 0.80% TTC PD example (ρ = 0.15) checks out. Z = 0: 0.45% → 0.80%. Baseline 2027 (Z = +0.056): 0.42% → 0.75%. Adverse 2027 (Z = −1.294): 1.93% → 2.82%.

**Baseline S2 coverage pattern.** Explained, and it is not the worst grades defaulting out.
- The S2 grade mix barely matters. Holding the 2027 segment × grade mix fixed gives 5.50% → 4.44% → 3.61%, against 5.50% → 4.42% → 3.59% actual.
- Coverage falls within each segment and grade because the same facilities age. Their GCA-weighted remaining maturity drops from 5.9 to 4.9 to 4.1 years, and the lifetime horizon shrinks with it. A facility is replaced only at maturity (D7, A15).
- The fall is steepest in the short-dated books: P02 coverage goes 14.0% → 10.7% → 8.2% and P03 8.4% → 6.5% → 5.2%.
- It is the expected behaviour of a static balance sheet with replacement at maturity. Option 1 keeps the pattern: 6.6% → 5.3% → 4.3%.

### Open decision (owner)

- [x] Option 1, 2 or 3. Options 1 and 2 change results. Option 1 departs from design D13; option 2 reverses A8 (item 3) and C2. *Settled by the owner on 18 October 2026: option 1.*

### Steps

- [x] Work out the points under "Things to find out" and bring them to the owner (findings above, 18 October 2026).
- [x] Settle the decision above. If it departs from the design, agree it first and update the design with it (D13, including the "a little below TTC" wording). (D13 and the R6 formula updated. PD-10's own text still shows the divisor; changing it is the owner's, see C9 in `docs/assumptions.md`.)
- [x] Create a branch off `main` for this work (`todo/first-year-release`).
- [x] Run it through `/improve` and show the effect with `stress compare` output against `20261017T2304Z-core-b559d9dd`. Option 2 also needs `uv run python -m foundation.synth` to build the new input set. (Compared against `20261018T2152Z-core-fdcada28`, which reproduces it; new run `20261018T2154Z-core-c10c21fd`. Cumulative charge 2027–2029: baseline €60.6m → €129.7m, adverse €496.0m → €634.9m.)
- [x] Update `docs/assumptions.md` (A1, A8, C2 and the first-year-charge note), the first-year-charge paragraph in `docs/technical-implementation/`, and `README.md` and `docs/runbook.md` wherever results or the input set hash appear. (`README.md` and `docs/runbook.md` name no results and the input set is unchanged, so they need nothing. Also done: C9, `docs/architecture.md` §6 items 3 and 7, `src/stress/params/CLAUDE.md`, and `notebooks/02_annual_pd_calculation.ipynb`, which rebuilds the shift by hand.)

## Qualitative SICR triggers: 30+ DPD, watchlist and forbearance

**Goal.** Add three qualitative triggers that move a performing facility from S1 to S2, alongside the relative PD test:

- [ ] **30+ days past due backstop**
- [ ] **Watchlist**
- [ ] **Forbearance**

The input data must carry all three for every facility, as checked inputs that can trigger S2 independently of the grade.

### What the code does now

- Stage comes from one rule only: a slice is S2 when the lifetime PD of its grade is at least k times the lifetime PD at origination (MIG-07, design D2). R3 checks it against the reported stage, and R7 applies it every year (`stage_of_rank`, `src/stress/projection/kernels.py:46`).
- MIG-07 and design D3 leave the three triggers out on purpose: "not used in the synthetic books". MIG-05 and PD-06 expect a bank's SICR to use qualitative triggers and to keep them separate.
- The input `facilities` table already has `dpd`, `watchlist` and `forborne` (`src/stress/contracts/inputs.py:88-90`). R2 loads them. R3 does not check them, and no step reads them.
- O3 sets them to agree with the stage the rule already gives (`foundation/synth/generate.py:384-414`). In input set `514ed0e86e3dc760`, no S1 facility is 30+ DPD, on the watchlist or forborne. Of the 1,324 S2 facilities, 432 are 30–89 DPD, 509 are on the watchlist and 143 are forborne. Switching the triggers on with today's data would change no opening stage.

### Input data

- [ ] Make `dpd`, `watchlist` and `forborne` required inputs on every facility. R3 rejects a missing value; it never reads it as "no trigger" (the same rule as `poci` today).
- [ ] Record the source definition and observation date of each flag (§12.2, credit status row).
- [ ] Put the trigger settings in the parameter set: the DPD threshold (30 days) and which triggers are switched on, per segment if needed.
- [ ] Change O3 so the flags are no longer just a copy of the stage. Some S2 facilities should be S2 because of a flag alone, with a grade still above the SICR line. The reported opening stage then equals "PD test or any flag". This restates SYN-PAR-08 and gives a new input set.

### Things to find out

- **Projection.** The flags exist at end-2026 only. In 2027–2029 the engine moves grades, not DPD, watchlist or forbearance. A flag belongs to a facility while stage belongs to a grade slice, so a flagged facility would make all its performing slices S2.
- **Effect.** Today, S2 slices whose grade improves back over the line return to S1 (€47.5m in baseline 2027, run `20261017T2304Z-core-b559d9dd`, before the √(1−ρ) divisor was dropped). If a flag holds a facility in S2, part of that return stops.
- **Facilities that can never reach S2.** The 930 facilities with no S2 grade (€417.7m, mostly long-dated P01 mortgages) can reach S2 only through these triggers. Check how many of them the new O3 flags.
- **Reporting.** Whether the stage migration report should split S2 by trigger: PD test, DPD, watchlist or forbearance.

### Open decisions (owner)

- [ ] **Agree the departure from the design.** This reverses the last sentence of MIG-07 and design D3. Agree it first, then update the design (D2, D3 and the R3 and R7 text) and the requirements (MIG-07, SYN-PAR-08). `docs/spec/` is written by code only, so the requirements change goes through O1.
- [ ] **How flags behave over 2027–2029.**
  - (a) Hold each flag at its opening value: a flagged facility stays S2 until it defaults.
  - (b) A flag lapses after a probation period.
  - (c) Project the flags from grade moves. This counts the same deterioration twice and is not recommended.

  Recommendation: (a) for v1.

### Steps

- [ ] Settle the decisions above.
- [ ] Create a branch off `main` for this work.
- [ ] Input data: change O3, rebuild with `uv run python -m foundation.synth`, and note the new input set hash.
- [ ] Engine, through `/improve`: tests first (new AT-48 cases for each trigger, R3 rejection of a missing flag, unit tests for the stage rule with flags), then the R3 check and the R7 stage. Show the effect with `stress compare` output against `20261017T2304Z-core-b559d9dd`.
- [ ] Update `docs/assumptions.md`, and `README.md` and `docs/runbook.md` wherever the input set hash or results appear.

## Follow-ups found in the reviews of 18–19 October 2026

Small points the `change-reviewer` found outside the changes it reviewed. None blocks a run today.

- [ ] **R6 rebuilds the share not yet prepaid itself.** `facility_parameters` (`src/stress/params/__init__.py:193-194`) computes SP[k] with a pandas `cumprod().shift(1).fillna(1.0)` instead of calling the tested kernel `not_prepaid_share` (`src/stress/params/prepay.py`). The two agree today. But `fillna(1.0)` would read a NaN prepayment rate as "no prepayment", against "missing is never zero". Have R6 call the kernel, or point the property test at R6's own code.
- [ ] **No range check on CPR_TTC and v.** R3 (`src/stress/validate/__init__.py`, `_check_parameters`) checks only that they are present. D14 requires CPR_TTC in (0, 1) and v ≥ 0. A finite and range check in R3 would also close the extreme inputs behind the float-saturation case of `test_not_prepaid_share`.
- [ ] **Notebook 02 starts runs directly.** Its `start_run()` calls `stress.cli.execute`, while `notebooks/README.md` says to start runs only with `nb.run_engine`. Either use `nbtools` or note the exception (notebook 02 imports no helper module on purpose).
- [ ] **Design header.** `docs/stress-engine-code-flow.html` still opens with "Proposal for agreement · 17 October 2026", although D5, D13, D2 and D3 now record owner decisions.
