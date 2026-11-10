# TODO

Work that is not done yet. Two other places hold what this file does not:

- **Decisions that wait on the owner** are listed once, in [docs/architecture.md](docs/architecture.md) §6.
- **Items that are decided and built** are kept as written in [docs/settled-items/settled-items.md](docs/settled-items/settled-items.md), because the assumptions and the design cite their findings and figures.

## Not built yet

- [ ] Split S2 by trigger (PD test, DPD, watchlist, forbearance) in the stage-migration report (A30). `analysis_sicr_attribution.csv` already gives the split by trigger and flag combination for each scenario and year.
- [ ] Make notebook 04 a permanent output of every run, if wanted: through `/improve`, then update `README.md` and `docs/runbook.md`.

## At the next input-set rebuild

A rebuild gives a new hash in every document, notebook and test, a new small dataset and a new approval. On 9 November 2026 the owner decided that these steps wait for the next rebuild that is needed anyway. The first step was due "at the next rebuild" since 18 October 2026, and two rebuilds (`57bf340df85d5a54`, `5a296ffe0e198705`) went by without it.

- [ ] Rename or split the parameter-set convention `stub_pd: constant_hazard_by_grade`, which describes O4 and the R3 SICR line only (A7).
- [ ] Remove, or start reading, the parameter-set keys that nothing reads: all six `conventions`, `terminal_rule.method`, `terminal_rule.baseline`, `terminal_rule.s1_end_of_horizon` and `master_scale.default_grade`. R2 requires the `conventions` block to be there, but no code reads a value, so changing one gives a new hash and identical results.
- [ ] Give the parameter set a new id or version. Four different parameter sets (in `32415eb9d5bbcd74`, `514ed0e86e3dc760`, `d62d0386f2c5256e`, and `57bf340df85d5a54` with `5a296ffe0e198705`) all say `SYN-PS-0.1-proposed`, version `0.1`, so a run's manifest tells them apart only by the input-set hash (OPS-01).
- [ ] Then follow "After changing the requirements or the parameter set" in `docs/runbook.md`.

## EBA 2027 review: decisions waiting on the owner

The review's findings are built and on `main`: see [its status table](docs/eba-2027-review/eba-2027-review-findings.md#status-of-the-findings). The open decisions are items 9–12 of `docs/architecture.md` §6.

The baseline S2 note under "Baseline 2027 releases provisions" in the [settled items](docs/settled-items/settled-items.md) calls falling S2 coverage "the expected behaviour of a static balance sheet with replacement at maturity". That note is reopened: ECL-06 and the draft's ¶76, ¶123 and ¶125 read it differently (C14).

## Input checks: gaps found while writing the guide to step 1

The review of the control room's guide on 1 November 2026 ran altered copies of the small dataset through the engine. These are engine behaviour, so a fix sits under `src/`. The guide states the crashes as rules that stop a run partway (`LATE_RULES` in `control_room/guide.py`), and those lines can go once the sanity checks catch them. The blank `portfolio` and the unknown `repayment_profile` word were closed on 10 November 2026 (A44).

### Steps

- [ ] Make R3 block with a reason code on a blank `snapshot_date`, which raises a raw `TypeError` today.
- [ ] Make a blank `counterparty_sector`, and a Scenarios file with no `index_of` or `starting_values`, block with a reason code. They pass R1 to R4 and then stop the run with `INTERNAL_ERROR`. Since 10 November 2026 R2 checks the shape of `index_of` and `starting_values` when they are there, not that they are there.
- [ ] Have the sanity checks reach the rules that block only later: facility LTV and collateral type, the two price index names and `template_class` at the report step; a variant with no repayment profile for a product at R5; a `residual_maturity` past `last_bucket_year` and a scenario value that breaks the point-in-time matrix at R6.
- [ ] Reject a blank or misspelt `regulatory_approach`. `src/stress/report/excel.py` keeps only rows that say `IRB`, so a blank seals a run with a wrong workbook figure: 123.58 against 138.85 on the Portfolios sheet, for one €15.3m loan left blank on the small dataset.
- [ ] Decide whether R2 should enforce `Column.nullable` in `src/stress/contracts/inputs.py`, which no code reads, or whether to remove it. Blanks in six columns marked non-nullable (`rate_type`, `entity_id`, `group_id`, `regulatory_class`, `origination_date`, `sme_flag`) pass R2 and R3 and seal with no rejection.

## Segment models: what the change of 6 November 2026 left to do

Each segment now has its own PD, LGD and prepayment model in `src/stress/models/`, and the parameter set only names them and the segment's matrix file (A42, C20). The engine, the one-off steps, the core documents and the control room follow the new form. The items below still describe the old one.

