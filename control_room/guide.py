"""What step 1 expects, as the page's guide shows it.

The columns, allowed values and required sections come from the engine's contract. Each rule names the
engine's own reasons or block codes, and the consequence of a record rule follows from them. test_guide.py
fails if a column, a section, a reason or a block code has no place here. The plain words are this file's,
and only reading them against the engine shows that they are right: a test cannot.
"""

from preflight import FILE_GUIDE

from stress.contracts.errors import RUN_BLOCKING_REASONS, Block, Reason
from stress.contracts.inputs import (
    APPROACHES,
    CENTRAL_BANK_SECTOR,
    COMMITMENTS,
    CURRENCY,
    DATASETS,
    DEFAULT_GRADE,
    FACILITIES,
    OBLIGORS,
    OFF_BALANCE_CATEGORY,
    ON_BALANCE_CATEGORY,
    OPENING_PROVISIONS,
    PARAMETER_SET,
    PRODUCTS,
    REPAYMENT_PROFILES,
    SCENARIO_UNITS,
    SCENARIO_VALUE_FIELDS,
    SCENARIO_VALUE_TYPES,
    SCENARIOS,
    SEGMENT_PARAMETERS,
    STAGES,
    SYNTHETIC,
    TABLE_DATASETS,
    TERM_PRODUCTS,
    TTC_MATRIX,
    Column,
    DatasetSpec,
)
from stress.contracts.preparation import COLLATERAL_INDEX
from stress.contracts.status import ALL_STATUSES
from stress.validate.sicr import HOLD_UNTIL_DEFAULT

STOPS, LATE, LEFT_OUT = "stops", "late", "left_out"


def _words(names, joiner: str = "and") -> str:
    """Names in a sentence: a, b and c."""
    names = [str(name) for name in names]
    return f"{', '.join(names[:-1])} {joiner} {names[-1]}" if len(names) > 1 else names[0]


def _labels(specs) -> str:
    return _words(FILE_GUIDE[spec.name][0] for spec in specs)


KINDS = {"str": "Text", "float": "Number", "int": "Whole number", "bool": "True or false", "date": "Date"}
# The kinds of file in the guide's order: the four tables, the matrix files, then the two YAML files.
GUIDED = (*TABLE_DATASETS, TTC_MATRIX, *(spec for spec in DATASETS if spec not in TABLE_DATASETS))

EVERY_FILE = (
    ("A run needs the six files in the rows below, plus one Rating transitions file per segment, which comes "
    "from the saved set. Each row starts with the saved file, so add only the ones you want to change. A new "
    "file must fit the others: the same IDs, segments and snapshot date."),
    ("The row you add a file to decides what it is, so the file can have any name. Files dropped on this "
    "card go to the row their name matches."),
    (f"{_labels((*TABLE_DATASETS, TTC_MATRIX))} are Parquet tables. {_labels((SCENARIOS, PARAMETER_SET))} are YAML files. "
    "The engine reads no other format, so convert a file first."),
    ("A table holds every column listed for it and no others. A column can also have a companion column, "
    f"<name>__status, that says {_words(sorted(str(status) for status in ALL_STATUSES), 'or')}."),
    ("In the tables, amounts are in euros, and rates and probabilities are decimal fractions, so 5% is 0.05. "
    "Scenario values are different: each is read in its own unit, as Scenarios explains."),
    ("A date column holds a Parquet date or text written YYYY-MM-DD, not a timestamp. A true or false column "
    "takes true, false, 1 or 0."),
    ("A value of the wrong kind stops the run, such as 1.5 in a whole number column or a date written "
    "31/12/2026. So does an unknown word in a companion column."),
    "A blank means missing, never zero. The rules for each file say which columns must be filled in.",
)

AFTER_YOU_ADD = (
    ("The page checks a file as soon as you add it: that it can be read and has the right columns or "
    "sections. If not, its row says what is wrong."),
    ("Use these files saves them, with the saved set's Rating transitions files, as a new frozen copy. Your "
     "own files and the saved files stay as they are."),
    "The sanity checks then read every value, without calculating anything.",
    "A problem they find shows at the top of the page, and the next step stays closed until you fix it.",
    ("They stop before the calculation, so a few problems show only when the run stops partway. The rules "
    "for each file list the known ones separately."),
    ("A record that is left out is listed with its reason, and the run can go ahead without it. If every "
    "record is left out, the run stops."),
    "Scenarios you add and settings you change here apply to this run only. The files stay as they are.",
)

