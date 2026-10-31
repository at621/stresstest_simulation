"""Build the workflow page from three sealed runs and check its YAML against the stored files.

    uv run python docs/run-workflow/sources/build_page.py <static_run> <dynamic_run> <default_run>

The run IDs quoted in template.html are the ones the page reports. Runs of the same files on the
same code give the same figures.
"""
import html
import pathlib
import re
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
ST, DY, CT = (pathlib.Path(arg) for arg in sys.argv[1:4])
page = (HERE / "template.html").read_text(encoding="utf-8")
static_yaml = (HERE.parent / "walkthrough.yaml").read_text(encoding="utf-8")
dynamic_yaml = (HERE.parent / "walkthrough-dynamic.yaml").read_text(encoding="utf-8")


def minus(text: str) -> str:
    return text.replace("-", "−")


def f1(x: float) -> str:
    return minus(f"{x:,.1f}")


def cumulative(run):
    i = pd.read_csv(run / "results/reports/impairment.csv")
    return i[i.year == 2029].pivot_table(index="portfolio", columns="scenario", values="cumulative_charge") / 1e6


ctl, wlk, dyn = cumulative(CT), cumulative(ST), cumulative(DY)
assert round(ctl.loc["Total", "baseline"], 1) == 130.4 and round(ctl.loc["Total", "adverse"], 1) == 635.0
assert [round(wlk.loc["Total", s], 1) for s in ("baseline", "adverse", "energy_crisis")] == [132.3, 662.2, 1173.4]
assert [round(dyn.loc["Total", s], 1) for s in ("baseline", "adverse", "energy_crisis")] == [132.3, 636.1, 1023.8]

names = {"P01": "P01 Residential mortgages", "P02": "P02 Consumer credit", "P03": "P03 SME lending",
         "P04": "P04 Commercial real estate", "P05": "P05 Corporate lending, without NACE D",
         "P06": "P06 Sovereigns and institutions", "P07": "P07 Energy, new"}
top = wlk.drop(index="Total").to_numpy().max()


def pair(p, s):
    new = wlk.loc[p, s]
    if p not in ctl.index:
        return f'<td class="n grp">–</td><td class="n moved">{f1(new)}</td>'
    old = ctl.loc[p, s]
    cls = "n" if abs(old - new) < 5e-7 else "n moved"
    return f'<td class="n grp">{f1(old)}</td><td class="{cls}">{f1(new)}</td>'


rows = []
for p, name in names.items():
    bars = []
    for key, label, cls in (("baseline", "Baseline", "c-base"), ("adverse", "Adverse", "c-adv"),
                            ("energy_crisis", "Energy crisis", "c-crisis")):
        v = wlk.loc[p, key]
        bars.append(f'<span class="hit" data-tip="{p}, {label}: €{v:,.1f}m"><span class="bar {cls}" '
                    f'style="width:{v / top * 100:.1f}%"></span></span>')
    rows.append(f'<tr><td>{name}</td>{pair(p, "baseline")}{pair(p, "adverse")}'
                f'<td class="n grp moved">{f1(wlk.loc[p, "energy_crisis"])}</td>'
                f'<td class="grp"><div class="bars">{"".join(bars)}</div></td></tr>')
rows.append(f'<tr class="total"><td>Total</td><td class="n grp">{f1(ctl.loc["Total", "baseline"])}</td>'
            f'<td class="n">{f1(wlk.loc["Total", "baseline"])}</td><td class="n grp">{f1(ctl.loc["Total", "adverse"])}</td>'
            f'<td class="n">{f1(wlk.loc["Total", "adverse"])}</td><td class="n grp">{f1(wlk.loc["Total", "energy_crisis"])}</td>'
            '<td class="grp"></td></tr>')
results = ('<div class="scroll"><table class="tbl w-wide"><thead><tr><th rowspan="2">Portfolio</th>'
           '<th colspan="2" class="grp">Baseline</th><th colspan="2" class="grp">Adverse</th>'
           '<th class="grp">Crisis</th><th rowspan="2" class="grp">This run, to scale</th></tr>'
           '<tr><th class="n grp">Default</th><th class="n">This run</th><th class="n grp">Default</th>'
           '<th class="n">This run</th><th class="n grp">This run</th></tr></thead><tbody>'
           + "".join(rows) + "</tbody></table></div>")
base_sum = wlk.loc["P05", "baseline"] + wlk.loc["P07", "baseline"]
adv_sum = wlk.loc["P05", "adverse"] + wlk.loc["P07", "adverse"]
p0507 = (f'Together, P05 and P07 cost €{base_sum:.1f}m in baseline against €{ctl.loc["P05", "baseline"]:.1f}m, '
         f'and €{adv_sum:.1f}m in adverse against €{ctl.loc["P05", "adverse"]:.1f}m.')
