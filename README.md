# Stress engine

Deterministic credit stress-test engine for EBA 2027 preparation. It projects stage migration, PD, LGD, EAD and provisions for a synthetic €11bn EUR, amortised-cost book over 2027–2029, in a baseline and an adverse scenario.

| | |
|---|---|
| **Design (leading)** | [docs/stress-engine-code-flow.html](docs/stress-engine-code-flow.html) |
| **Requirements** | [docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md](docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md) |
| **Repository rules** | [docs/architecture.md](docs/architecture.md) |

**Status:** structure only; no engine code yet. v1 runs in synthetic mode only, and regulatory mode blocks the run. The synthetic parameter values (N, ρ, k, β, μ, σ, w, CPR_TTC, v) and the oracle values of three acceptance cases are still to be supplied (requirements §1.5).

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
uv run pytest
uv run lint-imports
```

## License

MIT. See [LICENSE](LICENSE).