WARNINGS = {  # what no check catches
    FACILITIES.name: f"Fill in portfolio on every row, and regulatory_approach as {_words(APPROACHES, 'or')}. Nothing "
                     "checks either: the run seals with no record left out, and reported figures come out wrong.",
    SCENARIOS.name: "value is read in its own unit: 1.5% is 1.5 with unit percent, or 0.015 with unit decimal. "
                    "Nothing checks this: a value in the wrong scale can run and give wrong results, or stop "
                    "the run partway.",
    PARAMETER_SET.name: f"repayment_profile in variants takes {_words(REPAYMENT_PROFILES, 'or')}. Nothing checks "
                        "this: any other word runs as linear and changes the results.",
}

MEANINGS = {
    FACILITIES.name: {
        "facility_id": "The loan's identifier.",
        "obligor_id": "The borrower, as in the Obligors file.",
        "entity_id": "The legal entity that holds the loan.",
        "portfolio": "The reporting portfolio. Any name works, but a segment stays in one portfolio.",
        "segment": "The risk segment. It needs its own rating transitions and parameters.",
        "product": "The kind of product.",
        "ifrs_stage": "The IFRS 9 stage.",
        "poci": "Whether the loan was purchased or originated credit-impaired.",
        "accounting_category": "How the loan is measured.",
        "currency": "The loan's currency.",
        "principal": "The drawn principal, in euros.",
        "accrued_interest": "The accrued interest, in euros.",
        "accrued_in_gca": "Whether the gross carrying amount includes the accrued interest.",
        "gca": "The gross carrying amount, in euros.",
        "contractual_limit": "The contractual limit, in euros.",
        "interest_rate": "The annual effective interest rate.",
        "rate_type": "Fixed or floating.",
        "residual_maturity": "Years from the snapshot date to maturity.",
        "repayment_profile": "The repayment profile in the contract. A run repays by its variant, not by this column.",
        "regulatory_approach": "The capital approach: internal ratings based (IRB) or standardised (STA).",
        "regulatory_class": "The regulatory exposure class.",
        "current_grade": f"The rating grade now: a grade on the master scale, or {DEFAULT_GRADE} once defaulted.",
        "origination_grade": "The rating grade when the loan started.",
        "ttc_lgd": "Through-the-cycle loss given default, from 0 to 1.",
        "dpd": "Days past due.",
        "watchlist": "Whether the loan is on the watchlist.",
        "forborne": "Whether the loan is forborne.",
        "credit_status_date": "The date dpd, watchlist and forborne were observed.",
        "origination_date": "The date the loan started.",
        "stage_entry_date": "The date the loan entered its stage.",
        "default_date": "The date of default, for a defaulted loan.",
        "collateral_type": "The kind of collateral. Blank for an unsecured loan.",
        "ltv": "Loan to value, as a decimal: 0.8 is 80%. Blank for an unsecured loan.",
        "dscr": "Debt service coverage ratio.",
        "snapshot_date": "The reporting date.",
    },
    OBLIGORS.name: {
        "obligor_id": "The borrower's identifier.",
        "group_id": "The group of connected borrowers it belongs to.",
        "entity_id": "The legal entity that holds the relationship.",
        "country": "The country of domicile.",
        "counterparty_sector": f"The borrower's sector, such as households. {CENTRAL_BANK_SECTOR} is not covered.",
        "nace_code": "The NACE economic activity code.",
        "nace_version": "The NACE version of that code.",
        "principal_activity": "The borrower's main activity.",
        "sme_flag": "Whether the borrower is a small or medium-sized enterprise.",
        "regulatory_default": "Whether the borrower is in regulatory default.",
        "snapshot_date": "The reporting date.",
    },
    COMMITMENTS.name: {
        "commitment_id": "The commitment's identifier.",
        "facility_id": "The loan it belongs to.",
        "currency": "The commitment's currency.",
        "nominal_undrawn": "The undrawn amount, in euros.",
        "accounting_ccf": "The credit conversion factor, from 0 to 1.",
        "ccf_source": "Where that factor comes from.",
        "asset_category": "Always the same value, because a commitment is off balance.",
        "provision_classification": "How its provision is classified.",
        "snapshot_date": "The reporting date.",
    },
    OPENING_PROVISIONS.name: {
        "facility_id": "The loan it belongs to.",
        "currency": "The provision's currency.",
        "allowance_on": "The on-balance allowance, in euros.",
        "provision_off": "The off-balance provision, in euros.",
        "overlay_amount": "The management overlay, in euros.",
        "overlay_risk": "The risk the overlay covers.",
        "overlay_owner": "Who owns the overlay.",
        "overlay_reason": "Why the overlay was made.",
        "method": "How the provision was calculated.",
        "frozen": "Whether the provision is frozen as starting data.",
        "snapshot_date": "The reporting date.",
    },
    TTC_MATRIX.name: {
        "from_grade": "The grade at the start of the year.",
        "to_grade": "The grade at the end of the year.",
        "probability": "The one-year probability of that move, from 0 to 1.",
        "from_rank": f"The position of from_grade: 1 is the best grade and {DEFAULT_GRADE} is last.",
        "to_rank": "The position of to_grade.",
        "master_scale_pd": "The one-year probability of default of from_grade on the master scale.",
    },
}

