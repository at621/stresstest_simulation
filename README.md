# Stress engine

Deterministic credit stress-test engine for EBA 2027 preparation. It projects stage migration, PD, LGD, EAD and provisions for a synthetic €11bn EUR, amortised-cost book over 2027–2029, in a baseline and an adverse scenario.

**Goals:**

1. **EBA 2027:** meet the exercise's requirements for projecting credit losses and provisions.
2. **Dynamic assumptions:** enable projections in which the balance sheet changes under the scenario, as an alternative to the static EBA approach.
3. **Multiple portfolios:** enable new portfolios to be added without new calculation logic.
4. **Portfolio-specific macro models:** enable the use of a different macro model for each portfolio, as an option.
5. **Clear inputs and configuration:** define every input and setting in one specification.
6. **Ad hoc crisis scenarios:** enable new crisis scenarios to be defined and run without changing the solution.

| | |
|---|---|
| **Design (leading)** | [docs/stress-engine-code-flow.html](docs/stress-engine-code-flow.html) |
| **Requirements** | [docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md](docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md) |
| **Repository rules and open items** | [docs/architecture.md](docs/architecture.md) |
| **Assumptions and conflicts** | [docs/assumptions.md](docs/assumptions.md) |
| **How staging works** | [docs/staging/stress-engine-staging.html](docs/staging/stress-engine-staging.html) |
| **How PD curves are built** | [docs/pd-curves/pd-curve-flow.html](docs/pd-curves/pd-curve-flow.html) |
| **Operating the engine** | [docs/runbook.md](docs/runbook.md) |
| **Control room** | [control_room/README.md](control_room/README.md) |
| **Traceability matrix** | [docs/traceability/traceability-matrix.md](docs/traceability/traceability-matrix.md), regenerated with `uv run python -m tests.traceability` |

The engine supports optional dynamic performing volumes, named crisis scenarios,
per-segment linear/nonlinear/external-score macro models, and portfolio reporting mappings.
Use the [input and run specification](docs/eba-2027-review/input-and-run-specification.md) as
the operational reference. Static exposure is the default.

```
uv run stress run --specification docs/examples/configurable-projection.yaml
uv run python -m foundation.synth package --source <prepared-directory> --out inputs
```

The example supplies illustrative assumptions, not forecasts or approved models. Dynamic growth
scales existing facility prototypes; fresh origination vintages, sales, write-offs and cures are
not implemented. Packaging preserves supplied datasets and records pending owner approval.

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

Calculation controls reject malformed booleans/dates, non-finite scenario values and invalid
synthetic parameter domains. Facility ECL inputs must cover exactly the independent R5
contractual schedule; a missing middle or final bucket blocks the run.

Optional preparation analyses use the June 2026 EBA draft and explicit synthetic model inputs.
The [runnable example](docs/examples/README.md) covers benchmark selection, recovery LGD,
capital, separate climate, reporting mappings and reverse-loss diagnostics. Add
`--terminal-treatment parameters` for a separate linear-parameter reversion sensitivity.
`--s2-treatment held`, `--horizon-runoff replaced` and `--lgd-path trough` select the draft's reading
instead of the design's default (see [conflicts C14 to C16](docs/assumptions.md)).
These features do not enable regulatory submissions; the readiness report records the open gates.

```
uv run stress run --inputs inputs/d62d0386f2c5256e --scenarios baseline,adverse --variant core
uv run stress report --run runs/<run_id>      # print results/reports/summary.md
uv run stress rerun --run runs/<run_id>       # rerun from the manifest; output hashes must match
uv run stress compare --base runs/<a> --new runs/<b>
```

`stress compare` keeps its report in `runs/comparisons/<a>__<b>/` (see the [runbook](docs/runbook.md)). Report, compare and rerun verify sealed input/output hashes before reading them. Rerun uses
the saved `data/` files and checks source-content and runtime identity. CI runs the locked
environment, regression suite, import boundaries, lint and generated-spec drift check.

Input sets must include `credit_status_date`. Runs and replays using input sets without this field block at R2; see the [runbook](docs/runbook.md) for input-set compatibility.

To run it from Jupyter and see each step's intermediate results, open [notebooks/01_full_run_walkthrough.ipynb](notebooks/01_full_run_walkthrough.ipynb) with the `.venv` kernel, or start `uv run jupyter lab` (see [notebooks/README.md](notebooks/README.md)).

A run takes about 25 seconds and writes `runs/<run_id>/` (see [runs/README.md](runs/README.md)). Two files show what happened:

