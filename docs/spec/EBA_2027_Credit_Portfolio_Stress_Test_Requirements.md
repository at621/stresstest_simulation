# Credit portfolio stress testing: EBA 2027 preparation requirements

**Document version:** 1.3  
**Reference date:** 17 October 2026  
**Deliverable:** Business, functional, data, methodology and acceptance requirements, including synthetic portfolio definitions.  
**Audience:** Credit risk, stress testing, finance, regulatory reporting, model validation and delivery teams.  
**Regulatory basis:** EBA 2027 EU-wide stress test **draft** package published on 11 June 2026.  
**Status:** Requirements for preparation and testing within the agreed EUR-only, amortised-cost scope, excluding climate risk. Final methodology, scenarios, benchmarks and reporting instructions must be incorporated before regulatory submission.

## 1. Purpose and interpretation

Specify a credit portfolio stress testing capability that can project exposure migration, credit impairments and credit risk exposure amounts under the EBA 2027 framework. Define fictional portfolios with sufficient variation to assess whether the capability behaves correctly under baseline and adverse macro-financial stresses.

This document contains requirements only. It does not deliver an executable model, implementation code, a populated regulatory submission or calibrated bank forecasts. All portfolio sizes, borrower examples, scenario values and acceptance tolerances introduced here are synthetic design choices.

The EBA's public exercise page identified the June 2026 package as draft when checked for this document. No final 2027 scenario calibration is assumed. The 2027 exercise must not be confused with the 2025 exercise, whose projection horizon also included the calendar year 2027. [S1–S3]

### 1.1 Requirement labels

| Label | Meaning |
|---|---|
| DRAFT | Requirement traced to the published 2027 draft. Reconfirm against the final package. |
| DESIGN | Proposed operating, data or quality requirement for this specification. It is not an additional EBA rule. |
| SYNTHETIC | Deliberately fictional input, portfolio target or test example. |
| OPEN | A dependency or interpretation that must be resolved before submission readiness. |

“Shall” denotes a mandatory requirement within this specification. A DESIGN requirement may be changed by the project owner with a documented impact assessment. A DRAFT requirement may be changed only through an updated authoritative source or a documented competent-authority instruction.

### 1.2 Working assumptions

| Item | Required preparation basis |
|---|---|
| Bank | Fictional consolidated EU banking group, domiciled in the Netherlands |
| Accounting | IFRS 9; all on-balance assets measured at amortised cost (AC); off-balance commitments and guarantees retain separate provision treatment |
| Starting point | 31 December 2026 |
| Projection dates | 31 December 2027, 2028 and 2029 |
| Scenarios | Separate baseline and adverse macro-financial runs |
| Climate risk | Out of scope; no transition or physical-risk modules |
| Currency | EUR only for exposures, borrower cash flows, collateral, recoveries, scenarios and outputs; no FX conversion or currency mismatch |
| Main measurement | Gross carrying amount for accounting exposure; distinct regulatory exposure measures |
| Balance sheet | Static, subject to the precise exercise rules |
| History | Support historical periods required by the final templates; the synthetic definitions here specify the 2026 starting point |

The 2026 year-end synthetic portfolio is hypothetical: its date is a future snapshot relative to this document's preparation date.

### 1.3 Agreed scope

The project owner has fixed the following scope. These are project decisions, not EBA rules:

- One currency, EUR, for exposures, borrower cash flows, collateral, recoveries, scenarios and outputs, including the Polish exposures. No FX inputs, conversion or mismatch.
- No climate risk (§9).
- All on-balance assets at amortised cost (AC). P06 is entirely AC, so total on-balance AC GCA is €11,000 million. Off-balance commitments and financial guarantees keep a separate provision treatment and are not AC assets.
- Securitisations, POCI and central-bank exposures are not in the main books and have no acceptance cases (SCP-03).

Any wider exercise obligations require separate coverage before a full regulatory-readiness claim. Requirement and acceptance-case identifiers are stable and never reused, so their numbering has gaps.

### 1.4 Synthetic modelling method

The synthetic configuration uses one method throughout, specified in §8:

- One Z-score per segment, country, year and scenario summarises the scenario (SCN-08).
- PD and stage migration come from one TTC rating matrix per reference segment, shifted each year by the Z-score (PD-09–PD-11). Stages follow from rating grades through a SICR rule against the origination grade (MIG-07, MIG-08).
- LGD is a TTC LGD shifted by the same Z-score (LGD-12). The S3 allowance uses that LGD with a per-exposure floor (ECL-11).
- EAD comes from each facility's contractual cash-flow schedule after scenario-dependent prepayment (EAD-10, EAD-11).
- After 2029 the Z-score reverts, and the matrices, LGD and prepayment follow it (ECL-10).

The design is described in `docs/stress-engine-code-flow.html`. All DESIGN and SYNTHETIC items are project requirements, not published EBA calibrations.

### 1.5 Open items

1. Parameter values, supplied by the project owner per segment: number of performing grades N, matrix correlation ρ, SICR multiple k, Z-score weights β with driver means μ and standard deviations σ, LGD sensitivity w, and prepayment rate CPR_TTC with its sensitivity v (SYN-PAR-06).
2. Oracle values for the numerical parts of AT-48, AT-51 and AT-52, to be approved by the project owner.
3. LGD-01 and LGD-04 describe collateral and recovery modelling that LGD-12 does not use. Confirm whether they stay for later production work.

## 2. Regulatory alignment and change control

The following is a concise traceability register. Detailed EBA provisions remain authoritative; the subsequent sections specify how the project shall make the requirements operational and testable.

| ID | DRAFT requirement | Source anchor | Required evidence |
|---|---|---|---|
| REG-01 | Use the 2026 starting point and 2027–2029 horizon. | S3, §1.3 | Run configuration and date checks |
| REG-02 | Apply static balance-sheet constraints. | S3, §§1.3.8, 2.3.6 | Exposure reconciliation |
| REG-03 | Separate accounting-loss and regulatory-REA perimeters. | S3, §2.2 | Scope bridge |
| REG-04 | Preserve stage flows and distinguish existing/new S3. | S3, §§2.3, 2.4.3 | Cohort reconciliation |
| REG-05 | Prevent S3 cures and exposure-level provision releases. | S3, ¶86, ¶141 | Constraint results |
| REG-06 | Apply perfect foresight and prescribed terminal treatment. | S3, ¶123–125 | Lifetime parameter evidence |
| REG-07 | Use scenario-specific impairments, without scenario blending. | S3, ¶128 | Separate result sets |
| REG-08 | Follow model/benchmark hierarchy and sovereign rules. | S3, ¶113–120, ¶145–146 | Parameter provenance |
| REG-09 | Apply REA floors at their prescribed aggregation. | S3, ¶153, ¶178 | Floor bridge |
| REG-13 | Retain prescribed sector and country breakdowns. | S3, §§2.3.8–2.3.9 | Mapping evidence |
| REG-14 | Treat off-balance-sheet exposures separately. | S3, §§2.3.4, 2.6 | Commitment/provision bridge |

### 2.1 Source precedence and updates

**GOV-01 — DESIGN.** Maintain a dated source register containing document title, version, publication date, source URL, relevant paragraph, local approval date and affected requirement IDs.

**GOV-02 — DESIGN.** Resolve changes using the final EBA package, applicable exercise FAQs and documented competent-authority instructions. Do not silently resolve conflicting instructions through a model assumption.

**GOV-03 — DESIGN.** Every source change shall produce an impact assessment covering data, perimeter, calculations, assumptions, reporting and acceptance cases. Preserve the previous specification and results for comparison.

**GOV-04 — OPEN.** Before submission, confirm final dates, scenarios, benchmarks, template versions, reporting taxonomy, materiality thresholds, proportionality eligibility, capital treatment and QA requirements. Synthetic values shall never fill an unavailable official parameter in a submission run.

### 2.2 Known draft interpretation issues

1. **NACE version:** Core credit sector reporting refers to NACE Rev. 2.1 in S3 ¶95. Retain source classification and mapping version separately. Resolve each output's target taxonomy against the final package. The synthetic portfolios below use **Rev. 2** labels; they are not ready-made core reporting codes.
2. **Proposed reporting dependencies:** References to forthcoming supervisory reporting templates shall be versioned. A proposed reporting change shall not be treated as an already applicable final reporting obligation.
3. **Template coordinates:** Template families can be specified now. Exact cell coordinates, validation rules and export formats shall be bound only to the approved workbook and guidance version.

## 3. Business scope and exclusions

### 3.1 Included capabilities

**SCP-01 — DESIGN.** Support residential mortgages, consumer lending, SME lending, commercial real estate, corporate lending, sovereign exposures and exposures to credit institutions.

**SCP-02 — DRAFT/DESIGN.** Distinguish the following perimeters throughout the workflow:

| Perimeter | Treatment |
|---|---|
| Amortised-cost assets | All on-balance assets in the six main portfolios; credit impairment projection and relevant credit REA |
| Loan commitments and financial guarantees | Separate off-balance-sheet exposure and provision projection |
| FVOCI/FVPL assets | Excluded from this capability; reject any such record presented as in-scope |
| Counterparty credit risk | External REA interface only: obtain required EUR exposure measures from the CCR workstream; derivatives are outside the AC accounting-asset population |
| Securitisations | Documented exclusion; retain pool information and approach-specific constraints where applicable |
| POCI | Separate classification and provision treatment; do not force into ordinary S1/S2/S3 migration |
| Climate risk | Excluded from this capability; no climate input, calculation, reporting or validation deliverable |

Source: S3 §§2.2, 2.3.6 and 2.7, subject to the project scope decisions in §1.3.

**SCP-03 — DESIGN.** The six main synthetic portfolios shall test ordinary lending and debt securities, all at AC. Securitisations, POCI and central-bank balances are not in the main books and have no acceptance cases. Derivatives/CCR remain outside the main accounting portfolio; obtain relevant EUR REA inputs from the separate CCR workstream. None of these exposures or interfaces forms part of the main €11 billion portfolio.

