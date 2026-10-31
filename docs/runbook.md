# Runbook

## Calculation integrity

R2 rejects invalid boolean/date representations and infinite numeric values. R3 rejects
non-finite or out-of-domain synthetic parameters. R8 compares facility parameter coverage
against the R5 schedule, including the last bucket; missing data never becomes zero ECL.
Resolve a blocked input by rebuilding a new input set, not by editing a sealed run.

## Protection check

Run this after setting up the repo, after any change to `.claude/`, and after upgrading Claude Code.

### Archive and `inputs/bank/`

1. Outside Claude Code, create `archive/canary.md` containing a unique marker, for example `CANARY-7f3e2a`. Do the same in `inputs/bank/canary.md`.
2. Start Claude Code from the repo root and run `/permissions`. Check that the deny rules from `.claude/settings.json` are listed.
3. Ask Claude Code to try each of the following and report what happened:
   - read `archive/canary.md`;
   - search the whole repo for the marker with the Grep tool;
   - list `archive/` with the Glob tool;
   - run `cat archive/canary.md` and `rg <marker>` from the repo root in Bash;
   - run `Get-Content archive\canary.md` in PowerShell;
   - run `git log -p` (once the repo is in git);
   - ask a subagent to read the file.
4. Every attempt must be blocked or return nothing. If the marker appears anywhere in Claude's output, the protection has a gap. Fix it before putting anything real in `archive/`.
5. Delete the canary files.

### Locked folders

Ask Claude Code to add a line to `docs/spec/README.md`, a file under `inputs/<hash>/` and a file under `runs/<run_id>/`. Each Edit or Write must be denied.

## Engine runs

### A full run

```
uv run stress run --inputs inputs/d62d0386f2c5256e --scenarios baseline,adverse --variant core
```

Runs need input set `d62d0386f2c5256e` or later: since 18 October 2026 the input contract carries `credit_status_date`, and the engine blocks at R2 on the older sets. `stress rerun` of a run made on them blocks for the same reason.

1. The command prints the run ID, the status and two headline lines. Exit code 0 means the run is sealed SYNTHETIC. Exit code 2 means it blocked: the folder is still sealed, with status BLOCKED, and the step, reason code and message are in `manifest.json` under `blocked`.
2. Open `runs/<run_id>/results/reports/stress_report.xlsx` for the results by portfolio, baseline against adverse. Read `runs/<run_id>/run.log` for what each step did and how long it took. `summary.md` (or `uv run stress report --run runs/<run_id>`) gives the headline in text.
3. Check `rejections.parquet`: it is empty for the committed input set. Any row is a rejected record with its reason code.
4. Run `uv run stress rerun --run runs/<run_id>` on the machine that made the run (C18). It must report "reproduced". Exit code 3 lists the outputs whose hash differs.

### After changing the requirements or the parameter set

1. Requirements changed: run `uv run python -m foundation.transcribe`. Check the diff of `docs/spec/`, then have the `change-reviewer` agent and the owner approve it (GOV-03).
2. Parameter set or generator changed: run `uv run python -m foundation.synth` on the machine that built the current input set. The hash depends on the operating system and the CPU's BLAS kernel, and a rebuild elsewhere can give a different book, not only different bytes (A36). It writes a new `inputs/<hash>/` and never edits an old one. Update the `--inputs` path wherever it is used.
3. Run `uv run pytest`. The test `test_the_committed_set_is_what_the_generator_produces` fails until the new input set is in `inputs/`. It runs on Windows only and passes only under the kernel that built the set, so CI cannot catch a missing rebuild.
4. Compare the old and new results with `uv run stress compare --base runs/<old> --new runs/<new>` (version-change control). It prints the impairment differences and keeps the full report in `runs/comparisons/<old>__<new>/`: `summary.md`, the differences in impairment, stage stocks and coverage, PD and LGD, and `comparison.json`, which ties them to both runs. Sealed runs are write-once, so the report sits beside them; `--out` chooses another folder outside them.

### Gates

- **Test gate:** when Claude Code stops after changing code, `.claude/hooks/test_gate.py` runs pytest, lint-imports and ruff (about three minutes), and blocks the stop until they pass.
- **Pre-commit:** enable once per clone with `git config core.hooksPath tests/githooks`. It runs the same checks and refuses protected paths and run folders.
- **Traceability:** after changing a test marker, an ID named in code, an acceptance docstring, `docs/assumptions.md` or `docs/traceability/requirement-status.yaml`, run `uv run python -m tests.traceability` to regenerate [the matrix](traceability/traceability-matrix.md) and [the source register](source-register/source-register.md); a control test fails until they are current, and `--check` compares without writing.

### Draft preparation and replay

Use [the example commands](examples/README.md) to generate a synthetic analysis sidecar and
pass it with `--analysis`. R2 validates its schema/status/input-set binding and seals its exact
bytes. Omitted sections are reported as NOT_PROVIDED; explicitly supplied incomplete sections
block. `analysis_readiness.csv` records input approval, draft status, model status and remaining
bank/owner gates. An approval record is evidence, not a digital signature or a newly granted approval.

`--terminal-treatment z` is the default. `--terminal-treatment parameters` instead linearly
reverts transition probabilities and LGD from adverse 2029 to baseline 2029 over six years.
Baseline stays flat. End-2029 S1 uses the resulting 2030 PD and LGD, while the default retains
the existing product-loss-rate interpolation. Prepayment retains its Z convention. Compare
the two sealed runs to quantify the sensitivity; do not mix them into one reported scenario.

`--s2-treatment held`, `--horizon-runoff replaced` and `--lgd-path trough` are selectable readings
of the draft (C14–C16). The defaults stay the design's. A run with any of them carries a tag in its
run ID, for example `-core+held-`, and is named in its headline, `summary.md`, workbook, manifest and
`analysis_readiness.csv`. `--horizon-runoff replaced` works on bullet schedules only and blocks at R5
on the `annuity` and `linear` variants. Compare it with a default run; do not report it as the core run.

`stress report`, `compare` and `rerun` reject tampered sealed artifacts. Strict rerun first
checks source contents and Python/package versions, then reads the verified saved `data/`
snapshot, including the optional sidecar. It does not require the original input folder.
Hashes detect accidental alteration; manifests are not cryptographic attestations from an approver.

For the complete local CI gate, run `uv run python tests/ci_gate.py`. It checks O1 drift,
Ruff, import boundaries and all tests. CI runs the same entry point. Numerical approval
oracles remain open until supplied by the owner; passing automated checks does not close them.
