# Repository rules

How this repository is organised and what is enforced. The engine design is in [stress-engine-code-flow.html](stress-engine-code-flow.html), and the [README](../README.md) gives the overview.

## 1. Who writes what

| Folder | Written by | Protection |
|---|---|---|
| `docs/spec/` | O1 (`foundation/transcribe`); requirements text by the project owner | Locked |
| `inputs/<hash>/` | O2–O4 (`foundation/matrices`, `foundation/synth`) | Locked; R2 checks every file's hash |
| `runs/<run_id>/` | R1–R11 | Locked; write-once, sealed by R11 |
| `foundation/`, `src/stress/`, `tests/`, `notebooks/`, `control_room/`, rest of `docs/` | People and Claude Code | Normal review |
| `archive/` | People only | Claude Code fully blocked; not in git |
| `inputs/bank/` | Nobody yet | Claude Code fully blocked; not in git |

"Locked" means Claude Code's Edit and Write tools are denied there. Only code writes these folders, so changing their content means changing the code and rerunning the step. The deny rules also cover shell writes that Claude Code recognises, such as redirects, `tee`, `mv` and `rm`. A script can still write these folders, which is how the one-off steps and the run work.

## 2. Code rules

Checked by `lint-imports`, configured in `pyproject.toml`:

- `foundation` and `stress` never import each other.
- Pipeline steps are independent packages that share only `stress.contracts` and the segment models in `stress.models`, and `cli.py` wires them in order. A step gets another step's output as a table defined in `contracts`, never by importing that step. `stress.models` imports only `contracts`.

Held by the engine and its tests:

- Every input enters through R2. No later step reads a file.
- Optional specification resolution is an R2 preflight before R1 so the resolved settings enter
  run identity. R2 captures those same bytes and applies overrides to in-memory tables only.
- Each segment has its own PD, LGD and prepayment model (6 November 2026, A42): a documented function
  in `src/stress/models/<portfolio>.py` that holds its coefficients. The parameter set and a run
  specification name a model only as `<portfolio>.<function>`, from that closed registry, and only a
  model of the segment's own portfolio, never an import path or coefficients.
- The configurable extension (31 October 2026, A37–A40) can point a segment at another model of its portfolio and can
  adjust performing drawn/undrawn volume before R7. S3 stocks/floors are retained. The R5
  reference schedule remains common; R8 scales reference EAD to current slices. Dynamic is an
  internal option, not a relaxation of the EBA static requirement. See the operational specification.
- R5 is the only step that creates cash flows. They are contractual and the same in every scenario.
- One Z per segment, model, country, year and scenario: the PD model's drives the PD matrix, the LGD model's the LGD and the prepayment model's prepayment. Each value is stressed once, by its own model's Z. The selectable parameter reversion after 2029 (C8), zero prepayment inside the horizon (C15) and trough reading of LGD (C16) are the only departures, and only when selected.
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
- **`/improve`** (`.claude/skills/improve/SKILL.md`) makes one major improvement on its own branch, once the user has approved its scope. The root `CLAUDE.md` sorts small changes from major ones.
  1. Tests first.
  2. The gate.
  3. A full run, compared against the run before the change.
  4. Review.
- **`change-reviewer`** (`.claude/agents/change-reviewer.md`): a read-only reviewer that must approve every major change before it is merged. It returns APPROVE or CHANGES REQUESTED.
- **Test gate** `.claude/hooks/test_gate.py`, a Stop hook: when code under `src/`, `foundation/` or `tests/` has changed, it runs pytest, lint-imports and ruff, and blocks the stop until they pass.
- **Git pre-commit hook** `tests/githooks/pre-commit`: refuses protected paths and run folders, then runs the same three checks. It skips pytest, and checks traceability instead, when every staged file is on the small-change list in the hook. Enable it once per clone with `git config core.hooksPath tests/githooks`.

## 6. Open items

v1 is complete. These items wait on the owner, and until they are settled the engine runs on the assumptions in [assumptions.md](assumptions.md). When one is settled, record the answer in the design or the requirements and remove it here. This is the one list of what waits on the owner: [TODO.md](../TODO.md) holds the work that needs no decision.

1. **Parameter values and oracle values** (requirements §1.5): proposed values are in `foundation/parameter_set.yaml` and await the owner. The AT-48, AT-51 and AT-52 numbers stay open. See [assumptions.md](assumptions.md) A2 and A10.
2. **LGD-01 and LGD-04:** production recovery-model integration remains open (A12). The October 2026 preparation extension adds a separate synthetic single-date recovery diagnostic, without changing core LGD. Confirm the production model and its calibration (requirements §1.5).
3. **Requirement texts to amend.** The owner has decided each of these, but the requirement still says what it said before. `docs/spec/` is written only by O1, which retranscribes once the owner has amended the source and signed it off (GOV-03); the conflict named gives the proposed wording.
   - PD-10 (C9): the owner dropped the √(1−ρ) divisor of the PD-10 shift on 18 October 2026 (D13, A29), which also settles SYN-PAR-09 (A8, C2). PD-10's text still prescribes the divisor and calls Z = 0 the median year. O1 then reruns, and a new input set follows.
   - PD-06, and a note to PD-02 (C10): the part-year bucket is taken pro rata in the ECL.
   - MIG-07's last sentence, SYN-PAR-08 and AT-48 (C11): the qualitative SICR triggers are used.
   - SCN-08, LGD-10 and SYN-PAR-06 (C20): each segment has its own PD, LGD and prepayment model, with its coefficients in the model function.
   - The requirements §15 note that the draft's paragraph references are unverified (C8): they were checked on 18 October 2026. Consider adding the draft's Box 1 to the citations of ECL-04 and ECL-10.
