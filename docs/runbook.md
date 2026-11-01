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

### Configurable portfolios, models and crises

Read the complete [input and run specification](eba-2027-review/input-and-run-specification.md).
Start from `docs/examples/configurable-projection.yaml`: it combines a third named crisis,
a nonlinear consumer model, a separate terminal policy and annual dynamic volume assumptions.
Run it with `uv run stress run --specification docs/examples/configurable-projection.yaml`.
Place calculation settings in the YAML; only `--quiet` and `--runs-dir` may accompany it.

The file is bound to the immutable base input hash. Its exact bytes and resolved inputs are
sealed with the run. `stress rerun --run runs/<run_id>` reads the sealed copy even after the
original YAML is removed. Read `effective_specification.json`, `macro_models.csv`,
`analysis_readiness.csv` and, for dynamic mode, `exposure_movements.csv` and `dynamic_books.csv`.
Complete runoff is reported as zero stock. The static EBA template replica is not applicable
to dynamic runs and is omitted. Default commands still use static exposure.

New portfolios use the same five tables and two documents as existing ones. Prepare them,
then run `uv run python -m foundation.synth package --source <prepared-directory> --out inputs`.
Supply a reporting class for each new segment. The package command does not generate or
recalibrate loans and does not grant approval. Model calibration, official inputs and final
regulatory acceptance remain separate dependencies.

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
5. A new full input set also changes what Heroku would host, and a run of it there is stopped for lack of memory. Point `FULL` in `control_room/small_set.py` at the new set and run that script to rebuild the sample. Add lines to `.slugignore` for the new full set and the old sample. Update both hashes and the sample's figures in A41 of [the assumptions](assumptions.md), the sample's hash in [Hosting on Heroku](#hosting-on-heroku), and its figures in `README.md`. Then stage the new sets and run `uv run pytest control_room`, which checks this: the gate does not.

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

## Control room

`uv run python control_room/server.py` opens the page on this machine, and [its README](../control_room/README.md) covers the page itself. Its tests are not part of the gate: run `uv run pytest control_room`, which takes about two and a half minutes.

### Hosting on Heroku

Heroku hosts the control room as a web app. `Procfile` starts it. `.python-version` keeps it on Python 3.12, the version the lock file and the tests use. Heroku receives committed files only, so nothing git ignores, including `runs/`, reaches it.

1. Create the app.

   ```
   heroku create <app-name>
   ```

2. Deploy. A new app gets a Basic dyno, which is enough for the sample.

   ```
   git push heroku <branch>:main
   ```

3. Open `https://<app-name>.herokuapp.com`. Start a run, and check that its headline matches a local run of `inputs/70a9337b7d75f668`.

**No sign-in.** Anyone with the address can use the page: start runs, add files, approve input sets and read results.

**The hosted input set.** Heroku deploys `inputs/70a9337b7d75f668` alone, because `.slugignore` leaves every other set out. Heroku applies that file when it builds with a classic buildpack, as this app does. A new committed set needs its own line there, and a room test fails until it has one. The sample holds a tenth of the facilities in each portfolio and opening stage of the full book. `uv run python control_room/small_set.py` rebuilds it, and A41 in [the assumptions](assumptions.md) records how close it comes. It cannot meet the requirements' exact targets, so the page lists those differences. Locally the page still opens on the full book, because it opens on the largest set it can read.

**Dyno size.** Measured on Linux on 1 November 2026, the page and the engine together peak at about 0.55 GB on the sample and 1.7 GB on the full book, in a run with two scenarios. More scenarios need more. Going over quota logs an R14 warning and may slow the run. Heroku stops the dyno only at the limit in the third column.

| Dyno | Memory quota | Stopped at | The sample | The full book |
|---|---:|---:|---|---|
| eco, basic, standard-1x | 0.5 GB | 1 GB | Fits, slightly over quota | Is stopped partway |
| standard-2x | 1 GB | 2 GB | Fits | Is over quota and close to being stopped |
| performance-m | 2.5 GB | 5 GB | Fits | Fits |

**What does not last.** Heroku clears the app's files at every deploy, config change and restart, and at least once a day. A restart also stops any run in progress. These all go with the files:

- runs and their folders, so a rerun works only until the next restart;
- input sets packaged on the page, and sign-offs made there;
- setups saved on the page, and files added there.

The sample comes back with each deploy. To keep a result, download the workbook from the outcomes step. Heroku is not the retention store for approved runs (OPS-03).

**Synthetic data only.** Files added on a hosted page leave this machine for Heroku, and anyone with the address can see them, so never add bank data there.

**Why the `Procfile` sets `PYTHONPATH`.** Heroku builds the app in a temporary folder, and the installed project can keep pointing there. `PYTHONPATH` makes the server and the engine import the deployed source, and it lets a run fingerprint that source. A dyno has no `.git`, so a run's code version reads `0.1.0+unknown+source.<hash>`.
