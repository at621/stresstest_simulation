# params/ (R6): rules that are easy to get wrong

- PD comes only from the matrices. Shift each TTC row with the year's Z (PD-10), then `F[k] = (e_g × M(y+1) × … × M(y+k))[D]` (PD-11). Never sum conditional PDs. Check the PD-03 identities on every curve.
- PD curves hold whole years only. Never build part-year rows here: R8 takes a final bucket of d years pro rata (A7).
- Every PiT row sums to 1 within 1e-10; block otherwise.
- One Z per segment, country, year and scenario drives matrix, LGD and prepayment. Never apply a second stress to the same value.
- `LGD[k] = Φ(Φ⁻¹(LGD_TTC) − w × Z[k])`. No cap, no add-on, no collateral data. An LGD_TTC of 0 or 1 passes through unchanged (LGD-12).
- Prepayment is applied once, in `EAD_drawn[k] = B[k] × SP[k]` with `SP[1] = 1`. Never also in the default survival `S[k]`. The undrawn part is not prepaid (EAD-11).
- EAD is conditional on default: never multiply it by PD or survival inside the EAD calculation. Store drawn, undrawn and total (EAD-02).
- `B[k]` and `DF[k]` come from R5's schedule. Never build cash flows here.
- Apply the accounting CCF once and the regulatory CCF once, never in sequence. Keep the regulatory EAD bridge apart (EAD-04, EAD-07, MOD-02).
- Buckets after 2029 use the reverted Z (ECL-10). A missing terminal bucket blocks; it is never zero.
- Build baseline parameters before adverse, because adverse reverts toward baseline 2029.
- Every value is a ParameterRecord under the MOD-06 key. A duplicate or missing key blocks.
