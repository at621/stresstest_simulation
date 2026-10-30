# Published benchmarks

[eba-2025-published.yaml](eba-2025-published.yaml) holds published results of the 2025 EU-wide stress test, adverse scenario. `foundation.synth.analysis` copies it into the sidecar's `plausibility` section, and a run given that sidecar writes `analysis_plausibility.csv`: the engine's adverse result next to each published figure, with the multiple.

Basel principle 8 expects benchmarking, and EBA/GL/2018/04 ¶62 expects external benchmarks where available. Finding 13 of the [EBA 2027 review](../eba-2027-review/eba-2027-review-findings.md) has the first reading.

## How to read the sheet

The sheet shows a difference. It does not judge it, and nothing fails on it. That judgement is the owner's.

The comparison is not like for like. The synthetic book is deliberately riskier than the EU sample, its opening S3 share is nearly twice the EU one, and its perimeter and portfolio mix differ. The ECB's figure for `credit_loss_rate` on P02 is its highest class, unsecured retail. The two property figures compound the ESRB's annual cross-country medians, so they are approximate.

## Open for the owner

These change results and need a new input set, so they are not built:

- **Driver moments.** A19 records that driver volatility was loosened after a first result (7.6% of GCA) was judged too severe, so severity was set partly from the outcome. Set the moments from published or estimated data instead.
- **Z scale.** Every segment's |β| sum to 1, so Z has unit variance only if its drivers are perfectly correlated. With uncorrelated drivers its standard deviation would be 0.58 to 0.83. Standardise Z, or record why not.

## Changing the file

Add a row with a `measure`, a `scope`, a `published` value and a `source` from `sources`. The measures are defined in `plausibility_sheet` in `src/stress/report/assessment.py`, and an unknown measure blocks the run. Scope is `Total`, a book (`P01`–`P06`), or `Scenario` for a macro measure. Raise `version` when a value changes.
