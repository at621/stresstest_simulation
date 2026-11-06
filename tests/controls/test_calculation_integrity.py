"""Regression controls for absent buckets and malformed input values."""

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from stress.contracts.errors import BlockingError
from stress.contracts.inputs import segments_of
from stress.ecl import _dense
from stress.ingest import _cast, attach_models
from stress.models.forms import z_score
from stress.validate import _check_parameters


@pytest.mark.req("ECL-08", "MOD-06")
@pytest.mark.parametrize("buckets", [[1, 3], [1, 2], [1, 2, 2, 3], [0, 1, 2]])
def test_facility_parameter_coverage_is_exact(buckets):
    schedule = pd.DataFrame({"facility_id": ["F"] * 3, "period": [1, 2, 3],
                             "fraction": [1.0] * 3, "bucket_year": [2027, 2028, 2029]})
    rows = pd.DataFrame({"facility_id": ["F"] * len(buckets), "default_bucket": buckets,
                         "fraction": 1.0, "bucket_year": [2026 + k for k in buckets],
                         "ead_drawn": 1.0, "ead_undrawn": 0.0, "lgd": 1.0,
                         "discount_factor": 1.0})
    with pytest.raises(BlockingError):
        _dense(rows, np.array(["F"]), schedule)


@pytest.mark.req("DAT-02")
def test_boolean_strings_do_not_use_python_truthiness():
    values = _cast(pd.Series(["False", "true", "0", "1", None]), "bool", "flag", "test")
    assert values.tolist() == [False, True, False, True, None]


@pytest.mark.req("DAT-02")
@pytest.mark.parametrize("kind,value", [("bool", "maybe"), ("bool", 2),
                                        ("date", "2026-02-30"), ("float", np.inf)])
def test_invalid_typed_values_block(kind, value):
    with pytest.raises(BlockingError):
        _cast(pd.Series([value]), kind, "field", "test")


@pytest.mark.req("SYN-PAR-06")
@pytest.mark.parametrize("name,value", [("cpr_ttc", 1.2), ("cpr_v", -1),
                                        ("lgd_w", -1), ("sicr_k", np.nan), ("rho", np.inf)])
def test_parameter_domain_rejected_before_projection(name, value):
    path = Path(__file__).parents[2] / "foundation/parameter_set.yaml"
    ps = copy.deepcopy(yaml.safe_load(path.read_text(encoding="utf-8")))
    ps["segments"] = segments_of(ps)
    for settings in ps["segments"].values():
        settings.update(ttc_matrix="matrices/x.parquet", ccf=None)
    attach_models(ps)
    ps["segments"][next(iter(ps["segments"]))][name] = value
    with pytest.raises(BlockingError):
        _check_parameters(ps, set(ps["segments"]), "core")


@pytest.mark.req("SCN-08")
def test_nonfinite_scenario_value_blocks():
    with pytest.raises(BlockingError):
        z_score({"x": np.nan}, {"x": {"beta": 1.0, "mean": 0.0, "sd": 1.0}})