delta = wlk.loc["Total", "baseline"] - ctl.loc["Total", "baseline"]
assert round(delta, 1) == 1.8 or round(delta, 1) == 1.9, delta
page = page.replace("The €1.9m rise in the baseline total", f"The €{delta:.1f}m rise in the baseline total")

z = pd.read_csv(ST / "results/reports/z_scores.csv")
z = z[z.year.isin([2027, 2028, 2029])]
assert z.groupby(["segment", "scenario", "year"]).z.nunique().max() == 1, "Z differs by country"
wide = z.drop_duplicates(["segment", "scenario", "year"]).pivot_table(index="segment", columns=["scenario", "year"], values="z")
order = ["P01", "P02", "P03", "P04", "P05", "P05_ENERGY", "P06_GG", "P06_CI"]
linked = {"P02", "P04", "P05_ENERGY"}
rows = []
for seg in order:
    cells = []
    for s in ("baseline", "adverse", "energy_crisis"):
        for n, y in enumerate((2027, 2028, 2029)):
            value = wide.loc[seg, (s, y)]
            text = minus(f"{value:+.2f}") if round(value, 2) != 0 else "0.00"
            cells.append(f'<td class="n{" grp" if n == 0 else ""}">{text}</td>')
    rows.append(f'<tr{' class="linked"' if seg in linked else ""}><td><code>{seg}</code></td>{"".join(cells)}</tr>')
head = "".join(f'<th colspan="3" class="grp">{t}</th>' for t in ("Baseline", "Adverse", "Energy crisis"))
years = "".join(f'<th class="n{" grp" if n % 3 == 0 else ""}">{y}</th>' for n, y in enumerate([2027, 2028, 2029] * 3))
z_table = (f'<div class="scroll"><table class="tbl w-wide"><thead><tr><th rowspan="2">Segment</th>{head}</tr><tr>{years}</tr>'
           f'</thead><tbody>{"".join(rows)}</tbody></table></div>')

FID = "F09030"


def trace(run, segment, scenario):
    pit = pd.read_csv(run / "results/reports/pit_matrices.csv")
    q = pit[(pit.segment == segment) & (pit.country == "IT") & (pit.year == 2027) & (pit.from_grade == "G5")
            & (pit.to_grade == "D") & (pit.scenario == scenario)].iloc[0]
    sl = pd.read_parquet(run / "results/slices.parquet", filters=[("facility_id", "==", FID), ("scenario", "==", scenario), ("year", "==", 2027)])
    ch = pd.read_parquet(run / "results/charges.parquet", filters=[("facility_id", "==", FID), ("scenario", "==", scenario)]).set_index("year")
    par = pd.read_parquet(run / "results/parameters.parquet", filters=[("facility_id", "==", FID), ("scenario", "==", scenario),
                                                                       ("valuation_year", "==", 2027), ("default_bucket", "==", 1)])
    share = sl.groupby("stage").gca.sum() / sl.gca.sum()
    return {"z": q.z, "pd": q.probability, "s2": share[2], "s3": share[3], "lgd": par.lgd.iloc[0],
            "close": ch.loc[2027, "closing_on"] / 1e3, "charge": ch.loc[2027, "charge_on"] / 1e3, "cum": ch.charge_on.sum() / 1e3}


cols = [trace(CT, "P05", "adverse"), trace(ST, "P05_ENERGY", "baseline"), trace(ST, "P05_ENERGY", "adverse"),
        trace(ST, "P05_ENERGY", "energy_crisis")]
assert round(cols[3]["pd"], 4) == 0.1055 and round(cols[3]["z"], 2) == -3.48
lines = [("Z, 2027", lambda c: minus(f"{c['z']:+.2f}") if round(c["z"], 2) != 0 else "0.00"),
         ("PD, G5 to default within 2027", lambda c: f"{c['pd'] * 100:.2f}%"),
         ("Share in S2 at end-2027", lambda c: f"{c['s2'] * 100:.2f}%"),
         ("Share in S3 at end-2027", lambda c: f"{c['s3'] * 100:.2f}%"),
         ("LGD, first default bucket after end-2027", lambda c: f"{c['lgd'] * 100:.2f}%"),
         ("Provision at end-2027, €k", lambda c: f"{c['close']:,.1f}"),
         ("Charge in 2027, €k", lambda c: f"{c['charge']:,.1f}"),
         ("Cumulative charge 2027–2029, €k", lambda c: f"{c['cum']:,.1f}")]