**SCP-06 — DESIGN.** Validate EUR as the sole currency and AC as the sole measurement category for on-balance assets. Reject missing or inconsistent currency and accounting classifications before projection. Off-balance records shall use a not-applicable asset measurement category and retain their separate provision classification. Country of domicile shall not determine currency or accounting category.

### 3.2 Interfaces rather than complete bank models

**SCP-04 — DESIGN.** Provide credit impairments, credit REA, regulatory expected loss and deduction inputs to the bank's capital aggregation process. Obtain net interest income, fees, market risk, operational risk, taxes, distributions and other capital components from their respective owners.

**SCP-05 — DESIGN.** Label any capital ratio produced with incomplete non-credit inputs as a **credit-only sensitivity**, not the bank's EBA stress-test capital ratio. Do not invent an EBA pass/fail threshold. Internal limits shall be explicitly named as internal.

## 4. Required data and definitions

### 4.1 General data rules

**DAT-01 — DESIGN.** Retain facility, obligor, connected-client group and collateral identities separately. A borrower with several facilities shall remain identifiable across portfolios and scenarios.

**DAT-02 — DESIGN.** Store all monetary amounts in EUR, dates unambiguously, ratios as decimal fractions, and units with every scenario variable. Retain a currency code fixed to EUR; no conversion-rate field or FX calculation is required. Distinguish a missing value, a true zero, a non-applicable value and an estimated value.

**DAT-03 — DESIGN.** Preserve raw data, approved adjustments and the final starting point separately. An adjustment shall have an owner, reason, amount, affected exposures and approval reference.

**DAT-04 — DESIGN.** Treat IFRS stage, regulatory default, non-performing status, forbearance and arrears as distinct attributes. They shall be reconciled, not equated by assumption. Explain legitimate differences and block unexplained conflicts.

### 4.2 Minimum data dictionary

| Group | Required attributes | Definition and quality requirement |
|---|---|---|
| Identity | Facility ID, obligor ID, connected-group ID, entity ID | Stable, non-recycled identifiers; referential integrity |
| Dates | Snapshot, origination, maturity, default entry, stage entry | Snapshot is consistent across the approved starting point |
| Counterparty | Country of domicile, counterparty sector, SME flag | Country of borrower is separate from collateral country |
| Industry | NACE code, NACE version, principal activity | Preserve original code and mapped output code |
| Product | Mortgage, consumer loan, term loan, revolver, guarantee, debt security | Each product has a defined scope and treatment |
| Accounting | AC for on-balance assets; not applicable for off-balance asset measurement; IFRS stage, POCI flag | Validate the permitted classification; no stage migration applied to POCI as though it were ordinary S3 |
| Credit status | Regulatory default, NPE, DPD, forbearance, watchlist | Source definition and observation date required |
| Amounts | GCA, accrued interest, undrawn amount, contractual limit | Reconcile components; do not equate limit, GCA and EAD |
| Currency | Instrument, borrower cash-flow, collateral and recovery currency | EUR for every monetary item; reject non-EUR or missing currency; no mismatch or FX conversion |
| Accounting provisions | On-balance allowance, off-balance provision, overlays | Separate opening stock from subsequent expense |
| EAD | Accounting and regulatory exposure measures, CCF and CCF source | Separate nominal commitment from converted exposure |
| Credit risk | PiT PD, regulatory PD, TTC LGD, LGD, regulatory LGD, lifetime loss rate | Identify parameter basis, stage, horizon and model version |
| Rating | Current and origination grade on the master scale (PD-09), external credit assessment where relevant | Record rating-to-PD mapping and source; grade and stage reconcile under MIG-07 |
| SICR | Origination risk, current risk, lifetime comparison, qualitative triggers | Origination 12-month PD alone is not a complete SICR measure |
| Contract | Effective interest rate, fixed/floating rate, residual maturity, repayment profile (bullet, annuity or linear) | Support the contractual schedule (EAD-10), discounting, replacement and refinancing tests |
| Collateral | ID, type, value, valuation date, country, lien, allocation | Avoid assigning full shared collateral to every linked facility; not used by LGD-12 |
| Recovery | Costs, timing, seniority, guarantees, expected cash flows | Separate gross collateral value from recoverable proceeds; not used by LGD-12 |
| Borrower finance | Income/debt service or revenue, operating costs, debt, DSCR | Period, units, completeness and estimation status required |
| Capital | Regulatory approach/class, eligibility, CRM, maturity, regulatory EL | Internal product label is not a regulatory asset class |
| Lineage | Source system, extract date, model, scenario, adjustment and approval IDs | Every reported amount must be reconstructable |

### 4.3 Additional production information

**DAT-05 — DESIGN.** Retain default and recovery history, rating transitions, stage migration, write-offs, cures, collateral values, origination information and macroeconomic history adequate for model estimation and independent validation. The synthetic portfolios do not replace this evidence.

**DAT-06 — DESIGN.** Historical reporting inputs shall cover every period required by the approved in-scope templates. The 2026 synthetic design below shall not be presented as supplying historical periods that it does not contain.

**DAT-07 — DESIGN.** Reconcile the starting point to accounting and regulatory reporting, documenting differences in perimeter, measurement, netting, accrued interest, provisions, CCF and consolidation. Validate EUR throughout; currency-conversion differences shall be zero.

## 5. Synthetic portfolio specifications

All values in this section are **SYNTHETIC**. They are controlled test targets, not estimates of European banks' actual portfolios. The definitions constitute six fictional books within one bank, not six separate banks.

### 5.1 Portfolio sizes and primary uses

Amounts are in **EUR millions**. GCA is the opening on-balance carrying amount before allowances. The illustrative CCF applies only to the undrawn test commitments.

| ID | Portfolio | Facilities | GCA | Undrawn | Test CCF | Illustrative GCA + converted commitments | Primary test purpose |
|---|---|---:|---:|---:|---:|---:|---|
| P01 | Residential mortgages | 4,000 | 1,200 | 0 | — | 1,200 | LTV, household affordability and collateral price stress |
| P02 | Consumer credit | 3,000 | 60 | 0 | — | 60 | High PD/LGD, unemployment, stage migration |
| P03 | SME lending | 1,500 | 1,500 | 600 | 50% | 1,800 | Sector stress, guarantees, utilisation and shared borrowers |
| P04 | Commercial real estate | 500 | 2,000 | 0 | — | 2,000 | DSCR, collateral falls, refinancing, concentration |
| P05 | Corporate lending | 800 | 4,000 | 1,400 | 50% | 4,700 | Sector GVA, group concentration and debt-service sensitivity |
| P06 | Sovereigns and credit institutions | 200 | 2,240 | 0 | — | 2,240 | Benchmark routing, accounting perimeter and low-default modelling |
| **Total** | | **10,000** | **11,000** | **2,000** | | **12,000** | |

The €12 billion column is a synthetic exposure arithmetic check. It is not an assertion that accounting EAD and COREP exposure value are identical. The 50% CCF is a test assumption, not a prescribed universal EBA or CRR conversion factor.

### 5.2 Opening stage composition

The following are exact target facility counts. For the main synthetic design, the corresponding GCA shares shall equal the count shares within each portfolio. Different individual facility sizes are permitted provided both totals reconcile.

| Portfolio | Stage 1 count | Stage 2 count | Stage 3 count | S1 GCA | S2 GCA | S3 GCA |
|---|---:|---:|---:|---:|---:|---:|
| P01 | 3,520 | 400 | 80 | 1,056.0 | 120.0 | 24.0 |
| P02 | 2,430 | 450 | 120 | 48.6 | 9.0 | 2.4 |
| P03 | 1,155 | 270 | 75 | 1,155.0 | 270.0 | 75.0 |
| P04 | 370 | 100 | 30 | 1,480.0 | 400.0 | 120.0 |
| P05 | 680 | 96 | 24 | 3,400.0 | 480.0 | 120.0 |
| P06 | 190 | 8 | 2 | 2,128.0 | 89.6 | 22.4 |
| **Total** | **8,345** | **1,324** | **331** | **9,267.6** | **1,368.6** | **363.8** |

Opening allowances shall be calculated consistently with each facility's stage and risk assumptions and then frozen as starting data. They shall not be selected after observing stress losses to obtain a desired outcome.

### 5.3 Geography, currency, accounting and approach

| Dimension | Synthetic target |
|---|---|
| Borrower countries | NL 30%, DE 20%, FR 15%, ES 10%, IT 10%, PL 15% of GCA in each portfolio |
| Currency | EUR for all exposures, commitments, borrower cash flows, collateral, recoveries and outputs |
| FX treatment | No foreign-currency balances, exchange-rate inputs, conversion calculations or currency mismatches |
| Accounting | P01–P06 entirely AC for on-balance assets; off-balance commitments treated separately |
| P06 counterparties | 60% general governments and 40% credit institutions by GCA |
| P06 accounting allocation | All €2,240 million at AC |
| IRB share | P01 60%, P02 40%, P03 50%, P04 70%, P05 70%, P06 0%, measured by GCA |
| Remaining approach | STA; retain a separate standardised comparator for IRB exposures |
| POCI | None in the main books |

Country allocation and regulatory approach shall be controlled independently. A country or product label shall not automatically determine the regulatory risk weight.

The accounting perimeter shall reconcile to **€11,000 million AC**, with no FVOCI or FVPL balances. Core credit-impairment calculations shall use the eligible AC population and the separately measured off-balance population. The total opening IRB GCA target is €5,694 million and the STA target is €5,306 million, before applying regulatory exposure-value definitions.

### 5.4 Risk profiles and distributions

Ranges below are proposed test ranges, not regulatory limits. PiT PD ranges apply to performing exposures; defaulted status shall be represented separately. Stage 2 generally uses the riskier portion of the relevant distribution, with explicit overlap permitted.

