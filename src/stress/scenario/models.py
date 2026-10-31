"""Selectable portfolio macro models. MOD-01, SCN-03, SCN-08.

Models return a single economic score; R6 still applies each risk transformation once.
Terms are evaluated as data, never Python expressions or executable plugin names.
"""

from math import isfinite

from stress.contracts.specification import invalid, mapping, number, text
from stress.scenario.kernels import z_score


def evaluate_model(model, index, scenario, country, year):
    mapping(model, {"kind", "source", "version", "drivers", "terms", "intercept", "values"},
            "macro model", ("kind", "source", "version"))
    text(model["source"], "model source")
    text(model["version"], "model version")
    kind = text(model["kind"], "model kind")
    permitted = {
        "linear": {"kind", "source", "version", "drivers"},
        "polynomial": {"kind", "source", "version", "terms", "intercept"},
        "supplied": {"kind", "source", "version", "values"},
    }
    if kind not in permitted:
        invalid(f"unknown macro model kind {kind}")
    mapping(model, permitted[kind], f"{kind} macro model")
    if kind == "supplied":
        values = model.get("values")
        if not isinstance(values, list) or not values:
            invalid("supplied model needs score values")
        scores = {}
        for row in values:
            mapping(row, {"scenario", "country", "year", "z"}, "supplied score",
                    ("scenario", "country", "year", "z"))
            text(row["scenario"], "score scenario")
            text(row["country"], "score country")
            if type(row["year"]) is not int:
                invalid("score year must be an integer")
            key = (row["scenario"], row["country"], row["year"])
            if key in scores:
                invalid(f"duplicate supplied score {key}")
            scores[key] = number(row["z"], "supplied score")
        key = (scenario, country, year)
        if key not in scores:
            invalid(f"missing supplied score {key}")
        value = scores[key]
        return value, [("supplied_score", value, 0.0, 1.0, 1.0, value)]
    if kind == "linear":
        drivers = model.get("drivers")
        if not isinstance(drivers, dict) or not drivers:
            invalid("linear model needs drivers")
        x = {name: index.get((scenario, name, country, year), (None, "missing"))[0]
             for name in drivers}
        for name, coefficients in drivers.items():
            mapping(coefficients, {"beta", "mean", "sd"}, f"driver {name}", ("beta", "mean", "sd"))
        value, parts = z_score(x, drivers, f"{scenario}/{country}/{year}")
        if not isfinite(value) or any(not isfinite(part) for part in parts.values()):
            invalid("non-finite linear macro score")
        return value, [(name, x[name], drivers[name]["mean"], drivers[name]["sd"],
                        drivers[name]["beta"], part) for name, part in parts.items()]
    terms = model.get("terms")
    if not isinstance(terms, dict) or not terms:
        invalid("polynomial model needs named terms")
    intercept = number(model.get("intercept", 0.0), "model intercept")
    out = [("__intercept__", 1.0, 0.0, 1.0, intercept, intercept)]
    for name, term in terms.items():
        text(name, "model term")
        if name == "__intercept__":
            invalid("reserved model term __intercept__")
        mapping(term, {"variable", "lag", "power", "mean", "sd", "beta"}, f"term {name}",
                ("variable", "mean", "sd", "beta"))
        text(term["variable"], "term variable")
        lag, power = term.get("lag", 0), term.get("power", 1)
        if type(lag) is not int or lag < 0 or type(power) is not int or power not in (1, 2, 3):
            invalid("term lag must be nonnegative and power must be 1, 2 or 3")
        mean = number(term["mean"], "term mean")
        sd = number(term["sd"], "term sd", 0)
        beta = number(term["beta"], "term beta")
        if sd == 0:
            invalid("term sd must be positive")
        key = (scenario, term["variable"], country, year - lag)
        value, status = index.get(key, (None, "missing"))
        if status == "missing" or value is None:
            invalid(f"missing model driver/history {key}")
        value = number(value, "model driver")
        try:
            contribution = beta * ((value - mean) / sd) ** power
        except OverflowError:
            invalid(f"non-finite contribution in term {name}")
        if not isfinite(contribution):
            invalid(f"non-finite contribution in term {name}")
        out.append((name, value, mean, sd, beta, contribution))
    value = sum(row[-1] for row in out)
    if not isfinite(value):
        invalid("non-finite macro score")
    return value, out
