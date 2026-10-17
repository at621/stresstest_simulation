"""R3 validate and route: schema and referential integrity, EUR-only and AC-only scope,
TTC matrix checks, grade explains stage, section 12.2 input controls. Sends each record
down exactly one route; a rejected record goes to the log with a reason code.

DAT-01, DAT-04, SCP-02, SCP-06, MIG-01, MIG-07, section 12.2.
"""
