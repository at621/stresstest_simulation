# Acceptance tests

One test per acceptance case: `test_at_xx.py`, marked `at("AT-xx")`. Expected values and tolerances come from `docs/spec/oracles/AT-xx.yaml`.

A green test should prove the engine, not a helper. R7 and R8 use their own vectorised code, so a kernel can stay right while the engine drifts from it. Each case is therefore asserted on the tables of a sealed run wherever the engine has an equivalent. A test that has a kernel assertion keeps it, then asserts the same case on the run.

## How a case reaches a run

- **Reference run** (`reference_runs`): `builders.reference_set` turns oracle inputs into facilities. Matrix rows give a grade exactly the case's PD or transitions, and rho = 0, w = 0 and no prepayment make PiT, LGD and EAD equal their TTC inputs, so the run reproduces the case's own numbers. Most cases share P03. Cases that read a whole segment or rewrite grade rows have their own, listed in `builders.REFERENCE_SEGMENTS`. A new facility reads only its own rows, so it does not disturb the others.
- **Core run** (`core_run`): the full synthetic book, for a level or a rule that must hold on real data.
- **Mini run**: the small input set, for a planted defect or a repayment variant.

## Cases

| AT | Proof | Route | Why |
|---|---|---|---|
| AT-01 | No run | Input set | The case is about what O2–O4 build, which exists before any run. AT-22 takes the allocation through R3. |
| AT-02 | Pipeline | Reference, core | `stage_flows` and `slices` give the closing stages from the opening book and transition rows. On the real book, closing stages reconcile to incoming flows every year. |
| AT-03 | Pipeline | Reference | R8 floors an opening S3 facility at its opening allowance in year one, and marks the floor as binding. |
| AT-04 | Pipeline | Reference | R7 opens the cohort from the flow. R8 books it once and re-measures it afterwards. |
| AT-05 | Pipeline | Reference | R8's provision for a whole S1 exposure. |
| AT-06 | Pipeline | Reference | A segment with Z scaled to 0 on baseline and -1 on adverse in 2029 gives both scenarios' PD and LGD, and R8's end-2029 S1 provision carries the interpolated loss rate. |
| AT-07 | Pipeline | Reference, core | `charges` shows the change in the stock, not the stock. On the real book, three years of charges add up to the change in the stock. |
| AT-08 | Pipeline | Reference | R6's total EAD, against both named wrong answers. |
| AT-10 | Pipeline | Capital bridge | `capital_bridge` floors IRB and STA separately on oracle REA. The bridge runs only with a capital sidecar, so the case calls the step directly. |
| AT-11 | Pipeline | Capital bridge | `capital_bridge` compares UTREA with the floored STREA on the oracle's amounts, as the case above. |
| AT-16 | Pipeline | Core | R4 writes every country's index level to `indices.parquet`. |
| AT-18 | Pipeline | Reference, core | Of two S3 facilities whose raw total rises, R8 still floors the one that would release. On the real book, many S3 slices would release and none does. |
| AT-21 | Pipeline | Core | `charges` and the starting-point report. |
| AT-22 | Pipeline | Core | The starting-point report accepts the whole allocation, stage by stage. |
| AT-25 | Pipeline | Reference, core | A chain of matrix rows gives the case's curve in `pd_curves`. The PD-03 identities hold on every curve of the real book. |
| AT-28 | Kernel-only | None | R8 takes a part year pro rata, `d × m`, by owner decision (A7, C10), so no run output carries this constant-hazard PD. A run would differ from the oracle by design. PD-06's text is the owner's to change (C10). |
| AT-29 | Pipeline | Reference | `stage_flows` and the new S3 cohorts carry the defaults by origin stage. |
| AT-33 | Pipeline | RPT-06 report | `default_weighted_lgd`, which every run calls, keeps a zero-EAD book as not applicable with zero loss. |
| AT-34 | Pipeline | Reference | R6's EAD split and R8's `allowance_on` and `provision_off`. |
| AT-35 | Pipeline | Reference | The core and utilisation variants, as separate labelled runs. |
| AT-36 | Kernel-only | None | The static book has no drawdown transfers: nothing calls `permitted_transfer`, and R7 blocks any movement of drawn or undrawn balances. |
| AT-37 | Pipeline | Reference | R5's first balance and R6's drawn EAD at every valuation date. |
| AT-38 | Kernel-only | None | `capital_bridge` computes regulatory EAD inline, so nothing calls `regulatory_bridge`, and the accounting-to-regulatory bridge of this case is in no report. |
| AT-39 | Pipeline | Reference | The AT-25 curve through R8: one bucket for S1, the whole life for S2. |
| AT-40 | Pipeline | Reference | R5's discount factor, applied once in R8. |
| AT-41 | Pipeline | Mini | A run without its terminal bucket blocks. The missing-baseline branch calls `terminal_s1` directly. |
| AT-42 | Pipeline | Reference | The P03 reference traced through R5, R6 and R8. |
| AT-44 | Pipeline | Core | The static books in `slices`, every year. |
| AT-45 | Pipeline | Mini | A broken matrix blocks the run. Validity is checked on the input set's matrices. |
| AT-46 | Pipeline | Core | The matrices the run used, from `pit_matrices`, plus a kernel grid of Z values. |
| AT-47 | Pipeline | Core | Within one grade in `pit_matrices`, the lower a year's Z, the higher its PD. |
| AT-48 | Pipeline | Core | The SICR rule on every sampled slice. The expected stages are OPEN, so the case proves the rule. |
| AT-49 | Pipeline | Core, reference | `lgd_of_year` follows LGD-12 and rises as Z falls. The AT-06 facility has w > 0 and Z = 0, and keeps its TTC LGD. The 0 and 1 boundaries are kernel only: no facility has them. |
| AT-50 | Pipeline | Core, mini | Prepayment in EAD only, with and without it. |
| AT-51 | Pipeline | Mini | `cf_schedule` under each profile's variant. The values are OPEN, so the case proves the profile rules. |
| AT-52 | Pipeline | Core, mini | The Z path and its reversion in `drivers`. A missing coefficient blocks. |

## A case that stays kernel-only

It says so in the first line of its module docstring, with the reason, and has a row here. When the engine gains the path, the test moves to a run and the row changes.
