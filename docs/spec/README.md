# docs/spec/

Locked. Holds the requirements and the data transcribed from them. `foundation/transcribe` (O1) writes the data files. The step reviewer and the project owner check them, and then they are locked. Claude Code cannot edit anything here.

| Path | Content |
|---|---|
| `EBA_2027_Credit_Portfolio_Stress_Test_Requirements.md` | Requirements |
| `targets.yaml` | §5.1–5.5 portfolio targets (O1) |
| `scenarios.yaml` | §6.2 scenario paths with units and SYNTHETIC status (O1) |
| `calibration_targets.yaml` | §8.7 S1 and S2 PDs that the TTC matrices are calibrated to (O1) |
| `oracles/AT-xx.yaml` | One record per acceptance case: input, expected value, tolerance and the named wrong answer, such as "not 27" or "not 36" (O1) |

The O1 files are not written yet. The oracle values the requirements leave open (AT-48, AT-51 and AT-52) are added only after the project owner approves them.

## Rules

- Rerun O1 only when the requirements change, with an impact assessment (GOV-03).
- Tests load expected values from here. Never type an oracle value into a test.