- **`results/reports/stress_report.xlsx`**: the Excel report. Sheets: Summary (key results and charts), Portfolios (the book at end-2026), Results by portfolio (baseline and adverse side by side, with differences), Impairment, Stage migration, Coverage by stage, S3 cohorts, Parameters, Starting point, Checks and Notes. Amounts are in EUR millions. Engine results are written as values (blue) and every derived figure is an Excel formula (black).
- **`run.log`**: every step's facts, checks and timings. The console shows the same lines while the run works; use `-q` for warnings only. Variants: `core` (bullet, fixed CCF), `annuity`, `linear` and `utilisation` (the AT-35 CCF sensitivity). Exit codes: 0 sealed, 2 blocked (the folder is sealed with status BLOCKED and the reason), 3 rerun not reproduced.

To rebuild the one-off material: `uv run python -m foundation.transcribe` (O1, `--check` to compare) and `uv run python -m foundation.synth` (O2–O4, writes a new `inputs/<hash>/` when anything changes, and that includes the machine: see A36 in [docs/assumptions.md](docs/assumptions.md)).

## Control room

The control room is one page that takes a run from its files to its results in four steps. Every action on it is an engine or one-off command, and every verdict is the engine's own.

```
uv run python control_room/server.py
```

This opens <http://127.0.0.1:8770>.

The page opens on one of two datasets, and the setting is `small`:

| Setting | Input set | Holds | A run needs | Use it for |
|---|---|---|---:|---|
| `small` (default) | `inputs/70a9337b7d75f668` | 1,002 facilities, about €1.2bn of GCA | about 0.55 GB | Trying the page. Its results cannot stand in for the full book's. |
| `large` | `inputs/d62d0386f2c5256e` | 10,000 facilities, €11bn of GCA | about 1.7 GB | The full book the requirements describe. |

To change it, pass `--dataset`, or set the `DATASET` environment variable, which `--dataset` overrides:

```
uv run python control_room/server.py --dataset large
```

The setting belongs to the page. `stress run` names its input set with `--inputs`, and the `DATASET` variable does not affect it.

| Step | What you do there |
|---|---|
| **1 Files and settings** | See the seven files a run needs and what each must contain, replace any of them, choose the scenarios and set the run's options. The engine's sanity checks run here without calculating anything. |
| **2 Review the files** | View each table, rating transition matrix, scenario path and parameter. |
| **3 Run** | See what will run, start it and follow its progress. |
| **4 Outcomes** | Read the figures and charts, download the workbook, check that the run reproduces, and compare it with another run. |

A run started here is an ordinary sealed folder under `runs/`, the same as one started in a terminal. See the [control room's README](control_room/README.md) for adding files by hand, scenarios and how each action maps to the engine.

### On Heroku

The control room can also be hosted as a Heroku web app: `Procfile` starts it. A hosted page has no sign-in, so anyone with its address can use it, and it answers over https only.

```
heroku create <app-name>
git push heroku <branch>:main
```

Heroku gets both datasets and follows the same setting, so the app starts on `small`. To move it to `large`, resize the dyno first, then set a config var:

```
heroku ps:type performance-m
heroku config:set DATASET=large
```

Two limits shape how to use it:

- **Memory:** a `small` run with two scenarios needs about 0.55 GB, slightly over a Basic dyno's 0.5 GB quota but well under the 1 GB where Heroku stops it. A `large` run needs about 1.7 GB, so Heroku stops it on a Basic dyno.
- **Files do not last:** Heroku clears the app's files at every deploy and restart, and at least once a day. Runs and anything added on the page go with them, so download the workbook to keep a result.

Use synthetic data only. See [Hosting on Heroku](docs/runbook.md#hosting-on-heroku) in the runbook.

## Making changes

- **Branches:** each improvement goes on its own branch. Nothing is committed directly to `main`.
- **Size:** a small change, such as page wording or a document, needs only the relevant tests and a look at the result. A major change, meaning anything that touches the engine, the inputs or what the engine is said to do, needs the owner's approval of its scope first and then follows the steps below. [CLAUDE.md](CLAUDE.md) has the exact line between them.
- **Rules:** the [design](docs/stress-engine-code-flow.html) leads, and the code rules in [architecture §2](docs/architecture.md#2-code-rules) hold.
- **Tests:** a change that touches a calculation comes with a test that carries a marker, and expected values are read from `docs/spec/`.
- **Gate:** before merging a major change, `uv run pytest`, `uv run lint-imports --cache-dir tests/.import_linter_cache` and `uv run ruff check` must pass. A full run must seal, and `stress compare` against the last run shows the effect.
- **Inputs:** a change to the parameter set or the generator writes a new input set. Never edit an old one; follow [the runbook](docs/runbook.md#after-changing-the-requirements-or-the-parameter-set).
- **Records:** a new assumption, or a conflict with the design, goes into [docs/assumptions.md](docs/assumptions.md).

In Claude Code, `/improve <what to change>` follows these steps, and the `change-reviewer` agent reviews the result.

## License

MIT. See [LICENSE](LICENSE).
