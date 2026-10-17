# Stress engine (EBA 2027 preparation)

A deterministic credit stress-test engine. It projects stage migration, PD, LGD, EAD and provisions for a synthetic €11bn EUR, amortised-cost book over 2027–2029, in a baseline and an adverse scenario.

## Where to look

| For | Read |
|---|---|
| What to build next | `docs/plan.md` |
| How the engine works | `docs/stress-engine-code-flow.html`, the design |
| What the engine must do, and the acceptance cases | `docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md` |
| Code and repository rules | `docs/architecture.md` |
| Rules for one step | the `CLAUDE.md` in that step's folder, where there is one |

The design leads. If another document disagrees with it, follow the design and tell the user about the conflict so it can be resolved.

## How to work

- Build in the step order of `docs/plan.md`. When a step's outcomes are met, set its status to Done.
- Do all new work on a dedicated branch, never directly on `main`. Merge into `main` only when the user explicitly permits it.
- Keep to the code rules in `docs/architecture.md` §2.
- When something is unclear or a tool call is blocked, ask instead of guessing or working around it.

## Layout

- `foundation/`: the one-off steps O1–O4. They build the spec data and the synthetic input set once, and their only products are files.
- `src/stress/`: the engine. One package per run step R1–R11, plus `contracts/` for the tables the steps share and `cli.py`, which wires the steps.
- `tests/`: `unit/`, `acceptance/` (one test per AT) and `controls/`.
- `docs/spec/`, `inputs/<hash>/`, `runs/<run_id>/`: written only by code; see below.

## Protected folders

| Path | Rule |
|---|---|
| `archive/` | Never read, list, search, write or reference it, and never run a tool against it. If something you need seems to be there, ask. |
| `inputs/bank/` | Never read it. |
| `docs/spec/`, `inputs/<hash>/`, `runs/<run_id>/` | Never edit by hand. Only the one-off steps (O1–O4) and the run (R1–R11) write them. |

`.claude/settings.json` and `.claude/hooks/guard_paths.py` enforce these rules.

## Commands

After `uv sync`:

- `uv run pytest`: all tests; add `-m at` for acceptance cases only
- `uv run lint-imports`: import rules
- `uv run ruff check`: lint
- `uv run stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core`: a full run, once the engine exists
