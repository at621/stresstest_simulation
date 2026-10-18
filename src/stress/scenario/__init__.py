"""R4 scenarios and Z-score: compound property indices, standardise the drivers and combine
them into one Z per segment, country, year and scenario. Extend Z past 2029 by the
terminal rule.

SCN-01–SCN-05, SCN-08, ECL-10.
"""

import logging

import pandas as pd

from stress.contracts.errors import Block, BlockingError
from stress.contracts.inputs import SYNTHETIC, LoadedInputs
from stress.contracts.run import BASELINE, RunContext
from stress.contracts.tables import (
    DRIVER_CONTRIBUTIONS,
    INDICES,
    Z_SCORES,
    Z_SOURCE_FLAT,
    Z_SOURCE_PATH,
    Z_SOURCE_REVERSION,
    Drivers,
)
from stress.scenario.kernels import STEP, adverse_weight, compound_index, reverted_z, z_score

LOG = logging.getLogger("stress.R4")


def check_provenance(meta: dict, values: pd.DataFrame, requested: tuple[str, ...]) -> None:
    """SCN-04 and the section 12.2 scenario-provenance control: in a synthetic run every
    scenario and value must be labelled SYNTHETIC; a synthetic scenario labelled official
    blocks."""
    known = {s["id"]: s for s in meta["scenarios"]}
    for name in requested:
        if name not in known:
            raise BlockingError(STEP, Block.UNKNOWN_SCENARIO, f"scenario {name!r} is not in the input set")
        scenario = known[name]
        if scenario.get("source_type") == "synthetic" and scenario.get("status") != SYNTHETIC:
            raise BlockingError(STEP, Block.SCENARIO_PROVENANCE,
                                f"synthetic scenario {name!r} is labelled {scenario.get('status')!r}")
        if scenario.get("status") != SYNTHETIC:
            raise BlockingError(STEP, Block.SCENARIO_PROVENANCE,
                                f"scenario {name!r} is not SYNTHETIC; v1 runs synthetic inputs only")
    used = values[values["scenario"].isin(requested)]
    if (used["status"] != SYNTHETIC).any():
        raise BlockingError(STEP, Block.SCENARIO_PROVENANCE, "a scenario value is not labelled SYNTHETIC")
    if meta.get("status") != SYNTHETIC:
        raise BlockingError(STEP, Block.SCENARIO_PROVENANCE, "the scenario set is not labelled SYNTHETIC")