rows = "".join("<tr><td>" + label + "</td>" + "".join(f'<td class="n{" grp" if i < 2 else ""}">{fn(c)}</td>' for i, c in enumerate(cols)) + "</tr>"
               for label, fn in lines)
loan = ('<div class="scroll"><table class="tbl w-mid"><thead><tr><th rowspan="2">Loan F09030</th><th class="grp">Default run</th>'
        '<th colspan="3" class="grp">This run, <code>energy_sector</code></th></tr><tr><th class="n grp">Adverse</th>'
        '<th class="n grp">Baseline</th><th class="n">Adverse</th><th class="n">Energy crisis</th></tr></thead><tbody>'
        + rows + "</tbody></table></div>")

m = pd.read_csv(ST / "results/reports/macro_models.csv")
m = m.sort_values("segment", key=lambda s: s.map({x: i for i, x in enumerate(order)}))
rows = "".join(f'<tr{' class="linked"' if r.segment in linked else ""}><td><code>{r.segment}</code></td><td><code>{r.model_id}</code></td><td>{r.kind}</td></tr>'
               for r in m.itertuples())
models = ('<div class="scroll"><table class="tbl"><thead><tr><th>Segment</th><th>Model</th><th>Kind</th></tr></thead><tbody>' + rows + "</tbody></table></div>")


def book(run, name):
    b = pd.read_csv(run / f"results/reports/{name}")
    return b[b.year == 2029]


sb, db = book(ST, "static_books.csv"), book(DY, "dynamic_books.csv")
scen = ("baseline", "adverse", "energy_crisis")
g_s = sb.groupby("scenario").gca.sum() / 1e6
g_d = db.groupby("scenario").gca.sum() / 1e6
p7 = db[db.portfolio == "P07"].set_index("scenario")
assert round(p7.loc["energy_crisis", "gca"] / 1e6, 1) == 909.5
rows = [("Charge 2027–2029, static, €m", [wlk.loc["Total", s] for s in scen]),
        ("Charge 2027–2029, dynamic, €m", [dyn.loc["Total", s] for s in scen]),
        ("GCA at end-2029, static, €m", [g_s[s] for s in scen]),
        ("GCA at end-2029, dynamic, €m", [g_d[s] for s in scen]),
        ("P07 GCA at end-2029, dynamic, €m", [p7.loc[s, "gca"] / 1e6 for s in scen]),
        ("P07 undrawn at end-2029, dynamic, €m", [p7.loc[s, "undrawn"] / 1e6 for s in scen])]
body = "".join("<tr><td>" + label + "</td>" + "".join(f'<td class="n">{f1(v)}</td>' for v in vals) + "</tr>" for label, vals in rows)
dynamic_table = ('<div class="scroll"><table class="tbl w-mid"><thead><tr><th></th><th class="n">Baseline</th><th class="n">Adverse</th>'
                 '<th class="n">Energy crisis</th></tr></thead><tbody>' + body + "</tbody></table></div>")
assert round(wlk.loc["P07", "energy_crisis"], 1) == 108.1 and round(dyn.loc["P07", "energy_crisis"], 1) == 111.5


def check(fragment: str, source: str, label: str):
    """Every line of a page fragment must be a real line of the file that ran."""
    real = {line.strip() for line in source.splitlines()}
    for line in re.sub(r"<[^>]+>", "", fragment).splitlines():
        text = html.unescape(line).strip()
        if text and not text.startswith("#") and text not in real:
            raise SystemExit(f"{label}: not in the file: {text}")


for match in re.finditer(r'<pre class="cmd" data-check>(.*?)</pre>', page, re.DOTALL):
    check(match.group(1), static_yaml, "static fragment")
for match in re.finditer(r'<pre class="cmd" data-check-dyn>(.*?)</pre>', page, re.DOTALL):
    check(match.group(1), dynamic_yaml, "dynamic fragment")
page = page.replace(' data-check-dyn>', '>').replace(' data-check>', '>')

for token, value in {"%%T_RESULTS%%": results, "%%T_Z%%": z_table, "%%T_LOAN%%": loan, "%%T_MODELS%%": models,
                     "%%T_DYNAMIC%%": dynamic_table, "%%P0507%%": p0507,
                     "%%YAML_STATIC%%": html.escape(static_yaml), "%%YAML_DYNAMIC%%": html.escape(dynamic_yaml),
                     "%%N_STATIC%%": str(len(static_yaml.splitlines())), "%%N_DYNAMIC%%": str(len(dynamic_yaml.splitlines()))}.items():
    page = page.replace(token, value)
assert "%%" not in page
(HERE.parent / "stress-run-workflow.html").write_text(page, encoding="utf-8", newline="\n")
print("built", len(page), "bytes")
