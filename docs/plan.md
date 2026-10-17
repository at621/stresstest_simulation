# Development plan

The order in which the engine is built and what each step must deliver. The [code flow](stress-engine-code-flow.html) is the design and leads; this plan only orders the work. Where the two disagree, follow the design and raise the conflict so it can be resolved.

| # | Step | Waits on | Status |
|---|---|---|---|
| 1 | Secure the workspace | Owner | To do |
| 2 | Groundwork | Owner | To do |
| 3 | Transcribe the spec (O1) | 2 | To do |
| 4 | Calculation kernels | 2, 3 | To do |
| 5 | Run frame (R1–R3, R11) | 2 | To do |
| 6 | Synthetic starting point (O2–O4) | 3, owner | To do |
| 7 | Scenario and parameters (R4–R6) | 4, 5, 6, owner | To do |
| 8 | Projection and provisions (R7–R9) | 7, owner | To do |
| 9 | Reports and first full run (R10) | 8 | To do |
| 10 | Variants | 9, owner | To do |

Steps 4 and 5 can run side by side, and neither needs the open parameter values.

## 1. Secure the workspace

Make the guard hook work in whatever Python environment Claude Code starts in, and make it fail closed.

**Outcome:**
- The hook command uses an interpreter that works under any active virtualenv, such as `py -3`.
- After the CLI upgrade, the hook has `"onFailure": "block"`.
- The protection check in [runbook.md](runbook.md) passes: every attempt is blocked.

## 2. Groundwork

Everything the steps share, in place before any calculation.

**Outcome:**
- `stress.contracts` defines the seven input datasets, value status, schedule row, facility slice and ParameterRecord.
- Tests load expected values from `docs/spec/`, and a test without an `at`, `req` or `control` marker fails collection.
- `uv run stress --help` works.
- The Claude Code setup planned in [architecture.md](architecture.md) §5 is in place: `/build-step`, `step-reviewer`, the test gate and the pre-commit hook.

## 3. Transcribe the spec (O1)

`foundation/transcribe` turns the requirements into data in `docs/spec/`.

**Outcome:**
- `targets.yaml`, `scenarios.yaml`, `calibration_targets.yaml`, and one `oracles/AT-xx.yaml` per acceptance case with input, expected value, tolerance and the named wrong answer.
- The numerical parts of AT-48, AT-51 and AT-52 stay OPEN.
- The step reviewer and the owner approve the files, and they are locked.

## 4. Calculation kernels

The pure functions inside the steps, proven by the acceptance cases that bring their own inputs: PD arithmetic, contractual schedule, EAD and CCF, ECL and discounting, S3 floors, stage arithmetic, stock to flow, property indices and REA floors.

**Outcome:**
- AT-02–08, AT-10, AT-11, AT-16, AT-18, AT-25, AT-28, AT-29 and AT-33–42 pass against their oracles.
- Each module has unit tests, including property tests for bounds and identities.

## 5. Run frame (R1–R3, R11)

The pipeline shell: open the run, load and hash-check the inputs, validate and route, seal the run. `cli.py` wires them in order.

**Outcome:**
- On a small input set built by the tests, `stress run` opens and seals a run folder with its manifest.
- Rejected records go to `rejections.parquet` with a reason code, and the §12.2 input controls pass in `tests/controls/`.
- A rerun gives identical output hashes, and regulatory mode blocks.

## 6. Synthetic starting point (O2–O4)

Build the TTC matrices (O2), generate the portfolio with its grades (O3) and freeze the opening allowances (O4), written as one hashed input set.

**Outcome:**
- `inputs/<hash>/` holds the seven datasets.
- AT-01, AT-22, AT-45, AT-46 and the opening part of AT-44 pass.
- R3 accepts every facility: each grade explains its stage.
- The owner approves the input set.

## 7. Scenario and parameters (R4–R6)

Z per segment, country, year and scenario, with the reversion after 2029 (R4). Contractual schedules (R5). Every PD, LGD, prepayment and EAD value per default bucket as a ParameterRecord (R6).

**Outcome:**
- AT-46, AT-47, AT-49, AT-50, AT-51 and AT-52 pass.
- The PD-03 identities hold on every curve, and every PiT row sums to 1 within 1e-10.
- Drivers, schedules, PiT matrices and parameters are written for both scenarios.

## 8. Projection and provisions (R7–R9)

For 2027 to 2029: move grade slices with the year's matrix, derive stages, keep S3 cohorts and replace matured facilities (R7), compute year-end provisions (R8) and charges (R9).

**Outcome:**
- AT-48 passes, and AT-44 holds in each projected year.
- No S3 exposure cures or releases provision.
- Slices, provisions and charges are written for both scenarios, never blended.

## 9. Reports and first full run (R10)

The four v1 reports: starting-point reconciliation, stage migration, parameters and impairment. Rounding happens only here.

**Outcome:**
- `stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core` gives a sealed SYNTHETIC run.
- Reconciliations are within the §12.3 tolerances, and a rerun gives identical output hashes.
- The owner reviews the results, including the first-year charge that comes from O4.

## 10. Variants

The annuity and linear repayment profiles and the AT-35 utilisation sensitivity, each as its own `--variant` run.

**Outcome:**
- Each variant is a separate, labelled run, and the core run is unchanged.
- AT-35 passes as a run.

## Owner inputs

Each step waits only for the inputs it needs. Answers go into the design or the requirements, not only into this plan.

| Input | Before step |
|---|---|
| CLI upgrade; a person runs the protection check | 1 |
| Agreement on design decisions D1–D14, including D5 for S2 after 2029 | 2 |
| ParameterRecord key: include the grade slice, or define "cohort" as the slice | 2 |
| `run_id` kept out of stored rows, or out of the output hashes | 2 |
| Country in the `scenarios` key | 2 |
| Parameter values (N, ρ, k, β, μ, σ, w, CPR_TTC, v) and where they are recorded | 6 |
| SICR horizon: remaining life at each valuation date, or fixed at opening | 6 |
| [architecture.md](architecture.md) §6 items 2–4; whether O4 uses a bullet or the facility's own schedule | 6 |
| PD for a stub final bucket; oracle values of AT-51 and AT-52 | 7 |
| Oracle value of AT-48; provision for the undrawn part of a new S3 cohort | 8 |
| How a variant changes the repayment profile | 10 |

## When a step is done

- Its outcomes are met.
- `uv run pytest`, `uv run lint-imports` and `uv run ruff check` pass.
- The step is reviewed and approved, and its status above is set to Done.
