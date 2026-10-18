# Repository rules

How this repository is organised and what is enforced. The engine design is in [stress-engine-code-flow.html](stress-engine-code-flow.html), and the [README](../README.md) gives the overview.

## 1. Who writes what

| Folder | Written by | Protection |
|---|---|---|
| `docs/spec/` | O1 (`foundation/transcribe`); requirements text by the project owner | Locked |
| `inputs/<hash>/` | O2–O4 (`foundation/matrices`, `foundation/synth`) | Locked; R2 checks every file's hash |
| `runs/<run_id>/` | R1–R11 | Locked; write-once, sealed by R11 |
| `foundation/`, `src/stress/`, `tests/`, `notebooks/`, rest of `docs/` | People and Claude Code | Normal review |
| `archive/` | People only | Claude Code fully blocked; not in git |
| `inputs/bank/` | Nobody yet | Claude Code fully blocked; not in git |

"Locked" means Claude Code's Edit and Write tools are denied there. Only code writes these folders, so changing their content means changing the code and rerunning the step. The deny rules also cover shell writes that Claude Code recognises, such as redirects, `tee`, `mv` and `rm`. A script can still write these folders, which is how the one-off steps and the run work.

## 2. Code rules

Checked by `lint-imports`, configured in `pyproject.toml`:

- `foundation` and `stress` never import each other.
- Pipeline steps are independent packages that share only `stress.contracts`, and `cli.py` wires them in order. A step gets another step's output as a table defined in `contracts`, never by importing that step.

Held by the engine and its tests:

- Every input enters through R2. No later step reads a file.
- R5 is the only step that creates cash flows. They are contractual and the same in every scenario.
- One Z per segment, country, year and scenario drives the PD matrix, LGD and prepayment. Nothing is stressed twice.
- Missing is never zero. Every input value carries a status, and a missing value blocks the calculation that needs it.
- Amounts are in EUR, and rates and probabilities are decimal fractions, held as float64 and unrounded until R10.
- A run folder is write-once, and a rerun is a new folder. Baseline and adverse are never blended.
- No number is typed by hand. Expected values come from `docs/spec/`, and computed values come from code.
- Every test carries `@pytest.mark.at(...)`, `req(...)` or `control(...)`. Requirement and acceptance-case IDs are never reused (requirements §1.3).

## 3. Runs

One folder per run, holding the manifest, the config used, a copy of the input set and the results. See [runs/README.md](../runs/README.md).

## 4. Archive

`archive/` is the shelf for material people keep but that must not feed the build. Only people put things in or take them out, and anything the build needs stays outside it.

On native Windows, Claude Code's sandbox doesn't run, so protection uses several layers:

1. **Deny rules** in `.claude/settings.json` for Read and Edit on `/archive` and `/archive/**`. On a best-effort basis these also cover Grep, Glob, `@` mentions, the file open in VS Code, and simple shell commands such as `cat`. A leading `/` means the project root, so start Claude Code from the repo root.
2. **Hook** `.claude/hooks/guard_paths.py`, run before every tool call, including calls by subagents.
   - It blocks any call whose path, glob or command names `archive` as a path segment, regardless of case or slash direction.
   - It also blocks `git grep`.
3. **Git and search:**
   - `archive/` is in `.gitignore`, so git never tracks or shows it. `archive/** -diff` in `.gitattributes` is a second guard in case the folder is ever force-added.
   - `.ignore` keeps ripgrep out when a search starts from the repo root.
4. **Tool excludes:** ruff and pytest skip `archive/`.
5. **CLAUDE.md** says the archive is off-limits and to ask instead.

`inputs/bank/` gets the same treatment.

**Remaining gaps:**
- This is not an OS-level block. A script that walks the whole tree could still read the archive.
- The hook is deliberately strict, so a command that merely mentions `archive` is also blocked.

Check the protection with [runbook.md](runbook.md) after any change to `.claude/`.

## 5. Claude Code setup

- **CLAUDE.md files:** at the root, plus one each in `src/stress/params/` and `src/stress/ecl/`. Those two list the "apply once" rules for R6 and R8.
- **`.claude/settings.json`:** deny rules for the archive, `inputs/bank/` and the locked folders, and the two hooks below. The hooks run with `py -3 -I`, so they work under any active virtualenv.
- **The guard hook** `.claude/hooks/guard_paths.py`, before every tool call.
- **`/improve`** (`.claude/skills/improve/SKILL.md`) makes one improvement on its own branch:
  1. Tests first.
  2. The gate.
  3. A full run, compared against the run before the change.
  4. Review.
- **`change-reviewer`** (`.claude/agents/change-reviewer.md`): a read-only reviewer that must approve every change before it is merged. It returns APPROVE or CHANGES REQUESTED.
- **Test gate** `.claude/hooks/test_gate.py`, a Stop hook: when code under `src/`, `foundation/` or `tests/` has changed, it runs pytest, lint-imports and ruff, and blocks the stop until they pass.
- **Git pre-commit hook** `.githooks/pre-commit`: refuses protected paths and run folders, then runs the same three checks. Enable it once per clone with `git config core.hooksPath .githooks`.

## 6. Open items

v1 is complete. These items wait on the owner, and until they are settled the engine runs on the assumptions in [assumptions.md](assumptions.md). When one is settled, record the answer in the design or the requirements and remove it here.

1. **Parameter values and oracle values** (requirements §1.5): proposed values are in `foundation/parameter_set.yaml` and await the owner. The AT-48, AT-51 and AT-52 numbers stay open. See [assumptions.md](assumptions.md) A2 and A10.
2. **LGD-01 and LGD-04:** kept for later production work and not built (A12). Confirm, or remove them (requirements §1.5).
3. **SYN-PAR-09 (opening allowances):** "PD curves from the TTC matrix (Z = 0)". Under PD-10 the PiT matrix at Z = 0 is not the TTC matrix. Built with the TTC matrix itself (A8, C2). Confirm.
4. **§8.7 opening performing LGD:** used as each segment's reference (mean) TTC LGD (A13). Confirm.
5. **`inputs/bank/`:** protected and not in git. Delete it by hand, or keep it as the future place for real data (OPS-05).
6. **Fail-closed hooks:** the terminal `claude` CLI is 2.1.263. After updating it to 2.1.295 or later, add `"onFailure": "block"` to both hooks so they fail closed (C7). A person then runs the protection check in [runbook.md](runbook.md), and every attempt must be blocked.
7. **Owner sign-offs of the v1 build.** Claude Code's reviewer approved each of these, but the owner has not yet:
   - the transcribed spec in `docs/spec/` (GOV-03);
   - the input set `inputs/514ed0e86e3dc760/`;
   - the results of the first full core run, including the first-year charge that comes from O4 (see "Results that need the owner's eye" in [assumptions.md](assumptions.md)).
