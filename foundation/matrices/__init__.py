"""O2: build the TTC PD matrices, one per reference segment.

Shared master scale of N performing grades plus default D. Rows sum to 1, D is absorbing
and PD rises with the grade. Calibrated to the section 8.7 S1 and S2 PDs.

PD-09, SYN-PAR-05.
"""
