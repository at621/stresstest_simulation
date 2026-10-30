# Synthetic preparation example

Generate a new sidecar package without changing the committed synthetic input set:

```powershell
uv run python -m foundation.synth.analysis --inputs inputs/d62d0386f2c5256e --out docs/examples/preparation.yaml
uv run stress run --inputs inputs/d62d0386f2c5256e --scenarios baseline,adverse --variant core --analysis docs/examples/preparation.yaml
```

The generator refuses to overwrite an existing output. Use a new filename when generating
again, or use the existing package directly with the second command. Generated YAML is ignored
by Git; the deterministic generator is the maintained source.
It contains invented, versioned inputs for benchmark selection, one collateral recovery,
regulatory and standardised risk weights, a CET1 bridge, one mortgage's separate climate
projection, illustrative export cells and a named one-year loss budget. No synthetic number
is represented as an approved regulatory input.

For a separate terminal-method sensitivity:

```powershell
uv run stress run --inputs inputs/d62d0386f2c5256e --scenarios baseline,adverse --variant core --terminal-treatment parameters --analysis docs/examples/preparation.yaml
uv run stress compare --base runs/<default_run> --new runs/<parameter_run>
```

Results are `results/analysis_*.parquet` and `results/reports/analysis_*.csv`. Every run also
reports readiness, country/NACE/stage totals, group concentrations, SICR flag attribution,
remaining-horizon SICR thresholds, a mathematical calibration diagnostic, LTV under the scenario's
price indices, average maturity, the default-loss-weighted LGD and a replica of the draft's
CSV_CR_SCEN provisions (`analysis_template_replica.csv`) beside the engine's stock. The optional
mapping writes a long cell table with source/measure/version and matching row counts; it is
not an official EBA workbook. Missing matches and duplicate destinations block.

The `npe_backstop` section holds an illustrative calendar: only the unsecured 35% in the third
year comes from the draft (footnote 75). Replace the other factors from Article 47c before use.
`analysis_npe_backstop.csv` reports the calculated shortfall; the capital bridge keeps its
supplied `npl_deduction_change`, so the two can be compared.

The `plausibility` section copies [docs/benchmarks/](../benchmarks/README.md), published results
of the 2025 exercise and not invented values. `analysis_plausibility.csv` sets the adverse result
beside them. The comparison is not like for like and judges nothing.

The package is bound to its input-set hash, loaded only at R2, copied into `data/analysis.yaml`
and hashed in the run manifest. An unchanged-source rerun uses those sealed copies even if
the original input folder and YAML no longer exist. Restore the recorded source and Python/
package environment before rerunning after a software change.

The [implementation register](../implementation-status.md) describes each model boundary and
remaining approval dependency. Keep owner AT-48, AT-51 and AT-52 numerical sign-offs open.
