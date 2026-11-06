# params/ (R6): rules that are easy to get wrong

- PD comes only from the matrices. Shift each TTC row with the year's Z (PD-10), then `F[k] = (e_g × M(y+1) × … × M(y+k))[D]` (PD-11). Never sum conditional PDs. Check the PD-03 identities on every curve.
- The shift is `C_PiT = Φ(Φ⁻¹(C_TTC) − √ρ × Z)` with no `√(1 − ρ)` divisor, so Z = 0 gives back the TTC matrix, as the LGD and prepayment rules give back their TTC values (D13, owner decision of 18 October 2026). Don't bring the divisor back: O4 values the opening at TTC, and the two must agree at Z = 0.
- PD curves hold whole years only. Never build part-year rows here: R8 takes a final bucket of d years pro rata (A7).
- Every PiT row sums to 1 within 1e-10; block otherwise.
- Each segment's three models give their own Z per country, year and scenario (`Drivers.of`): the PD model's drives the matrix, the LGD model's the LGD and the prepayment model's prepayment. Never apply a second stress to the same value, and never feed one model's Z to another parameter.
- Authorised configurable extension (31 October 2026): R4 can resolve linear, polynomial/lagged
  or externally supplied models per segment, now functions in `stress.models`. R6 consumes each
  model's single score without knowing the model family. The LGD w and prepayment v come from
  the segment's models (R2 copies them as `lgd_w` and `cpr_v`). Scenario terminal weights may be flat or explicitly reverted; baseline
  stays flat. ParameterRecords retain the original facility reference exposure basis.
- `LGD[k] = Φ(Φ⁻¹(LGD_TTC) − w × Z[k])`. No cap, no add-on, no collateral data. An LGD_TTC of 0 or 1 passes through unchanged (LGD-12).
- Prepayment is applied once, in `EAD_drawn[k] = B[k] × SP[k]` with `SP[1] = 1`. Never also in the default survival `S[k]`. The undrawn part is not prepaid (EAD-11).
- EAD is conditional on default: never multiply it by PD or survival inside the EAD calculation. Store drawn, undrawn and total (EAD-02).
- `B[k]` and `DF[k]` come from R5's schedule. Never build cash flows here.
- Apply the accounting CCF once and the regulatory CCF once, never in sequence. Keep the regulatory EAD bridge apart (EAD-04, EAD-07, MOD-02).
- Buckets after 2029 use the reverted Z (ECL-10). A missing terminal bucket blocks; it is never zero.
- Build baseline parameters before adverse, because adverse reverts toward baseline 2029.
- Authorised preparation alternative (30 October 2026): `terminal_treatment=parameters` linearly blends terminal matrix probabilities and LGD endpoints; prepayment remains Z-driven. R8 bypasses its default terminal product interpolation for this option. Standalone benchmark/recovery/challenge diagnostics never overwrite core ParameterRecords. See the design preparation addendum and implementation register.
- Proposed selectable reading, not settled by the owner: `horizon_runoff=replaced` sets prepayment to zero in buckets up to 2029 and R5 keeps every facility alive to end-2029 (¶125, C15). Bullet schedules only. The default is contractual run-off in every bucket.
- Proposed selectable reading, not settled by the owner: `lgd_path=trough` gives LGD alone the path's worst Z for adverse property-secured books (`lgd_drivers`, C16). PD and prepayment keep their own Z. The default is LGD-12 as written.
- Every value is a ParameterRecord under the MOD-06 key. A duplicate or missing key blocks.
