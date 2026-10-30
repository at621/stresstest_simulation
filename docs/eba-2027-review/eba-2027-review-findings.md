# EBA 2027 review of the stress engine

| | |
|---|---|
| **Date** | 30 October 2026 |
| **Baseline** | `main` at `b59446e` (tag `v1.1.0`) |
| **Reference run** | `20261019T0511Z-core-05ddae55`, input set `d62d0386f2c5256e` |
| **Regulatory text** | EBA 2027 draft package of 11 June 2026. No final package was found at this date |
| **Status** | Findings and proposals by Claude Code. Not reviewed by `change-reviewer` and not decided by the owner. This review changed nothing in the engine, the requirements or the design |

## Summary

The engine's core method follows the EBA draft well. The review found two calculation gaps that understate provisions, one bug that can block a correct run, and several things the 2027 exercise needs that are not built.

- **Calculation.** Closing the two main gaps adds about €120m (19%) to the €635m adverse cumulative charge and about €52m (40%) to the €130m baseline charge.
- **Bug.** A check in R9 can only fail through float rounding, and when it fails it seals a correct run as BLOCKED.
- **Scope.** On `main` the engine stops at provisions, while the EBA reports impact in CET1 (¶26). Work on another branch adds a capital bridge from supplied inputs, but no CRR risk-weight calculation.

Recommended order: fix finding 5 first, because it is small and safe. Then settle findings 1 and 2, because they change results and depart from the design, so they need the owner's agreement before `/improve`. Finding 9 comes after them, because it depends on the parameters they change.

| # | Finding | Effect on cumulative charge (adverse / baseline) | Next step |
|---|---|---|---|
| 1 | S2 provisions shrink as exposures age | +€76m to +€90m / +€31m to +€52m | Owner decides, then `/improve` |
| 2 | LGD falls while collateral is at its lowest | +€40m / nil | Owner decides, then `/improve` |
| 3 | The S3 requirements conflict | Under €0.3m / nil | Owner amends the text |
| 4 | Run-off inside the horizon | Timing only: +€9.6m / +€6.9m in 2027, nil cumulative | Decide with finding 1 |
| 5 | R9 can block a correct run | None on a sealed run | `/improve` |
| 6 | Acceptance tests bypass the pipeline | None; weaker evidence | `/improve` |
| 7 | No traceability matrix | None | Build |
| 8 | `stress compare` is too narrow | None | `/improve` |
| 9 | No `CSV_CR_SCEN` replica | Template S1 is 5–11% above the engine | After findings 1 and 2 |
| 10 | LTV and maturity outputs are missing | None | `/improve` |
| 11 | No sector stress | Not sized | Owner decides |
| 12 | NPE backstop is not calculated | Not sized | After the capital work |
| 13 | No external plausibility check | Not applicable | Build; owner judges |
| 14 | Not ready for the final package | None | Build before the final package |
| 15 | Polish EUR exposures are not recorded as a conflict | None | Add to `docs/assumptions.md` |

## How the findings were reached

**Sources.** The draft note's chapter 2 (credit risk), sections 1.3.5–1.3.11 and ¶562–564, and section 2.2.2 of the draft template guidance. EBA/GL/2018/04 sections 4.6, 4.7.1 and 4.7.8. The Basel Committee's stress testing principles. The 2025 EBA results, the 2025 ESRB scenario and the 2025 ECB results as benchmarks. ¶ and Box numbers refer to the draft note, and § numbers refer to the requirements, unless stated otherwise.

**Engine evidence.** Code findings were read from `main`, and run statistics come from the sealed reference run. Sizes come from experimental runs: the engine was exported from `main`, patched in memory, and run with its folders outside the repository.

The control run reproduced all 15 Parquet outputs of the reference run by hash, so the differences below are measured against the real `v1.1.0` numbers. The `annuity`, `linear` and `utilisation` variants also seal on `main`.