| Portfolio | Performing 12-month PD | ECL LGD | Residual maturity | Additional attributes |
|---|---|---|---|---|
| P01 | 0.2%–5% | 5%–40% | 5–30 years | LTV 35%–110%; fixed/floating mix; household debt service |
| P02 | 1%–20% | 50%–95% | 1–7 years | Unsecured; income bands; 0–29, 30–89 and 90+ DPD cases |
| P03 | 0.5%–15% | 15%–70% | 1–8 years | Secured/unsecured; committed lines; multiple facilities per borrower |
| P04 | 0.5%–12% | 10%–60% | 2–10 years | LTV 40%–105%; DSCR 0.7–2.5; balloon and refinancing exposures |
| P05 | 0.1%–10% | 15%–65% | 1–10 years | Ratings, connected groups, operating costs and debt-service capacity |
| P06 | 0.01%–3% | 10%–60% | 1–15 years | Sovereign/bank flags; benchmark eligibility; AC impairment and credit-REA coverage |

**SYN-01.** Include common borrower-level drivers across facilities: country, sector, financial strength and regulatory default where obligor-level application is appropriate. Do not independently assign contradictory financial profiles to the same borrower.

**SYN-02.** Make risk attributes economically coherent. Examples: weaker DSCR increases stress sensitivity; higher LTV reduces the recovery cushion; longer recovery delays reduce discounted recoveries; floating-rate debt raises vulnerability when interest rates increase.

**SYN-03.** Permit exceptions with explicit reasons. A borrower can have low current arrears and high credit risk; a collateralised loan can have high LGD because of senior claims or long recovery delays.

**SYN-04.** Include concentration deliberately. Target the ten largest connected groups at 20% of P05 GCA and 25% of P04 GCA. These targets shall be achieved without duplicate exposures or double-counted guarantees.

### 5.5 Sector and collateral attributes

| Portfolio | Required design |
|---|---|
| P01 | Residential property collateral; retain LTV, valuation date and fixed/floating rate characteristics |
| P02 | Unsecured consumer lending; retain borrower income and employment sensitivity |
| P03 | NACE Rev. 2 sections A 10%, C 25%, D 10%, F 15%, G 20%, H 10%, M 10% |
| P04 | NACE Rev. 2 L, real estate; identify office, retail, industrial and residential rental collateral separately |
| P05 | NACE Rev. 2 A 5%, C 30%, D 20%, F 10%, G 10%, H 15%, M 10% |
| P06 | General-government and credit-institution classification; all debt securities at AC |

The P03 and P05 sector shares are measured by GCA and shall each total 100%. Core country and sector stress remains in scope.

## 6. Scenario requirements

### 6.1 Official scenario management

**SCN-01 — DESIGN.** Each scenario shall have an immutable identifier, source, release date, revision, geography, period, units and completeness status.

**SCN-02 — DESIGN.** Record whether each value is a level, annual growth rate, cumulative change, percentage-point change, basis-point shock or index. A scenario cannot be approved if units are ambiguous.

**SCN-03 — DESIGN.** Support country and sector GDP/GVA, unemployment, property prices, interest rates and inflation. Monetary scenario inputs shall use EUR; exchange-rate paths and climate variables are outside scope. Specify how each model uses the available variables, including lags and any interpolation.

**SCN-04 — DESIGN.** Do not substitute synthetic scenarios for unavailable official data. Preparation runs shall carry a visible synthetic status. Scenario revisions require impact analysis and rerunning all affected results.

### 6.2 Illustrative macroeconomic paths

The following common paths are deliberately simple test inputs for all six countries. Country-specific official shocks shall replace them for regulatory work. Starting unemployment is 6%, the reference rate is 2.5%, and property indices are 100.

| Variable and unit | Baseline 2027 | 2028 | 2029 | Adverse 2027 | 2028 | 2029 |
|---|---:|---:|---:|---:|---:|---:|
| Real GDP annual growth, % | 1.5 | 1.7 | 1.8 | -3.0 | -2.0 | 0.5 |
| Unemployment level, % | 6.0 | 5.8 | 5.7 | 7.5 | 9.0 | 9.2 |
| Residential property annual price change, % | 2.0 | 2.5 | 3.0 | -12.0 | -10.0 | -3.0 |
| CRE annual price change, % | 2.0 | 2.5 | 3.0 | -15.0 | -12.0 | -5.0 |
| Reference interest rate level, % | 2.5 | 2.3 | 2.2 | 4.0 | 4.5 | 3.5 |

**SCN-05 — SYNTHETIC.** Property price changes shall compound. The adverse residential index shall be 88.00 in 2027, 79.20 in 2028 and 76.824 in 2029. The corresponding CRE indices shall be 85.00, 74.80 and 71.06. Adding annual percentage changes instead of compounding shall fail acceptance.

**SCN-08 — DESIGN — Z-score.** Combine the standardised scenario drivers of each segment into one Z-score per segment, country, year and scenario: `Z = sum_i(β_i × (x_i - μ_i) / σ_i)`. Drivers are those relevant to the segment, such as GDP growth, unemployment and property price change. A positive Z means a better economy than average. The same Z drives the rating matrix (PD-10), LGD (LGD-12) and prepayment (EAD-11); no second stress is applied to the same parameter. β, μ and σ are SYNTHETIC values in the parameter set (SYN-PAR-06). A missing scenario value or Z coefficient blocks the run. After 2029, Z follows ECL-10.

## 7. Exposure projection and stage migration

### 7.1 Static-balance requirements

**EXP-01 — DRAFT/DESIGN.** Preserve the exercise exposure stock through migrations and prescribed replacement. Maturity or amortisation shall not create an unapproved decline in the portfolio. Replacement shall preserve the required credit characteristics, stage and residual maturity. [S3 ¶86–89]

**EXP-02 — DRAFT.** Do not replace defaulted exposures with performing assets, cure S3 balances, remove them through projected NPL sales, or use write-offs to shrink projected credit exposure. Accounting recovery assumptions within LGD are distinct from removing the exposure stock. [S3 ¶86 and footnote 14]

**EXP-03 — DESIGN.** Retain original product, country and reporting-class labels where required by the exercise. A changed economic risk weight shall not automatically move exposure to a different reporting bucket.

**EXP-05 — DESIGN — like-for-like replacement.** A facility that matures before end-2029 is replaced like for like: same segment, same current and origination grade (and therefore the same stage), same country, and the starting residual maturity. The replacement restarts its contractual schedule (EAD-10). Total GCA and nominal undrawn amounts stay at their end-2026 levels; maturity and prepayment do not run the stock off (EXP-01, EAD-05).

### 7.2 Stage transition requirements

**MIG-01 — DESIGN.** For every period and relevant risk segment, define transitions from S1 to S1/S2/S3, from S2 to S1/S2/S3, and S3 remaining S3. Probability rows shall total one and contain no negative value.

**MIG-02 — DESIGN.** Distinguish an end-year stage stock from a migration flow during the year. Opening stage balances multiplied by transition probabilities determine flows. Closing balances shall reconcile to all incoming flows.

**MIG-03 — DESIGN.** Maintain the cohort entering S3 in each projection year and the original end-2026 S3 cohort. Retain the stage from which each new S3 cohort originated.

**MIG-04 — DESIGN.** Demonstrate how PDs and rating migration are consistent with stage-default flows. Do not calculate default volumes from both a PD model and an independent transition matrix and then add them.

**MIG-05 — DESIGN.** Specify SICR using the bank's approved lifetime-risk assessment and qualitative triggers. Any synthetic threshold, such as a multiple of origination PD, shall be labelled a test convention rather than an EBA threshold.

**MIG-06 — DESIGN.** Expected exposure migration may create fractional exposure amounts. This is acceptable for deterministic stress testing. A stochastic borrower simulation is optional and shall not replace the required deterministic result without approval.

**MIG-07 — DESIGN — stage from grade.** Each performing facility carries a current grade and an origination grade g0 on the master scale (PD-09). A grade slice is S3 when its grade is D, S2 when its lifetime PD is at least k times the lifetime PD at g0, and S1 otherwise. Both lifetime PDs come from the segment's TTC matrix over the same remaining horizon (PD-06), so the SICR line is fixed per facility and only rating moves change stage. A slice returns to S1 when its grade improves back over the line; D never cures. k is set per segment in the parameter set (SYN-PAR-06) and is a test convention under MIG-05, not an EBA threshold. Qualitative triggers such as 30+ DPD, watchlist and forbearance are not used in the synthetic books.

**MIG-08 — DESIGN — projection by grade slice.** Project one row per facility and slice: one slice per performing grade, plus the original S3 slice and each new S3 cohort. Each year, closing = opening × M(y) (PD-10). Exposure reaching D becomes a new S3 cohort that keeps its entry year and origin stage (MIG-03). S3 slices bypass the matrix: no cure, sale or write-off removal (EXP-02). Stage flows are sums of matrix cells grouped by MIG-07, so S1↔S2 shares are outputs rather than inputs, and default volumes come from one matrix only (MIG-04). The reported stage migration is the exposure-weighted sum over slices.

## 8. PD, LGD, EAD and impairment requirements

### 8.1 Model and benchmark selection

**MOD-01 — DESIGN.** Specify model scope, target parameter, estimation sample, macro drivers, lag structure, calibration, out-of-time validation, limitations and fallback method for every material portfolio.

**MOD-02 — DESIGN.** Keep PiT accounting parameters separate from regulatory PD/LGD and expected-loss parameters. Do not use a single PD/LGD pair for both purposes without a documented, approved justification.

**MOD-03 — DRAFT/DESIGN.** Implement the draft hierarchy for internal models and ECB benchmarks. Track benchmark coverage and eligibility by required aggregation and parameter family. A benchmark choice shall not change opportunistically between scenarios or years. [S3 ¶113–120]

In particular, the draft contains a 10% model-coverage test at pivot asset-class level, separately addressing the completeness of PD/TR and LR/LGD estimates. The selection design shall reproduce ¶117, including its whole-pivot benchmark fallback where coverage is insufficient. Do not replace that test with a 10% threshold on the bank's total book.

**MOD-04 — DRAFT/DESIGN.** Route general-government AC exposures to prescribed ECB parameters where available. Central-bank exposures require their specified zero-loss treatment. Record fallback justification for countries lacking the prescribed sovereign parameters. [S3 ¶145–146]

