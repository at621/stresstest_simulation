"""Command line: stress run · stress report.

The only module that wires the pipeline steps together, in order R1 to R11.

    stress run --inputs inputs/<hash> --scenarios baseline,adverse --variant core
    stress report --run runs/<run_id>
    stress rerun --run runs/<run_id>      rerun from the manifest, compare output hashes
    stress compare --base runs/<a> --new runs/<b>
"""

import argparse
import logging
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from stress import (
    accounting,
    cashflows,
    ecl,
    ingest,
    lineage,
    projection,
    report,
    scenario,
    validate,
)
from stress import params as parameters
from stress.contracts.errors import BlockingError
from stress.contracts.run import MODE_SYNTHETIC, MODES, REPORTS_DIR, RESULTS_DIR, RUN_LOG, RunConfig
from stress.contracts.tables import (
    CHARGES,
    DRIVER_CONTRIBUTIONS,
    ECL_BUCKETS,
    GRADE_FLOWS,
    INDICES,
    LGD_OF_YEAR,
    PARAMETERS,
    PD_CURVES,
    PIT_MATRICES,
    PROVISIONS,
    REJECTIONS,
    SCHEDULE,
    SLICES,
    STAGE_FLOWS,
    Z_SCORES,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2
EXIT_NOT_REPRODUCED = 3

LOG = logging.getLogger("stress")
FILE_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)-10s %(message)s"
CONSOLE_FORMAT = "%(name)-10s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
STEPS = {
    "R1": "open the run", "R2": "load inputs", "R3": "validate and route",
    "R4": "scenarios and Z-score", "R5": "generate cash flows", "R6": "build parameters",
    "R7": "project the year", "R8": "year-end provisions", "R9": "stock to flow",
    "R10": "aggregate and report", "R11": "seal the run",
}


@contextmanager
def step(code: str, detail: str = ""):
    """Log a step's start and end with its duration; a failure is logged by ``execute``."""
    log = logging.getLogger(f"stress.{code}")
    log.info("start: %s%s", STEPS[code], f" ({detail})" if detail else "")
    began = time.perf_counter()
    yield log
    log.info("done in %.1f s", time.perf_counter() - began)


def attach_run_log(ctx) -> logging.Handler:
    """Every log line of this run, with times, goes to runs/<run_id>/run.log."""
    handler = logging.FileHandler(ctx.run_dir / RUN_LOG, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FILE_FORMAT, DATE_FORMAT))
    handler.setLevel(logging.DEBUG)
    LOG.addHandler(handler)
    LOG.setLevel(logging.DEBUG)
    return handler


def detach(handler: logging.Handler) -> None:
    LOG.removeHandler(handler)
    handler.close()