| Run | What changed | Adverse cumulative, EUR m | Baseline cumulative, EUR m | Adverse charge 2027 / 2028 / 2029 |
|---|---|---:|---:|---|
| Control | Nothing | 635.0 | 130.4 | 439.8 / 108.0 / 87.3 |
| E1 | Residual maturity held at its opening value at every valuation date | 711.0 (+76.0) | 182.2 (+51.8) | 462.7 / 138.0 / 110.3 |
| E2 | Maturity extended to at least end-2029, and no prepayment in buckets up to 2029. R9 tolerance relaxed to 1e-6 (finding 5) | 635.0 (nil) | 130.4 (nil) | 449.4 / 105.3 / 80.4 |
| E3 | Adverse LGD of default years 2027–2029 taken at the path's worst Z, then reverting from that level | 675.3 (+40.3) | 130.4 (nil) | 457.9 / 120.1 / 97.3 |
| E1 + E3 | Both together | 755.1 (+120.0) | 182.2 (+51.8) | 482.5 / 151.9 / 120.7 |

**How far to trust the sizes.** Each experiment uses a simple proxy to size a gap and is not a proposed implementation. The parameter set is still PROPOSED, so the sizes will move with it.

## What the sources say

### EBA 2027 status

The EBA's stress test page lists only the draft package of 11 June 2026: methodology, templates and template guidance. It shows no 2027 scenarios, and searches found no later package. KPMG expects the final methodology around end-2026, the start in late January 2027 and results in August 2027. These are its expectations, not EBA dates.

The approach continues from earlier exercises: constrained bottom-up, static balance sheet, 2027–2029, no hurdle rate, and results feeding the SREP. The sample is 63 banks, and required data points fall by 55%.

The main credit changes are in reporting:

- `CSV_CR_SCEN` moves to FINREP-based portfolios and gross carrying amounts.
- A new `CSV_CR_SCEN_OFF_BS` template covers off-balance exposures.
- REA splits into separate STA and IRB templates under CRR3.
- The sector template moves to NACE level 1.
- A climate module is added, which does not affect core results.

### How a stress test should be run

The Basel Committee's principles and EBA/GL/2018/04 ask for:

- **Scenarios:** severe but plausible, internally consistent and backed by a narrative, run at several severities to reveal non-linear and threshold effects (GL ¶68, ¶75, ¶79).
- **Test types:** sensitivity analysis, scenario analysis and reverse stress testing (GL section 4.6).
- **Credit coverage:** PD, LGD including collateral values, and EAD including undrawn amounts (GL ¶104). Shocks should be market-wide, counterparty-specific and sector- or region-specific, with the effect on both provisions and own funds (GL ¶107, ¶112).
- **Concentration:** single names and connected groups, sectors, geography, products, and collateral and guarantees (GL ¶172).
- **Governance:** documented models, overlays that are justified and challenged, independent review, and backtesting or benchmarking (Basel principles 7 and 8).

The ECB's reverse stress test of 110 banks, published on 31 July 2026, gives a recent reading of what supervisors look for. Banks had to design scenarios reaching a 300bp CET1 depletion. The ECB's criticisms covered the granularity of risk assessment, consistency between narrative and impact, and overly optimistic mitigating actions.

### What already matches the draft

- The rating-matrix approach (¶119).
- No cures, and no S3 release checked per exposure (Box 2, ¶141).
- The end-2029 S1 loss-rate blend (Boxes 4–5).
- Stage flows that reconcile to the static book (¶86–89).

The six-year adverse reversion also matches, apart from the Z-based reading the owner signed off (C8).

## Findings

Changes to requirement text go through the owner and O1, because `docs/spec/` is written only by code.

### Calculation gaps

#### 1. S2 provisions shrink as exposures age