ALLOWED = {  # the only values a column takes, as the engine's contract states them
    FACILITIES.name: {"product": PRODUCTS, "ifrs_stage": STAGES, "accounting_category": (ON_BALANCE_CATEGORY,),
                      "currency": (CURRENCY,), "repayment_profile": REPAYMENT_PROFILES,
                      "regulatory_approach": APPROACHES,
                      "collateral_type": tuple(COLLATERAL_INDEX)},
    COMMITMENTS.name: {"currency": (CURRENCY,), "asset_category": (OFF_BALANCE_CATEGORY,)},
    OPENING_PROVISIONS.name: {"currency": (CURRENCY,)},
}

SECTIONS = {  # the required sections first, in the contract's order; the rest the first check does not ask for
    SCENARIOS.name: {
        "scenario_set_id": "The name of this set of scenarios.",
        "source": "Where the set comes from.",
        "release": "Its release.",
        "revision": "Its revision.",
        "status": "Its status.",
        "scenarios": "The list of scenarios, each with id, label, status and source_type.",
        "variables": "The list of macro variables, each with id, label, unit and value_type.",
        "values": f"One entry per scenario, variable, country and year, with {_words(SCENARIO_VALUE_FIELDS)}.",
        "starting_values": "The starting levels, each with variable, country, year, value, unit and value_type.",
        "index_of": "Which index each yearly price change builds.",
    },
    PARAMETER_SET.name: {
        "parameter_set_id": "The name of this parameter set.",
        "version": "Its version.",
        "status": "Its status.",
        "horizon": "The dates: snapshot_date, snapshot_year, projection_years and last_bucket_year.",
        "master_scale": "The rating scale: grades, default_grade and each grade's ttc_pd.",
        "portfolios": (f"Each portfolio's segments, and for each segment {_words(SEGMENT_PARAMETERS)}. The "
                       "three models are named as <portfolio>.<function>, functions in the engine's "
                       "src/stress/models/ that hold their own coefficients; ttc_matrix names the segment's "
                       "Rating transitions file, such as matrices/P01.parquet."),
        "terminal_rule": "What happens after the last scenario year: method, baseline, last_scenario_year, "
                         "reversion_years and s1_end_of_horizon.",
        "conventions": "The calculation conventions on record.",
        "tolerances": "The tolerances the checks use for probabilities, amounts and totals.",
        "variants": "The named run variants, each with label, repayment_profile and ccf.",
        "sicr_triggers": "The qualitative triggers for a significant increase in credit risk: enabled, "
                         "dpd_days, hold, definitions and source.",
    },
}

