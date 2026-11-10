# Control room

One page that takes a run through four steps. Every action on it is an engine or one-off command, and every verdict on a setup or a run is the engine's own. The page does one sum itself: "Compare with…" in step 4 subtracts another run's four headline figures from this run's.

```
uv run python control_room/server.py
```

This opens <http://127.0.0.1:8770>. Ctrl+C stops the page. A run in progress still finishes, because the engine runs in its own process group. Use `--port` for another port, `--no-browser` to skip opening the page, `--runs-dir` to read and write runs in another folder, and `--dataset` to choose the book. To host the page instead, see [On Heroku](#on-heroku).

## Small or large

The page opens on the book the setting names, and the setting is `small`. `BOOKS` and `DATASET` at the top of `server.py` hold both.

| Setting | The book |
|---|---|
| `small` | The sample, a tenth of the full book, for trying the page. |
| `large` | The full book the requirements describe. |

`--dataset large` changes it for one start. The `DATASET` environment variable does the same, and `--dataset` overrides it. To change it for good, edit `DATASET` in `server.py`. A value that is neither, or a book that is missing or that the engine cannot read, stops the server with a message, so the page never opens on the other book by accident.

## The four steps

The bar at the top stays in view. It shows the four steps, each as Passed or Not passed, marks the one you are on with You are here, and holds the button that moves you on. A line appears under it only when something needs saying: a missing file, an error, a run in progress.

| Step | What you do there |
|---|---|
| **1 Files and settings** | The files the run needs, one row each: what the file holds, the file in use, its rows and size, and whether it fits. Add or replace any file with your computer's file dialog, or by dropping files on the card. "What this step expects" opens the guide: the rules every file follows, what happens to a file, and for each file its columns or sections, and which problems stop the run, stop it partway or leave a record out. Everything that changes a run is here: choose the scenarios, see their descriptions and macro paths side by side with the portfolios each variable drives, add your own and type their values, the balance sheet with its yearly volumes, the method choices, and each segment's settings and models: its asset correlation, Stage 2 multiple and prepayment rate, and for its PD, LGD and prepayment the model, chosen from those of its own portfolio. A model's coefficients are not edited here: they live in its function in `src/stress/models/`. The sanity checks then run without calculating, and the next step opens only when nothing stops them. |
| **2 Review the files** | View only. Each table with its summary and a searchable row preview, the scenarios with their descriptions and macro paths, and one card per portfolio. For each segment the card shows its settings, its three models, each with its name, where its function lives, its sensitivity and its description as the function's docstring states it, and its rating transition matrix file. Then the Z of each segment, model, scenario and year. If something is wrong, go back to step 1. |
| **3 Run** | What will run, in one list. Start, then the engine's progress and its log. The exact command is folded below the list. |
| **4 Outcomes** | The run's figures, charts and workbook, a check that it reproduces, a comparison with another run, and every earlier run. The comparison is the difference between the two runs' cumulative impairment losses, first-year losses, stock of provisions and Stage 3 exposure, worked out on the page; `stress compare` in a terminal gives the engine's full difference report. "Run again with changes" loads the setup back into step 1. |

## Adding files by hand

The engine reads only a frozen folder, `inputs/<hash>/`, and only the one-off step writes one. So a file added on the page waits in a temporary folder of this server, and is checked at once against the columns or sections its row needs. "Use these files" copies the added files and the saved files for the other rows together and runs `foundation.synth package`. If the contents match a saved set, that set comes back unchanged. Your originals and the saved sets are not touched.

The file's row decides what it is, so a file can have any name. Files dropped on the card go to rows by name, and the page says which ones it could not place. Files wait until the server stops. The engine reads Parquet and YAML only, so a file in another format has to be converted first.

A YAML file, or a setup pasted as YAML, may use aliases, but not to stand for more than it could hold written out: one whose aliases expand to more than 100,000 values, or more values than it has characters if that is larger, is refused before it is read. A few hundred bytes of nested aliases would otherwise expand to thousands of millions of values.

