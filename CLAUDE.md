# Stress engine (EBA 2027 preparation)

A deterministic credit stress-test engine. It projects stage migration, PD, LGD, EAD and provisions for a synthetic €11bn EUR, amortised-cost book over 2027–2029, in a baseline and an adverse scenario.

v1 is complete and working. The work now is improving it, not building it: every change starts from a working, tested engine and must leave it that way.

## Where to look

| For | Read |
|---|---|
| How the engine works | `docs/stress-engine-code-flow.html`, the design |
| What the engine must do, and the acceptance cases | `docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md` |
| Code and repository rules; open items awaiting the owner | `docs/architecture.md` (§2 and §6) |
| Assumptions taken and conflicts between documents | `docs/assumptions.md` |
| Running, rerunning and rebuilding inputs | `docs/runbook.md` |
| Rules for one step | the `CLAUDE.md` in that step's folder, where there is one |
| Items to fix or settle in the future, each with its open decisions and steps | `TODO.md` at the root |

The design leads. If another document disagrees with it, follow the design and tell the user about the conflict so it can be resolved.

## How to work

- Do each improvement on its own branch, never directly on `main`. Merge into `main` only when the user explicitly permits it.
- Use `/improve` for a change to the engine or the one-off steps: tests first, then the gate, then a full run compared against the last one, then review by `change-reviewer`.
- Keep to the code rules in `docs/architecture.md` §2. A change that alters results must say so, with `stress compare` output; a change that is not meant to alter results must reproduce them.
- Record any new assumption, or conflict with the design, in `docs/assumptions.md`. When behaviour or commands change, update `README.md` and `docs/runbook.md` to match. A change that departs from the design needs the user's agreement first, and the design is updated with it.
- When something is unclear or a tool call is blocked, ask instead of guessing or working around it.
- Never add a folder at the repository root without the user's permission. This includes folders a tool creates as a side effect, such as a test or cache folder: ask first, or configure the tool to write inside an existing folder.
- Keep each document together with everything that belongs to it in its own folder under `docs/`. The technical implementation document lives in `docs/technical-implementation/`: its markdown source, the PDF made from it, `images/` and `figure-sources/` all stay in that folder, and nothing of it goes anywhere else.

## Layout

- `foundation/`: the one-off steps O1–O4. They build the spec data and the synthetic input set once, and their only products are files.
- `src/stress/`: the engine. One package per run step R1–R11, plus `contracts/` for the tables the steps share and `cli.py`, which wires the steps.
- `tests/`: `unit/`, `acceptance/` (one test per AT) and `controls/`.
- `notebooks/`: Jupyter notebooks that start runs through `stress.cli` and read sealed runs back; shared helpers in `nbtools.py`. See `notebooks/README.md`.
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
- `uv run lint-imports --cache-dir tests/.import_linter_cache`: import rules; the option keeps its cache out of the root
- `uv run ruff check`: lint
- `uv run stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core`: a full run (current input set `514ed0e86e3dc760`); `stress report`, `stress rerun` and `stress compare` read sealed runs
- `uv run python -m foundation.transcribe` (O1) and `uv run python -m foundation.synth` (O2–O4): rebuild the one-off material
