# GOV-03 impact assessment template

GOV-03 asks for an impact assessment of every source change, covering data, perimeter, calculations, assumptions, reporting and acceptance cases, and for the previous specification and results to be kept for comparison. Copy this template for each change, and keep the completed copy in this folder as `gov-03-<yyyy-mm-dd>-<source>.md`.

The affected requirements come from the [source register](source-register.md). The current status of each one is in the [traceability matrix](../traceability/traceability-matrix.md).

## 1. The change

| Field | Entry |
|---|---|
| Assessment date | |
| Prepared by | |
| Source, by S-number and title | |
| Previous version, publication date and URL | |
| New version, publication date and URL | |
| Origin (GOV-02) | Final EBA package / exercise FAQ / documented competent-authority instruction |
| Register rows affected | |
| Requirement IDs affected | |
| Label of each (§1.1) | DRAFT / DESIGN / SYNTHETIC / OPEN |
| What changed, quoted from the source | |
| Paragraphs renumbered, old to new | |
| Conflict with another instruction (GOV-02) | None / describe it. Do not settle a conflict through a model assumption: record it under the next free C-number in `docs/assumptions.md` and take it to the owner |

## 2. Impact

Complete every row, and write "none" with the reason where nothing changes.

| Area | Affected? | What changes | Requirement IDs | Owner (§13.1) | Evidence |
|---|---|---|---|---|---|
| Data: input contract, data dictionary (§4), synthetic targets | | | | | |
| Perimeter: scope, exclusions, accounting and REA populations | | | | | |
| Calculations: engine steps R1–R11, one-off steps O1–O4, parameters | | | | | |
| Assumptions: A and C numbers that change, new ones needed | | | | | |
| Reporting: reports, template mappings, materiality, taxonomy | | | | | |
| Acceptance cases: oracles, tests, tolerances, controls (§12) | | | | | |

## 3. Who may make the change (§1.1)

| Label | Rule |
|---|---|
| DRAFT | Changes only through an updated authoritative source or a documented competent-authority instruction |
| DESIGN | The project owner may change it, with this assessment |
| SYNTHETIC | A fictional input or test example. Never fills an official value in a submission run (GOV-04) |
| OPEN | Settled by the named owner before submission |

## 4. Previous state kept for comparison

| Item | Value |
|---|---|
| Requirements document version and commit | |
| Design commit | |
| Input set hash | |
| Sealed run ID, baseline and adverse | |
| Where that run is kept (OPS-03) | |

## 5. Steps

`docs/spec/` is written only by code. The owner amends the requirements, then O1 reruns. See "After changing the requirements or the parameter set" in the [runbook](../runbook.md).

- [ ] The owner amends the requirements. The version number changes.
- [ ] `uv run python -m foundation.transcribe`, then check the diff of `docs/spec/`.
- [ ] If the design changes, the owner agrees and the design is updated with it.
- [ ] `uv run python -m foundation.synth`, if the requirements version or the parameters changed. The input set hash changes, so update the `--inputs` path wherever it is used.
- [ ] `uv run pytest`, `uv run lint-imports --cache-dir tests/.import_linter_cache` and `uv run ruff check`.
- [ ] A full run, then `uv run stress compare --base runs/<old> --new runs/<new>`. Keep the quantified difference (§12.2, "Version change"; SCN-04 for a scenario revision).
- [ ] Update `docs/assumptions.md`, and the status of each affected requirement in `docs/traceability/requirement-status.yaml`.
- [ ] Record the approval date in `docs/source-register/source-approvals.yaml`, then `uv run python -m tests.traceability`.
- [ ] Review by `change-reviewer`.

## 6. Quantified effect

| Scenario | Measure | Before | After | Difference |
|---|---|---:|---:|---:|
| Baseline | Cumulative charge 2027–2029, EUR m | | | |
| Adverse | Cumulative charge 2027–2029, EUR m | | | |

Add any other measure the change moves: stage stocks, coverage, PD or LGD by book, REA.

## 7. Sign-off (§13.1)

| Owner | Responsible for | Name | Date | Decision |
|---|---|---|---|---|
| Credit Risk | Segmentation, credit assumptions, migration, recoveries | | | |
| Finance | Opening balances, allowances, P&L bridges, tax and capital interfaces | | | |
| Regulatory Reporting | Scope, taxonomy, template mapping, materiality, reporting validation | | | |
| Model Risk/Validation | Independent methodological and model challenge | | | |
| Data Owner | Data quality, reconciliation, lineage, remediation | | | |
| Programme Lead | Source changes, issue resolution, delivery readiness, sign-off evidence | | | |

## Checklist for the final 2027 package

Compare these against the final text when it is published, because paragraph numbers may move. Record the final reference, and open an assessment for each item that changed.

| Draft reference | Subject | Requirements | Compare, and known open points | Final reference | Changed? | Assessment |
|---|---|---|---|---|---|---|
| ¶123–125 | Perfect foresight, terminal treatment and S1/S2 reversion | REG-06, ECL-03, ECL-04, ECL-06 | The six-year reversion and whether it applies to parameters or Z (C8). Whether S2 ECL stays constant unless replaced (review finding 1) | | | |
| Boxes 4–9 | Provision formulas | ECL-03, ECL-07 (Box 9) | The end-2029 S1 blend in Boxes 4–5 (ECL-05, ECL-10, AT-06). `LRLT S2` in Box 7 (review finding 1). The first-year estimate in Box 9 (review finding 3) | | | |
| ¶113–118 | Model and benchmark hierarchy | REG-08, MOD-03 | The 10% pivot coverage test of ¶117 and its whole-pivot fallback. The requirements cite up to ¶120, so check ¶119–120 too | | | |
| ¶145–146 | Sovereign and central-bank routing | REG-08, MOD-04 | Prescribed ECB parameters, the zero-loss treatment and the fallback for countries without them | | | |
| ¶153 | Starting-point methodological REA floor | REG-09, CAP-03 | Floor applied separately to IRB and STA (AT-10). ¶178 is cited with it | | | |
| ¶562–564 | NPE coverage and deduction | CAP-09 | Also §6.4.6, footnote 75 (review finding 12) and the final `CSV_CR_NPL` instructions | | | |
| Template columns | Template families and their cells | §11.4, ACC-03, RPT-04 | Every family in §11.4 against S3 Annex II and S4 §2.2. Bind cell coordinates, validation rules and export formats to the approved version (§2.2 item 3). The NACE target of each output (§2.2 item 1). The provision lines and CCFs of review finding 9 | | | |

Also confirm the items of GOV-04 and the rest of the register. Each row of the [source register](source-register.md) names the requirements that depend on it.
