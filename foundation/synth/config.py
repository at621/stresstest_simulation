"""Generator design choices for O3. These shape the synthetic book within the section 5
targets; they are not targets themselves and the targets do not depend on them."""

SEED = 20261231
ENTITY = "NLBANK"
SIZE_DISPERSION = 0.6  # lognormal sigma of initial facility sizes before raking
TOP_GROUP_SIZE_FACTOR = 3.0  # initial size multiple for facilities of the ten largest groups
ACCRUED_MONTHS_MAX = 3.0  # accrued interest covers up to three months of interest
ONE_YEAR_SHARE = 0.03  # share of facilities with exactly one year to run, where the range allows
SICR_MARGIN = 1e-6  # generated grades stay clear of the SICR line by this relative margin
# A30: the share of each segment's S2 facilities that is S2 by a qualitative trigger alone, with
# a grade above the SICR line, and the mix of the trigger given to those that drew none. These
# draws use their own random stream, so the rest of the book is the same as without them.
FLAG_ONLY_S2_SHARE = 0.25
FLAG_ONLY_TRIGGER_MIX = {"dpd": 0.4, "watchlist": 0.4, "forborne": 0.2}
FLAG_STREAM = 1

# Per portfolio: facilities per obligor (size, probability), product mix of performing
# facilities, contractual repayment profiles per product, floating-rate share, rate spread
# around the section 8.7 reference EIR, counterparty sector, SME share, collateral.
DESIGN = {
    "P01": {
        "obligor_sizes": [(1, 0.9), (2, 0.1)],
        "products": {"mortgage": 1.0},
        "profiles": {"mortgage": {"annuity": 0.9, "bullet": 0.1}},
        "floating": 0.30, "rate_sd": 0.005, "sector": "households", "sme": 0.0,
        "collateral": "residential_property",
        "classes": {"IRB": "retail_secured_by_immovable_property",
                    "STA": "secured_by_mortgages_on_residential_property"},
    },
    "P02": {
        "obligor_sizes": [(1, 1.0)],
        "products": {"consumer_loan": 1.0},
        "profiles": {"consumer_loan": {"annuity": 1.0}},
        "floating": 0.0, "rate_sd": 0.02, "sector": "households", "sme": 0.0,
        "collateral": None,
        "classes": {"IRB": "retail_other", "STA": "retail"},
    },
    "P03": {
        "obligor_sizes": [(1, 0.5), (2, 0.3), (3, 0.2)],
        "products": {"term_loan": 0.6, "revolver": 0.4},
        "profiles": {"term_loan": {"linear": 0.6, "bullet": 0.4}, "revolver": {"bullet": 1.0}},
        "floating": 0.60, "rate_sd": 0.01, "sector": "non_financial_corporations", "sme": 1.0,
        "collateral": None,
        "classes": {"IRB": "corporate_sme", "STA": "corporate_sme"},
    },
    "P04": {
        "obligor_sizes": [(1, 0.6), (2, 0.25), (3, 0.15)],
        "products": {"term_loan": 1.0},
        "profiles": {"term_loan": {"bullet": 0.7, "linear": 0.3}},
        "floating": 0.50, "rate_sd": 0.0075, "sector": "non_financial_corporations", "sme": 0.5,
        "collateral": "cre",
        "classes": {"IRB": "specialised_lending_ipre", "STA": "secured_by_commercial_property"},
        "top_group_facilities": 40,
    },
    "P05": {
        "obligor_sizes": [(1, 0.4), (2, 0.35), (3, 0.25)],
        "products": {"term_loan": 0.5, "revolver": 0.5},
        "profiles": {"term_loan": {"bullet": 0.5, "linear": 0.5}, "revolver": {"bullet": 1.0}},
        "floating": 0.60, "rate_sd": 0.0075, "sector": "non_financial_corporations", "sme": 0.0,
        "collateral": None,
        "classes": {"IRB": "corporate", "STA": "corporate"},
        "top_group_facilities": 60,
    },
    "P06": {
        "obligor_sizes": [(4, 0.4), (6, 0.4), (8, 0.2)],
        "products": {"debt_security": 1.0},
        "profiles": {"debt_security": {"bullet": 1.0}},
        "floating": 0.10, "rate_sd": 0.005, "sector": None, "sme": 0.0,
        "collateral": None,
        "classes": {"STA": None},
    },
}

P06_SECTOR = {"P06_GG": "general_governments", "P06_CI": "credit_institutions"}
P06_CLASS = {"P06_GG": "central_governments_or_regional_governments", "P06_CI": "institutions"}
P06_SUBSEGMENT = {"general_governments": "P06_GG", "credit_institutions": "P06_CI"}
