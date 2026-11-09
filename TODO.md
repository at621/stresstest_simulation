# TODO

Work that is not done yet. Two other places hold what this file does not:

- **Decisions that wait on the owner** are listed once, in [docs/architecture.md](docs/architecture.md) §6.
- **Items that are decided and built** are kept as written in [docs/settled-items/settled-items.md](docs/settled-items/settled-items.md), because the assumptions and the design cite their findings and figures.

## Not built yet

- [ ] Split S2 by trigger (PD test, DPD, watchlist, forbearance) in the stage-migration report (A30).
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

The review of the control room's guide on 1 November 2026 ran altered copies of the small dataset through the engine. These are engine behaviour, so a fix sits under `src/` and they are not fixed. The guide states the crashes as rules that stop a run partway (`LATE_RULES` in `control_room/guide.py`), and those lines can go once the sanity checks catch them.

### Steps

- [ ] Reject a facility with a blank `portfolio`. A blank on one Stage 1 facility of €0.4m seals a run with baseline Stage 3 gross carrying amount 2029 at €85.6m against €91.6m, with no rejection and unchanged charges. Traced on 9 November 2026: R7 takes each segment's portfolio from its first facility (`src/stress/projection/__init__.py:187-188`), so one blank on that facility blanks the portfolio of all the segment's stage flows, and the segment's Stage 3 drops out of the by-portfolio totals. R3 lets it through because its one-portfolio-per-segment check (`src/stress/validate/__init__.py:425`) skips blanks.
- [ ] Make R3 block with a reason code on a blank `snapshot_date`, which raises a raw `TypeError` today.
- [ ] Make a blank `counterparty_sector`, and a Scenarios file with no `index_of` or `starting_values`, block with a reason code. They pass R1 to R4 and then stop the run with `INTERNAL_ERROR`.
- [ ] Have the sanity checks reach the rules that block only later: facility LTV and collateral type, the two price index names and `template_class` at the report step; a variant with no repayment profile for a product at R5; a `residual_maturity` past `last_bucket_year` and a scenario value that breaks the point-in-time matrix at R6.
- [ ] Reject a blank or misspelt `regulatory_approach`. `src/stress/report/excel.py` keeps only rows that say `IRB`, so a blank seals a run with a wrong workbook figure: 123.58 against 138.85 on the Portfolios sheet, for one €15.3m loan left blank on the small dataset.
- [ ] Reject an unknown word in a variant's `repayment_profile`. It falls to the linear formula in `src/stress/cashflows/__init__.py` and seals a run: adverse €61.8m against €65.1m on the small dataset.
- [ ] Decide whether R2 should enforce `Column.nullable` in `src/stress/contracts/inputs.py`, which no code reads, or whether to remove it.

## Segment models: what the change of 6 November 2026 left to do

Each segment now has its own PD, LGD and prepayment model in `src/stress/models/`, and the parameter set only names them and the segment's matrix file (A42, C20). The engine, the one-off steps, the core documents and the control room follow the new form. The items below still describe the old one.

The owner's two decisions for this item are in `docs/architecture.md` §6: calibrating the LGD and prepayment models apart from the PD models (item 7), and the requirement texts of C20 (item 3).

### Steps

- [ ] Rebuild the workflow page (`docs/run-workflow/`): `template.html`, `build_page.py` and `blocked_cases.py` still describe the inline `models:` section, `macro_model` and `macro_models.csv`. The walkthrough YAMLs are already in the new form and give the page's totals unchanged (static 132.3 / 662.2 / 1,173.4, dynamic 132.3 / 636.1 / 1,023.8 EUR m), so the page needs new runs and words, not new figures.
- [ ] Refresh the generated pages that name `ttc_pd_matrix.parquet`, `z_drivers`, `lgd_w` or `cpr_v`: `docs/run-inputs/`, `docs/input-data/input-data-overview.html`, `docs/staging/`, `docs/pd-curves/` and the technical implementation document with its PDF.
- [ ] Two places still state the old rules: the status deck's architecture slide (`docs/status-deck/slides/architecture.html`, "One Z drives PD, LGD and prepayment") and the docstring of `src/stress/__init__.py` ("Pipeline steps share only stress.contracts"). The docstring is in `src/`, so fixing it goes through `/improve`.
- [ ] Control room: let a person add or replace a segment's matrix file. Today the matrix files always come from the saved set, so a parameter set that names a new matrix file cannot be assembled on the page.

## Control room: a restart leaves the page showing a run in progress

When Heroku stopped the dyno during a run on 1 November 2026, the page stayed on "The run is in progress" and still said the run carries on if the page is closed. The restarted server had forgotten the job, and `/api/job` answered idle.

### Steps

- [ ] Have the page notice that the job it was following has gone, and say the run stopped.

## Follow-ups found in the reviews of 18–19 October 2026

Small points the `change-reviewer` found outside the changes it reviewed. None blocks a run today.

- [ ] **R6 builds the share not yet prepaid itself.** `facility_parameters` (`src/stress/params/__init__.py:234-241`) computes SP[k] with its own `cumprod` and `shift` instead of calling the tested kernel `not_prepaid_share` (`src/stress/params/prepay.py`). The two agree today. Since 30 October 2026 R6 sets only the first bucket to 1 and blocks a non-finite rate or share, so a missing rate can no longer read as "no prepayment". What is left: no test ties R6's share to the kernel, and AT-50 passes for any share. Have R6 call the kernel, or point a test at R6's own output.
- [ ] **Notebook 02 starts runs directly.** Its `start_run()` calls `stress.cli.execute`, while `notebooks/README.md` says to start runs only with `nb.run_engine`. Either use `nbtools` or note the exception (notebook 02 imports no helper module on purpose).
- [ ] **Design header.** `docs/stress-engine-code-flow.html` still opens with "Proposal for agreement · 17 October 2026", although D5, D13, D2 and D3 now record owner decisions.

## Follow-ups found in the review of 31 October 2026

- [ ] **`largest_remainder` lets the machine break a tie.** `foundation/synth/generate.py` splits 5 across grades 4 and 5 on weights of almost exactly 0.5 each, so the BLAS kernel's last digit decides the split, and with it the rest of the book (A36). The reviewer tried a tie-safe version in a monkeypatch only: with shares and remainders rounded to 9 decimals and the later key winning ties, the default kernel keeps `d62d0386f2c5256e`, and four other kernels differ from the committed book only in floats, by at most 6.44e-13. With the earlier key winning, the input set and results change. Linux is untested. It would let the byte test become a comparison on every system, with discrete columns exact and floats within a tolerance. Needs the owner's decision (architecture §6 item 13).