4. **§8.7 opening performing LGD:** used as each segment's reference (mean) TTC LGD (A13). Confirm.
5. **`inputs/bank/`:** protected and not in git. Delete it by hand, or keep it as the future place for real data (OPS-05).
6. **Fail-closed hooks:** the terminal `claude` CLI is 2.1.263. After updating it to 2.1.295 or later, add `"onFailure": "block"` to both hooks so they fail closed (C7). A person then runs the protection check in [runbook.md](runbook.md), and every attempt must be blocked.
7. **Owner sign-offs of the v1 build.** Claude Code's reviewer approved each of these, but the owner has not yet:
   - the transcribed spec in `docs/spec/` (GOV-03);
   - the input set `inputs/5a296ffe0e198705/`, which since 6 November 2026 names each segment's models and holds one matrix file per segment (A42), with the data of `inputs/d62d0386f2c5256e/` (the qualitative SICR triggers, A30) unchanged, and three synthetic scenarios beyond section 6.2 with a description of every scenario (A43);
   - each segment's LGD and prepayment model (A42), which start from the PD model's drivers until they are calibrated;
   - the results of the full core run. The first-year charge that came from O4 is gone since the divisor was dropped; see "Results that need the owner's eye" in [assumptions.md](assumptions.md).
8. **Draft preparation to production:** reconcile the final 2027 package when released, validate the selected terminal convention, supply approved model/benchmark and capital inputs, extend sovereign fallback where needed, establish the complete climate perimeter and approve official template mappings. The user authorised draft-based synthetic examples on 30 October 2026; this does not close model validation or owner numerical sign-offs. See the [implementation register](implementation-status.md).
9. **Readings of the draft (C13–C16):** decide S2 repricing or held, run-off inside the horizon, and the LGD path. The defaults stay the design's, and the other readings are selectable. Together they add €99.3m adverse and €31.1m baseline. A default run does not meet ECL-06: only the held reading does. Whichever stands, record it in the design, and amend ECL-11 (C13) through O1.
10. **NPE calendar (A33):** supply the factors of Article 47c, which could not be retrieved, and the capital team's approval (CAP-09). Only the unsecured 35% of the draft's footnote 75 is sourced.
11. **Sector stress and calibration:** explicit NACE-based segment assignment and supplied sector drivers are available in the configurable extension (A38). Supply and validate sector paths, driver moments and Z calibration from data (A19); none are empirically estimated by this extension. Overrides are hash-bound and sealed as an experiment.
12. **Unmet requirements with no decision:** REG-03, SCP-05, DAT-07, SYN-02, SYN-03, PD-07, LGD-11 and EAD-07, in the [traceability matrix](traceability/traceability-matrix.md). Accept each, or plan it. SCN-03 is no longer among them: it is recorded as deferred under A38, and what it still needs is item 11.
13. **Reproducing on another machine (A36, C18):** decide whether a rerun has to reproduce only on the same machine or within a tolerance, and whether to make `largest_remainder` tie-safe so that every system can compare its book with the committed set.
14. **Assumptions proposed by Claude Code and not yet approved.** Approve or replace each one. Those with their own item above are left out here (A33 is item 10, A36 is item 13).
    - A30: the five settings around the qualitative SICR triggers that the owner's decision of 18 October 2026 did not cover.
    - A31: the LTV path and the average maturity in the reports.
    - A32: the template replica.
    - A34: how the traceability matrix links requirements, and that the authorisation of 30 October 2026 is not read as a local approval date.
    - A35: the readings behind the published benchmarks.
    - A43: the paths and descriptions of the three synthetic scenarios.
    - A44: the readings taken with the input checks of 10 November 2026, among them that a rerun which reproduces a block exits 0 and that a run from a specification carries `+spec` in its name.
    - A45: the four report choices made beside the owner's two decisions on coverage and the EAD profile.
    - A46: the reasons written for six requirements in the traceability matrix, and the hand links that make REG-04, MIG-04 and LGD-08 read `tested`.
    - C6: one opening horizon for both lifetime PDs of the SICR line, which the conflict asks the owner to confirm.
15. **Design sentences that no longer match the build.** The design leads, so each correction needs the owner's approval, as C1, C4 and C5 had on 9 November 2026.
    - R9's card says overlays are "tracked by risk and year", R10's card says nothing feeds the REA floor functions portfolio REA, and the R10 card still speaks of four v1 reports (C22).
    - The R2 to R11 overview says "One command runs both scenarios"; a run holds any scenarios of the set (A43).
    - D1 and C4 count "up to 7 S3 slices": seven is the number of slice names, and one facility holds at most five.
    - R4's "Blocks on" list does not name the provenance block that R1's line now sends there (C5), and the pipeline figure still labels the parameter set "Z weights, ρ, w, k, CCF, CPR" although the Z weights and w moved to the models (A42).
    - The page still opens with "Proposal for agreement · 17 October 2026".
16. **PD-01 is met in part (C23).** The input contract has no opening 12-month PiT PD, no observation date for the grade and no default-event definition, and R3 does not check that one obligor's facilities share a grade. Decide whether the contract gains them or the requirement text changes.
