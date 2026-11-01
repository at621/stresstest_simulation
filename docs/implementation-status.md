# Stress-testing review implementation

Requested on 30 October 2026. Baseline: `runs/20261030T2013Z-core-31320d93`.

The request authorises the reviewed scope extensions. It does not attest to bank model validation,
approve numerical oracles, or supply official scenarios, benchmarks, capital inputs or submission
mappings. Those remain explicit dependencies. Existing synthetic conventions remain available.

## Delivery register

The subsequent six-goal extension is recorded separately in the
[configurable projection plan](eba-2027-review/implementation-plan.md). Its optional execution
capabilities do not close the regulatory and empirical-model dependencies listed here.

| Review item | Delivery | Verification / remaining dependency |
|---|---|---|
| 1–2 calculation and input controls | Implemented | Exact schedule coverage; strict types and finite domains; core comparison unchanged |
| 3 reproducibility and integrity | Implemented | Source content hashes, Python/package evidence, verified reads, sealed-input replay |
| 4 requirements and approvals | Implemented preparation controls | Methodology/approval evidence and readiness report; owner sign-offs remain open |
| 5 terminal treatment | Implemented selectable sensitivity | Linear matrix/PD and LGD reversion, including horizon S1; default retained |
| 6 independent validation | Implemented diagnostics | Gaussian quadrature checked against analytic expectation; owner numerical oracles remain open |
| 7 model/benchmark routing | Implemented synthetic selector | Complete bundles, fixed pivot populations, separate families, sovereign benchmark/central-bank routes; production model integration remains open |
| 8 LGD and SICR alternatives | Implemented diagnostics | Recovery amount/timing/discount/allocation controls; remaining-horizon thresholds |
| 9 capital interfaces | Implemented synthetic bridge | External regulatory/standardised CCFs and risk weights, separate floors, explicit CET1 movements |
| 10 reporting mappings | Implemented preparation exports | Country/NACE/stage aggregation; versioned cell mapping; official reporting package remains open |
| 11 climate module | Implemented separate synthetic projection | Adverse transition/flood windows, stage transitions and cohort floors, insurance and annual charges |
| 12 challenge and automation | Implemented diagnostics and CI | Concentrations, SICR flag attribution, severity/reverse-loss analyses and repeatable gate |

## Calculation controls

R8 must match facility parameter keys, fractions and default years to the independent R5
schedule, including terminal buckets. Missing or duplicate buckets and non-finite values block.
Boolean strings are parsed explicitly; invalid dates and infinite numeric inputs block at R2.
R3 validates the domains of the synthetic parameters. CPR endpoints zero and one remain valid
for deterministic boundary cases (including existing acceptance cases); rho is in [0,1), SICR
multiple is positive, and LGD/prepayment sensitivities are nonnegative. The core formulas are
unchanged. Only the first bucket receives prepayment survival one; a later missing value blocks.

## Draft reference and limits

The user authorised the June 2026 draft and synthetic examples, not official compliance or
bank-approved calibration. The reference is the [EBA draft methodology, 11 June 2026](https://www.eba.europa.eu/sites/default/files/2026-06/7185aac4-4a70-4d83-ae1b-1cfca979ae07/2027%20EU-wide%20stress%20test%20-%20Draft%20Methodological%20Note.pdf).
No final 2027 package was identified in the review dated 30 October 2026. The broader governance
review used the [BCBS stress-testing principles](https://www.bis.org/publications/201810-guidelines-stress-testing-principles.pdf).

The code delivers preparation workflows. It does not provide empirical model estimation,
bank historical backtesting, official ECB benchmarks or a submission-ready EBA workbook.
`--mode regulatory` remains blocked. No existing input set or owner numerical oracle is changed.

The benchmark selector implements a fixed opening population and the draft's 10% coverage
threshold independently for transition and loss-rate families. Sovereigns require supplied
benchmarks; the draft's conservative-own-estimate fallback when a country benchmark is
unavailable is **unsupported and blocks**. These selected bundles are reported for review and
are not automatically substituted into the rating-based core engine.

Recovery LGD is a one-recovery-date model, with a supplied net recovery, allocation control
for shared collateral and one discount to default. It does not create contractual cash flows
or replace the core TTC-LGD formula. Remaining-horizon SICR is a threshold comparison only;
it preserves the core stage path and the existing persistent qualitative flags.

The capital bridge uses supplied, versioned regulatory model outputs. It calculates separate
regulatory and standardised EAD, floors aggregate IRB and STA REA against their starting points,
then applies the supplied bank-wide output-floor factor after adding explicit other REA.
It does not implement CRR risk-weight, regulatory EL, DTA or NPL-deduction estimation. Those
effects enter as explicit inputs, including an explicit zero when applicable. Tax is a symmetric
synthetic rate; the example uses zero. The example's factor and risk weights are illustrations,
not prescribed values for 2027.

Climate is an independent projection from supplied stage-transition matrices and destination
loss rates (S1 12-month, S2 lifetime, S3 LGD), conditional on adverse macro stress. Transition
covers 2027–2029; flood covers 2027. It accepts selected AC NFC/house-purchase exposures,
retains NACE/energy/location/flood classifications and applies per-cohort S3 floors. Insurance
is an explicit reduction to incremental provision stocks; annual incremental charges are the
change in those stocks. Aggregate channel/year climate effects must not offset macro stress.
The examples cover one mortgage, not the full eligible bank perimeter. Climate values never
enter the core impairment or capital bridge; transition and flood are not summed together.

The severity and reverse-stress reports use one-year PD × accounting EAD × LGD under Z =
minus severity. They are diagnostic sensitivities to a named internal loss budget, not full
lifetime ECL or a regulatory capital breach. Calibration output checks mathematical cycle
averages under a standard-normal Z assumption; it is not validation against bank history.

See [the runnable example](examples/README.md), [runbook](runbook.md), and the preparation
addendum in the [design](stress-engine-code-flow.html#preparation).

## Full-book verification

The original baseline is `runs/20261030T2013Z-core-31320d93`. The completed default with all
synthetic analyses is `runs/20261030T2042Z-core-fb9fde74`: all 42 impairment comparison rows
have zero differences. Default cumulative charges remain EUR 130.4m baseline and
EUR 635.0m adverse (the precise values are in the sealed impairment report).

The same package with parameter reversion is `runs/20261030T2042Z-core-cca24825`. Baseline
differences are zero. Adverse cumulative charge changes by EUR 961,910.88 in 2027,
EUR 1,341,566.22 in 2028 and EUR 1,387,315.04 in 2029; the 2029 closing-provision change is
the same final amount. Grade/stage paths do not change because the alternative only affects
post-2029 risk parameters used to value remaining lifetime losses. Early-year S2 valuations
already include that future tail, explaining the impact before 2029.

The full-book replay `runs/20261030T2043Z-core-6e1b1370` reproduced all 57 output hashes of
the default package run. Integration tests also remove access to the original generated
input set and analysis file before replaying the sealed snapshot.

Final gate: **148 tests passed**, Ruff clean, all three import contracts kept, generated O1
specification current. The independent change reviewer returned **APPROVE** after verifying
the comparisons, replay, capital bridge and climate stock-to-flow reconciliation. The changes
reached `main` in tag `v1.2.0`.
