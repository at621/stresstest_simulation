# notebooks/

Jupyter notebooks that run the engine and show what each step produced. A notebook starts a run through `stress.cli.execute`, the entry point behind `stress run`, so a run started here is an ordinary sealed run under `runs/`. It then reads the run's tables back from that folder.

## Setup

```
uv sync                 # also installs the notebooks group: Jupyter, ipykernel, matplotlib
uv run jupyter lab      # in the browser, from the repo root
```

In VS Code, open the `.ipynb` and pick the kernel `.venv\Scripts\python.exe` (Python 3.12) of this repository. Any other interpreter lacks the engine.

## Notebooks

| Notebook | What it shows |
|---|---|
| [01_full_run_walkthrough.ipynb](01_full_run_walkthrough.ipynb) | Runs R1–R11 on one input set and shows each step's tables, with the identities behind them. It follows one facility from its cash flows to its charge. |
| [02_annual_pd_calculation.ipynb](02_annual_pd_calculation.ipynb) | Rebuilds every annual PD by hand from the input set (Z-score, PiT matrices, PD curves, portfolio PD) and checks each value against a sealed run. |
| [03_input_data_overview.ipynb](03_input_data_overview.ipynb) | What the engine starts from: the input set, its portfolios, loans, interest rates and SICR triggers. It reads files only and starts no run. |
| [04_loan_term_structure.ipynb](04_loan_term_structure.ipynb) | Two tables per loan from a sealed run: a loan summary (stage, 12-month and lifetime ECL, PD, LGD, maturity, rate, booked provision) and a term structure (PD, LGD, EAD, DF and ECL share per default bucket). Controls recompute the booked S1 and S2 provisions and R8's `ecl_buckets` for every scenario and valuation date. Exports to `output/<run_id>/`. |

## Shared helpers: `nbtools.py`

| Call | Returns |
|---|---|
| `nb.run_engine(inputs, scenarios, variant)` | Runs R1–R11 and returns the sealed `Run`. It raises with the reason if the run is BLOCKED. |
| `nb.open_run("latest")` or `nb.open_run(run_id)` | A sealed `Run` |
| `nb.list_runs()`, `nb.input_sets()` | What is in `runs/` and `inputs/` |
| `run.table("slices")`, `run.data("facilities")`, `run.report("impairment")` | `results/*.parquet`, the input copy in `data/`, `results/reports/*.csv` |
| `run.overview()`, `run.outputs()`, `nb.reproduction(run)` | Versions, hashed outputs, and the comparison with other runs of the same config |
| `nb.millions(df)`, `nb.grade_order(...)`, `nb.slice_order(...)` | Display helpers |

## Rules

- Start runs only with `nb.run_engine`. Never wire the steps in a notebook: `cli.py` is the only place that wires the pipeline.
- Read `runs/<run_id>/` and `inputs/<hash>/`; never write to them. A notebook that exports files writes them to `notebooks/output/<run_id>/`, which git ignores.
- No expected value is typed by hand. A check recomputes an identity from the run's own tables.
- `uv run ruff check` lints the notebooks and `nbtools.py` with the rest of the repo.
- Saved outputs point to a local run folder, which is not in git. Clear them before committing if they shouldn't travel: `uv run jupyter nbconvert --clear-output --inplace notebooks/*.ipynb`.
