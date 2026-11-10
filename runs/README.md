# runs/

One folder per run. Each folder holds everything needed to reproduce and explain that run: the configuration used, the exact input data and the results.

```
stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core
```

```
runs/<run_id>/
├── manifest.json            # R1 and R11: input-set hash, git SHA, rule and parameter-set versions,
│                            #   status label, hashes of every input and output
├── config.yaml              # the run as invoked: input set, scenarios, variant and options
├── run.log                  # what each step did and how long it took
├── data/                    # R2: copy of the input set used, checked against its hash: four tables,
│                            #   two YAML documents, matrices/ with one file per segment, and the
│                            #   set's manifest.json and approval.json
└── results/
    ├── rejections.parquet            # R3: rejected records with reason codes
    ├── drivers.parquet               # R4: Z by segment, model, country, scenario and year
    ├── driver_contributions.parquet  # R4: each driver's value, mean, sd, beta and contribution to a Z
    ├── indices.parquet               # R4: property price indices by scenario, country and year
    ├── cf_schedule.parquet           # R5: contractual schedule
    ├── pit_matrices.parquet          # R6: PiT matrices by segment, country, scenario and year
    ├── pd_curves.parquet             # R6: PD ParameterRecords, a curve per segment, country, grade, scenario and valuation year
    ├── parameters.parquet            # R6: facility ParameterRecords (LGD, prepayment, EAD per bucket)
    ├── lgd_of_year.parquet           # R6: each facility's LGD of the year, and its CCF as the run applies it
    ├── slices.parquet                # R7: facility slices per year-end, with the provisions R8 gives them
    ├── stage_flows.parquet           # R7: GCA and undrawn moved between stages, by segment
    ├── grade_flows.parquet           # R7: GCA moved between grades, by segment and country
    ├── provisions.parquet            # R8: raw and constrained, on- and off-balance
    ├── ecl_buckets.parquet           # R8: ECL per default bucket, by segment and stage
    ├── charges.parquet               # R9: charge = closing − opening
    ├── analysis_*.parquet            # preparation analyses, written after the last year and before R10
    └── reports/                      # R10: summary.md, stress_report.xlsx and the other reports
```

Every run that completes writes three analysis tables: `analysis_calibration.parquet`, `analysis_sicr_horizon.parquet` and `analysis_loss_weighted_lgd.parquet`. A run with an analysis file (`--analysis`, or `run.analysis` in a specification) adds one or two for each of the sections benchmarks, recoveries, capital, NPE backstop, climate and challenge that the file supplies, and keeps the file's exact bytes as `data/analysis.yaml`. A run from a specification keeps it as `data/specification.yaml`. A dynamic run also writes `exposure_movements.parquet` (R7).

A static run with no analysis file and no specification writes 32 reports: `summary.md`, which `stress report` prints; the workbook `stress_report.xlsx`; `effective_specification.json`; and 29 CSV files. Those are `starting_point_reconciliation` and `static_books`; `stage_migration`, `grade_migration` and `s3_cohorts`; `impairment`, `impairment_by_stage` and `ecl_by_bucket`; `z_scores`, `driver_contributions`, `property_indices`, `ttc_matrices`, `pit_matrices`, `pd_curves`, `portfolio_pd`, `lgd_by_z`, `ead_profile` and `segment_models` for the parameters; and eleven `analysis_*` reports. A dynamic run writes `dynamic_books.csv` and `exposure_movements.csv` in place of `static_books.csv`, and leaves out `analysis_template_replica.csv`.

## Comparisons

`stress compare --base runs/<a> --new runs/<b>` writes `runs/comparisons/<a>__<b>/`, beside the run folders, because a sealed run is write-once: `summary.md`, the differences in impairment, stage stocks and coverage, PD and LGD as CSV, and `comparison.json`, which names both runs by digest and hashes the files. The same two runs give the same bytes.

## Run ID

`<yyyymmddThhmmZ>-<variant>-<hash8>`, for example `20261017T1830Z-core-3f2a9c1b`. The hash covers the config, the input set, the code version and the spec version. A run that selects a reading of the draft in place of the design's default carries it after the variant, for example `20261031T0900Z-core+held-3f2a9c1b`, so it cannot be read as the core run.

## Rules

- **One run, every scenario it names.** A run holds any scenarios of its input set, and any its specification defines, baseline always among them: unless a specification holds a scenario flat, the others revert toward it after 2029 (A20, A43). They run through the same code in one run and are never blended (REG-07). A sensitivity, such as the AT-35 utilisation case or the annuity and linear profiles, is a separate run with its own `--variant`.
- **Write-once.** Once R11 seals a run, nothing in its folder changes. A rerun is a new folder, and a rerun from the manifest must give identical output hashes (§12.2).
- **Status.** Every preparation run is labelled SYNTHETIC. Regulatory mode blocks the run in v1.
- **Not in git.** Run folders stay local. Approved runs go to the bank's retention store (OPS-03).
