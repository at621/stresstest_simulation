"""Trigger each failure the workflow page lists and print the real engine message.

    uv run python docs/run-workflow/sources/blocked_cases.py <scratch_folder>

Case files and blocked runs go to the scratch folder, outside the repository.
"""
import copy
import pathlib
import subprocess
import sys

import yaml

W = pathlib.Path(sys.argv[1])
examples = pathlib.Path(__file__).resolve().parents[1]
INPUTS = (examples.parents[1] / "inputs" / "d62d0386f2c5256e").as_posix()
static = yaml.safe_load((examples / "walkthrough.yaml").read_text(encoding="utf-8"))
dynamic = yaml.safe_load((examples / "walkthrough-dynamic.yaml").read_text(encoding="utf-8"))


def p06_on_portfolio(d):
    d["segments"]["P06"] = {"macro_model": "consumer_nonlinear"}


def typo(d):
    d["segments"]["P02"] = {"macro_modell": "consumer_nonlinear"}
    d["segments"]["P01"] = {"macro_model": "consumer_nonlinear"}


def unassigned(d):
    d["models"]["spare"] = copy.deepcopy(d["models"]["energy_sector"])


def supplied_gap(d):
    d["models"]["cre_external"]["values"].pop()


def driver_gap(d):
    d["additional_values"] = [r for r in d["additional_values"] if r["scenario"] != "baseline"]


def wrong_hash(d):
    d["input_set_hash"] = "0" * 64


def no_baseline(d):
    d["run"]["scenarios"] = ["adverse", "energy_crisis"]


def no_class(d):
    d["segments"]["P05_ENERGY"].pop("template_class")


def assign_none(d):
    d["assignments"][0]["where"]["nace_code"] = "Z"


def star_and_country(d):
    d["scenarios"]["energy_crisis"]["overrides"].append(
        {"variable": "gdp_growth", "country": "IT", "year": 2027, "value": -0.10,
         "unit": "decimal", "value_type": "growth"})


def existing_name(d):
    d["scenarios"]["adverse"] = d["scenarios"].pop("energy_crisis")
    d["run"]["scenarios"] = ["baseline", "adverse"]
    d.pop("terminal_policies")
    d["additional_values"] = [r for r in d["additional_values"] if r["scenario"] != "energy_crisis"]


def reparent(d):
    d["segments"]["P02"]["inherits"] = "P01"


def official(d):
    d["status"] = "OFFICIAL"


def overwrite(d):
    d["additional_values"].append({"scenario": "adverse", "country": "*", "variable": "gdp_growth",
                                   "year": 2027, "value": -0.05, "unit": "decimal", "value_type": "growth"})


def split_segment(d):
    d["assignments"] = [{"where": {"portfolio": "P05", "nace_code": "D"}, "segment": "P05_ENERGY", "portfolio": "P07"},
                        {"where": {"portfolio": "P03", "nace_code": "D"}, "segment": "P05_ENERGY"}]


def volume_gap(d):
    d["balance_sheet"]["assumptions"].pop()


cases = [("p06_on_portfolio", static, p06_on_portfolio), ("typo", static, typo), ("unassigned", static, unassigned),
         ("supplied_gap", static, supplied_gap), ("driver_gap", static, driver_gap), ("wrong_hash", static, wrong_hash),
         ("no_baseline", static, no_baseline), ("assign_none", static, assign_none),
         ("star_and_country", static, star_and_country), ("existing_name", static, existing_name),
         ("reparent", static, reparent), ("official", static, official), ("overwrite", static, overwrite),
         ("split_segment", static, split_segment), ("volume_gap", dynamic, volume_gap), ("no_class", static, no_class)]
stress = str(pathlib.Path(".venv/Scripts/stress.exe"))
for name, source, change in cases:
    doc = copy.deepcopy(source)
    change(doc)
    doc["run"]["inputs"] = INPUTS
    path = W / f"case_{name}.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    done = subprocess.run([stress, "run", "--specification", str(path), "--runs-dir", str(W / "blocked"), "--quiet"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    lines = [line for line in (done.stderr + done.stdout).splitlines() if line.strip()]
    tail = [line[:230] for line in lines if "BLOCKED" in line or "INVALID" in line or "blocked at" in line] or lines[-3:]
    print(f"== {name} exit {done.returncode}\n" + "\n".join(tail[:2]), flush=True)
done = subprocess.run([stress, "run", "--specification", str(W / "case_typo.yaml"), "--variant", "annuity",
                       "--runs-dir", str(W / "blocked"), "--quiet"], capture_output=True, text=True, check=False,
                      encoding="utf-8", errors="replace")
print(f"== cli_mix exit {done.returncode}\n" + (done.stderr + done.stdout).strip()[:230], flush=True)
