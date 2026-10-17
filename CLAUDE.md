# Stress engine (EBA 2027 preparation)

Deterministic engine projecting stage migration, PD, LGD, EAD and provisions for a synthetic €11bn EUR, amortised-cost book over 2027–2029, baseline and adverse.

- Design, leading: `docs/stress-engine-code-flow.html`. Where anything disagrees with it, it wins; raise the conflict rather than pick a side.
- Requirements: `docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md`.
- Repository rules: `docs/architecture.md`.

## Map

- `foundation/`: Part 1, one-off steps O1–O4. Their only products are files in `docs/spec/` and `inputs/<hash>/`.
- `src/stress/`: Part 2, the engine. One package per pipeline step (R1–R11), plus `contracts/` and `cli.py`.
- `docs/spec/`, `inputs/<hash>/`: locked outputs of the one-off steps.
- `runs/<run_id>/`: one folder per run (manifest, config, data, results). See `runs/README.md`.
- `tests/`: `unit/`, `acceptance/` (one test per AT, reads `docs/spec/` oracles), `controls/`.

## Off-limits and locked

- `archive/`: never read, list, search, reference or write it, and never run a tool against it. If something you need seems to be there, ask the user.
- `inputs/bank/`: protected. Never read it.
- `docs/spec/`, `inputs/<hash>/` and `runs/<run_id>/` are never edited by hand. Only one-off code (O1–O4) and the run (R1–R11) write them.

All of these are enforced by `.claude/settings.json` and `.claude/hooks/guard_paths.py`. Don't work around a block; ask.

## Invariants

1. `foundation` and `stress` never import each other. Pipeline steps share only `stress.contracts`; `cli.py` wires them. Checked by `lint-imports`.
2. Every input enters through R2. No later step reads a file.
3. R5 is the only step that creates cash flows. They are contractual and the same in every scenario.
4. One Z per segment, country, year and scenario drives the PD matrix, LGD and prepayment. Nothing is stressed twice.
5. No number is typed by hand. Expected values come from `docs/spec/`; computed values come from code. Never work out an oracle yourself.
6. Missing is never zero. Every input value carries a status, and a missing value blocks the calculation that needs it.
7. Amounts in EUR, rates and probabilities as decimal fractions, float64, unrounded until R10.
8. A run folder is write-once; a rerun is a new folder. Baseline and adverse are never blended.
9. Every test carries `@pytest.mark.at(...)`, `req(...)` or `control(...)`. Requirement and acceptance-case IDs are never reused (requirements §1.3).

## Open values

N, ρ, k, β, μ, σ, w, CPR_TTC and v per segment, and the oracle values of AT-48, AT-51 and AT-52, are supplied by the project owner. Never fill them in yourself.

## Commands

After `uv sync`:

- `uv run pytest`: all tests; `-m at` for acceptance cases only
- `uv run lint-imports`: import contracts
- `uv run ruff check`: lint
- `uv run stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core` (once the engine exists)