The owner's two decisions for this item are in `docs/architecture.md` §6: calibrating the LGD and prepayment models apart from the PD models (item 7), and the requirement texts of C20 (item 3).

### Steps

- [ ] Rebuild the workflow page (`docs/run-workflow/`): `template.html`, `build_page.py` and `blocked_cases.py` still describe the inline `models:` section, `macro_model` and `macro_models.csv`. The walkthrough YAMLs are already in the new form and give the page's totals unchanged (static 132.3 / 662.2 / 1,173.4, dynamic 132.3 / 636.1 / 1,023.8 EUR m), so the page needs new runs and words, not new figures.
- [ ] Refresh the generated pages that name `ttc_pd_matrix.parquet`, `z_drivers`, `lgd_w` or `cpr_v`: `docs/run-inputs/`, `docs/input-data/input-data-overview.html`, `docs/staging/`, `docs/pd-curves/` and the technical implementation document with its PDF.
- [ ] The status deck's architecture slide (`docs/status-deck/slides/architecture.html`) still says "One Z drives PD, LGD and prepayment".
- [ ] Control room: let a person add or replace a segment's matrix file. Today the matrix files always come from the saved set, so a parameter set that names a new matrix file cannot be assembled on the page.

## Follow-ups found in the reviews of October 2026

- [ ] **Design header.** `docs/stress-engine-code-flow.html` still opens with "Proposal for agreement · 17 October 2026", although D5, D13, D2 and D3 now record owner decisions.
- [ ] **`largest_remainder` lets the machine break a tie.** `foundation/synth/generate.py` splits 5 across grades 4 and 5 on weights of almost exactly 0.5 each, so the BLAS kernel's last digit decides the split, and with it the rest of the book (A36). The reviewer tried a tie-safe version in a monkeypatch only: with shares and remainders rounded to 9 decimals and the later key winning ties, the default kernel keeps `d62d0386f2c5256e`, and four other kernels differ from the committed book only in floats, by at most 6.44e-13. With the earlier key winning, the input set and results change. Linux is untested. It would let the byte test become a comparison on every system, with discrete columns exact and floats within a tolerance. Needs the owner's decision (architecture §6 item 13).

## Found in the repository review of 9–10 November 2026 and not fixed

The review's findings were fixed on six branches (`improve/document-corrections`, `control-room-fixes`, `input-checks`, `report-fixes`, `tests-gates`, `engine-docs`). These are what the fixes and their reviews left open. None changes a result of a valid plain run.

### After the merge, once

- [ ] A person runs the protection check of `docs/runbook.md`: the guard hook's patterns changed, and neither the author nor the reviewer may try them against the real folders.
- [ ] Push and see CI: the control room's tests are in the gate now and have only ever run on Windows.
- [ ] Re-execute notebooks 01 and 04 in the main checkout. Their saved outputs name the worktree they were run in, the summary and coverage they show predate the report fixes, and notebook 01 heads its coverage table "provisions / GCA" over a figure that is on-balance allowance over GCA.
- [ ] Remove the unused `grades` parameter of `opening_slices` (`src/stress/projection/__init__.py`), whose only caller is `src/stress/cli.py`, and correct the comment in `cli.py` that a run blocked at R10 can have written a summary. Two branches owned the two files.
- [ ] Look at the control room in a browser: the layout after the unused CSS went, dark mode (it now follows the system only), the rejected-record lines, the "In progress" row after a reload mid-run, the stopped and restart notices, and the over-size message on a hosted page.
- [ ] `control_room/README.md` says its suite takes about two and a half minutes; with the new tests it takes about four and a half.

### Engine