**MOD-05 — DESIGN.** Separate model output, benchmark substitution, expert adjustment and methodological constraint. Report each contribution to the final parameter or loss. Synthetic PD ranges are neither regulatory floors nor production model calibration.

**MOD-06 — DESIGN.** Each parameter record shall have a unique key comprising run ID, facility ID, scenario, valuation date, stage/default cohort, future default bucket and parameter basis (`accounting` or `regulatory`). Retain source/model version, benchmark version, input snapshot, raw value, adjustment, constraint and final value. A missing key, duplicate key or missing required parameter shall block the affected calculation. Regulatory fields not required for STA shall be marked not applicable, not populated with invented IRB values.

### 8.2 Probability of default (PD)

**PD-01 — DESIGN — inputs.** For each performing facility, supply obligor ID, PD segment, opening 12-month PiT PD, observation date, model default-event definition, IFRS stage, rating, origination risk information, remaining life, borrower country/sector and model driver values. Record default-event differences between accounting, regulatory default and S3 explicitly. Corporate facilities of the same obligor shall share an obligor PD unless a documented facility-level model scope justifies a difference.

**PD-02 — DESIGN — outputs.** For each baseline/adverse valuation date, produce a conditional PD curve for every remaining default interval, survival at the start of each interval, marginal PD and cumulative PD. Retain the 12-month PD and lifetime PD as separate outputs. The run must supply parameters beyond 2029 where needed for end-2029 provisions or remaining lifetime; a missing terminal curve is a blocking error. Use the exercise timing and reversion rules in ECL-03–ECL-06.

**PD-03 — DESIGN — probability arithmetic.** Let `q[k]` be the probability of default in interval `k` conditional on survival to its start, and `S[0] = 1`. Calculate:

- `m[k] = S[k-1] × q[k]` (marginal, unconditional default probability).
- `S[k] = S[k-1] × (1 - q[k])`.
- `F[k] = 1 - S[k] = sum(m[1..k])` (cumulative default probability).

Require `0 ≤ q[k], m[k], S[k], F[k] ≤ 1`, non-decreasing `F`, non-increasing `S`, and `F[k] + S[k] = 1` within 1e-10. Do not sum conditional PDs to obtain lifetime PD. A zero PD requires an explicit supported zero-risk input or rule; it shall not be a missing-value substitute. Already-defaulted exposures bypass performing PD estimation; do not multiply S3 recovery shortfalls by a performing PD.

**PD-04 — DESIGN — scenario transformation.** Each approved production model shall specify the transformation, coefficient values, driver units, lags, interactions and calibration date that map the scenario into `q[k]`. Store separate GDP/GVA, unemployment, interest-rate and borrower-risk contributions where used. Drivers and omissions shall be justified by portfolio: household income/employment for P01/P02, sector activity and debt service for P03/P05, DSCR/refinancing for P04, and separate sovereign/bank routing for P06. A statement that PD 'increases under stress' is insufficient. The TTC rating matrices and Z-score shift in PD-09–PD-11 provide the mandatory preparation test alternative; they are not an estimated production model.

**PD-05 — DESIGN — migration consistency.** For the aligned-default synthetic test cases, set each performing origin-stage row's transition to S3 equal to that origin stage's one-year conditional PD. New defaulted GCA is the sum of opening performing GCA times the respective PD; closing S3 equals opening S3 plus those new flows. Allocate the remaining probability to S1/S2 under the separately approved migration rule. For production populations with different accounting/regulatory event definitions or timing, provide an explicit event bridge instead of forcing equality. Do not apply PD again to an exposure amount that is already a probability-weighted default flow.

**PD-06 — DESIGN — horizon and SICR.** Identify the date and horizon of each PD curve. Compare origination and current lifetime risk over a consistent remaining horizon for SICR; retain qualitative triggers separately. For a synthetic fractional interval of `d` years, use `q[d] = 1 - (1 - q[annual])^d` under a constant-hazard convention. A production model using another within-year convention shall record and validate it. Do not use the original full-life PD as though it were the current remaining-life PD.

**PD-07 — DESIGN — regulatory separation.** Store regulatory PD, parameter regime, regulatory class, applicable floor and model version separately from accounting PiT PD. Apply regulatory constraints only in the relevant calculation. Prescribed sovereign/central-bank routes and benchmark substitution under MOD-03/MOD-04 take precedence over the synthetic PD formula in a regulatory-mode run.

**PD-08 — DESIGN — validation.** Check every mandatory performing curve for completeness, bounds and the probability identities in PD-03. Backtest default frequency and rating discrimination on appropriate historical cohorts; document sample period, observation weighting, defaults, calibration error and limitations for low-default populations. Model Validation shall approve numerical performance thresholds before production acceptance; synthetic arithmetic success alone is insufficient.

**PD-09 — DESIGN/SYNTHETIC — TTC rating matrices.** Each §8.7 reference segment has one one-year through-the-cycle transition matrix on a shared master scale of N performing grades plus default D. Every row sums to one within 1e-10, no cell is negative, D is absorbing and the probability of default rises with the grade. The matrices are SYNTHETIC, built once and calibrated under SYN-PAR-05. A missing or invalid matrix blocks the run.

**PD-10 — DESIGN — scenario shift.** For year y, shift each row of the segment's TTC matrix with that year's Z (SCN-08). With `C(i,j)` the probability of ending in grade j or worse when starting in grade i, and `C(i,j) = 0` beyond D, calculate `C_PiT(i,j) = Φ((Φ⁻¹(C_TTC(i,j)) - sqrt(ρ) × Z) / sqrt(1 - ρ))` and `M(i,j) = C_PiT(i,j) - C_PiT(i,j+1)`, with ρ per segment (SYN-PAR-06). Every shifted row shall sum to one within 1e-10. A worse economy (Z < 0) moves probability toward worse grades and default. The D column of M(y) is each grade's PD for year y. In this form Z = 0 gives the median year, slightly below the TTC average, not the TTC matrix itself.

**PD-11 — DESIGN — PD curve from the matrices.** For a slice in grade g valued at the end of year y, calculate `F[k] = (e_g × M(y+1) × … × M(y+k))[D]`, `m[k] = F[k] - F[k-1]` and `S[k] = 1 - F[k]`, where `e_g` is the unit row vector for grade g and each M is the scenario's own matrix for that year (perfect foresight, ECL-06). The curve allows for rating migration on the way to default. Conditional PDs follow as `q[k] = m[k] / S[k-1]`, and the PD-03 identities shall be checked on every curve. Buckets after 2029 use the matrices from ECL-10.

### 8.3 Recovery and LGD

**LGD-01 — DESIGN.** Project recoveries using collateral values, senior claims, recovery costs, timing, guarantees and borrower cash flows. Discount consistently with the accounting model.

**LGD-04 — DESIGN.** Analyse longer recovery periods and higher realisation costs as independent sensitivities. A collateral price fall shall not automatically equal the same percentage increase in LGD.

**LGD-08 — DESIGN — bounds and exception handling.** The synthetic reference profile requires final LGD between 0% and 100%. Preserve raw values and identify any cap; unexplained out-of-range values fail validation. Production recovery costs can require a separately approved treatment outside this simplified profile: never silently truncate a legitimate raw estimate or apply a synthetic cap as a regulatory rule. Missing collateral or recovery data shall trigger an approved proxy with an explicit flag or block the affected model; missing is not zero collateral by default.

**LGD-10 — DESIGN — production and synthetic methods.** Each segment shall declare either a cash-flow recovery method or an approved statistical/benchmark LGD method. A statistical method shall provide its equation, driver coefficients, any collateral/recovery linkage and validation evidence. Every synthetic segment uses the statistical method in LGD-12, with its coefficients in the parameter set (SYN-PAR-06).

**LGD-11 — DESIGN — regulatory LGD and challenge.** Keep accounting LGD distinct from regulatory downturn LGD, in-default estimates, floors and adjustments. Test higher costs, delayed recoveries, lower collateral values and reduced guarantor capacity one at a time. For fixed EAD and otherwise unchanged non-negative recovery cash flows, less or later recovery shall not reduce LGD when the discount rate is non-negative. Backtest recovery amount and timing separately, including incomplete workouts and selection bias.

**LGD-12 — DESIGN/SYNTHETIC — LGD from TTC and the Z-score.** Each exposure carries a through-the-cycle LGD, `LGD_TTC`. For default bucket k, calculate `LGD[k] = Φ(Φ⁻¹(LGD_TTC) - w × Z[k])`, with the Z of the default year (SCN-08) and `w ≥ 0` per segment (SYN-PAR-06). Z = 0 returns LGD_TTC, a worse economy (Z < 0) raises LGD, and the result stays between 0 and 1 without a cap; an LGD_TTC of exactly 0 or 1 passes through unchanged. No collateral, guarantee or recovery data is used, so LGD carries no recovery discounting and ECL discounts once, from default date to valuation date (ECL-08). The same LGD applies to S1 and S2 buckets, new S3 cohorts and the original S3 allowance (ECL-11). For zero EAD, monetary loss is zero and LGD is not applicable (AT-33). A missing LGD_TTC blocks the affected calculation.

### 8.4 Exposure at default (EAD)

**EAD-01 — DESIGN — inputs.** Require drawn principal, accrued interest and whether it is already in GCA, nominal undrawn commitment, contractual limit, product type, maturity, repayment schedule, cancellation rights, expected drawdown profile and accounting CCF. Regulatory EAD additionally requires regulatory approach/class, CCF regime/source, eligible netting/CRM and adjustment fields. Store monetary values in EUR and CCFs as decimal fractions. Do not calculate undrawn as `limit - GCA` where accrued interest or product definitions make that identity invalid.

**EAD-02 — DESIGN — accounting calculation.** At future default bucket `k`, define `D[k]` as the drawn exposure measure including eligible accrued interest exactly once, `U[k]` as the undrawn nominal commitment and `c[k]` as the conditional expected additional-drawdown fraction. For the ordinary loan/commitment profile, calculate `EAD_drawn[k] = D[k]`, `EAD_undrawn[k] = U[k] × c[k]`, and `EAD_total[k] = D[k] + U[k] × c[k]`. Store all three. These are conditional-on-default exposures: do not multiply them by PD or survival within the EAD calculation. Collateral and guarantees received affect the designated LGD/CRM treatment, not a second deduction from gross accounting EAD.

