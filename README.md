# Stress engine

Deterministic credit stress-test engine for EBA 2027 preparation. It projects stage migration, PD, LGD, EAD and provisions for a synthetic €11bn EUR, amortised-cost book over 2027–2029, in a baseline and an adverse scenario.

| | |
|---|---|
| **Design (leading)** | [docs/stress-engine-code-flow.html](docs/stress-engine-code-flow.html) |
| **Requirements** | [docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md](docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md) |
| **Repository rules and open items** | [docs/architecture.md](docs/architecture.md) |
| **Assumptions and conflicts** | [docs/assumptions.md](docs/assumptions.md) |
| **How staging works** | [docs/staging/stress-engine-staging.html](docs/staging/stress-engine-staging.html) |
| **How PD curves are built** | [docs/pd-curves/pd-curve-flow.html](docs/pd-curves/pd-curve-flow.html) |
| **Operating the engine** | [docs/runbook.md](docs/runbook.md) |

**Status:** v1 is complete and runs end to end, in synthetic mode only; regulatory mode blocks the run. From here on, work goes into improvements, each on its own branch (see [Making changes](#making-changes)).

Still open with the owner ([architecture §6](docs/architecture.md#6-open-items)):
- Sign-off of the transcribed spec in `docs/spec/`, the input set `inputs/d62d0386f2c5256e/` (with the qualitative SICR triggers; it replaces `514ed0e86e3dc760`) and the full-run results.
- The parameter values (N, ρ, k, β, μ, σ, w, CPR_TTC, v). Claude Code proposed them (requirements §1.5, [assumptions A2](docs/assumptions.md)).
- The oracle values of AT-48, AT-51 and AT-52.

## How the engine works

The code has two parts that share no code:
- **One-off steps** build the synthetic starting point and the test material once.
- **The run pipeline** is the engine:
  1. It reads one input set.
  2. It builds each facility's contractual cash flows from balance, interest rate and maturity.
  3. One Z-score per segment and year moves the TTC rating matrix, the TTC LGD and the prepayment rate with the economy.
  4. EAD at each default date is the contractual balance after prepayment.
  5. Rating grades decide stages, and the run projects and reports provisions.

### Part 1 · One-off: build once, then lock

![One-off steps: O1 transcribes the spec, O2–O4 build the TTC matrices, portfolio and opening allowances](docs/img/01-one-off.svg)

The figure shows two independent chains whose only products are files:
- O1 writes the transcribed spec to `docs/spec/`.
- O2–O4 write the hashed starting point to `inputs/<hash>/`.

The code lives in `foundation/`. It imports nothing from the engine, and the engine imports nothing from it.

### Part 2 · The run pipeline

```
stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core
```

![Run pipeline: R1 open, R2–R3 ingestion, R4–R9 calculation with R7–R9 repeated per year, R10–R11 output](docs/img/02-run-pipeline.svg)

- **Inputs:** every input enters through R2, and nothing enters later.
- **Cash flows:** R5 is the only step that creates them. The contractual schedule is the same in every scenario, so it is built once.
- **Scenario:** R6 applies it, turning each year's Z into PiT matrices, LGDs, prepayment rates and EAD.
- **Yearly loop:** R7–R9 repeat for 2027, 2028 and 2029.
- **Scenarios kept apart:** baseline and adverse run through the same code and are never blended (REG-07).

## Repository layout

This is the layout from the [code flow](docs/stress-engine-code-flow.html#layout), which is leading.

```
stress-engine/
├── foundation/            PART 1 own package, imports no engine code
│   ├── transcribe/        O1
│   ├── matrices/          O2 synthetic TTC PD matrices
│   └── synth/             O3–O4 generator, opening allowances
├── inputs/<hash>/         input set 7 datasets
├── runs/<run_id>/         config, data, results + manifest.json
├── src/stress/            PART 2 the engine
│   ├── cli.py             stress run · stress report
│   ├── contracts/         input schema, keys, value status
│   ├── ingest/            load inputs, hash checks
│   ├── validate/          scope, matrix and grade checks, routing
│   ├── scenario/          indices, Z-score
│   ├── cashflows/         contractual schedule
│   ├── params/            matrix (TTC → PiT), pd, lgd,
│   │                      prepay, ead, terminal, store
│   ├── projection/        grade migration, stage rule
│   ├── ecl/               year-end provisions
│   ├── accounting/        stock to flow
│   ├── report/  capital/  aggregation, reports, REA floor functions
│   └── lineage/           open and seal the run, manifest
├── tests/
│   ├── unit/              one file per module, property tests
│   ├── acceptance/        reads docs/spec/ oracles, one test per AT
│   └── controls/          §12.2 rejections, no imports across parts
├── docs/                  code flow, repo rules, runbook
│   └── spec/              locked requirements, targets, AT oracles
└── archive/               people only Claude Code is blocked
```

The folders marked locked are written only by the one-off code and the run. See [docs/architecture.md](docs/architecture.md) for how that is enforced.

## Setup

```
uv sync
git config core.hooksPath tests/githooks   # once per clone: the pre-commit gate
uv run pytest                         # all tests; -m at for the acceptance cases
uv run lint-imports --cache-dir tests/.import_linter_cache
uv run ruff check
```

## Running

```
uv run stress run --inputs inputs/d62d0386f2c5256e --scenarios baseline,adverse --variant core
uv run stress report --run runs/<run_id>      # print results/reports/summary.md
uv run stress rerun --run runs/<run_id>       # rerun from the manifest; output hashes must match
uv run stress compare --base runs/<a> --new runs/<b>
```

To run it from Jupyter and see each step's intermediate results, open [notebooks/01_full_run_walkthrough.ipynb](notebooks/01_full_run_walkthrough.ipynb) with the `.venv` kernel, or start `uv run jupyter lab` (see [notebooks/README.md](notebooks/README.md)).

A run takes about 25 seconds and writes `runs/<run_id>/` (see [runs/README.md](runs/README.md)). Two files show what happened:

- **`results/reports/stress_report.xlsx`**: the Excel report. Sheets: Summary (key results and charts), Portfolios (the book at end-2026), Results by portfolio (baseline and adverse side by side, with differences), Impairment, Stage migration, Coverage by stage, S3 cohorts, Parameters, Starting point, Checks and Notes. Amounts are in EUR millions. Engine results are written as values (blue) and every derived figure is an Excel formula (black).
- **`run.log`**: every step's facts, checks and timings. The console shows the same lines while the run works; use `-q` for warnings only. Variants: `core` (bullet, fixed CCF), `annuity`, `linear` and `utilisation` (the AT-35 CCF sensitivity). Exit codes: 0 sealed, 2 blocked (the folder is sealed with status BLOCKED and the reason), 3 rerun not reproduced.

To rebuild the one-off material: `uv run python -m foundation.transcribe` (O1, `--check` to compare) and `uv run python -m foundation.synth` (O2–O4, writes a new `inputs/<hash>/` when anything changes).

## Making changes

- **Branches:** each improvement goes on its own branch. Nothing is committed directly to `main`.
- **Rules:** the [design](docs/stress-engine-code-flow.html) leads, and the code rules in [architecture §2](docs/architecture.md#2-code-rules) hold.
- **Tests:** a change that touches a calculation comes with a test that carries a marker, and expected values are read from `docs/spec/`.
- **Gate:** before merging, `uv run pytest`, `uv run lint-imports --cache-dir tests/.import_linter_cache` and `uv run ruff check` must pass. A full run must seal, and `stress compare` against the last run shows the effect.
- **Inputs:** a change to the parameter set or the generator writes a new input set. Never edit an old one; follow [the runbook](docs/runbook.md#after-changing-the-requirements-or-the-parameter-set).
- **Records:** a new assumption, or a conflict with the design, goes into [docs/assumptions.md](docs/assumptions.md).

In Claude Code, `/improve <what to change>` follows these steps, and the `change-reviewer` agent reviews the result.

## License

MIT. See [LICENSE](LICENSE).