- [ ] **A rerun after any later commit reports "NOT reproduced".** `summary.md` and the workbook print the code version, which holds the commit, while the replay check compares the source fingerprint and lets the rerun start. Even a documents-only commit therefore fails the rerun of an earlier run on those two files. Refuse a rerun at another commit, or say in the runbook that a rerun is made at the commit that made the run.
- [ ] **Code that only tests call.** About fifteen kernels in `src/` are called by acceptance or unit tests while the run uses its own inline code: `s3_original_allowance`, `s3_new_booking`, `s1_loss_rate_provision`, `monetary_loss`, `ecl_split`, `stage_flows`, `aligned_default_flows`, `curve_from_conditional`, `stub_pd`, `permitted_transfer`, `regulatory_bridge`, `drawn_measure`, `not_prepaid_share`, `compare_runs`, `adverse_weight` and `reverted_z`. The run's results are right (R5 to R9 were recomputed independently), and AT-50 now holds R6's own share to its kernel. Have the run call the others, or point their tests at the run.
- [ ] **`CODE_PATHS` includes `foundation/`** (`src/stress/lineage/__init__.py`), which the engine never imports. Editing `foundation/parameter_set.yaml` or `foundation/scenarios.yaml`, the documented way to change an assumption, marks later runs dirty and stops a rerun of every earlier run with `SOURCE_MISMATCH`. Decide whether that is wanted.
- [ ] **Three codes say "belongs to another input set":** `INPUT_HASH_MISMATCH` for the approval, `BAD_VALUE_TYPE` for the analysis file and `INVALID_SPECIFICATION` for the specification.
- [ ] **The "own portfolio" rule for models is checked only inside the parameter set.** A segment filed under another portfolio there seals with that portfolio's models while its facilities report under their own. A specification's carve-out does this on purpose (A42), so a check would apply to the base set only. The owner's call.
- [ ] **Input fields nothing reads.** `opening_provisions.frozen` (set to False on every row, a run seals unchanged), a stated status beside a value for most columns (`ifrs_stage__status = missing` is ignored), `ttc_matrix.master_scale_pd`, `commitments.ccf_source` and `provision_classification`, and a scenario value's `completeness`.
- [ ] **A rerun compares only the step and code of a block,** so two different engine faults read as reproduced.
- [ ] **Smaller.** A volume-assumption block reads R2 in the control room's dry run and R3 in a run, because `invalid()` hard-codes the step. Only the two duplicate cases that crashed now block under a specification. An unreadable analysis file leaves the run hash on its path. `SCENARIOS.key` in `src/stress/contracts/inputs.py` omits `country`, which R2 enforces. The first docstring line of `cli.py` names two of the four commands. A run folder path over 260 characters ends as `INTERNAL_ERROR` on Windows, and `+spec` adds five. A scenario label that starts with `=` is written into the workbook as a formula.

### Reports

- [ ] The Stage migration sheet's check shows `--` for a residue of −1e-13 in a dynamic run and `-` for +1e-13; rounding in the formula would show one dash.
- [ ] `pit_matrices` under `--terminal-treatment parameters` carries the reverted Z beside a matrix that is a blend.
- [ ] The Starting point sheet shows only the on-balance engine view beside the frozen on- and off-balance columns; the CSV has both.
- [ ] The Summary sheet's column headers and chart legends show scenario ids where the group headers show labels, because its formulas match on those cells.
- [ ] `static_books.csv` calls its column `converted`; only `summary.md` and the specification document say it uses the applied CCF.

### Tests and gates

- [ ] **No gate executes the notebooks.** Notebook 02 failed its own last check from 7 November 2026, when the Scenarios file gained three scenarios, until 10 November.
- [ ] **A change to the control room alone is tested by no local gate.** The pre-commit hook skips the suite for a small change; only CI runs the room's tests after a push.
- [ ] **Git's hooks path in this clone is absolute** (`C:\projects\stresstest_repo\tests\githooks`), where `docs/architecture.md` §5 gives the relative form. A commit from any other worktree therefore runs the main checkout's hook, not its own.
- [ ] **Tests that do not exist:** nothing reads `s3_cohorts.csv`; EXP-03 and MIG-06 have no test; no test reaches R6's `LGD_OUT_OF_RANGE` block; AT-01 does not assert the §5.4 ranges, and the retry in `foundation/synth/generate.py` (`months = max(12, int(months * 0.8))`) can go below a portfolio's lower maturity bound, though the committed book has no violation.
- [ ] `tests/ci_gate.py` leaves its `tests/.ci-*` folder behind on Windows, because sealed runs are read-only. Git ignores it.
- [ ] `notebooks/nbtools.py`: `open_run("latest")` returns a `-core+spec-` run as the latest core run.

### Control room

- [ ] **Added files are one list for everyone on a hosted page.** A visitor inherits a file a stranger added and can only package it or remove it. The README now says so; the page does not separate visitors.
- [ ] A corrupt `manifest.json` of an input set or of a run still breaks `/api/state` for everyone (`nbtools.input_sets()` and `_listed` raise).
- [ ] "N records will be left out" counts rule hits, so a record that breaks two rules is counted twice.
- [ ] A rerun that reproduces a block would read "Reproduced: every output matches". It is reachable only by a direct request, because the page disables the button for a blocked run.
- [ ] `control_room/preflight.py` still types `"INVALID_SPECIFICATION"` as text, where the engine now has a `Block` member.
- [ ] The walk of the page's own script through all four steps, made under node for this review, could become a committed test if a node dependency is acceptable.

### Documents

- [ ] Notebook 02's closing text says a year cut short uses the constant-hazard PD; its own section 5 and A7 say R8 takes it pro rata.
- [ ] `pyproject.toml` and `src/stress/__init__.py` say version `0.1.0` while the tags run to `v1.4.0`. Every run's code version starts with that number.
- [ ] `docs/eba-2027-review/eba-2027-review-findings.md` lines 229–231 name three functions that were removed on 10 November 2026; it is a dated record.