**Draft.** ¶76: "ECL on S2 assets may change afterwards only if, during the stress test horizon, exposures mature, amortise or migrate to S3 or S1." ¶125: "The ECL for the remaining part of S2 exposures shall be kept constant unless replaced." Requirement ECL-06 says not to reprice an unchanged S2 cohort repeatedly.

**Engine.** R8 re-prices S2 at every year-end on the facility's shorter remaining life and on the adverse years still ahead. Coverage falls while the stock grows, so the adverse S2 stock releases provisions in 2028 and 2029.

| Year-end | 2027 | 2028 | 2029 |
|---|---:|---:|---:|
| Adverse S2 GCA, EUR m | 1,788 | 2,102 | 2,235 |
| Adverse on-balance S2 coverage | 11.0% | 7.1% | 5.4% |
| Baseline S2 GCA, EUR m | 1,530 | 1,651 | 1,743 |
| Baseline on-balance S2 coverage | 5.7% | 4.6% | 3.7% |
| Adverse S2 weighted remaining maturity, years | 5.95 | 5.08 | 4.30 |

ECL-06 has no test. `TODO.md` records the baseline pattern as "the expected behaviour of a static balance sheet with replacement at maturity"; that note should be reopened.

**Effect.** Two measures bracket it:

| Measure | Adverse | Baseline |
|---|---:|---:|
| E1: residual maturity held constant | +€76.0m | +€51.8m |
| Exposures staying in S2 keep last year's coverage, and new S1-to-S2 inflows take that year's coverage | +€90.2m | +€30.6m |

The second measure is a calculation on the sealed run, not an engine run. It is higher in the adverse because it also stops adverse years leaving the lifetime window. It is lower in the baseline because it starts from the engine's end-2027 stock, while E1 also raises that stock.

Either measure moves the adverse first-year share of losses from 69% to 61–65%, closer to the 48% in the 2025 EU results.

**Open point.** Box 7 multiplies by `LRLT S2(t+1)`, a rate reported for each year, so the formula allows a yearly value even though the text says constant. The owner needs to settle the reading.

**Next step.** Decide the reading, update the design, add an ECL-06 test, then run it through `/improve`.

#### 2. LGD falls while collateral is at its lowest

**Draft.** ¶121 requires LGD to reflect the fall in collateral value. ¶123: "The first year of the LGD/LR calculation shall incorporate, for example, the cumulative house price shocks and the impact of the scenario in the workout period and respective time-in-default." ¶130 gives the same point for old S3.

**Engine.** LGD-12 and design D4 take the Z of the default year, and Z uses annual price changes. When prices keep falling but more slowly, Z improves and LGD falls, although the price level is still dropping. The compounded indices are calculated but feed nothing.

| Adverse | 2027 | 2028 | 2029 |
|---|---:|---:|---:|
| P04 Z | −1.50 | −1.32 | −0.58 |
| P04 exposure-weighted LGD | 48.6% | 46.8% | 39.8% |
| CRE price index | 85.0 | 74.8 | 71.1 |
| P04 average stressed LTV | 0.88 | 1.00 | 1.05 |
| P01 exposure-weighted LGD | 21.6% | 21.7% | 18.6% |
| Residential price index | 88.0 | 79.2 | 76.8 |

The S3 floors hide part of this: at end-2029 they mask €69.4m of on-balance LGD relief in the adverse.

**Effect.** E3 adds €40.3m in the adverse: S1 +€5.9m, S2 +€12.9m, S3 +€21.5m. Holding LGD at its worst year is only a proxy, and a model using the cumulative price fall could give a larger number.

**Next step.** Drive LGD from the property index level and each facility's LTV for the secured books. Both already exist. This changes LGD-12 and D4, and it would overlap with LGD-01, which is kept for later.

#### 3. The S3 requirements conflict

ECL-07 and Box 9 use the first-year estimate: `MAX{Exp S3(t=0) × LGD S3(t=1); Prov S3(t=0)}`, and ¶144 says "based on the first-year risk parameter". ECL-11 and D6 use the LGD of each year.

