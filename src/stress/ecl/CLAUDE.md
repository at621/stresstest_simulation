# ecl/ (R8): rules that are easy to get wrong

- S1: `Σ m[k] · EAD[k] · LGD[k] · DF[k]` over bucket y+1 only. S2: the same sum from y+1 to maturity, with maturity taken from R5.
- The PD curves hold whole years. A final bucket of d years takes `d × m[K]`, the whole-year marginal PD pro rata by the maturity (`part_year_pd`, A7); end-2029 S1 takes `d × PD` the same way (A27). A curve with a gap blocks; it is never read as zero.
- End-2029 S1 uses the interpolated 2030 loss rate (AT-06), not separately interpolated PD and LGD (ECL-05). Block if the 2030 input is missing (AT-41).
- PD, LGD and EAD in one product must share scenario, valuation date, default bucket and event basis.
- `DF` discounts from default date to valuation date, once. LGD carries no recovery discounting (LGD-12).
- Original S3: `max(GCA × LGD of the year, prior allowance)`, checked per exposure, never on the total (ECL-11, AT-18).
- New S3: `flow × LGD of the default year`, booked once; it never falls below that amount afterwards.
- Never apply PD to a new-S3 flow: it is already default-weighted (PD-05).
- The drawn part goes to the on-balance allowance and the undrawn part to the off-balance provision, never both (EAD-08).
- Keep raw and constrained values, and report what a binding floor masks (ECL-09).
- Stage comes from the grade slice in R7. Don't recompute it here.
- Optional dynamic mode adjusts performing volumes before R7. Scale the reference EAD by
  each current slice's drawn and undrawn shares separately, as in the static path. R9 compares
  with the actual prior closing provisions so volume changes enter P&L once; S3 floors remain.
- Proposed selectable reading, not settled by the owner: `s2_treatment=held` keeps the allowance of what stayed in S2 from the second projected year (C14, `hold_s2`). `raw_on` and `raw_off` still hold the lifetime ECL, and R10's `ecl_bridge` adds the held amount to the buckets to reach the booked provisions. The default reprices S2 every year-end.
