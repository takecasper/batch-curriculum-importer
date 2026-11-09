# One45 Schedule Wrangler: Design Notes

This document explains how `wrangler.py` works and why key design decisions were made. Domain terms (Partner, Batch, Partner Workbook, Schedule Sheet, Mapping Sheet, Batch Import, Portfolio Tab, Course Tab, File Tab, Change Log Tab, Check Run, Combine Run, Flagged Cell) are defined in `GLOSSARY.md`. The output columns and what the One45 importer requires of each are in `IMPORT-FORMAT.md`. The window (`wrangler_gui.py`) is described under "Window" below.

## Goals

- Let non-technical users make a Batch Import from a folder of Partner Workbooks by double-clicking, with no terminal.
- Standardize inconsistent Partner exports into one import-ready Batch Import.
- Turn a Partner's many per-Course uploads into one import per Portfolio.
- Keep output safe for One45 import constraints:
  - one Portfolio per tab
  - no `portfolio` column in the imported file
  - consistent header order/case
  - parseable date/time values
- Keep execution isolated from system Python/site-packages.

## Runtime Isolation

- `setup-venv.sh` creates a package-local `.venv` (or the directory passed as `VENV_DIR`) and installs dependencies. It rebuilds the venv if its interpreter no longer runs (for example after a Python upgrade removes the one it was built with).
- `run.sh` executes the script with `.venv/bin/python` only.
- The app bundle keeps its own venv in `~/Library/Application Support/One45 Schedule Wrangler/venv`, separate from a checkout's `.venv`.

### Why this decision

- Prevents environment drift between users.
- Avoids accidental dependency/version conflicts from global Python installs.

## High-Level Flow

1. Resolve the input directory: `--input-dir`, else `schedule-workbooks/` next to the script, else `~/Downloads`.
2. Discover `.xlsx` files there. Exclude lock files (`~$...`), the output path, and prior outputs (`-batch-import`, plus the older `-master-schedule` and `_schedule-import` names).
3. **Collect.** For each Partner Workbook and each sheet:
   1. Materialize formulas to cached values (Step 0).
   2. Detect the header row by fuzzy matching against the canonical headers, looking through the first `--header-scan-rows` rows (default 30) so title rows above the header are fine.
   3. Skip Mapping Sheets: the detected header row, or a title row above it, names `objective` or `objectives` (whole word, any case). This is a separate check, not part of fuzzy header scoring. Data rows are never checked, so a Session Name such as "Learning Objectives Review" does not skip a Schedule Sheet. A sheet with no detectable header is skipped either way; it is logged as a mapping sheet, rather than as having no matching headers, when one of its scanned rows names an objective.
   4. Skip sheets that map neither `portfolio` nor `Course Name`.
   5. Read rows, normalize times and dates, and mark rows whose End Time is not after Start Time.
4. **Check Portfolios.** Once the whole Batch is read, find rows that can't be routed (see "Missing Portfolios"). The command line fills them from `--portfolio` or stops with a list; the window asks.
5. **Decide.** Choose the run type and assign every row to a tab (see below).
6. **Write.** Create the tabs, write rows, and save as `<input-dir-name>-batch-import.xlsx` unless `--output` is given. With `--file-per-tab`, save one workbook per tab in a `<input-dir-name>-batch-import/` folder.
7. Print the run summary.

The steps are separate functions (`read_batch`, `portfolio_gap`, `Batch.fill`, `write_batch_import`) so the window can ask its questions between reading and writing.

### Why collect before routing

The tab layout depends on the whole Batch (whether *any* workbook has a Portfolio), so rows can't be routed while they are being read. Partner Workbooks are a few hundred rows each, so holding a Batch in memory is cheap.

## Run Types and Routing

The run type depends only on how many Partner Workbooks contributed rows: one is a Check Run, two or more is a Combine Run. It names the run in the summary and does not change routing. Routing depends on the Portfolios:

| Portfolios | Tabs | Summary Shows |
| :--- | :--- | :--- |
| Every row has one | One Portfolio Tab per Portfolio | `Check Run (Portfolio Tabs)` or `Combine Run (Portfolio Tabs)` |
| None, the Batch holds a single Course, and no `--unassigned-file-tabs` | One Course Tab named after the Course | `Check Run` or `Combine Run` |
| Some or none, with `--unassigned-file-tabs` | Portfolio Tabs, then one File Tab per workbook with blank Portfolios | `... (Portfolio Tabs and file tabs)` |
| Any other gap | None; the run stops first (see "Missing Portfolios") | *Execution halts prior to output generation* |