**EAD-03 — DESIGN — product treatment.** Fully drawn term loans and debt securities have `U = 0`; undrawn EAD is zero and CCF is not applicable. Revolvers and commitments use the drawn/undrawn split in EAD-02. Fully undrawn facilities have `D = 0` but can have positive EAD and provision. Issued financial guarantees require a separate expected payment/reimbursement model bounded by the covered obligation and contract: do not reuse a loan drawdown CCF without a documented basis.

**EAD-04 — DESIGN — CCF constraints.** In the synthetic ordinary-commitment profile, require `0 ≤ c[k] ≤ 1`, `D[k] ≥ 0` and `U[k] ≥ 0`, hence `D[k] ≤ EAD_total[k] ≤ D[k] + U[k]`. Missing CCF for positive undrawn exposure blocks the run; zero is accepted only as an explicit approved value. More complex products or production CCF estimates outside this profile require an approved separate method, not silent clipping. Apply the accounting CCF once and the regulatory CCF once in their respective calculations, never sequentially to the same exposure.

**EAD-05 — DESIGN — static exposure reconciliation.** Separate the contractual/default-date EAD profile used in loss measurement from the exercise balance-sheet stock. A contractual repayment or maturity shall not reduce projected exercise GCA without the prescribed replacement bridge. For the §8.7 synthetic core configuration, freeze each book's aggregate GCA and nominal undrawn amounts at §5.1 targets through 2027–2029, retain stage/default cohorts and use 50% accounting CCF for P03/P05 commitments. This gives an illustrative conditional exposure total of €12,000 million each year. This is a controlled test profile, not a statement that regulatory EAD must be constant or that a future commitment draw is additional booked GCA.

**EAD-06 — DESIGN — utilisation and default.** A separate utilisation sensitivity may change accounting CCF without changing nominal commitment, and shall report the resulting conditional EAD change explicitly. It must not be silently included in an exercise run where the methodology fixes conversion assumptions or prohibits the movement. Where an actual permitted drawdown transfer is modelled, increase drawn by the transferred amount and decrease undrawn by the same amount before applying CCF to the remainder. Once exposure is recorded as a defaulted drawn balance, do not add the same pre-default commitment conversion again; any surviving off-balance obligation needs its own record.

**EAD-07 — DESIGN — regulatory bridge.** Calculate `EAD_reg` through an approach-specific rule and retain the bridge from gross accounting exposure through regulatory adjustments, netting, CCF and CRM. Record rule/source and before/after amounts for each step. A difference from accounting EAD is permissible only with that reconciliation. Do not impose the synthetic accounting CCF on a regulatory class or infer regulatory EAD from GCA alone.

**EAD-08 — DESIGN — life and provision allocation.** Generate default-date EAD until the approved remaining exposure horizon, including documented behavioural life for revolving facilities where relevant. Distinguish a facility's contractual profile from prescribed synthetic replacement. Allocate the drawn-component ECL to on-balance allowance and the undrawn-component ECL to off-balance provision using the applicable presentation rule and ACC-03; if presentation differs, provide the reconciliation. Never expense combined ECL once as an allowance and again as a commitment provision.

**EAD-09 — DESIGN — validation.** Reconcile opening GCA and undrawn totals by portfolio to §5.1; test accrued interest, fully undrawn facilities, exhausted limits, expired commitments and defaulted facilities. Preserve separately any approved amount above a contractual limit. An unexplained limit breach, negative amount, duplicate commitment, missing applicable CCF or unreconciled regulatory bridge is a blocking defect.

**EAD-10 — DESIGN — contractual cash-flow schedule.** For each performing facility, build a yearly contractual schedule to maturity from the drawn balance D, with accrued interest counted once (AT-37), the interest rate r and the residual maturity M: opening balance, interest, principal and closing balance per year. The repayment profile sets the principal: bullet repays D at M; annuity pays a constant `A = D × r / (1 - (1 + r)^-M)`, with `A = D / M` when r = 0; linear repays `D / M` each year. Where M is not a whole number of years, the final period is a stub of fraction d of a year (PD-06). Floating-rate facilities keep their current rate. From the schedule, derive the contractual balance `B[k]` at each default date, before that date's payment, and the discount factor `DF[k] = (1 + r)^-t(k)` from default date k back to the valuation date. The schedule is contractual only and the same in every scenario: prepayment, default and drawdown are applied in EAD-11. A missing or non-positive maturity on a performing facility, a missing rate, or a rate of -100% or lower blocks the facility.

**EAD-11 — DESIGN — prepayment and EAD per default date.** For year t, calculate the prepayment rate `CPR[t] = Φ(Φ⁻¹(CPR_TTC) + v × Z[t])`, with CPR_TTC and `v ≥ 0` per segment (SYN-PAR-06); v > 0 lowers prepayment when the economy worsens and v = 0 keeps the TTC rate. The share of the drawn balance not yet prepaid at default date k is `SP[k] = (1 - CPR[1]) × … × (1 - CPR[k-1])`, with `SP[1] = 1`: prepayment during a year lowers EAD from the next bucket on. Then `EAD_drawn[k] = B[k] × SP[k]`, `EAD_undrawn[k] = U[k] × c[k]` and `EAD_total[k] = EAD_drawn[k] + EAD_undrawn[k]`, which defines `D[k]` in EAD-02 for the scheduled profile. The undrawn amount is not prepaid. Prepayment is applied once, in EAD, and never also in the default survival `S[k]`. It changes only the EAD profile used to measure loss: prepaid and matured balances are replaced in the balance-sheet stock (EXP-01, EXP-05), and at each year-end the profile restarts from the static stock balance (EAD-05). A missing prepayment rate blocks the affected calculation.

### 8.5 Lifetime expected credit loss

**ECL-01 — DESIGN.** Define expected loss using marginal default probabilities, exposure at each future default date, loss severity and discounting. Survival shall be applied once. A cumulative lifetime PD shall not be applied separately in every future year.

**ECL-02 — DESIGN.** S1 shall represent lifetime cash shortfalls associated with defaults occurring over the next 12 months. It shall not be limited to cash shortfalls paid within those 12 months. S2 shall use the relevant lifetime horizon. S3 shall reflect already credit-impaired exposure and expected recovery shortfalls.

**ECL-03 — DRAFT/DESIGN.** Use the risk-parameter timing prescribed in the draft: forward-looking parameters for end-year S1/S2, and the appropriate current/default-cohort treatment for S3. End-2029 S1 provision calculations require terminal treatment rather than a missing 2030 parameter. [S3 ¶55, ¶123–125, Boxes 4–9]

**ECL-04 — DRAFT/DESIGN.** Support the six-year S1/S2 reversion from adverse terminal risk parameters toward the 2029 baseline parameters, with baseline terminal parameters held flat. Preserve the separate S3 terminal macro/recovery assumptions. Do not extend the three-year scenario by simply setting every subsequent loss to zero. [S3 ¶123–125]

**ECL-05 — DESIGN.** Distinguish interpolation of a loss-rate product from interpolation of its components. The draft's specific end-2029 S1 provision examples shall be acceptance oracles. Multiplying separately interpolated PD and LGD does not necessarily reproduce the prescribed loss-rate interpolation.

**ECL-06 — DRAFT/DESIGN.** Preserve perfect-foresight cohort behaviour. Do not repeatedly reprice an unchanged S2 cohort as if it were newly originated. Explain changes caused by migration, replacement or another permitted event. [S3 ¶123–125, ¶137–139]

**ECL-07 — DRAFT/DESIGN.** Apply the no-release constraint to each S3 exposure/cohort, not merely to the total portfolio. The original S3 allowance treatment shall reflect the first projected year's prescribed loss estimate and its opening allowance floor. [S3 ¶141–144, Box 9]

**ECL-08 — DESIGN — integrated parameter calculation.** For a performing exposure valued at date `t`, use `ECL = sum_k(m[k] × EAD[k] × LGD_default[k] × DF(t, default[k]))`, where all inputs share scenario, event basis and default bucket. LGD_default contains recovery discounting from receipt to default; `DF` covers default back to the valuation date. For S1 include defaults only in the next 12 months, while retaining all post-default recoveries in LGD; for S2 include the approved remaining life. S3 uses recovery shortfalls directly. A prescribed EBA loss-rate/benchmark calculation can replace this decomposition, but must carry its own method flag and an explicit bridge; do not override ECL-03–ECL-07 with the generic formula.

**ECL-09 — DESIGN — reconciliation outputs.** Report each bucket's PD, EAD, LGD, discount factor and ECL contribution, with drawn/undrawn split and a total that reconciles to the final allowance/provision after methodological constraints. Parameter-route, benchmark-route and constrained outputs shall remain distinguishable. Changes to one input shall identify both the raw loss effect and any effect masked by a binding provision floor.

**ECL-10 — DESIGN — terminal treatment through the Z-score.** Default buckets 2027–2029 follow the scenario path. For later buckets, adverse Z reverts linearly to the baseline 2029 Z: `Z_adverse(t) = a(t) × Z_adverse(2029) + (1 - a(t)) × Z_baseline(2029)`, with adverse weights a(t) of 5/6, 4/6, 3/6, 2/6, 1/6 and 0 for 2030–2035 and 0 from 2036. Baseline Z is held flat at its 2029 value. The PiT matrices, LGD and prepayment rates after 2029 follow from the reverted Z, so they revert together. The end-2029 S1 provision uses the interpolated 2030 loss rate (ECL-05, AT-06); S2 lifetime provisions use the reverted matrices and LGD. Baseline parameters are built before adverse. A missing 2030 or terminal input blocks the calculation (AT-41). This is the project's reading of ECL-03–ECL-05 and SYN-PAR-04.

