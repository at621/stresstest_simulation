"""O3–O4: generate the synthetic portfolio and freeze opening allowances, written to inputs/<hash>/.

O3: seeded generator hitting every section 5 target exactly, with current and origination
grades chosen so the stage rule returns each facility's opening stage (SYN-PAR-08).
O4: end-2026 allowances from the generator's own formula, frozen as opening_provisions
(SYN-PAR-09). Writes a new file set and never edits an old one.
"""