- "Has a Portfolio" means a non-blank value, not merely a mapped `portfolio` header; a header with only blank cells carries no information.
- Portfolio names that differ only by case or whitespace (`Summer 2026, MED 4` vs ` summer 2026,  med 4 `) route to the same tab. The tab uses the first spelling seen.
- The `portfolio` column is never written; One45 rejects an import file that contains one, and the importer selects the Portfolio at import time. `Course Name` is always kept.

### Why this decision

- Partners usually send a whole term's curriculum as one file per Course, each already carrying its Portfolio (e.g. `Summer 2026, MED 4`). Grouping by Portfolio turns ~20 imports into one per Portfolio.
- A file holding several Portfolios is split, because one tab can only be imported into one Portfolio.
- A single Course with no Portfolio is one import anyway; the importer picks the Portfolio.

### Tradeoff

- Tab names are limited to 31 characters and cannot contain `[]:*?/\`, so long Portfolio names are shortened. The summary prints each tab's full name.

## Missing Portfolios

| Situation | Command Line | Window |
| :--- | :--- | :--- |
| No row has a Portfolio and the Batch holds several Courses | Stops and lists each workbook with its Courses, unless `--portfolio` or `--unassigned-file-tabs` is given | Asks: *"Are they all in the same Portfolio?"*<br>• **Yes:** Prompts for Portfolio name.<br>• **Give each its own tab:** Writes a File Tab per workbook.<br>• **No:** Lists the workbooks to fix and writes nothing. |
| Some rows have a Portfolio, others are blank | Stops and lists the workbooks with blank rows, unless `--portfolio` or `--unassigned-file-tabs` is given | Lists those workbooks, each with a dropdown of detected Portfolios (preselected when there is only one) that also accepts typed text.<br>• **Give each its own tab:** Portfolio rows go to Portfolio Tabs; unassigned rows go to a File Tab per workbook.<br>• **Cancel:** Writes nothing. |

- `--portfolio` fills every blank Portfolio with one name.
- A filled-in Portfolio is logged once per workbook (`Portfolio filled in`), not per row.
- `--unassigned-file-tabs` (the window's "Give each its own tab") routes blank-Portfolio rows to a File Tab named after their workbook, logged once per workbook (`No Portfolio: given its own tab`). File Tabs follow Portfolio Tabs, and the window callout reports their count. The Portfolio is assigned at import time in One45.
- Use it to force output generation when a folder mixes files with and without Portfolios (e.g., an unsorted downloads folder).

### Why this decision

- File Tabs are strictly opt-in, ensuring a Batch with missing Portfolios cannot be imported into the wrong target container by accident.
- Prevents silent fallback failures: earlier heuristics that guessed Course Tabs or dumped stragglers into a generic "Review" tab created dangerous cross-import risks. Missing Portfolios require human confirmation before disk writes occur.

## One File per Portfolio

- `--file-per-tab` (the window's "A separate file per Portfolio") writes each tab as its own workbook, named after the full Portfolio (not limited to 31 characters). Filesystem-reserved characters (`/ \ : * ? " < > |`) are sanitized to `_`.
- Each workbook has its own Change Log: entries for its own rows, entries for the Partner Workbooks and sheets that fed it, and skipped workbooks and sheets (which fed no file and appear in every log).
- Output directories reside inside the Batch folder. The tool reads only files directly in the Batch folder, never subfolders, so generated outputs are not read back as input on later runs.
- The CLI writes into an existing folder and overwrites files with colliding names. The GUI prompts for confirmation before overwriting.

## Window