Every row of the book the page opens on can be replaced. A set packaged here stays in use until the page is reloaded, when the page goes back to the setting's book. To reach it again, use "Load its setup" on one of its runs, or add its files again. Older sets the engine cannot read are not offered.

## Scenarios

The page assumes no number of scenarios and no names, apart from baseline, which the engine requires. Every scenario in the Scenarios file is listed with its description and starts in the run, so a file with five gives five. Below the list, one table sets the macro paths side by side: a column per scenario, a row per variable and year, and the portfolios each variable drives. "Drives" comes from the model functions themselves: the room calls each segment's PD, LGD and prepayment model once and notes which variables it asks for, so it follows a model picked under the segment parameters.

"Add a scenario" adds as many more as you need. Each one starts from a scenario before it, chosen at the head of its column, keeps a name and description, and takes the values typed in its column; an empty cell keeps the value it starts from. It runs from a specification, so the Scenarios file itself stays as it is. A scenario that every run should offer belongs in the Scenarios file instead; the [runbook](../docs/runbook.md) says how to add one. The page has no control for how a scenario returns to baseline after 2029, so each follows the parameter set's rule unless the YAML sets its own (`terminal_policies`); a setup loaded with one keeps it.

Each scenario keeps one colour wherever it appears. There are eight colours. Beyond eight, further scenarios are grey in the charts and the legends and tables still name them.

## The sign-off

A sign-off records that the owner of the files accepts them, with `foundation.synth approve`. A run does not need one, and it changes neither the files nor the results. Each run states it in `analysis_readiness.csv`. The line sits under the file list, with a name field when no sign-off has been given.

## How it maps to the engine

A plain setup runs as `stress run` with its options, on the `core` variant. Anything else (an added scenario, a segment setting or model, a path after 2029, dynamic volumes) is written as a specification YAML under `control_room/specifications/<name>.yaml` and runs with `--specification`. The sealed run keeps its own copy, so a run reproduces even if the file goes. "Load its setup" brings an earlier run's setup back, including any variant or analysis package it used. Other variants and analysis packages are not offered on the page. They stay available through `stress run` in a terminal.

The method choices are the readings of the draft recorded in `docs/assumptions.md` as C14 to C16, plus `--terminal-treatment`. Standard is the design's default.

The sanity checks are the engine's own: `preflight.dry_run` runs R1 to R4 for real, in a temporary folder, and stops before R5. Nothing is calculated and nothing reaches `runs/`. "No errors observed" appears only when they pass with nothing left out. A stopped setup shows the engine's own message and cannot be started. Records the engine leaves out are listed before the run, one line per reason and detail, each with its own count. A setup that names no scenarios is checked, and shown, with the two the engine runs by default, baseline and adverse.

The page does not compare the files with the requirements, because the small dataset differs from them by design. `preflight.differences` makes that comparison, using the measures and tolerances of AT-01, SYN-PAR-05 and section 6.2, and the tests hold the full book to it.

## Rules it keeps