# The checks of a single record, with the engine's reasons for each. Whether a rule stops the run or
# leaves the record out follows from those reasons.
RECORD_RULES = {
    FACILITIES.name: (
        ("Each facility_id appears once. All copies of a repeated one are left out.", (Reason.DUPLICATE_FACILITY,)),
        ("Its obligor_id is in the Obligors file.", (Reason.ORPHAN_FACILITY,)),
        (f"currency is {CURRENCY}.", (Reason.MISSING_CURRENCY, Reason.NON_EUR_CURRENCY)),
        (f"accounting_category is {ON_BALANCE_CATEGORY}, amortised cost.",
         (Reason.MISSING_ACCOUNTING_CATEGORY, Reason.NON_AC_ON_BALANCE)),
        (("poci, accrued_in_gca, dpd, watchlist and forborne are filled in, and so is the borrower's "
         "regulatory_default."), (Reason.MISSING_FLAG,)),
        ("dpd is not negative.", (Reason.INVALID_DPD,)),
        ("credit_status_date is filled in and not after the snapshot date.", (Reason.INVALID_CREDIT_STATUS_DATE,)),
        ("poci is false: purchased or originated credit-impaired loans are not covered.", (Reason.POCI_NOT_IN_V1,)),
        ("The borrower is not a central bank.", (Reason.CENTRAL_BANK_NOT_IN_V1,)),
        ("segment has both rating transitions and parameters.", (Reason.UNKNOWN_SEGMENT,)),
        ("The borrower's country has values in the Scenarios file.", (Reason.UNMAPPED_COUNTRY,)),
        ("product is one of the listed values.", (Reason.UNKNOWN_PRODUCT,)),
        ("ifrs_stage is 1, 2 or 3.", (Reason.INVALID_STAGE,)),
        ("principal, accrued_interest, gca and contractual_limit are filled in.", (Reason.MISSING_AMOUNT,)),
        ("gca equals principal, plus accrued_interest when accrued_in_gca is true.",
         (Reason.GCA_COMPONENTS_MISMATCH,)),
        ("In Stage 1 or 2, interest_rate is filled in and above -100%.", (Reason.MISSING_RATE, Reason.INVALID_RATE)),
        ("In Stage 1 or 2, residual_maturity is filled in and above zero.", (Reason.INVALID_MATURITY,)),
        ("In Stage 1 or 2, repayment_profile is one of the listed values.", (Reason.UNKNOWN_REPAYMENT_PROFILE,)),
        ((f"current_grade and origination_grade are filled in and on the master scale, and origination_grade is "
         f"not {DEFAULT_GRADE}."), (Reason.MISSING_GRADE, Reason.UNKNOWN_GRADE)),
        ((f"Stage 3 is in grade {DEFAULT_GRADE} and Stages 1 and 2 are not. Stage 1 or 2 matches what the rating "
         "move and the qualitative triggers give: a Stage 1 loan on the watchlist is left out, not moved to "
         "Stage 2."), (Reason.STAGE_GRADE_CONFLICT,)),
        ("ttc_lgd is filled in and from 0 to 1.", (Reason.MISSING_TTC_LGD, Reason.TTC_LGD_OUT_OF_RANGE)),
        ("regulatory_default in the Obligors file is true exactly when the stage is 3.",
         (Reason.DEFAULT_STAGE_CONFLICT,)),
        ("It has a row in the Opening provisions file.", (Reason.MISSING_OPENING_PROVISION,)),
        (("A commitment or opening provision that is left out takes its loan with it, and a loan that is left "
         "out takes both of them."), (Reason.LINKED_RECORD_REJECTED,)),
        ("principal, accrued_interest, gca and contractual_limit are not negative.", (Reason.NEGATIVE_AMOUNT,)),
        ("principal plus the undrawn amount in the Commitments file does not exceed contractual_limit.",
         (Reason.LIMIT_BREACH,)),
    ),
    OBLIGORS.name: (
        ("Each obligor_id appears once. All copies of a repeated one are left out, with their loans.",
         (Reason.DUPLICATE_OBLIGOR,)),
    ),
    COMMITMENTS.name: (
        ("Each commitment_id appears once, and a loan has one commitment at most.", (Reason.DUPLICATE_COMMITMENT,)),
        ("nominal_undrawn is not negative.", (Reason.NEGATIVE_AMOUNT,)),
        ("accounting_ccf is filled in when nominal_undrawn is above zero.", (Reason.MISSING_CCF,)),
        ("accounting_ccf is from 0 to 1.", (Reason.CCF_OUT_OF_RANGE,)),
        ("facility_id is in the Facilities file.", (Reason.ORPHAN_COMMITMENT,)),
        (f"currency is {CURRENCY}.", (Reason.MISSING_CURRENCY, Reason.NON_EUR_CURRENCY)),
        (f"asset_category is {OFF_BALANCE_CATEGORY}.", (Reason.OFF_BALANCE_CATEGORY,)),
        ("nominal_undrawn is filled in.", (Reason.MISSING_AMOUNT,)),
        ("accounting_ccf equals the segment's ccf in the Parameters file.", (Reason.CCF_MISMATCH,)),
        (f"{_words(TERM_PRODUCTS)} are fully drawn, so they have no undrawn amount.",
         (Reason.UNDRAWN_ON_TERM_PRODUCT,)),
    ),
    OPENING_PROVISIONS.name: (
        ("Each facility_id appears once. All copies of a repeated one are left out.",
         (Reason.DUPLICATE_OPENING_PROVISION,)),
        ("facility_id is in the Facilities file.", (Reason.ORPHAN_OPENING_PROVISION,)),
        (f"currency is {CURRENCY}.", (Reason.MISSING_CURRENCY, Reason.NON_EUR_CURRENCY)),
        ("allowance_on, provision_off and overlay_amount are filled in.", (Reason.MISSING_AMOUNT,)),
        ("allowance_on, provision_off and overlay_amount are not negative.", (Reason.NEGATIVE_AMOUNT,)),
    ),
}