@contextmanager
def console_logging(quiet: bool):
    """Progress on stderr while a command runs; stdout keeps the result lines."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    handler.setLevel(logging.WARNING if quiet else logging.INFO)
    LOG.addHandler(handler)
    LOG.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        LOG.removeHandler(handler)


def _sorted(df: pd.DataFrame, spec) -> pd.DataFrame:
    return df.sort_values(list(spec.key), kind="mergesort").reset_index(drop=True)


def pipeline(ctx) -> dict:
    """R2-R10 for one opened run; returns the report summary for the manifest."""
    with step("R2"):
        loaded = ingest.load_inputs(ctx)
    ps = loaded.parameter_set
    ctx.lineage["parameter_set"] = {k: ps.get(k) for k in ("parameter_set_id", "version", "status")}
    ctx.lineage["load_controls"] = loaded.load_controls["rows"]

    with step("R3"):
        routed = validate.validate_and_route(loaded, ctx)
        lineage.write_table(ctx, REJECTIONS.filename, routed.rejections)
        validate.raise_if_blocking(routed.rejections)
    ctx.lineage["rejections"] = {
        "records": len(routed.rejections),
        "facilities": int(routed.rejections.loc[routed.rejections["record_type"] == "facility",
                                                "record_id"].nunique()),
    }

    with step("R4", ", ".join(ctx.scenarios)):
        drivers = scenario.build_drivers(loaded, ctx)
        lineage.write_table(ctx, Z_SCORES.filename, drivers.z)
        lineage.write_table(ctx, DRIVER_CONTRIBUTIONS.filename, drivers.contributions)
        lineage.write_table(ctx, INDICES.filename, drivers.indices)

    with step("R5", f"variant {ctx.variant}"):
        schedule = cashflows.build_schedules(routed.portfolio, ps, ctx.variant)
        lineage.write_table(ctx, SCHEDULE.filename, schedule)

    with step("R6", "baseline first: adverse reverts toward it"):
        params = parameters.build_parameters(routed, schedule, drivers, loaded, ctx)
        lineage.write_table(ctx, PIT_MATRICES.filename, params.pit)
        lineage.write_table(ctx, PD_CURVES.filename, params.pd_curves)
        lineage.write_table(ctx, PARAMETERS.filename, params.facility)
        lineage.write_table(ctx, LGD_OF_YEAR.filename, params.lgd_of_year)

    tol = ps["tolerances"]["aggregate"]
    start = int(ps["horizon"]["snapshot_year"])
    years = [int(y) for y in ps["horizon"]["projection_years"]]
    last = int(ps["terminal_rule"]["last_scenario_year"])
    generations = schedule.drop_duplicates(["facility_id", "valuation_year"])
    out = {name: [] for name in ("slices", "stage_flows", "grade_flows", "provisions", "ecl_buckets", "charges")}
    for name in parameters.scenario_order(ctx.scenarios):
        state = projection.opening_slices(routed.portfolio, routed.grades, start, name)
        with step("R8", f"{name} {start}, diagnostic of the opening"):
            opening = ecl.year_end_provisions(state, params, drivers.z, routed.portfolio, name, start,
                                              routed.grades, last, opening=True)
        out["slices"].append(state)
        out["provisions"].append(opening.provisions)
        out["ecl_buckets"].append(opening.ecl_buckets)
        for year in years:
            pit = params.pit[(params.pit["scenario"] == name) & (params.pit["year"] == year)]
            gen = generations[generations["valuation_year"] == year].set_index("facility_id")["generation"]
            with step("R7", f"{name} {year}"):
                moved = projection.project_year(state, pit, routed.portfolio, routed.grades, year,
                                                name, gen, tol)
            with step("R8", f"{name} {year}"):
                provided = ecl.year_end_provisions(moved.slices, params, drivers.z, routed.portfolio,
                                                   name, year, routed.grades, last)
            with step("R9", f"{name} {year}"):
                charges = accounting.stock_to_flow(state, provided.slices, routed.portfolio, name, year)
            for key, table in (("slices", provided.slices), ("stage_flows", moved.stage_flows),
                               ("grade_flows", moved.grade_flows), ("provisions", provided.provisions),
                               ("ecl_buckets", provided.ecl_buckets), ("charges", charges)):
                out[key].append(table)
            state = provided.slices
    results = {
        "slices": _sorted(pd.concat(out["slices"], ignore_index=True), SLICES),
        "stage_flows": _sorted(pd.concat(out["stage_flows"], ignore_index=True), STAGE_FLOWS),
        "grade_flows": _sorted(pd.concat(out["grade_flows"], ignore_index=True), GRADE_FLOWS),
        "provisions": _sorted(pd.concat(out["provisions"], ignore_index=True), PROVISIONS),
        "ecl_buckets": _sorted(pd.concat(out["ecl_buckets"], ignore_index=True), ECL_BUCKETS),
        "charges": _sorted(pd.concat(out["charges"], ignore_index=True), CHARGES),
    }
    for key, spec in (("slices", SLICES), ("stage_flows", STAGE_FLOWS), ("grade_flows", GRADE_FLOWS),
                      ("provisions", PROVISIONS), ("ecl_buckets", ECL_BUCKETS), ("charges", CHARGES)):
        lineage.write_table(ctx, spec.filename, results[key])

    with step("R10"):
        return report.build_reports(ctx, loaded, routed, drivers, schedule, params, results)


def execute(config: RunConfig, runs_dir: Path) -> tuple[object, dict]:
    """R1, the pipeline, then R11. A blocking error still seals the run, as BLOCKED."""
    try:
        ctx = lineage.open_run(config, runs_dir)  # R1
    except BlockingError as exc:
        logging.getLogger("stress.R1").error("blocked: %s: %s", exc.code, exc.message)
        raise
    handler = attach_run_log(ctx)
    log = logging.getLogger("stress.R1")
    log.info("run %s opened in %s", ctx.run_id, ctx.run_dir.as_posix())
    log.info("input set %s; scenarios %s; variant %s; mode %s; status label %s",
             ctx.input_set_hash[:16], ", ".join(ctx.scenarios), ctx.variant, ctx.config.mode,
             ctx.status_label)
    log.info("code %s; spec version %s", ctx.code_version, ctx.spec_version)
    began = time.perf_counter()
    blocked = None
    trace = None
    summary = None
    try:
        summary = pipeline(ctx)
    except BlockingError as exc:
        blocked = exc
        logging.getLogger(f"stress.{exc.step}").error("BLOCKED %s: %s", exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 - an engine fault must not leave an unsealed folder
        trace = traceback.format_exc()
        blocked = BlockingError("engine", "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")
        LOG.error("engine fault, run sealed as BLOCKED:\n%s", trace)
    seal = logging.getLogger("stress.R11")
    seal.info("sealing the run as %s after %.1f s", "BLOCKED" if blocked else ctx.status_label,
              time.perf_counter() - began)
    detach(handler)  # the log is complete before R11 hashes it
    manifest = lineage.seal_run(ctx, blocked=blocked, summary=summary)  # R11
    seal.info("sealed: %d outputs, digest %s", len(manifest["outputs"]), manifest["outputs_digest"][:16])
    if trace:
        manifest["traceback"] = trace
    return ctx, manifest


def _print_result(ctx, manifest: dict) -> int:
    print(f"run {ctx.run_id}: {manifest['status']}")
    print(f"folder {ctx.run_dir.as_posix()}")
    if "blocked" in manifest:
        b = manifest["blocked"]
        print(f"blocked at {b['step']}: {b['code']}: {b['message']}", file=sys.stderr)
        if "traceback" in manifest:  # already in the log and on the console
            return EXIT_ERROR
        return EXIT_BLOCKED
    summary = manifest.get("summary", {})
    for line in summary.get("headline", []):
        print(line)
    return EXIT_OK


def cmd_run(args) -> int:
    config = RunConfig(
        inputs=Path(args.inputs).as_posix(),
        scenarios=tuple(s.strip() for s in args.scenarios.split(",") if s.strip()),
        variant=args.variant, mode=args.mode,
    )
    try:
        ctx, manifest = execute(config, Path(args.runs_dir))
    except BlockingError:  # blocked before a run folder exists (R1); already logged
        return EXIT_BLOCKED
    return _print_result(ctx, manifest)


def cmd_report(args) -> int:
    run_dir = Path(args.run)
    manifest = lineage.read_manifest(run_dir)
    summary = run_dir / RESULTS_DIR / REPORTS_DIR / report.SUMMARY_FILE
    print(f"run {manifest['run_id']}: {manifest['status']}")
    if summary.exists():
        sys.stdout.write(summary.read_text(encoding="utf-8"))
    elif "blocked" in manifest:
        b = manifest["blocked"]
        print(f"blocked at {b['step']}: {b['code']}: {b['message']}")
    return EXIT_OK


def cmd_rerun(args) -> int:
    """Reproducibility control: same approved inputs and assumptions, same output hashes."""
    run_dir = Path(args.run)
    first = lineage.read_manifest(run_dir)
    cfg = first["config"]
    config = RunConfig(inputs=cfg["inputs"], scenarios=tuple(cfg["scenarios"]),
                       variant=cfg["variant"], mode=cfg.get("mode", MODE_SYNTHETIC))
    runs_dir = Path(args.runs_dir) if args.runs_dir else run_dir.parent
    ctx, second = execute(config, runs_dir)
    differing = lineage.compare_outputs(first, second)
    print(f"rerun {ctx.run_id}: {second['status']}")
    if differing or first["status"] != second["status"]:
        print(f"NOT reproduced: {len(differing)} output(s) differ", file=sys.stderr)
        for name in differing:
            print(f"  {name}", file=sys.stderr)
        return EXIT_NOT_REPRODUCED
    print(f"reproduced: all {len(first['outputs'])} output hashes identical to {first['run_id']}")
    return EXIT_OK


def cmd_compare(args) -> int:
    """Version-change control: a quantified difference report between two sealed runs."""
    table = report.compare_runs(Path(args.base), Path(args.new))
    with pd.option_context("display.width", 160, "display.max_rows", 200):
        print(table.to_string(index=False))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stress",
        description="Deterministic credit stress-test engine (EBA 2027 preparation). "
                    "v1 runs in synthetic mode only; regulatory mode blocks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run R1-R11 on one input set")
    run.add_argument("--inputs", required=True, help="input set folder, inputs/<hash>")
    run.add_argument("--scenarios", default="baseline,adverse",
                     help="comma-separated scenarios (default: baseline,adverse)")
    run.add_argument("--variant", default="core", help="core, annuity, linear or utilisation")
    run.add_argument("--mode", default=MODE_SYNTHETIC, choices=MODES,
                     help="synthetic (default); regulatory blocks in v1")
    run.add_argument("--runs-dir", default="runs", help="where run folders go (default: runs)")
    run.add_argument("-q", "--quiet", action="store_true",
                     help="console shows warnings only; runs/<run_id>/run.log keeps every line")
    run.set_defaults(func=cmd_run)
    rep = sub.add_parser("report", help="print the summary report of a sealed run")
    rep.add_argument("--run", required=True, help="run folder, runs/<run_id>")
    rep.set_defaults(func=cmd_report)
    rer = sub.add_parser("rerun", help="rerun a sealed run from its manifest and compare hashes")
    rer.add_argument("--run", required=True)
    rer.add_argument("--runs-dir", default=None)
    rer.add_argument("-q", "--quiet", action="store_true")
    rer.set_defaults(func=cmd_rerun)
    cmp = sub.add_parser("compare", help="quantified difference report between two runs")
    cmp.add_argument("--base", required=True)
    cmp.add_argument("--new", required=True)
    cmp.set_defaults(func=cmd_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with console_logging(getattr(args, "quiet", False)):
        return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