def build_drivers(loaded: LoadedInputs, ctx: RunContext) -> Drivers:
    ps = loaded.parameter_set
    values = loaded.scenario_values
    requested = tuple(ctx.scenarios)
    check_provenance(loaded.scenario_meta, values, requested)
    if any(s != BASELINE for s in requested) and BASELINE not in requested:
        raise BlockingError(STEP, Block.BASELINE_REQUIRED,
                            "adverse Z reverts toward baseline 2029, so baseline must run too (ECL-10)")
    years = [int(y) for y in ps["horizon"]["projection_years"]]
    rule = ps["terminal_rule"]
    last = int(rule["last_scenario_year"])
    reversion = int(rule["reversion_years"])
    last_bucket = int(ps["horizon"]["last_bucket_year"])
    if max(years) != last:
        raise BlockingError(STEP, Block.HORIZON_MISMATCH, "terminal rule and projection years disagree")
    countries = sorted(values["country"].unique())
    index = {(r.scenario, r.variable, r.country, r.year): (r.value, r.value_status)
             for r in values.itertuples(index=False)}
    order = [BASELINE] + [s for s in requested if s != BASELINE] if BASELINE in requested else list(requested)

    z_rows, contrib_rows = [], []
    z_last: dict[tuple[str, str, str], float] = {}
    for scenario in order:
        for segment in sorted(ps["segments"]):
            drivers = ps["segments"][segment]["z_drivers"]
            for country in countries:
                for year in years:
                    x = {}
                    for name in drivers:
                        value, status = index.get((scenario, name, country, year), (None, "missing"))
                        x[name] = None if status == "missing" else value
                    where = f"for {segment}/{country}/{scenario}/{year}"
                    z, parts = z_score(x, drivers, where)
                    z_rows.append((segment, country, scenario, year, z, Z_SOURCE_PATH, 1.0))
                    for name, part in parts.items():
                        coef = drivers[name]
                        contrib_rows.append((segment, country, scenario, year, name, x[name],
                                             coef["mean"], coef["sd"], coef["beta"], part))
                    if year == last:
                        z_last[(segment, country, scenario)] = z
                for year in range(last + 1, last_bucket + 1):
                    if scenario == BASELINE:
                        z = z_last[(segment, country, BASELINE)]
                        z_rows.append((segment, country, scenario, year, z, Z_SOURCE_FLAT, 1.0))
                    else:
                        a = adverse_weight(year, last, reversion)
                        z = reverted_z(year, z_last[(segment, country, scenario)],
                                       z_last[(segment, country, BASELINE)], last, reversion)
                        source = Z_SOURCE_REVERSION if a > 0 else Z_SOURCE_FLAT
                        z_rows.append((segment, country, scenario, year, z, source, a))
    z_table = pd.DataFrame(z_rows, columns=list(Z_SCORES.all_columns))
    contributions = pd.DataFrame(contrib_rows, columns=list(DRIVER_CONTRIBUTIONS.all_columns))
    LOG.info("scenario provenance checked: %s, all SYNTHETIC", ", ".join(requested))
    for scenario in order:
        path = z_table[(z_table["scenario"] == scenario) & z_table["year"].isin(years)]
        by_year = path.groupby("year")["z"].mean()
        LOG.info("%s Z by year (mean over %d segments): %s", scenario, len(ps["segments"]),
                 ", ".join(f"{y} {v:+.2f}" for y, v in by_year.items()))
    LOG.info("Z extended to %d by the terminal rule: adverse reverts to baseline %d over %d years",
             last_bucket, last, reversion)
    indices = property_indices(loaded, requested, years)
    for (scenario, variable), part in indices[indices["year"] == last].groupby(["scenario", "variable"]):
        LOG.info("%s %s %d: %.3f", scenario, variable, last, part["index"].mean())
    return Drivers(
        z=Z_SCORES.check(z_table, STEP).sort_values(list(Z_SCORES.key)).reset_index(drop=True),
        contributions=DRIVER_CONTRIBUTIONS.check(contributions, STEP)
        .sort_values(list(DRIVER_CONTRIBUTIONS.key)).reset_index(drop=True),
        indices=indices,
    )


def property_indices(loaded: LoadedInputs, scenarios: tuple[str, ...], years: list[int]) -> pd.DataFrame:
    """Compound each annual property price change into an index from its starting level."""
    meta = loaded.scenario_meta
    index_of = meta.get("index_of", {})
    starting = {(s["variable"], s["country"]): s["value"] for s in meta.get("starting_values", [])}
    values = loaded.scenario_values
    rows = []
    for scenario in scenarios:
        for change_var, index_var in sorted(index_of.items()):
            for country in sorted(values["country"].unique()):
                sel = values[(values["scenario"] == scenario) & (values["variable"] == change_var)
                             & (values["country"] == country)].set_index("year")
                if sel.empty:
                    continue
                if (index_var, country) not in starting:
                    raise BlockingError(STEP, Block.MISSING_SCENARIO_VALUE,
                                        f"no starting level for {index_var} in {country}")
                if any(y not in sel.index for y in years) or sel.loc[years, "value"].isna().any():
                    raise BlockingError(STEP, Block.MISSING_SCENARIO_VALUE,
                                        f"{change_var} missing for {scenario}/{country}")
                changes = [float(sel.loc[y, "value"]) for y in years]
                levels = compound_index(changes, starting[(index_var, country)])
                for year, change, level in zip(years, changes, levels):
                    rows.append((scenario, country, index_var, year, change, level))
    table = pd.DataFrame(rows, columns=list(INDICES.all_columns))
    return INDICES.check(table, STEP).sort_values(list(INDICES.key)).reset_index(drop=True)
