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

### Open decision (owner)

- [ ] Option 1, 2 or 3. Options 1 and 2 change results. Option 1 departs from design D13; option 2 reverses A8 (item 3) and C2.

### Steps

- [ ] Work out the points under "Things to find out" and bring them to the owner.
- [ ] Settle the decision above. If it departs from the design, agree it first and update the design with it (D13, including the "a little below TTC" wording).
- [ ] Create a branch off `main` for this work.
- [ ] Run it through `/improve` and show the effect with `stress compare` output against `20261017T2304Z-core-b559d9dd`. Option 2 also needs `uv run python -m foundation.synth` to build the new input set.
- [ ] Update `docs/assumptions.md` (A1, A8, C2 and the first-year-charge note), the first-year-charge paragraph in `docs/technical-implementation/`, and `README.md` and `docs/runbook.md` wherever results or the input set hash appear.

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
- **Effect.** Today, S2 slices whose grade improves back over the line return to S1 (€47.5m in baseline 2027). If a flag holds a facility in S2, part of that return stops.
- **Facilities that can never reach S2.** The 930 facilities with no S2 grade (€417.7m, mostly long-dated P01 mortgages) can reach S2 only through these triggers. Check how many of them the new O3 flags.
- **Reporting.** Whether the stage migration report should split S2 by trigger: PD test, DPD, watchlist or forbearance.

### Findings (18 October 2026, input set `514ed0e86e3dc760`, run `20261018T1959Z-core-36ace84d`)

- **The flags today.**
  - No S1 facility is flagged.
  - Of the 1,324 S2 facilities, 432 are 30–89 DPD, 509 on the watchlist and 143 forborne. 833 carry at least one flag. The other 491 (€580.3m of €1,368.6m S2 GCA) are S2 on the PD test alone.
  - All 331 S3 facilities are 90+ DPD and on the watchlist, and 97 are forborne.
  - No flag is missing anywhere: `dpd` is an integer and `watchlist` and `forborne` are booleans, with no `__status` column. Making them required inputs therefore rejects nothing in today's set.
- **Facilities that can never reach S2: 930, €417.7m.** The PD test cannot move them, because k × their lifetime PD at origination is higher than the lifetime PD of any grade. Every one was originated at a weak grade.

  | Segment, product | Facilities | GCA, EUR m | Origination grades |
  |---|---:|---:|---|
  | P01 mortgage | 582 | 180.1 | G6, G7 |
  | P02 consumer loan | 216 | 4.3 | G9, G10 |
  | P03 revolver and term loan | 105 | 100.5 | G8, G9 |
  | P04 term loan | 18 | 91.8 | G8 |
  | P05 revolver and term loan | 9 | 41.0 | G8 |

  By count most are long-dated P01 mortgages (23.8 years on average). By GCA, 57% are SME and corporate loans. The new O3 should flag some of them, so that the triggers have something to do there.
- **Effect of option (a) with today's flags.**
  - Every flagged facility is already S2 at the opening. Option (a) therefore stops only their returns to S1.
  - The PD test sends €47.5m / €53.0m / €56.7m of S2 GCA back to S1 in the baseline (2027 / 2028 / 2029), and €13.8m / €18.0m / €39.3m in the adverse.
  - The part that belongs to flagged facilities is €27.3m / €50.8m / €70.5m of S1 GCA in the baseline (€8.1m / €13.3m / €21.8m adverse). Valuing it at lifetime instead of 12 months adds €0.43m / €0.53m / €0.49m to provisions in the baseline and €0.25–0.28m in the adverse.
  - With today's data the triggers are therefore almost neutral. Their real effect depends on the new O3: how many S1-by-grade facilities it flags, and which ones.
- **Projection and reporting.** Nothing new found. The points above stand: a flag is per facility and a stage per slice, and splitting S2 by trigger is a report choice.

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
