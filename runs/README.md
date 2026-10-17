# runs/

One folder per run. Each folder holds everything needed to reproduce and explain that run: the configuration used, the exact input data and the results.

```
stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core
```

```
runs/<run_id>/
├── manifest.json            # R1 and R11: input-set hash, git SHA, rule and parameter-set versions,
│                            #   status label, hashes of every input and output
├── config.yaml              # the run as invoked: input set, scenarios, variant
├── data/                    # copy of the input set used (seven datasets), checked against its hash
└── results/
    ├── rejections.parquet   # R3: rejected records with reason codes
    ├── drivers.parquet      # R4: Z by segment, country, year and scenario
    ├── cf_schedule.parquet  # R5: contractual schedule
    ├── pit_matrices.parquet # R6: PiT matrices by segment, year and scenario
    ├── parameters.parquet   # R6: ParameterRecords (PD, LGD, prepayment, EAD per bucket)
    ├── slices.parquet       # R7: facility slices per year
    ├── provisions.parquet   # R8: raw and constrained, on- and off-balance
    ├── charges.parquet      # R9: charge = closing − opening
    └── reports/             # R10: starting-point reconciliation, stage migration, parameters, impairment
```

## Run ID

`<yyyymmddThhmmZ>-<variant>-<hash8>`, for example `20261017T1830Z-core-3f2a9c1b`. The hash covers the config, the input set, the code version and the spec version.

## Rules

- **One run, both scenarios.** Baseline and adverse run through the same code in one run and are never blended (REG-07). A sensitivity, such as the AT-35 utilisation case or the annuity and linear profiles, is a separate run with its own `--variant`.
- **Write-once.** Once R11 seals a run, nothing in its folder changes. A rerun is a new folder, and a rerun from the manifest must give identical output hashes (§12.2).
- **Status.** Every preparation run is labelled SYNTHETIC. Regulatory mode blocks the run in v1.
- **Not in git.** Run folders stay local. Approved runs go to the bank's retention store (OPS-03).