**ECL-11 — DESIGN — S3 allowance.** For the original end-2026 S3 cohort, the allowance is `max(GCA × LGD of the year, prior allowance)`, checked per exposure (ECL-07). A new S3 cohort is booked once, in its entry year, as `flow × LGD of the default year`, and its allowance shall not fall below that amount afterwards. LGD comes from LGD-12. Raw and constrained values are both kept (ECL-09). AT-03 and AT-04 apply as written.

### 8.6 Stock-to-flow accounting

**ACC-01 — DESIGN.** Present opening allowance, closing allowance and impairment expense separately. Under an unchanged perimeter without other movements, the expense is the change in allowance; the full closing allowance is not expensed again each year.

**ACC-02 — DESIGN.** If a bridge includes transfers, write-offs or other accounting items, identify each explicitly and show whether it is permitted in the exercise. FX movements shall be zero under the EUR-only scope. Do not introduce movements incompatible with the static projection rules.

**ACC-03 — DESIGN.** Distinguish on-balance allowance from off-balance provision. Preserve the FINREP-aligned categories and conversion conventions required by the approved guidance. The draft's off-balance definitions contain specific CCF references that must be implemented as written, not replaced with a generic management convention. [S3 ¶78–82]

**ACC-04 — DESIGN.** Track overlays by exposure/segment, scenario, year, risk addressed, overlap assessment and approval. Prevent an opening overlay and a new overlay for the same risk from being double-counted.

### 8.7 Mandatory synthetic parameter configuration

The following **SYNTHETIC** settings define deterministic parameter test cases, not bank estimates or EBA-prescribed parameters. They are reference observations within the wider distributions in §5.4; they do not replace facility heterogeneity, opening totals or any acceptance case that explicitly specifies a different input. P06 is split for parameter testing without changing its 60% sovereign/40% bank allocation. Each table row shall be exercised for both opening S1 and opening S2 reference exposures. The opening S1 and S2 12-month PDs are the calibration targets for the TTC matrices (SYN-PAR-05).

| Reference segment | Opening S1 12-month PD | Opening S2 12-month PD | Opening performing LGD | Reference remaining life | Reference EIR |
|---|---:|---:|---:|---:|---:|
| P01 mortgages | 0.80% | 4.00% | 15% | 25 years | 3.0% |
| P02 consumer | 3.00% | 12.00% | 75% | 4 years | 9.0% |
| P03 SME | 2.00% | 8.00% | 40% | 5 years | 5.0% |
| P04 CRE | 1.50% | 6.00% | 35% | 7 years | 4.5% |
| P05 corporate | 1.00% | 5.00% | 35% | 6 years | 4.0% |
| P06 general governments | 0.05% | 0.50% | 30% | 8 years | 2.0% |
| P06 credit institutions | 0.20% | 1.50% | 35% | 5 years | 3.0% |

**SYN-PAR-04 — timing and terminal completion.** The 2027–2029 parameters are indexed by the year of possible default, not merely the report label. End-year provision calculations select the future buckets prescribed by ECL-03–ECL-06, including the end-2029 loss-rate interpolation tested in AT-06. Apply the prescribed reversion/terminal treatment through the remaining life; the three-year table alone is insufficient for a lifetime run. Store the terminal-generation rule and each generated bucket. The reference table is never a substitute for mandatory sovereign benchmarks in regulatory mode. The reversion operates on the Z-score (ECL-10).

**SYN-PAR-05 — matrix calibration.** Calibrate each reference segment's TTC matrix (PD-09) so that the average one-year TTC PD of the grades holding its S1 exposures equals the segment's opening S1 12-month PD in the table above, and likewise for S2, using the drawn-exposure weighting of RPT-06; for example 0.80% and 4.00% for P01. The project owner chooses N. The calibrated matrices shall pass AT-45 and AT-46.

**SYN-PAR-06 — parameter set.** The parameter set holds, per segment: Z-score weights β with driver means μ and standard deviations σ (SCN-08), matrix correlation ρ (PD-10), SICR multiple k (MIG-07), LGD sensitivity w (LGD-12), prepayment rate CPR_TTC and its sensitivity v (EAD-11), the accounting CCFs (SYN-PAR-07) and the terminal rule (ECL-10). The project owner supplies the values; until then they are OPEN, and a run without them blocks. They are synthetic test conventions, not estimated or EBA-prescribed parameters.

**SYN-PAR-07 — reference exposure profile.** The core run uses the bullet profile for every facility; annuity and linear profiles run as a separate variant. Acceptance cases use the bullet profile with zero prepayment, as AT-34, AT-35 and AT-42 assume. P01/P02/P04/P06 have zero undrawn balances in the main books. P03/P05 use 50% accounting CCF in baseline and adverse core runs for all three projection years; the CCF sensitivity in AT-35 runs as a separate variant. Unless explicitly overridden, synthetic annual default buckets end at calendar-year-end and amounts stay unrounded until reporting. The reference discount rate is the facility's annual effective EIR; independent unit cases may explicitly use zero discounting to isolate arithmetic.

**SYN-PAR-08 — opening grades.** The synthetic generator gives each facility an origination grade and a current grade, chosen so that MIG-07 returns the facility's §5.2 opening stage and each segment's S1 and S2 average PD matches SYN-PAR-05. Grade and stage therefore never conflict (DAT-04), and validation blocks any facility whose stage the rule cannot explain.

**SYN-PAR-09 — opening allowances.** The synthetic generator calculates each facility's end-2026 allowance with its own formula: PD curves from the TTC matrix (Z = 0), TTC LGD, the TTC prepayment rate and a bullet schedule at the facility's rate and maturity; for S3, GCA × TTC LGD. The results are frozen as the opening provisions (§5.2) and a run never recomputes them. Any mismatch with the engine's own formula shows as a large first-year charge in the stock-to-flow report.

## 9. Climate risk exclusion

Climate risk is outside the agreed project scope. No transition or physical-risk model, climate overlay, dedicated climate data collection, climate report or climate acceptance case is required.

## 10. Credit REA and capital requirements

**CAP-01 — DESIGN.** Calculate credit risk exposure amounts by regulatory approach and applicable exposure class, using the relevant regulatory parameters and credit-risk mitigation. A fixed product-level risk weight is insufficient as a general production method.

**CAP-02 — DESIGN.** Reflect default/rating migration and stressed collateral eligibility in risk weights and regulatory expected loss. Keep reporting classification separate from the economic changes affecting the calculation.

**CAP-03 — DRAFT/DESIGN.** Apply the starting-point methodological credit-REA floor separately to aggregate IRB and STA contributions to UTREA. Do not apply that floor to the standardised credit-REA comparator feeding STREA. Apply the separate securitisation approach floors where relevant. [S3 ¶153, ¶178]

**CAP-04 — DESIGN.** Distinguish these methodological floors from the CRR output floor. The latter is a bank-wide calculation using the appropriate UTREA, STREA, transition rules and scope. It shall not be applied loan by loan or by replacing only the credit portion of the denominator.

**CAP-05 — OPEN.** Confirm the applicable CRR/CRD assumptions, transitional and fully loaded treatment, output-floor settings, adjustments and reporting definitions against the approved exercise package. Do not freeze a transition schedule merely because it was used in an earlier exercise.

**CAP-06 — DESIGN.** Reconcile accounting allowances to the relevant regulatory provision basis, regulatory expected loss and any IRB shortfall/excess treatment. Calculate resulting capital impacts through the approved capital process; do not subtract both the full expected loss and the same provision expense as independent CET1 losses.

**CAP-07 — DESIGN.** Produce a capital bridge identifying credit impairment, tax effects, shortfall/deductions, other profit/loss, distributions, numerator adjustments and denominator changes. Preserve transitional and fully loaded views where required.

**CAP-08 — DESIGN.** Capital reporting shall identify whether the ratio is a full exercise result or a limited credit sensitivity. A material non-credit input that is unavailable shall be marked missing, not silently set to zero.

**CAP-09 — DRAFT/DESIGN.** Include the non-performing exposure coverage/calendar and relevant deduction interface. Retain origination, default and guarantee/collateral information needed to distinguish applicable populations and avoid double-counting existing deductions or provisions. The capital team shall approve the treatment against S3 §6.4.6, ¶562–564, and the final CSV_CR_NPL instructions.

## 11. Aggregation and reporting requirements

### 11.1 Required analytical dimensions

Retain scenario, year, entity, country, counterparty type, portfolio, accounting category, stage, default cohort, regulatory approach/class, NACE version/code and collateral type. Currency is fixed to EUR; the on-balance accounting category is fixed to AC. Off-balance records remain separately identified.

**RPT-01 — DESIGN.** Preserve full internal detail even when regulatory reporting applies materiality thresholds. Store both the full amount and the reportable subset.

**RPT-02 — DESIGN.** Fix reporting country selection using the approved starting-point rules. Country selection shall not change each year because a scenario changes risk weights or provisions.

**RPT-03 — DESIGN.** Support different country selection rules for accounting-loss and REA templates. Do not apply one generic “top countries” list to all outputs.

**RPT-04 — DESIGN.** Reconcile material-sector subsets to the NFC total with an explicit excluded-small-sectors bridge. The draft permits differences between sector-subset totals and full country totals; these shall not automatically be treated as errors or forced into false equality. [S3 ¶98–99]

**RPT-05 — DESIGN.** Aggregate parameters using the correct denominator. A PD, LGD, transition rate, coverage ratio and loss rate can require different weights. Never average segment ratios without retaining their underlying numerator and denominator.

**RPT-06 — DESIGN.** For internal parameter diagnostics, calculate one-year portfolio PD as `sum(D[i] × q[i]) / sum(D[i])` over the relevant opening performing cohort and disclose its drawn-exposure weighting. Calculate default-loss-weighted LGD as `sum(m[i] × EAD[i] × LGD[i]) / sum(m[i] × EAD[i])` for the same default bucket; return not applicable when the denominator is zero. Sum monetary ECL from facility/bucket results. Do not multiply independently averaged PD, LGD and EAD to recreate portfolio loss. Regulatory output weighting follows the approved template definitions where they differ.

### 11.2 Draft reporting-selection parameters

The selection design shall capture the following draft settings, their denominators and their source versions. Threshold edge cases require explicit tests.