# A file that fails one of these stops the run, with the engine's block codes for each.
FILE_RULES = {
    FACILITIES.name: (
        ("facility_id is filled in.", (Block.MISSING_KEY,)),
        ("A segment belongs to one portfolio only.", (Block.PARAMETER_ALIGNMENT,)),
    ),
    OPENING_PROVISIONS.name: (
        ("facility_id is filled in.", (Block.MISSING_KEY,)),
    ),
    TTC_MATRIX.name: (
        ("Each file has every move from grade to grade once, and no probability is blank.",
         (Block.INVALID_MATRIX,)),
        ("All segments use the same grades, and they match the master scale in the Parameters file.",
         (Block.INVALID_MATRIX,)),
        (f"from_rank runs 1, 2, 3 and so on, with {DEFAULT_GRADE} last.", (Block.INVALID_MATRIX,)),
        ("The probabilities from each grade add up to 1, and none is negative.", (Block.INVALID_MATRIX,)),
        (f"{DEFAULT_GRADE} stays in {DEFAULT_GRADE} with probability 1.", (Block.INVALID_MATRIX,)),
        ("The one-year probability of default rises with every grade.", (Block.INVALID_MATRIX,)),
        (("Over a loan's lifetime, the grades past the Stage 2 line form one unbroken block at the weak end "
         "of the scale."), (Block.MATRIX_NOT_MONOTONE,)),
    ),
    SCENARIOS.name: (
        ("baseline is one of the scenarios, because the other scenarios revert toward it.",
         (Block.BASELINE_REQUIRED,)),
        (f"The set, each scenario in the run and that scenario's values have the status {SYNTHETIC}.",
         (Block.SCENARIO_PROVENANCE,)),
        (f"Each value has a unit, which is {_words(SCENARIO_UNITS, 'or')}.", (Block.SCENARIO_WITHOUT_UNIT,)),
        (f"value_type is {_words(SCENARIO_VALUE_TYPES, 'or')}.", (Block.BAD_VALUE_TYPE,)),
        ("No scenario, variable, country and year appears twice.", (Block.DUPLICATE_KEY,)),
        (("Each variable a segment's models read has a value for every country in the file, every projection year "
         "and every scenario in the run."), (Block.MISSING_SCENARIO_VALUE,)),
        ("Each yearly price change has a starting level in starting_values.", (Block.MISSING_SCENARIO_VALUE,)),
    ),
    PARAMETER_SET.name: (
        (f"Each segment states {_words(SEGMENT_PARAMETERS)}, and nothing else.", (Block.MISSING_PARAMETER,)),
        ("Each model it names is a model of its own portfolio in src/stress/models/, in the right role.",
         (Block.UNKNOWN_MODEL,)),
        ("Its ttc_matrix is a Rating transitions file of this set, under matrices/.", (Block.UNREADABLE_FILE,)),
        (("asset_correlation is from 0 to below 1, sicr_k is above 0, the LGD and prepayment models' "
          "sensitivities are 0 or more, and cpr_ttc is from 0 to 1."), (Block.MISSING_PARAMETER,)),
        (("The snapshot date in horizon equals snapshot_date in "
         f"{_labels((FACILITIES, OBLIGORS, COMMITMENTS, OPENING_PROVISIONS))}."), (Block.HORIZON_MISMATCH,)),
        ("The last projection year equals last_scenario_year in terminal_rule.", (Block.HORIZON_MISMATCH,)),
        ((f"In sicr_triggers, dpd_days is above 0, hold is {HOLD_UNTIL_DEFAULT}, and each trigger switched on "
         "has a definition."), (Block.MISSING_PARAMETER,)),
        ("variants has core, the variant the page runs by default.", (Block.UNKNOWN_VARIANT,)),
    ),
}

