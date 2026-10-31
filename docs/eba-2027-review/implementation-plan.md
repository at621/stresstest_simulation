# Plan: configurable credit projections

Requested on 31 October 2026, following the assessment of the six high-level goals.
Starting revision: `477309d`. Branch: `improve/configurable-projections`.
Baseline: `runs/20261031T1301Z-core-53f91e0f` (EUR 130.4m baseline and EUR 635.0m adverse).

## Scope and decisions

Implement the missing reusable capabilities as optional extensions of the existing engine.
The existing input set and default static calculation remain the regression reference.
The request authorises the extensions to the previous static, single-model design; it does
not approve bank estimates, open numerical oracles, or a regulatory interpretation.
Regulatory execution remains unavailable until the external evidence is supplied.

The delivery has one cohesive configuration contract, introduced in dependency order below.
New functionality must run through R2–R11, be included in sealed replay, and have an explicit
financial reconciliation. No diagnostic is to be described as an integrated calculation.

## 1. One run specification and reproducible experiments

- Add a versioned YAML specification tying run settings, scenarios, portfolio metadata,
  model choices and exposure assumptions to an immutable input-set hash.
- Read through ingestion only, reject unknown settings and malformed domains, and retain
  exact original bytes and the resolved assumptions in the run.
- Permit execution from the specification and replay from the sealed copy after the
  original file has gone. Resolve relative paths against the specification directory.
- Keep legacy commands working. Prevent ambiguous command-line/specification precedence.
- Publish a complete input and configuration reference, including existing datasets,
  legacy defaults, optional preparation inputs and recorded methodology conflicts.

Acceptance: valid specification seals; unknown key, wrong hash, missing path and invalid
domain block; replay reproduces all outputs without the original specification.

## 2. Portfolios and ad hoc scenarios

- Move template classification to configurable segment metadata, with legacy mappings
  available for existing input sets. Require explicit classification for new segments.
- Check that each segment belongs to exactly one portfolio rather than silently selecting
  the first portfolio during aggregation.
- Add named scenarios from supplied country/year/variable paths or an explicit clone and
  overrides. Retain source/version/narrative and record inherited values as such.
- Allow additional driver variables and lag history. Do not silently invent missing paths.
- Generalise workbook comparison labels and retain all scenarios in outputs.
- Add an input-set packaging command for already prepared tables and YAML, without routing
  new portfolios through the six-book synthetic generator.

Acceptance: a new portfolio and segment, and a third named crisis, complete the full
pipeline using unchanged financial kernels; missing classification or scenario data blocks.

## 3. Portfolio-specific macro models

- Retain the existing linear Z model as the default.
- Add explicit model identifiers and versions with a selectable nonlinear polynomial/lagged
  driver model and an externally supplied score model.
- Route each segment independently; keep one resolved score per segment/country/year for
  PD, LGD and prepayment, including explicit terminal policy per scenario.
- Support sector-specific channels through configured segment assignment and sector-driver
  variables, while preserving the shared master scale.
- Retain model provenance, terms and contributions in reports.

Acceptance: different models coexist in one run; lag history and supplied score coverage
are enforced; changing one segment's model changes only its core parameters and losses.

## 4. Dynamic exposure assumptions

- Add an explicit `dynamic` mode alongside the unchanged static mode.
- Accept complete annual scenario/portfolio assumptions for changes to performing drawn
  and undrawn stocks before migration. These are externally supplied business-volume
  assumptions, not an endogenous lending or borrower-behaviour model.
- Retain Stage 3 cohorts and their provision floors; keep changes to performing exposure
  separate from default migration. Distinguish exposure growth/runoff from loan origination
  with a fresh vintage: the latter requires facility/cohort data and is not inferred.
- Reconcile opening stock + supplied volume change + credit migration = closing stock;
  value ECL on the resulting exposure and reconcile allowance stock to impairment charge.
- Make reports, labels and readiness clearly identify the balance-sheet mode. EBA static
  template arithmetic is not represented as applicable to a dynamic run.

Acceptance: zero changes reproduce static financial results; growth and contraction produce
the specified balance movements, undrawn changes affect off-balance provisions, Stage 3 is
retained, missing annual assumptions block, and accounting/bucket bridges close.

## 5. EBA preparation and specification consistency

- Retain selectable methodological readings and show unresolved choices in readiness.
- Produce an effective specification report so approved implementation decisions and
  legacy specification conflicts cannot be mistaken for interchangeable defaults.
- Remove stale statements that delivered reporting/control work is absent or unmerged.
- Record precisely which obligations remain outside this delivery: final-package review,
  official scenarios and benchmark calibration, approved CRR/Article 47c inputs, bank model
  estimation/backtesting, source/input/oracle sign-off, and official submission validation.
- Document remaining model limitations: recovery and benchmark diagnostics do not replace
  core models, and externally supplied business-volume paths do not estimate new vintages,
  sales, write-offs or cures.