| Selection | Draft preparation rule | Source |
|---|---|---|
| Non-domestic geographical reporting | Assess the 10% non-domestic original-exposure threshold using the prescribed COREP basis | S3 ¶100, ¶105 |
| Accounting-credit country detail | Maximum 10 countries under the specified selection rules; remaining exposures in Other | S3 ¶100–102 |
| REA country detail | Maximum 5 selected countries; common selection for IRB and STA; remaining exposures in Other | S3 ¶104–106 |
| Non-domestic country materiality | Apply the specified greater-than-1% test against domestic plus non-domestic original exposure | S3 ¶100, ¶105 |
| Core sector materiality | Retain the stated country/sector 0.5% test and reconcile the resulting subset | S3 ¶98–99 |

The implementation shall record the precise denominator and domestic-country treatment for each rule. Where the final package clarifies a denominator or boundary, update the selection and its acceptance cases together.

### 11.3 Output catalogue

| Output | Required contents |
|---|---|
| Starting-point reconciliation | Accounting exposure, regulatory exposure, provisions, stage and scope bridges; EUR-only and AC-only checks |
| Stage migration report | Opening/closing S1/S2/S3, all permitted flows, old/new S3 cohorts, with the grade-level detail behind them |
| Parameter report | Conditional/marginal/cumulative PD and survival curves; TTC and PiT rating matrices and Z-scores; LGD by Z-score; contractual schedule, prepayment and drawn/undrawn accounting EAD, and regulatory EAD bridge; bucket-level ECL, lifetime horizon, source, benchmark use, overlays and binding constraints |
| Impairment report | Opening/closing allowance, annual charge, cumulative charge, on/off-balance distinction |
| Credit-REA report | Raw result, methodological floors, adjustments, regulatory EL and standardised comparator |
| Concentration report | Largest obligors/groups, country/sector concentration and contribution to loss |
| Sensitivity report | Input change, affected population, loss/REA effect, explanation and limitations |
| QA report | Failed controls, severity, owner, resolution, approved exceptions and residual limitations |
| Explanatory note | Methods, data gaps, assumptions, benchmark choices, adjustments and material drivers |

### 11.4 Draft template families

| Template family | Required mapping |
|---|---|
| CSV_CR_SCEN | On-balance accounting credit projections |
| CSV_CR_SUM / CSV_CR_NPL | Credit summary and non-performing exposure coverage/calendar |
| CSV_CR_SCEN_OFF_BS | Off-balance exposures and provisions |
| CSV_CR_SECTOR | Required sector breakdown and materiality subset |
| CSV_CR_REA_IRB_DET / CSV_CR_REA_STA_DET | Credit-REA detail by approach |
| CSV_CR_REA_IRB / CSV_CR_REA_STA | Approach aggregation and methodological floor treatment |
| CSV_CR_REA_OF | Standardised comparator for output-floor purposes |
| CSV_CR_SEC / CSV_CR_SEC_SUM | Separate securitisation detail and summary when securitisations are in scope (SCP-03) |
| CSV_P&L / CSV_CAP / CSV_REA_SUM | Credit contributions to the full exercise aggregation |

Source: S3 Annex II; S4 §2.2, limited to the agreed project scope. The “CSV” prefix is a template name; it does not by itself specify a comma-separated-file delivery requirement. Final cell-level mappings remain an OPEN dependency.

## 12. Validation and acceptance criteria

### 12.1 Quantitative acceptance cases

All monetary amounts in the following table are in EUR unless explicitly stated in EUR millions; most are deliberately small test values. They are expected outcomes for validation, not portfolio forecasts.

| ID | Test input | Expected result |
|---|---|---|
| AT-01 | Synthetic portfolio targets in §5 | 10,000 facilities; GCA €11,000m; undrawn €2,000m; illustrative converted total €12,000m |
| AT-02 | Opening S1/S2/S3 = 900/80/20; S1 transitions 90%/8%/2%; S2 transitions 5%/85%/10%; S3 stays S3 | Closing S1/S2/S3 = 814/140/46; total 1,000 |
| AT-03 | S3 exposure 100; opening allowance 45; year-one lifetime loss rate 35% | Existing S3 allowance remains 45 under the prescribed floor |
| AT-04 | New S3 flow 20; applicable LGD 40% | New-cohort allowance 8, accumulated once |
| AT-05 | Closing S1 exposure 100; next-year PD 2%, LGD 30% | S1 provision 0.6 under the simplified loss-rate example |
| AT-06 | End-2029 adverse PD/LGD 6%/40%; baseline 2%/30% | Draft's 2030 S1 loss-rate interpolation: five-sixths of 2.4% plus one-sixth of 0.6% = 2.1% |
| AT-07 | Allowance stock rises from 20 to 27; no other movements | Impairment charge 7, not 27 |
| AT-08 | Drawn 100, undrawn 40, illustrative CCF 50% | Converted total exposure 120, not 140 or 160 |
| AT-10 | Starting IRB/STA REA 80/20; raw stressed REA 70/25 | Credit contribution after separate methodological floors = 105 |
| AT-11 | Bank-wide UTREA 105; STREA 160; illustrative fully loaded factor 72.5% | Output-floor comparison gives max(105,116) = 116; example does not set the transitional rule |
| AT-16 | Residential price shocks -12%, -10%, -3% | Terminal index 76.824 from initial 100 |
| AT-18 | S3 facility A provision falls 5; facility B rises 10 | Reject A's release even though aggregate provisions rise 5 |
| AT-21 | Currency scope across all six portfolios, borrower cash flows, collateral, recoveries and scenarios | Every monetary item is EUR; FX movements are zero |
| AT-22 | Accounting allocation in §5.3 | AC GCA €11,000m; P06 AC €2,240m; FVOCI/FVPL GCA zero; stage and regulatory-approach totals match §5.2 and §5.3 |
| AT-25 | Conditional annual PDs 2%, 3%, 4%; initially performing cohort | Marginal PDs 2%, 2.94%, 3.8024%; cumulative PDs 2%, 4.94%, 8.7424%; terminal survival 91.2576% |
| AT-28 | Annual conditional PD 4%; remaining interval 0.5 years | Stub PD = 1 - sqrt(0.96) = 2.0204102887% |
| AT-29 | Opening S1/S2/S3 GCA 800/150/50; origin-stage PDs 2.5%/8%; aligned default definition | New default flows 20 and 12; closing S3 82; closing performing total 918; total GCA 1,000 |
| AT-33 | Zero EAD with zero recovery | LGD not applicable; monetary loss is zero |
| AT-34 | Drawn 800,000; undrawn 400,000; accounting CCF 50%; one-bucket PD 2%; LGD 40%; DF 1 | EAD drawn/undrawn/total 800,000 / 200,000 / 1,000,000; ECL 6,400 on-balance + 1,600 off-balance = 8,000 |
| AT-35 | Separate utilisation sensitivity on AT-34: CCF rises from 50% to 75%, other inputs fixed | Conditional EAD rises from 1,000,000 to 1,100,000; ECL rises from 8,000 to 8,800; nominal balances unchanged; excluded from the fixed-CCF core reference run |
| AT-36 | Permitted-transfer unit case: drawn 600, undrawn 400; transfer 100 to drawn; CCF 50% | Drawn 700, undrawn 300, limit remains 1,000; conditional EAD 850; transferred 100 is not counted again as undrawn |
| AT-37 | Principal 100, accrued interest 5 already included in GCA 105, no undrawn | Accounting drawn EAD 105, not 110; no repeated interest addition |
| AT-38 | Drawn 100, undrawn 40; accounting CCF 50%; independently supplied hypothetical regulatory CCF 75%; other adjustments zero | Accounting EAD 120; regulatory EAD 130; explicit CCF bridge +10; do not apply both CCFs sequentially |
| AT-39 | PD curve from AT-25; EAD 1,000 each year; LGD 40%; EIR 0%; remaining life three years | S1 one-year ECL 8; S2 lifetime ECL 34.9696, rounded to 34.97 only at output; not 36 from summing conditional PDs |
| AT-40 | One-year default bucket; EAD 100; marginal PD 2%; default-date LGD 40%; EIR 5% | Reporting-date ECL = 0.8 / 1.05 = 0.7619047619; default-to-recovery discounting must not be reapplied |
| AT-41 | End-2029 S1 valuation without the required 2030/terminal input | Block calculation; do not set next-year PD or ECL to zero; terminal interpolation must pass AT-06 |
| AT-42 | P03 opening S1 reference: valuation 31 December 2026; default bucket 31 December 2027; PD of the 2027 bucket 4.296875% and LGD 45%, both given by the case; drawn 800,000, undrawn 400,000, CCF 50%; bullet profile, zero prepayment; EIR 5% | EAD 1,000,000; one-year ECL 18,415.1785714286, displayed as 18,415.18 |
| AT-44 | §5.1 main books under the §8.7 fixed-CCF core configuration in each projected year | GCA €11,000m; nominal undrawn €2,000m; converted commitments €1,000m; illustrative total €12,000m; P03 €1,800m and P05 €4,700m |
| AT-45 | Every TTC matrix (PD-09) | Each row sums to one within 1e-10, no cell is negative and D is absorbing; a matrix that breaks any of these is blocked |
| AT-46 | TTC matrix and its PiT shift for several Z values (PD-10) | Every PiT row sums to one within 1e-10; in the TTC and every PiT matrix, PD rises with the grade |
| AT-47 | One grade in one year, Z lowered with everything else fixed (PD-10) | The grade's one-year PD rises as Z falls |
| AT-48 | SICR case with origination grade, k and TTC matrix supplied (MIG-07) | A slice is S2 exactly when its lifetime PD is at least k times that at the origination grade, S3 in D and S1 otherwise; a slice that improves back over the line returns to S1; D never cures. Expected stage per grade: OPEN until approved |
| AT-49 | LGD_TTC of 0, 1 and an interior value, with Z = 0 and Z < 0 (LGD-12) | Z = 0 returns LGD_TTC within 1e-10; 0 and 1 pass through unchanged; with w > 0 the interior LGD rises as Z falls and stays below 1 |
| AT-50 | Facility with a positive prepayment rate and an undrawn commitment (EAD-11) | SP[1] = 1; EAD_drawn[k] = B[k] × SP[k]; the undrawn amount is not prepaid; default survival S[k] is identical with and without prepayment; a zero prepayment rate gives EAD_drawn[k] = B[k] |
| AT-51 | Schedule cases: bullet, annuity and linear facilities, one with a stub final period (EAD-10) | Bullet balance flat at D until M; annuity payment constant with closing balance 0 at M; linear principal D / M each year; stub of fraction d in the final period; accrued interest counted once. Schedule values: OPEN until approved |
| AT-52 | Z-score case with drivers, coefficients and a missing-coefficient case (SCN-08, ECL-10) | Z = 0 when every driver equals its mean; a missing coefficient blocks; adverse Z after 2029 follows weights 5/6 to 0 toward baseline 2029 and is flat from 2036. Z values: OPEN until approved |