- **A run is a `stress` command**, so it is an ordinary sealed folder under `runs/`, the same as one started in a terminal. Packaging and sign-off are the one-off steps, so an input set is written only by them.
- **It changes no run.** The folder is outside the paths `code_version` hashes, so adding or editing it alters no run ID or rerun check.
- **Only what the page offers runs.** The server checks the setup's shape and paths and rebuilds every command itself, so no text from the browser reaches a command line. A file name from the browser is only ever shown. The variant is one the input set holds, with flags and with a specification alike, because it names the run folder before the engine has judged anything. The rest of the setup's contents are the engine's to judge, as they would be at R2. It starts one job at a time.
- **It writes only its own files.** A setup that needs a specification is written under `specifications/` here, named by one file name, when its run starts and not before: a start refused because a job is in progress writes nothing. Added files go to a temporary folder that goes when the server stops.
- **No number is invented.** Every value comes from the files, a sealed run, `docs/spec/` or the engine's check. The differences "Compare with…" shows are the page's own subtraction of two sealed runs' figures.
- **This machine's folders stay here.** An answer to the browser names no temporary folder of the server, and a fault in a sanity check sends its one-line message; the traceback goes to the server's own output.
- **Closed folders stay closed.** Input sets are found by name, `inputs/<hash>/`, as in `nbtools.py`. A path in a setup is refused if it points into `archive/`, `inputs/bank/` or a tool cache.
- **Local unless hosted.** It listens on `127.0.0.1` and refuses requests from any other host or site. The page loads nothing from the internet, and files go no further than this machine. Listening anywhere else takes `--host`; see [On Heroku](#on-heroku).

After changing `server.py` or `preflight.py`, restart the server: it keeps its code in memory but reads the page fresh. The page notices one such gap only, a server too old to have the sanity-check route, and then says to restart it. Any other difference between the two goes unnoticed.

If the server restarts while a run is in progress, the page says that the server no longer follows the run, and stops showing it as in progress. Whether the run itself survived depends on what stopped the server. After Ctrl+C the engine carries on, and the run appears under Outcomes once it seals. When the whole machine or dyno restarts, the run is gone and its folder is listed as not finished. While the server does not answer at all, the page says so and keeps asking.

## On Heroku

`Procfile`, at the repository root, starts this server with `--host 0.0.0.0`. Given any host but `127.0.0.1`, the server behaves differently in three ways:

- **No sign-in.** Anyone with the address can use the page.
- **https only.** A plain http request is redirected.
- **Its own site only.** A request from another site is refused.

The page keeps no record of who did what, and a sign-off's name is whatever was typed. One job at a time applies to everyone on the page. So does the list of added files: the server holds one list, not one per visitor, so a file one visitor adds shows on every visitor's page, replaces a file another visitor added to the same row, and goes into whichever "Use these files" comes next. Two uploads to one row at the same moment each arrive whole, and the later one stays.

A hosted page takes smaller files than a local one, because anyone with the address can send one: 64 MB for a table and 4 MB for a YAML file. A larger file is refused before it is read. The local page keeps its limit of 8 GB a file.

Heroku gets both books and follows [the same setting](#small-or-large), so the app starts on `small`, because a run of the full book needs more memory than a small dyno has. `heroku config:set DATASET=large` moves it to the full book, which needs a larger dyno first.

The steps and limits are in [Hosting on Heroku](../docs/runbook.md#hosting-on-heroku).

## Files and tests

| File | What it does |
|---|---|
| `server.py` | Holds added files, has the engine judge a setup, writes it as a specification, starts the engine and the one-off steps, reads sealed runs, serves the page. |
| `preflight.py` | The files in words and each file's check, what a saved set holds, the dry run, the comparison with the requirements, the setup as YAML and back, and the reading of a YAML from outside within its limit. |
| `guide.py` | The guide to step 1. Columns, allowed values and required sections come from the engine's contract, and each rule names the engine's reasons or block codes. A test fails if a new column, section, reason or block code has no place in it. The plain words still have to be read against the engine. |
| `index.html` | The page: the bar and the four steps. Chart colours match `nbtools.py`. |
| `small_set.py` | Cuts the large dataset to a tenth to make the small one, and has `foundation.synth package` freeze it. |
| `specifications/` | Setups saved from the page, as the engine reads them. Created on first save. |
| `test_guide.py`, `test_preflight.py`, `test_server.py`, `test_small_set.py` | Their tests. |

```
uv run pytest control_room
```

The tests sit here, not under `tests/`. The room proves no requirement, and a marked test under `tests/` would enter the generated traceability matrix. `uv run pytest` alone therefore does not run them. The gates run them as a suite of their own, after the engine's tests: `tests/ci_gate.py`, which CI runs, the pre-commit hook for a commit that is not a small change, and the gate of `/improve` and of `change-reviewer`. A change to the room alone is a small change, which the pre-commit hook does not test, so run them before committing it. One test makes a real run with a derived scenario and reproduces it; others package and sign off copies of the committed set in temporary folders. The suite takes about two and a half minutes.