For new S3, ¶142 says provisions "are accumulated", while the engine re-floors each cohort against later years' LGD.

**Effect.** Very small here: +€0.12m on original S3 and +€0.17m on new S3, both adverse in 2028. Later-year LGD barely exceeds the 2027 value in this run.

**Next step.** The owner amends ECL-11 to match ECL-07 and Box 9, together with finding 2, because that finding decides what the first-year LGD contains.

#### 4. Run-off inside the horizon

¶125: "Maturity and amortisation of exposures without replacement can only be assumed by banks for time slices after the stress test horizon." In lifetime ECL, the engine applies prepayment and contractual maturity to the 2027–2029 time slices as well.

**Effect.** E2 moves the charge between years: adverse +€9.6m, −€2.7m and −€6.9m; baseline +€6.9m, −€2.6m and −€4.2m. The cumulative effect is nil, because the end-2029 valuation has no horizon slices left.

**Next step.** Low priority. Decide it with finding 1, since both change the same lifetime calculation.

### Bugs and test gaps

#### 5. R9 can block a correct run

[The bridge check](../../src/stress/accounting/__init__.py#L52) tests `opening + charge + fx + other - closing` against `RELEASE_EPS = 1e-9`. But `charge` is defined as closing minus opening, and FX and other movements are zero, so the identity always holds and only float rounding can trip it. When it trips, the run is sealed BLOCKED with `NOT_PERMITTED_MOVEMENT`.

Above about €8.4m, adjacent float64 values are 1.9e-9 apart, wider than the tolerance. Rounding appears when opening is well below closing, which is what happens when a large facility defaults.

- **Seen in practice:** experiment E2 blocked on a residual of 1.863e-09 EUR on a €14.7m allowance, and sealed once the tolerance was relaxed.
- **Example:** opening €441,702.80 and closing €13,605,787.16 fail the check.
- **Frequency:** 1.28% of random pairs with opening €10k–€1m and closing €8.4m–€16m fail.
- **Exposure today:** 6 of the reference run's 60,000 facility-years are above €8.4m, and none happened to fail. A larger book would hit this far more often.

**Next step.** Remove the check, or compare against the §12.3 tolerance. Add a test using the example above.

#### 6. Acceptance tests bypass the pipeline

21 of the 36 acceptance tests never go through a pipeline run: AT-02, 03, 04, 05, 06, 07, 08, 10, 11, 16, 18, 25, 28, 29, 33, 34, 36, 37, 38, 39 and 40. Those tests call a function directly.

At least 13 of them (AT-03, 05, 10, 11, 25, 29, 33, 34, 36, 37, 38, 39, 40) rest on helpers that no engine code calls. A green result there proves the helper, not the engine, because R7 and R8 use separate vectorised code. R5's `contractual_schedule` is the one case seen with a parity check: `test_kernels` and AT-51 compare it with the vectorised code. The 17 public functions with no caller in the engine are:

- `capital`: `methodological_floor`, `output_floor`
- `cashflows.kernels`: `drawn_measure`, `contractual_schedule`
- `contracts.status`: `status_column`
- `ecl.kernels`: `ecl_split`, `s1_loss_rate_provision`, `s3_original_allowance`, `monetary_loss`
- `params.ead`: `utilisation_sensitivity`, `permitted_transfer`, `regulatory_bridge`
- `params.lgd`: `loss_weighted_lgd`
- `params.pd`: `curve_from_conditional`, `curve_from_cumulative`, `lifetime_pd_ttc`
- `projection.kernels`: `aligned_default_flows`

Because `loss_weighted_lgd` has no caller, RPT-06's default-loss-weighted LGD is in no report.

**Next step.** Copy the AT-42 pattern, which puts a reference facility through a full run with `reference_runs`, wherever an AT has a pipeline equivalent. Keep kernel-only cases for pure arithmetic and label them as such.

#### 7. No traceability matrix

§14 lists a traceability matrix as deliverable 1, and none is in the repository. A scan of `main` found 42 of the 133 requirement IDs named in no code or test. It searches for ID names, so an unnamed requirement may still be met, and many are deferred on purpose in the design's "Handled elsewhere or later" list. Nothing records which is which.

CAP-01, CAP-02, CAP-05, CAP-06, CAP-07, CAP-09, DAT-05, DAT-06, DAT-07, GOV-01, GOV-02, LGD-01, LGD-04, MOD-01, MOD-04, OPS-02, OPS-03, OPS-05, OPS-06, OPS-08, OPS-09, PD-08, REG-03, REG-08, REG-09, REG-13, REG-14, RPT-02, RPT-03, RPT-04, SCP-01, SCP-03, SCP-04, SCP-05, SYN-01, SYN-02, SYN-03, SYN-PAR-06, VAL-01, VAL-02, VAL-03, VAL-04.

A further 33 IDs appear in code, directly or inside a range such as `ECL-01-ECL-11` in a docstring, but in no test. They include ECL-06, ECL-09 and MIG-03.

**Next step.** Generate the matrix from the spec and the test markers, with an explicit status per requirement: built, tested, deferred with a reason, or met by process.

#### 8. `stress compare` is too narrow

`compare_runs` in [the report module](../../src/stress/report/__init__.py) reads only `impairment.csv`, and the result is printed to the screen. §12.2 asks for a retained, quantified difference report. Stage stocks, coverage and parameters are not compared at all.

**Next step.** Add stage stocks, coverage, and PD and LGD by book, and write the report to a file. Runs stay write-once, so it cannot go inside a sealed run folder.

### Missing capabilities

#### 9. No `CSV_CR_SCEN` replica

The template calculates provisions from reported parameters (¶64, ¶133), so the reported PD, TR, LGD and LRLT must reproduce the engine's stock through Boxes 3–9. Nothing in the repository tests that.

A first replica at segment level used PD from stage flows, GCA-weighted LGD (¶67) and the 5/6 blend for end-2029 (EUR m):

| Scenario | Year-end | S1 template | S1 engine | Gap | New S3 template | New S3 engine | Gap |
|---|---|---:|---:|---:|---:|---:|---:|
| Adverse | 2027 | 107.7 | 102.5 | +5.0% | 203.9 | 203.5 | +0.2% |
| Adverse | 2028 | 52.3 | 48.8 | +7.3% | 199.9 | 199.7 | +0.1% |
| Adverse | 2029 | 44.0 | 41.2 | +6.8% | 113.4 | 113.3 | +0.1% |
| Baseline | 2027 | 27.8 | 26.4 | +5.3% | 58.0 | 57.8 | +0.3% |
| Baseline | 2028 | 25.6 | 23.8 | +7.7% | 55.3 | 55.1 | +0.2% |
| Baseline | 2029 | 24.7 | 22.3 | +11.0% | 53.5 | 53.4 | +0.2% |

About 4 points of the S1 gap are discounting: Boxes 4–5 carry no discount factor, while the engine discounts one year under ECL-08 and AT-40. The rest was not split. Likely causes are averaging PD and LGD separately instead of summing per facility, and part-year buckets, which the template does not have.

Also missing:

- The provision lines of ¶76 (`Prov S1-S1`, `S2-S1`, `S1-S2`, `S2-S2`). The engine does not track provisions by flow.
- A mapping of P01–P06 to the FINREP classes of Table 4.
- The CRR conversion factors ¶81 prescribes by approach, in place of the single 50% test CCF (ACC-03, SYN-PAR-07).

**Next step.** Build this after findings 1 and 2, as a report that reconciles template provisions to the engine's stock.

#### 10. LTV and maturity outputs are missing

¶69 asks for LTV on real-estate classes, with collateral following the scenario. ¶70 asks for average maturity. The `ltv` field and the price indices exist, but no calculation or report uses `ltv`.

A simple calculation, opening LTV divided by the index, shows what is not visible today:

| Adverse: share of GCA above 100% LTV | Opening | 2027 | 2028 | 2029 |
|---|---:|---:|---:|---:|
| P01 | 2.2% | 17.2% | 36.0% | 41.7% |
| P04 | 0.2% | 24.3% | 50.1% | 62.6% |

**Next step.** Add both outputs. No new modelling is needed.

#### 11. No sector stress

¶114: "The projected parameters are expected to be consistent with both the direction and the magnitude of the Gross Value Added shocks into the macroeconomic scenario." §5.1 names sector stress as a primary purpose of P03 and sector GVA as one of P05. SCN-03 asks for sector GDP/GVA.

Z has no sector dimension, so every sector in a segment takes the same shock. `nace_code` plays no part in the calculation. Adverse charge rates differ by section (P03 9.6–11.5%, P05 4.7–6.8%), but those differences can only come from the book's mix. `rate_type` is the same kind of gap: about 60% of P03 and P05 GCA is floating-rate, and no calculation uses the field, although SYN-02 expects floating-rate debt to be more vulnerable to rate rises.

**Next step.** The owner decides whether to extend the Z key. This changes SCN-08 and needs synthetic GVA paths.

#### 12. NPE backstop is not calculated

¶562–564 deduct insufficient NPE coverage from CET1, and footnote 75 applies a 35% minimum coverage for unsecured new S3 loans by end-2029. The engine's S3 cohorts carry the entry year and origin stage, and facilities carry origination dates and collateral type, which supplies part of the calculation.

**Next step.** Calculate the shortfall as part of the capital work rather than taking it as an input.

#### 13. No external plausibility check

Basel principle 8 expects benchmarking, and GL ¶62 expects external benchmarks where available. The engine's adverse result has not been compared with published outcomes. It shows about three times the EU loss rate under a milder GDP and unemployment path:

| Adverse, three years | This engine | EBA 2025 |
|---|---:|---:|
| Credit losses, % of exposure | 5.8% | 1.9% |
| S3 share, start to end | 3.3% to 14.6% | 1.7% to 6.0% |
| S2 share, start to end | 12.4% to 20.3% | 8.2% to 13.7% |
| First-year share of losses | 69% | 48% |
| CRE S3 share, start to end | 6.0% to 23.9% (P04) | 4.0% to 12.7% |
| GDP, cumulative | −4.5% | −6.3% |
| Unemployment rise | +3.2pp | +5.8pp |
| Residential prices, cumulative | −23% | about −19% |
| CRE prices, cumulative | −29% | about −30% |

The 2025 property figures compound the ESRB's annual cross-country medians, so they are approximate.

| Book | Adverse loss rate, three years |
|---|---:|
| P01 mortgages | 2.6% |
| P02 consumer | 14.4% |
| P03 SME | 10.3% |
| P04 CRE | 9.3% |
| P05 corporate | 5.7% |
| P06 sovereigns and banks | 1.1% |

For comparison, the ECB's highest class in 2025 was unsecured retail at 6.5%. In the baseline, P04 reaches 12.7% S3 by end-2029, the level EU CRE reached in the 2025 adverse.

This is not like for like: the book is deliberately riskier, with opening S3 nearly twice the EU share. But nothing tests whether that explains a factor of three.

Two calibration points add to this:

- A19 records that driver volatility was loosened after a first result (7.6% of GCA) was judged too severe. Severity was therefore set partly from the outcome.
- Z is not standardised. Every segment's |β| sum to 1, so Z has unit variance only if its drivers are perfectly correlated. With uncorrelated drivers its standard deviation would be 0.58 (P01), 0.71 (P02), 0.66 (P03), 0.62 (P04), 0.76 (P05), 0.83 (P06_GG) and 0.66 (P06_CI).

**Next step.** Build a benchmark sheet by book. Set the driver moments from published or estimated data rather than from the result. Standardise Z, or record why not. The owner judges the outcome.

#### 14. Not ready for the final package

If KPMG's expectation holds, the final methodology arrives within about two months, and paragraph numbers may move. GOV-01 asks for a dated source register and GOV-03 for an impact assessment of every source change. The requirements cite draft paragraphs inline and §15 lists the sources, but there is no register with local approval dates and affected requirement IDs, and no impact-assessment template.

**Next step.** Build the register now from the inline citations, and prepare a GOV-03 template. On publication, compare at least these against the final text: ¶123–125, Boxes 4–9, ¶113–118, ¶145–146, ¶153, ¶562–564 and the template columns.

#### 15. Polish EUR exposures are not recorded as a conflict

¶147–148 treat "exposures denominated in a currency other than the local currency of the borrower" as FX lending, with a 5% threshold per country of counterparty. Poland is 15% of each book and all of it is in EUR. §1.3 fixes one currency and no mismatch, including for the Polish exposures, so this is a scope decision and needs no build.

**Next step.** Record it as a conflict in `docs/assumptions.md` under the next free C-number, so the limitation is visible if the book ever moves towards real data.

## Work on another branch

`improve/eba-draft-preparation` began as `improve/calculation-controls`. On 30 October 2026 it held 22 changed tracked files plus new modules, all uncommitted, in the same working tree as this review. Its [status note](../implementation-status.md) reports all twelve of its review items as implemented, 148 tests passing, `change-reviewer` approval and default charges unchanged at €130.4m and €635.0m. This review read that work but did not test it, and the state may have moved since.

### Do not start these separately

The status note reports these as done on that branch:

- Run integrity and sealed-input replay
- Benchmark selection with the 10% test, as a synthetic selector
- Recovery-based LGD, as a diagnostic
- A capital bridge from supplied REA inputs
- Reporting exports and a versioned cell mapping
- Concentration, severity and reverse-loss diagnostics
- A selectable ¶124 parameter reversion
- CI

It also fixes a bug on `main`: `stress rerun` on a missing input set crashes with exit code 1 instead of the documented 2. It closes two of the follow-ups in `TODO.md` as well: the R6 `fillna(1.0)` and the missing CPR range check.

None of findings 1–15 is closed there. It partly touches finding 9 with a generic cell mapping, finding 11 with sector as a reporting dimension, and finding 12 by taking the deduction as an input.

### Results that can feed that work

**Concentration.** Expected-loss migration cannot see single names, so the group concentration that §5.1 names as a test purpose has no effect on the charge. The table adds a deterministic default of the largest non-sovereign groups, in the way the draft defaults the most vulnerable counterparties under CCR (Box 16).

| Largest groups, P03–P05 | EAD, EUR m | Loss over provisions held, EUR m | % of the adverse charge |
|---|---:|---:|---:|
| 1 | 150.0 | 53.0 | 8.3% |
| 3 | 421.6 | 147.5 | 23.2% |
| 5 | 622.3 | 218.0 | 34.3% |
| 10 | 1,020.1 | 350.5 | 55.2% |

EAD is GCA plus undrawn × CCF for performing facilities, the loss uses the adverse LGD of 2028, and provisions held are those at end-2029.

**Severity.** These are full engine runs with the distance between adverse and baseline Z scaled. The branch's reverse-stress report uses one-year PD × EAD × LGD, so it does not show these lifetime and stage effects.

| Shock multiple | Cumulative charge, EUR m | Multiple of the 1× charge | % of GCA | S3 share at end-2029 | First-year share |
|---:|---:|---:|---:|---:|---:|
| 1× | 635.0 | 1.0 | 5.8% | 14.6% | 69% |
| 1.25× | 838.6 | 1.3 | 7.6% | 17.2% | 72% |
| 1.5× | 1,082.2 | 1.7 | 9.8% | 20.3% | 75% |
| 2× | 1,703.0 | 2.7 | 15.5% | 28.1% | 79% |
| 3× | 3,476.8 | 5.5 | 31.6% | 48.6% | 85% |

The response is strongly non-linear (GL ¶68). At 3× about half the book is in S3, which is beyond the range where this model should be trusted.

### Points to check on that branch

- **Scope.** It adds a climate projection in `src/stress/ecl/climate.py`, but §1.3 and §9 exclude climate risk. Its status note says the request authorised scope extensions. If so, the requirements need the same change through O1.
- **Root folder.** It adds `.github/`, and `CLAUDE.md` requires the user's permission for a new root folder.
- **Branch size.** Twelve review items sit on one uncommitted branch, while `CLAUDE.md` asks for one branch per improvement. Parallel sessions in one working tree also see each other's unfinished code, so a run started here can use changes that are not committed.

## Limits

- The market-risk, NII, operational-risk and climate chapters of the draft were not reviewed.
- The June text is a draft and can change.
- The requirement scan (finding 7) matches ID names, and the caller scan (finding 6) is static, so both show where to look rather than prove a gap.
- The comparison with EBA 2025 (finding 13) is not like for like in perimeter or portfolio mix.
- Neither the experiments nor this document have been reviewed by `change-reviewer`.

## Sources

- [EBA EU-wide stress testing page](https://www.eba.europa.eu/risk-and-data-analysis/risk-analysis/eu-wide-stress-testing)
- [EBA press release, 11 June 2026](https://www.eba.europa.eu/publications-and-media/press-releases/eba-launches-early-consultation-simplified-eu-wide-stress-test-climate-risk-integration)
- [2027 EU-wide stress test: Draft Methodological Note](https://www.eba.europa.eu/sites/default/files/2026-06/7185aac4-4a70-4d83-ae1b-1cfca979ae07/2027%20EU-wide%20stress%20test%20-%20Draft%20Methodological%20Note.pdf)
- [2027 EU-wide stress test: Draft Template Guidance](https://www.eba.europa.eu/sites/default/files/2026-06/e4eedf91-0957-4f02-b4c9-22154f491904/2027%20EU-wide%20stress%20test%20-%20Draft%20Template%20Guidance.pdf)
- [EBA/GL/2018/04, Guidelines on institutions' stress testing](https://www.eba.europa.eu/sites/default/documents/files/documents/10180/2282644/2b604bc8-fd08-4b17-ac4a-cdd5e662b802/Guidelines%20on%20institutions%20stress%20testing%20%28EBA-GL-2018-04%29.pdf)
- [Basel Committee, Stress testing principles, October 2018](https://www.bis.org/bcbs/publ/d450.htm)
- [2025 EU-wide stress test: Results](https://www.eba.europa.eu/sites/default/files/2025-08/0178b9c5-2f0d-42ee-8226-6fa0a87c0d6c/2025%20EU-wide%20stress%20test%20-%20Results.pdf)
- [ESRB, macro-financial scenario for the 2025 stress test](https://www.esrb.europa.eu/mppa/stress/shared/pdf/esrb.stress_test250120~1bcaa4e336.en.pdf)
- [ECB, 2025 stress test of euro area banks, final results](https://www.bankingsupervision.europa.eu/ecb/pub/pdf/ssm.Report_2025_Stress_Test_202508.en.pdf)
- [ECB press release, 2026 geopolitical risk reverse stress test](https://www.bankingsupervision.europa.eu/press/pr/date/2026/html/ssm.pr260731~93964644b0.en.html)
- [KPMG Ireland, EBA 2027 stress test](https://kpmg.com/ie/en/insights/banking/eba-2027-stress-test.html)
- [Management Solutions, EU-wide Stress Test 2027](https://www.managementsolutions.com/sites/default/files/publicaciones/eng/eu-wide-stress-test-2027.pdf)
