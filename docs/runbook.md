# Runbook

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
uv run stress run --inputs inputs/514ed0e86e3dc760 --scenarios baseline,adverse --variant core
```

1. The command prints the run ID, the status and two headline lines. Exit code 0 means the run is sealed SYNTHETIC. Exit code 2 means it blocked: the folder is still sealed, with status BLOCKED, and the step, reason code and message are in `manifest.json` under `blocked`.
2. Open `runs/<run_id>/results/reports/stress_report.xlsx` for the results by portfolio, baseline against adverse. Read `runs/<run_id>/run.log` for what each step did and how long it took. `summary.md` (or `uv run stress report --run runs/<run_id>`) gives the headline in text.
3. Check `rejections.parquet`: it is empty for the committed input set. Any row is a rejected record with its reason code.
4. Run `uv run stress rerun --run runs/<run_id>`. It must report "reproduced". Exit code 3 lists the outputs whose hash differs.

### After changing the requirements or the parameter set

1. Requirements changed: run `uv run python -m foundation.transcribe`. Check the diff of `docs/spec/`, then have the `change-reviewer` agent and the owner approve it (GOV-03).
2. Parameter set or generator changed: run `uv run python -m foundation.synth`. It writes a new `inputs/<hash>/` and never edits an old one. Update the `--inputs` path wherever it is used.
3. Run `uv run pytest`. The test `test_generator_is_deterministic_and_matches_the_committed_set` fails until the new input set is in `inputs/`.
4. Compare the old and new results with `uv run stress compare --base runs/<old> --new runs/<new>` (version-change control).

### Gates

- **Test gate:** when Claude Code stops after changing code, `.claude/hooks/test_gate.py` runs pytest, lint-imports and ruff (about three minutes), and blocks the stop until they pass.
- **Pre-commit:** enable once per clone with `git config core.hooksPath tests/githooks`. It runs the same checks and refuses protected paths and run folders.
