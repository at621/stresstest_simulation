"""The trough reading of LGD (C16): collateral at its lowest holds LGD up for property-secured books."""

import numpy as np
import pandas as pd
import pytest

from stress import cli
from stress.contracts.run import LGD_TROUGH, RunConfig
from stress.params import lgd_drivers
from stress.params.lgd import lgd_from_z
from tests import builders


def z_table() -> pd.DataFrame:
    rows = []
    paths = {("P01", "adverse"): (-1.5, -1.3, -0.6, -0.5), ("P02", "adverse"): (-1.0, -0.8, -0.4, -0.3),
             ("P01", "baseline"): (0.1, 0.2, 0.3, 0.3), ("P02", "baseline"): (0.0, 0.1, 0.2, 0.2)}
    for (segment, scenario), values in paths.items():
        for year, value in zip((2027, 2028, 2029, 2030), values):
            rows.append({"segment": segment, "country": "DE", "scenario": scenario, "year": year, "z": value,
                         "adverse_weight": 5 / 6 if year == 2030 and scenario == "adverse" else 1.0})
    return pd.DataFrame(rows)


PS = {"horizon": {"projection_years": [2027, 2028, 2029]}, "terminal_rule": {"last_scenario_year": 2029}}


@pytest.mark.req("LGD-12")
def test_the_trough_joins_the_linear_reversion_of_the_parameters(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "inputs")
    config = RunConfig(str(inputs), ("baseline", "adverse"), "core", lgd_path=LGD_TROUGH,
                       terminal_treatment="parameters")
    ctx, manifest = cli.execute(config, tmp_path / "runs")
    assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
    z = builders.result(ctx, "drivers.parquet")
    z = z[(z["segment"] == "P04") & (z["model"] == "lgd")]
    tables = builders.load(inputs)
    facts = tables["facilities"].merge(tables["obligors"][["obligor_id", "country"]], on="obligor_id")
    fac = facts[facts["segment"] == "P04"].iloc[0]
    rule = tables["parameter_set"]["terminal_rule"]
    last = rule["last_scenario_year"]
    first = tables["parameter_set"]["horizon"]["projection_years"][0]
    path = z[(z["country"] == fac["country"]) & (z["scenario"] == "adverse") & z["year"].between(first, last)]
    end = z[(z["country"] == fac["country"]) & (z["scenario"] == "baseline") & (z["year"] == last)]["z"].iloc[0]
    w = builders.segments(tables)["P04"]["lgd_w"]
    params = builders.result(ctx, "parameters.parquet")
    rows = params[(params["facility_id"] == fac["facility_id"]) & (params["scenario"] == "adverse")
                  & (params["bucket_year"] > last)]
    assert len(rows)
    a = np.clip(1 - (rows["bucket_year"].to_numpy() - last) / rule["reversion_years"], 0, 1)
    expected = (a * lgd_from_z(fac["ttc_lgd"], w, path["z"].min()) + (1 - a) * lgd_from_z(fac["ttc_lgd"], w, end))
    assert np.allclose(rows["lgd"], expected, rtol=0, atol=1e-12), "the worst Z, not 2029's, is where it reverts from"


def value(table, segment, scenario, year):
    picked = table[(table["segment"] == segment) & (table["scenario"] == scenario) & (table["year"] == year)]
    return float(picked["z"].iloc[0])


@pytest.mark.req("LGD-12")
def test_a_secured_adverse_book_keeps_its_worst_z_then_reverts_from_it():
    z = z_table()
    out = lgd_drivers(z, PS, {"P01"})
    for year in (2027, 2028, 2029):
        assert value(out, "P01", "adverse", year) == pytest.approx(-1.5)
    assert value(out, "P01", "adverse", 2030) == pytest.approx(5 / 6 * -1.5 + 1 / 6 * 0.3)
    assert value(out, "P02", "adverse", 2028) == value(z, "P02", "adverse", 2028), "an unsecured book keeps its Z"
    assert value(out, "P01", "baseline", 2028) == value(z, "P01", "baseline", 2028), "baseline prices do not fall"
    assert z["z"].tolist() == z_table()["z"].tolist(), "the Z of PD and prepayment is left alone"


@pytest.mark.req("LGD-12")
def test_a_number_marked_missing_is_not_read_as_an_ltv(mini, tmp_path):
    mortgages = mini["facilities"]["segment"] == "P01"
    mini["facilities"].loc[mortgages[mortgages].index[0], "ltv__status"] = "missing"
    config = RunConfig(str(builders.write(mini, tmp_path / "inputs")), ("baseline", "adverse"), "core",
                       lgd_path=LGD_TROUGH)
    _, manifest = cli.execute(config, tmp_path / "runs")
    assert manifest["status"] == "BLOCKED" and "no usable LTV" in manifest["blocked"]["message"]


@pytest.mark.req("LGD-12")
def test_the_trough_moves_only_secured_adverse_lgd(mini_tables, tmp_path):
    inputs = builders.write(builders.copy_tables(mini_tables), tmp_path / "inputs")

    def execute(name, **options):
        ctx, manifest = cli.execute(RunConfig(str(inputs), ("baseline", "adverse"), "core", **options), tmp_path / name)
        assert manifest["status"] == "SYNTHETIC", manifest.get("blocked")
        return ctx

    base, trough = execute("base"), execute("trough", lgd_path=LGD_TROUGH)
    a, b = (builders.result(c, "lgd_of_year.parquet").set_index(["scenario", "year", "facility_id"]).sort_index()
            for c in (base, trough))
    p04 = a.index.get_level_values("facility_id").isin(
        builders.load(inputs)["facilities"].query("segment == 'P04'")["facility_id"])
    adverse = a.index.get_level_values("scenario") == "adverse"
    assert np.allclose(a.loc[~adverse, "lgd"], b.loc[~adverse, "lgd"], rtol=1e-12), "baseline does not move"
    assert (b.loc[adverse & p04, "lgd"] >= a.loc[adverse & p04, "lgd"] - 1e-12).all()
    assert (b.loc[adverse & p04, "lgd"] > a.loc[adverse & p04, "lgd"]).any()
    p05 = a.index.get_level_values("facility_id").isin(
        builders.load(inputs)["facilities"].query("segment == 'P05'")["facility_id"])
    assert np.allclose(a.loc[p05, "lgd"], b.loc[p05, "lgd"], rtol=1e-12), "an unsecured book does not move"
    curves = [builders.result(c, "pd_curves.parquet")["m"].to_numpy() for c in (base, trough)]
    assert np.array_equal(*curves), "PD keeps its own Z"
    params = [builders.result(c, "parameters.parquet") for c in (base, trough)]
    for column in ("prepayment_rate", "not_prepaid_share", "ead_drawn", "ead_undrawn"):
        assert np.array_equal(params[0][column].to_numpy(), params[1][column].to_numpy()), f"{column} keeps its Z"
    grades = [builders.result(c, "slices.parquet")["gca"].to_numpy() for c in (base, trough)]
    assert np.array_equal(*grades), "stages do not move"
    assert "LGD path trough" in (trough.reports_dir / "summary.md").read_text(encoding="utf-8")
