"""R1 open the run and R11 seal it.

R1: run ID, input set fixed by hash, git SHA, rule and parameter-set versions, status label
(SYNTHETIC for every preparation run). R11: manifest.json with hashes of every input and
output; a rerun must give identical output hashes. Owns runs/<run_id>/.

OPS-01, OPS-04, SCN-04, REG-01, section 12.2 reproducibility.
"""