# Stated in EVERY_FILE and AFTER_YOU_ADD, because they apply to any file.
GENERAL_BLOCKS = (Block.UNREADABLE_FILE, Block.UNKNOWN_COLUMN, Block.MISSING_COLUMN, Block.BAD_VALUE_TYPE,
                  Block.EMPTY_PORTFOLIO)

# These pass the sanity checks, and the run then stops partway (TODO.md, input checks). The ones with no
# block code stop on a plain message or a crash.
LATE_RULES = {
    FACILITIES.name: (
        ((f"A secured loan has an ltv and a collateral_type of {_words(COLLATERAL_INDEX, 'or')}. An unsecured "
         "loan has both blank, with not_applicable in ltv__status, which is filled in on every row."), ()),
        ("residual_maturity reaches no further than last_bucket_year in the Parameters file.",
         (Block.MISSING_TERMINAL_INPUT,)),
    ),
    OBLIGORS.name: (
        ("counterparty_sector is filled in.", ()),
    ),
    SCENARIOS.name: (
        (("The file has starting_values and index_of, and index_of builds "
         f"{_words(sorted(set(COLLATERAL_INDEX.values())))}."), ()),
        (("The values keep the probability of default rising with the grade. A whole variable in the wrong scale "
         "can break this and stop the run. A single value can run instead, as the notice above says."),
         (Block.INVALID_PIT_MATRIX,)),
    ),
    PARAMETER_SET.name: (
        ("A segment you add has a template_class.", ()),
        ("The core variant gives a repayment profile for every product, or a default.", (Block.UNKNOWN_VARIANT,)),
    ),
}


def _column(spec: DatasetSpec, column: Column) -> dict:
    allowed = ALLOWED.get(spec.name, {}).get(column.name)
    return {"name": column.name, "kind": KINDS[column.kind], "meaning": MEANINGS[spec.name][column.name],
            "values": [str(value) for value in allowed] if allowed else None}


def _rules(name: str) -> list[dict]:
    """A file's rules: whole-file rules first, as the page lists them under each consequence."""
    rules = [{"text": text, "effect": STOPS} for text, _ in FILE_RULES.get(name, ())]
    rules += [{"text": text, "effect": STOPS if reasons[0] in RUN_BLOCKING_REASONS else LEFT_OUT}
              for text, reasons in RECORD_RULES.get(name, ())]
    return rules + [{"text": text, "effect": LATE} for text, _ in LATE_RULES.get(name, ())]


def step_one() -> dict:
    """The guide: what every file follows, what happens to a file, and each file in the page's order."""
    files = []
    for spec in GUIDED:
        label, holds = FILE_GUIDE[spec.name]
        table = spec is TTC_MATRIX or spec in TABLE_DATASETS
        files.append({"name": spec.name, "label": label, "format": "Parquet table" if table else "YAML file",
                      "holds": holds, "warning": WARNINGS.get(spec.name),
                      "columns": [_column(spec, column) for column in spec.columns] if table else None,
                      "sections": None if table else [{"name": name, "holds": text}
                                                      for name, text in SECTIONS[spec.name].items()],
                      "rules": _rules(spec.name)})
    return {"every_file": list(EVERY_FILE), "after_you_add": list(AFTER_YOU_ADD), "files": files}
