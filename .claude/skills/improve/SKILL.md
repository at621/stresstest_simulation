---
name: improve
description: Make one improvement to the working stress engine or its one-off steps (a fix, a new capability, a refactor, a parameter or input-set change) on its own branch. Tests first, then the gate, then a full run compared against the last one, then approval by the change-reviewer agent. Use when asked to fix, change, extend or refactor the engine (for example "/improve add a CSV export of the charges").
---

# Make one improvement

The argument says what to change. v1 is complete and in use, so every change starts from a working, tested engine and must leave it that way. The design (`docs/stress-engine-code-flow.html`) leads. If the change would depart from it, or another document disagrees with it, stop and tell the user before building.

## 1. Read before writing

1. The design sections for the R or O steps the change touches, and the decisions D1–D14 they cite.
2. The requirements involved, in `docs/spec/EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md`.
3. `docs/architecture.md` §2 (code rules) and §6 (open items), `docs/assumptions.md`, and the `CLAUDE.md` in the step's folder where there is one (`src/stress/params/`, `src/stress/ecl/`).
4. The existing code and tests of the steps involved.

If the change needs an owner input that is still open (architecture §6) and `docs/assumptions.md` has no approved or explicitly authorised assumption for it, stop and ask.

Never touch the protected folders listed in the root `CLAUDE.md`. `docs/spec/`, `inputs/<hash>/` and `runs/<run_id>/` are written only by code: rerun O1 (`uv run python -m foundation.transcribe`), O2–O4 (`uv run python -m foundation.synth`) or the engine instead of editing them.

## 2. Branch and baseline

- Start a dedicated branch from the current main line, never `main` itself.
- Before changing anything, run the engine once (`uv run stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core`) and note the run folder. It is the baseline for the comparison in step 5.

## 3. Tests first

- A fix starts with a test that fails without it. A new capability starts with tests of what it must do.
- Acceptance cases live in `tests/acceptance/test_at_xx.py`, one per AT, marked `@pytest.mark.at("AT-xx")`. Expected values, tolerances and named wrong answers come from `docs/spec/oracles/AT-xx.yaml` through `tests/support.py`; never type an oracle value into a test.
- Unit and property tests go in `tests/unit/` marked `req(...)`; §12.2 controls in `tests/controls/` marked `control(...)`. A test without a marker, or with an ID the requirements do not contain, fails collection.
- If a case's numbers are OPEN in the spec (AT-48, AT-51, AT-52 today), test the rule and leave the numbers to the owner.

## 4. Build

- Write the code in the step's own package. Steps share only `stress.contracts`; a new table between steps is a `TableSpec` there. `cli.py` is the only module that wires steps.
- Amounts in EUR, rates as decimal fractions, float64, unrounded until R10. Missing is never zero: block the calculation that needs a missing value.
- A parameter-set or generator change writes a new input set: follow `docs/runbook.md` "After changing the requirements or the parameter set", and update the current input-set hash wherever it is named.

## 5. Gate and comparison

Run all three and fix every failure:

```
uv run pytest
uv run lint-imports --cache-dir tests/.import_linter_cache
uv run ruff check
```

Then run the engine again and compare it with the baseline run:

```
uv run stress compare --base runs/<baseline> --new runs/<new>
```

- If the change is not meant to alter results (a refactor, a report or tooling change), the results must match. Explain any difference or fix it.
- If it is meant to alter results, read `results/reports/summary.md` and check that the differences are the intended ones, and only those.

## 6. Review and record

1. Ask the `change-reviewer` agent to review the change. Give it what the change is meant to do, the files you changed, and the two run folders. Address every finding marked blocking, then ask again.
2. Record any new assumption in `docs/assumptions.md` and any conflict with the design in its "Conflicts" section. If an owner item in `docs/architecture.md` §6 is resolved or a new one arises, update the list.
3. When behaviour or commands change, update `README.md` and `docs/runbook.md`.
4. Tell the user what changed, the gate outcome and the effect on results. Merge into `main` only with their explicit permission.