`wrangler_gui.py` (Tkinter) is a native GUI wrapper invoked via `One45 Schedule Wrangler.app`, a bundle folder tracked in git whose executable is a shell script. The checkout's bundle holds only that script, `Info.plist` and the icon; `build.sh` copies `wrangler.py`, `wrangler_gui.py`, `setup-venv.sh` and `requirements.txt` into `Contents/Resources` and zips the result for a release. The app has to be complete on its own because Gatekeeper's App Translocation runs a downloaded, quarantined app from a read-only copy of the `.app` alone: an earlier launcher that looked for its files next to the app found nothing there. For the same reason the launcher writes nothing inside the bundle: the venv and the setup lock live in `~/Library/Application Support/One45 Schedule Wrangler/`, and the window runs with `python -B`. Finder gives the app a bare PATH, so it looks for python.org's Python under `/Library/Frameworks/Python.framework` (newest 3.10+ with Tkinter; never Apple's `/usr/bin/python3` stub). When none is found it offers the newest python.org release that has a macOS installer (read from python.org's folder listing; a pinned fallback release when that fails), verifies the Python Software Foundation's Developer ID signature on the download with `pkgutil --check-signature`, and opens it with Apple's Installer. A signature check covers any release, where a pinned checksum covered one. The newest release is taken even on the day an x.y.0 ships, since the app needs only Tkinter and openpyxl; the floor is 3.10, matching what the launcher accepts, so a Mac is never handed a Python the next open would skip. Nothing goes over the network before the person agrees to the download. It provisions the venv on initial run, logging to `~/Library/Logs/One45 Schedule Wrangler/`. There is no Terminal, so messages are `osascript` dialogs. The icon is built from `assets/icon.svg` by `assets/make-icon.sh`.

- **First open:** Displays instructional modal once per user (state persisted in `~/Library/Application Support/One45 Schedule Wrangler/` on macOS, `%APPDATA%` on Windows). The **How to use** button redisplays these instructions.
- **State persistence:** Caches the last selected folder and output preference in application support, defaulting to `~/Downloads` and one file with a tab per Portfolio.
- **Collision management:** If target files or folders exist, prompts **Replace it / Keep the old one / Cancel**. Retaining existing data renames old files to `... (previous YYYY-MM-DD HHMM)`. Because the string `-batch-import` is retained, archived runs are safely excluded from future input scans. Replacing a folder is deferred until the Portfolio questions are answered, so cancelling or answering No keeps the old files.
- **Execution callout:** Post-run alert highlighting flagged red cells, unparseable dates/times, multi-term Portfolio spans, or generated File Tabs.
- **Direct launch:** Provides direct buttons to open the generated workbook or destination folder.
- **Thread isolation:** Processing executes in a background thread to prevent UI freezing during large file parsing.
- **Platforms:** macOS today. The code avoids Mac-only paths, so Windows needs only a launcher.

## Date/Time Normalization

Parseable variants are normalized; unparseable strings pass through intact, appear under "Values left unchanged (could not be read)" in the summary, and are not flagged.

### Time (`Start Time`, `End Time`)

- Accepts native time/datetime cells, Excel day fractions, `9:00 AM`, `9:00AM`, `9am`, `9:00 a.m.`, `noon`, `13:30`, `13:30:00`, and military integers/strings (`0900`, `930`).
- Writes native Excel time serials formatted explicitly as `hh:mm` (24-hour time).

### Date (`Section Date`)

- Accepts native date/datetime cells, Excel day integers, numeric `yyyymmdd`, ISO formats, US slash/dash formats, and string dates (`May 5, 2026`, `5-May-2026`).
- Writes native Excel date serials formatted explicitly as `yyyymmdd`.

### Formative/Summative (`Session Formative/Summative`)

- `formative` or `summative` in any casing, with any surrounding spaces, becomes `Formative` or `Summative`, the only spellings the importer accepts. Each fix is logged as `Formative/Summative fixed`.
- Any other value passes through unchanged and is not flagged.

### Why this decision

- Text-formatted date/time values are a frequent cause of One45 import failures.
- Normalizing valid patterns eliminates manual spreadsheet cleanup while avoiding algorithmic guessing on ambiguous inputs.

## Flagged Cells

- **Trigger:** Evaluated strictly when `End Time <= Start Time` within the same record.
- **Formatting:** Both the `Start Time` and `End Time` cells receive a red fill.
- **Resolution:** These records require human verification or Partner confirmation. They are logged in the summary and Change Log.
- Semicolons are not flagged (irrelevant to schedule imports; only restricted in mapping imports).

## Change Log Tab

Every Batch Import workbook terminates with a **Change Log** tab documenting all automated transformations:
`Source File | Source Sheet | Source Row | Tab | Tab Row | Column | Change | Original | New`

It is excluded from One45 import operations.

| Scope | Recorded Events |
| :--- | :--- |
| **Workbook / Sheet** | Workbook unreadable/corrupt; sheet skipped (mapping sheet header, header threshold missed, missing Portfolio/Course Name, unreadable); formula-to-value materialization counts per sheet. |
| **Column** | `portfolio` column deleted; header renamed to canonical import syntax; unmapped column dropped; missing canonical column added (empty). |
| **Workbook Resolution** | Portfolio populated programmatically via CLI `--portfolio` or GUI modal. |
| **Row / Cell** | Time normalized; date normalized; Formative/Summative casing fixed; unparseable value passed through; flagged time interval (`End Time <= Start Time`); hidden source row skipped. |

- Time/date transformations are logged only when the input was text or numeric; native datetime-to-date type conversions are not logged to minimize noise.
- `Source Row` and `Tab Row` reflect 1-based Excel row indices. `Tab Row` counts the output tab's header as row 1, so its data starts at row 2. `Source Row` is the row in the Partner's sheet, which can be lower when title rows sit above the header.
- Formulas are tracked as aggregate replacement counts per sheet, not per individual cell.

### Why this decision

- Programmatic transformations occur silently; the log provides a transparent audit trail for support staff and Partners without requiring manual spreadsheet diffs.

## Run Summary

The terminal and GUI summary reports:
- Run type classification
- Output tab roster (`title <- kind: full name (rows)`)
- Count of invalid time intervals (flagged red)
- Count of skipped hidden rows
- Unparseable time/date values (first 20 samples)
- Change Log entry total
- Multi-term validation warning (triggers if Portfolios span multiple distinct academic terms, matched on season + year; non-blocking)

## Safety Behaviors

- Halts execution and writes zero bytes if any row lacks a Portfolio (excepting single-Course Batches), unless `--portfolio` or `--unassigned-file-tabs` is given.
- Automatically skips unreadable or corrupt `.xlsx` workbooks with non-fatal warnings.
- Ignores Excel lock files (`~$*`), targeted output files, and prior outputs matching `-batch-import`, `-master-schedule`, or `_schedule-import`.
- Fails cleanly if no `.xlsx` files remain post-filter or if zero valid schedule rows are collected.

## Key Tunables

- `--input-dir`, `--output`: Input source and output target paths.
- `--file-per-tab`: Output one standalone workbook per Portfolio within a directory.
- `--portfolio`: Explicit string used to populate all blank Portfolio cells.
- `--unassigned-file-tabs`: Directs unassigned rows to File Tabs named after source workbooks.
- `--tab-contains`: Prioritizes sheets containing this substring during candidate evaluation.
- `--fuzzy-threshold`: Minimum confidence threshold (`0..1`) for fuzzy header matching.
- `--header-scan-rows`: Row depth limit when scanning for headers (default: 30).
- `--min-header-matches`: Minimum number of recognized headers required to qualify a sheet.
- `--skip-formula-materialization`: Disables cached formula conversion, leaving raw formulas intact.
- `--skip-hidden-rows`: Excludes rows marked hidden in the source Excel file.

## Known Limitations

- **Merged Headers:** Complex multi-row or merged header layouts can degrade fuzzy detection accuracy.
- **Unusual Header Aliases:** Highly divergent header naming may fail to resolve unless aliases or `--fuzzy-threshold` are adjusted.
- **Lexical Portfolio Drift:** Semantic name variations beyond whitespace/casing (`Yr 1` vs `Year 1`) produce separate tabs.
- **Environment:** GUI requires a Python installation with working Tk bindings (included with python.org binaries; often omitted in Command Line Tools / Homebrew minimalist builds).
- **Style Stripping:** Original fonts, cell fills, and borders are intentionally omitted to generate clean, unstyled import matrices.
- **Mapping Sheet Check:** A Schedule Sheet whose header row has a column such as "Session Objectives" is skipped as `Sheet skipped (mapping sheet)`. Rename or remove that column and run again.

## Why This Is Not a General ETL Framework

This script is built specifically to address One45 schedule import constraints. It prioritizes strict validation, safe defaults, and zero-configuration execution for frontline support operations over general-purpose ETL flexibility.
