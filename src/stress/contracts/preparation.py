"""Keys and required values for optional preparation tables handed between pipeline steps."""

import pandas as pd

from stress.contracts.tables import TableSpec

# Paragraph 69: lending for house purchase follows residential prices, CRE loans follow CRE prices,
# residential rental included (A31).
COLLATERAL_INDEX = {"residential_property": "residential_price_index", "residential_rental": "cre_price_index",
                    "office": "cre_price_index", "retail": "cre_price_index", "industrial": "cre_price_index"}


def price_growth(indices: pd.DataFrame) -> pd.DataFrame:
    """The scenario's price indices as growth since the snapshot."""
    out = indices.sort_values(["scenario", "country", "variable", "year"]).copy()
    out["growth"] = (1.0 + out["annual_change"]).groupby([out["scenario"], out["country"], out["variable"]]).cumprod()
    return out


def spec(name, keys, columns):
    return TableSpec(name, f"analysis_{name}.parquet", tuple(keys.split()), tuple(columns.split()))


ANALYSES = {
    "calibration": spec("calibration", "segment grade", "anchor_pd cycle_pd_quadrature cycle_pd_analytic difference cycle_to_anchor assumption"),
    "sicr_horizon": spec("sicr_horizon", "facility_id valuation_year", "remaining_maturity generation segment origination_rank opening_horizon_rank remaining_horizon_rank changed"),
    "benchmark_selection": spec("benchmark_selection", "country pivot family scenario year exposure_id parameter", "gca model_coverage source source_version value"),
    "recovery_lgd": spec("recovery_lgd", "facility_id", "model_version net_recovery present_value lgd"),
    "capital": spec("capital", "scenario year", "opening_cet1 credit_charge profit_after_tax raw_credit_rea floored_credit_rea utrea strea total_rea cet1 cet1_ratio basis other_pnl tax_rate distributions irb_shortfall_change npl_deduction_change other_cet1_change other_utrea other_strea output_floor_factor"),
    "regulatory_exposure": spec("regulatory_exposure", "scenario year facility_id slice", "grade regulatory_approach regulatory_class regulatory_ccf regulatory_ead standardised_ccf standardised_ead risk_weight standardised_risk_weight raw_rea standardised_rea model_version"),
    "climate": spec("climate", "facility_id channel scenario year", "nace_code energy_bucket geolocation flood_category model_version gca reference_provision shock_provision incremental_before_insurance insurance_recovery incremental_after_insurance incremental_charge_after_insurance basis"),
    "sensitivity": spec("sensitivity", "severity", "loss z basis"),
    "reverse_stress": spec("reverse_stress", "limit_name", "status severity loss loss_limit_eur basis"),
    "loss_weighted_lgd": spec("loss_weighted_lgd", "scenario valuation_year portfolio stage", "numerator denominator loss_weighted_lgd"),
    "npe_backstop": spec("npe_backstop", "scenario year portfolio", "gca_in_scope unsecured_part secured_part minimum_coverage provisions capped_provisions insufficient_coverage insufficient_coverage_change calendar_version basis"),
}

ANALYSIS_RATES = {
    "calibration": ("anchor_pd", "cycle_pd_quadrature", "cycle_pd_analytic", "difference", "cycle_to_anchor"),
    "sicr_horizon": ("remaining_maturity",),
    "benchmark_selection": ("model_coverage", "value"),
    "recovery_lgd": ("lgd",),
    "capital": ("tax_rate", "output_floor_factor", "cet1_ratio"),
    "regulatory_exposure": ("regulatory_ccf", "standardised_ccf", "risk_weight", "standardised_risk_weight"),
    "climate": (),
    "sensitivity": ("severity", "z"),
    "reverse_stress": ("severity",),
    "concentration": ("gca_share", "hhi_contribution"),
    "mapped_cells": ("value",),
    "ltv": ("average_ltv", "share_above_100"),
    "maturity": ("average_maturity",),
    "template_replica": ("tr12", "tr21", "pd12m_s1", "pd12m_s2", "lgd_s1", "lgd_s2", "lrlt_s2", "loss_rate_s1_next",
                         "gap_s1", "gap_s2", "gap_s3_new", "gap_s3_old"),
    "loss_weighted_lgd": ("loss_weighted_lgd",),
}