Acceptance: no output claims regulatory compliance; readiness distinguishes implemented
capabilities from supplied evidence and open methodology decisions.

## 6. Verification and delivery

1. Write capability and rejection tests before the corresponding implementation.
2. Run targeted tests as each stage is completed.
3. Regenerate the traceability/source register using its generator.
4. Run the complete CI gate: specification drift, Ruff, import contracts and pytest.
5. Run the unchanged full static book and compare with the baseline; explain all differences.
6. Run a full-book crisis/dynamic example and replay the sealed result.
7. Obtain the repository's independent change-reviewer assessment and resolve blocking findings.
8. Leave changes on the implementation branch; merging is not part of this request.

## Delivery record

Implementation was prepared on `improve/configurable-projections`. After the implementation
review, the user authorised merging and pushing it to `main`, together with README cleanup
and a permanent rule keeping temporary status and owner-action tracking out of README.

| Goal | Delivered | Remaining boundary |
|---|---|---|
| EBA 2027 | Existing credit-loss pipeline and preparation controls retained; effective methodology/conflict record and readiness extended | Regulatory mode stays blocked. Final package, official paths/benchmarks, approved mappings, calibration and owner numerical sign-offs remain external dependencies. |
| Dynamic assumptions | Scenario/portfolio/year changes to performing drawn and undrawn stocks; S3 retention; exposure and on/off-balance accounting bridges; zero-stock reporting | Existing facility prototypes only. Fresh vintages, endogenous lending, sales, write-offs and cures require additional models/data. |
| Multiple portfolios | Generic packaging of prepared inputs, segment inheritance/assignment, configurable reporting classes and segment-to-portfolio control | Existing supported products, EUR/AC scope and shared grade scale remain. New product mathematics is not inferred. |
| Portfolio-specific macro models | Per-segment linear, polynomial/lagged and external-score registry; sector drivers and NACE assignment; source/version/term records | Empirical fitting, backtesting and validation remain outside the execution engine. |
| Clear inputs/configuration | Versioned strict run specification, consolidated field reference, immutable hash binding, effective JSON and sealed replay | Locked legacy requirement conflicts are exposed, not owner-approved or rewritten. Optional preparation sections retain their existing validation semantics. |
| Ad hoc crises | Named scenarios from complete paths or inheritance/overrides; extra driver/history inputs; scenario-specific terminal policies; arbitrary display labels | Complete dependencies must be supplied. The engine does not infer a scenario narrative into quantitative paths. |

### Verification evidence

- Tests were introduced before the corresponding changes. Review regressions cover mixed
  terminal policies, overlapping assignments, punctuation in scenario identifiers, complete
  portfolio and whole-book runoff, nested setting rejection, CCF mismatch and portable JSON.
- Original baseline: `runs/20261031T1301Z-core-53f91e0f`.
- Final static comparison: `runs/20261031T1336Z-core-60a40e71`. All calculation Parquets
  and existing financial CSVs are byte-identical: 45 of 48 original outputs match. Changes
  are limited to readiness, workbook and summary; two new provenance/specification reports
  are added. Cumulative charges remain EUR 130,439,625.29 baseline and EUR 635,012,849.09 adverse.
  Comparison evidence is in
  `runs/comparisons/20261031T1301Z-core-53f91e0f__20261031T1336Z-core-60a40e71`.
- Full dynamic/crisis example: `runs/20261031T1336Z-core+dynamic-4b8b458e`, sealed SYNTHETIC.
  Cumulative charges: baseline EUR 130,884,485.51; adverse EUR 610,408,595.30;
  energy crisis EUR 993,392,163.55. The baseline difference from the default is intentional:
  the example selects a different consumer model even though baseline volume changes are zero.
  End-2029 GCA is EUR 11.0bn / 10.11bn / 8.34bn respectively. These are demonstrations,
  not forecasts or validation of the illustrative coefficients.
- Sealed replay: `runs/20261031T1337Z-core+dynamic-e01d9514` reproduced all 51 output
  hashes from the full dynamic/crisis example. The static run, dynamic run and replay share
  source fingerprint `23ab75b9584c3cc4ee16c511850e9325f250f11cbcc94f7263237efebae01581`.
- Final full gate: `.venv/Scripts/python.exe tests/ci_gate.py`, exit 0. O1 specification
  files current, Ruff passed, all three import contracts kept, **291 tests passed** in
  443.71 seconds. The generated traceability files also pass `--check`. The existing
  EAD-07 traceability advisory remains: a test names it, but production regulatory EAD
  integration is still correctly recorded as deferred.
- Independent review verified the source and sealed manifests, exact static equality,
  replay equality, P02-only baseline model effects, dynamic volume residuals below EUR
  1e-8 and zero S3 volume changes. All blocking findings were resolved with regression tests.
  Final status: **APPROVE**, 31 October 2026, for source fingerprint `23ab75b9584c`.
  No blocking or advisory findings remain. This is implementation review, not regulatory
  readiness or external model/data approval.