### 12.2 Controls with required outcomes

| Control | Required result |
|---|---|
| Duplicate facility | Reject the duplicated record or reconcile an explicitly identified source duplicate before approval |
| Probability range or transition sum | Reject negative/>100% probabilities and non-unit transition rows |
| PD curve identities and completeness | Block missing future buckets, decreasing cumulative PD, inconsistent survival, or identity residual above 1e-10 |
| LGD rule | Block a missing TTC LGD or Z; a final LGD outside 0%–100% or an unexplained raw/final LGD difference is blocking; retain approved exceptions explicitly |
| EAD/CCF contract | Block missing applicable CCF, negative exposures, duplicate commitment conversion and unexplained limit breaches; use the profile-specific bounds in EAD-04 |
| Parameter alignment | Require the same scenario, valuation date, default bucket and event basis for PD/LGD/EAD multiplication |
| S3 parameter use | Exclude defaulted exposures from performing PD projection and prevent applying PD to already-weighted default flows |
| Missing scenario value | Block the affected run; do not carry forward an undisclosed default |
| Missing mandatory benchmark | Block regulatory-mode projection for the affected population |
| Country or taxonomy mapping | Unmapped material exposure shall block submission readiness |
| Currency and accounting scope | Reject non-EUR/missing currency and non-AC/missing on-balance accounting category; validate off-balance classification separately |
| Scenario provenance | Prevent synthetic scenarios from being labelled official |
| Static balance | Explain all differences; reject unapproved runoff, cures, sales and growth |
| Reproducibility | Same approved inputs and assumptions shall reproduce the same deterministic results |
| Version change | Rerun impacted cases and retain a quantified difference report |
| Rating matrices | Block a TTC or PiT row that does not sum to one within 1e-10, a negative cell or a non-absorbing D |
| Grade and stage | Block a missing current or origination grade, or a reported stage that the MIG-07 rule cannot explain |
| Cash-flow inputs | Block a performing facility with a missing or non-positive maturity, a missing rate, or a rate of -100% or lower |
| Z-score and prepayment | Block a missing Z coefficient, Z value or prepayment rate; prepayment applied in the default survival fails |

### 12.3 Proposed tolerances

These are DESIGN thresholds, not EBA thresholds. Final official template validation rules take precedence.

| Item | Proposed tolerance |
|---|---|
| IDs, counts, scope membership and classification | Exact match |
| Transition row sums and probability identities | Absolute error at most 0.0000000001 before display rounding |
| PD/LGD/CCF numerical test cases | Absolute error at most 1e-10 in decimal-fraction units, using unrounded oracle values |
| Individual test-case amounts | EUR 0.01 where the case is expressed in euros |
| Aggregate reconciliation | Greater of EUR 1 or 0.00000001 × reconciled amount; every residual explained |
| Reported amounts | Apply the official reporting-unit rounding only at the output boundary |
| Source completeness | 100% of mandatory material inputs supplied or covered by an explicitly permitted treatment |
| Critical/high-severity defects | Zero unresolved at release |

### 12.4 Sensitivity and plausibility requirements

**VAL-01 — DESIGN.** Test more severe property shocks, higher unemployment, a higher interest-rate path, weaker borrower income, longer recovery delays, lower guarantee recoveries, larger sector shocks and higher commitment utilisation where permitted.

**VAL-02 — DESIGN.** Evaluate sensitivity holding other factors constant. Do not require every segment's final adverse allowance to exceed every baseline allowance automatically: migration, timing and denominator changes can affect comparisons. Require a documented economic explanation for counterintuitive results.

**VAL-03 — DESIGN.** Assess concentration by obligor and connected group. Do not assume that many facilities necessarily constitute many independent borrowers.

**VAL-04 — DESIGN.** Perform independent challenge of model responsiveness, benchmark deviations, opening parameter representativeness, lifetime treatment, loss allocation and capital bridges. Synthetic test success does not establish model validity on actual bank data.

## 13. Operational and governance requirements

| ID | Requirement |
|---|---|
| OPS-01 | Every run shall identify source snapshot, scenario, parameter set, model version, rule version, reporting version and approver. |
| OPS-02 | Separate preparation, review and approval permissions. Changes after approval require a new version. |
| OPS-03 | Retain raw inputs, transformations, overrides, outputs, validation results and explanation material for the bank's required retention period. |
| OPS-04 | A report shall show whether it is draft, synthetic, validated, approved or superseded. |
| OPS-05 | Restrict access to real borrower information when introduced. Synthetic examples shall contain no real customer identities. |
| OPS-06 | Agree capacity and turnaround targets using the bank's actual portfolio size and delivery calendar. Performance acceptance shall include both calculation and reconciliation. |
| OPS-07 | An unresolved material data gap shall remain visible in results and readiness status; it shall not disappear through aggregation. |
| OPS-08 | Each override shall have a rationale, owner, expiry/review date and quantified effect. |
| OPS-09 | Maintain a single issue log for methodological questions, template changes, QA challenges and authority responses. |

### 13.1 Accountabilities

| Owner | Approval responsibility |
|---|---|
| Credit Risk | Portfolio segmentation, credit assumptions, migration, recoveries and explanations |
| Finance | Opening accounting balances, allowances, P&L bridges, tax and capital interfaces |
| Regulatory Reporting | Scope, taxonomy, template mapping, materiality and reporting validation |
| Model Risk/Validation | Independent methodological and model challenge |
| Data Owner | Data quality, reconciliation, lineage and remediation |
| Programme Lead | Source changes, issue resolution, delivery readiness and sign-off evidence |

## 14. Deliverables and completion gates

The delivery team shall produce the following reviewable requirements evidence before declaring the capability ready:

1. Approved requirements and a traceability matrix linking rules, data, outputs and acceptance cases.
2. Portfolio definitions satisfying §5, with controls showing count, exposure and stage totals.
3. Scenario catalogue separating official and synthetic inputs, with unit and completeness checks.
4. Model/benchmark inventory and documented parameter ownership, plus the PD/LGD/EAD input/output contract, model equations and coefficients, complete lifetime curves, TTC and PiT rating matrices, Z-score definitions, contractual schedules, EAD bridges and §8.7 synthetic reference results.
5. Exposure, allowance, impairment, REA and capital reconciliation designs.
6. Scope evidence confirming EUR throughout, all on-balance assets at AC and separate off-balance treatment.
7. Output catalogue and version-bound template mappings.
8. Independent validation and an issue log with no unresolved critical/high-severity defects.
9. Final methodology/scenario/template change assessment and documented approval.

| Gate | Exit requirement |
|---|---|
| Requirements approved | Scope, assumptions, ownership and open issues agreed |
| Synthetic design accepted | All portfolio totals reconciled |
| Methodology design accepted | PD/LGD/EAD rules and numerical acceptance cases passed; stage/cohort, lifetime, static-balance and capital rules independently reviewed |
| Reporting design accepted | Approved template version mapped; materiality and subset bridges defined |
| In-scope regulatory readiness | Final authoritative inputs loaded, production validation completed and required approvals obtained; wider exercise obligations separately accounted for |

**Current document status:** Requirements and synthetic portfolio blueprints are supplied. Production models, actual bank inputs, official scenario calibrations, final template mappings and regulatory submission readiness are outside this document's completed scope.

## 15. Sources

Sources were checked on 17 October 2026, when the EBA exercise page listed the June 2026 draft package. Direct access to the two draft PDFs was unavailable, so their paragraph-level references have not been verified against the PDFs. Paragraph numbers refer to the June 2026 draft. These documents should be consulted directly for the complete requirements and any subsequent changes.

- **S1 — EBA EU-wide stress testing landing page.** Identifies the 2027 draft package and publication date. [Official page](https://eba.europa.eu/risk-and-data-analysis/risk-analysis/eu-wide-stress-testing).
- **S2 — EBA, 11 June 2026, “The EBA launches early consultation on simplified EU-wide stress test, with climate risk integration.”** Source for the draft status and simplified reporting. [Official announcement](https://www.eba.europa.eu/publications-and-media/press-releases/eba-launches-early-consultation-simplified-eu-wide-stress-test-climate-risk-integration).
- **S3 — 2027 EU-wide stress test: Draft Methodological Note.** Primary methodology reference; particularly §1.3, §2 and Annex II for the retained scope. [Official PDF](https://www.eba.europa.eu/sites/default/files/2026-06/7185aac4-4a70-4d83-ae1b-1cfca979ae07/2027%20EU-wide%20stress%20test%20-%20Draft%20Methodological%20Note.pdf).
- **S4 — 2027 EU-wide stress test: Draft Template Guidance.** Primary reporting reference; particularly §2.2 for the retained scope. [Official PDF](https://www.eba.europa.eu/sites/default/files/2026-06/e4eedf91-0957-4f02-b4c9-22154f491904/2027%20EU-wide%20stress%20test%20-%20Draft%20Template%20Guidance.pdf).

All synthetic portfolio targets, illustrative scenarios, test-case amounts, proposed tolerances and operating requirements in this document were created for this specification. They are not published EBA calibrations.

The synthetic modelling method in §1.4 and §8 is a project design decision, described in `docs/stress-engine-code-flow.html`; it is not an EBA source.
