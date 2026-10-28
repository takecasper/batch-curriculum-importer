# One45 Schedule Wrangler: Design Notes

This document explains how `create-master-schedule-workbook.py` works and why key design decisions were made. Domain terms (Partner, Batch, Partner Workbook, Schedule Sheet, Mapping Sheet, Batch Import, Portfolio Tab, Course Tab, Change Log Tab, Check Run, Combine Run, Flagged Cell) are defined in `GLOSSARY.md`. The window (`wrangler-gui.py`) is described under "Window" below.

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

- `setup-venv.sh` creates a package-local `.venv` and installs dependencies. It rebuilds the venv if its interpreter no longer runs (for example after a Python upgrade removes the one it was built with).
- `run.sh` executes the script with `.venv/bin/python` only.

### Why this decision

- Prevents environment drift between users.
- Avoids accidental dependency/version conflicts from global Python installs.

## High-Level Flow

1. Resolve the input directory: `--input-dir`, else `schedule-workbooks/` next to the script, else `~/Downloads`.
2. Discover `.xlsx` files there. Exclude lock files (`~$...`), the output path, and prior outputs (`-batch-import`, plus the older `-master-schedule` and `_schedule-import` names).
3. **Collect.** For each Partner Workbook and each sheet:
   1. Skip Mapping Sheets (any `objective`/`objectives` cell in the scanned rows).
   2. Materialize formulas to cached values (Step 0).
   3. Detect the header row by fuzzy matching against the canonical headers.
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

| Run type | When | Tabs |
|---|---|---|
| Check Run / Combine Run (Portfolio Tabs) | One / two or more workbooks contributed rows, and every row has a Portfolio | One tab per Portfolio. |
| Check Run / Combine Run | No row has a Portfolio, and the Batch holds a single Course | One Course Tab named after it. |

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

| Situation | Command line | Window |
|---|---|---|
| No row has a Portfolio and the Batch holds several Courses | Stops and lists each workbook with its Courses, unless `--portfolio` or `--unassigned-file-tabs` is given | Asks "Are they all in the same Portfolio?" Yes: asks for the name. Give each its own tab: writes a File Tab per workbook. No: lists the workbooks to fix and writes nothing. |
| Some rows have a Portfolio, others are blank | Stops and lists the workbooks with blank rows, unless `--portfolio` or `--unassigned-file-tabs` is given | Lists those workbooks, each with a dropdown of the Portfolios found (preselected when there is only one) that also takes a typed name. Give each its own tab: the Portfolio rows still go to Portfolio Tabs and each listed workbook's blank rows go to its own File Tab. Cancel writes nothing. |

- `--portfolio` fills every blank Portfolio with one name.
- A filled-in Portfolio is logged once per workbook (`Portfolio filled in`), not per row.
- `--unassigned-file-tabs` (the window's "Give each its own tab") routes blank-Portfolio rows to a File Tab named after their workbook, logged once per workbook (`No Portfolio: given its own tab`). File Tabs come after the Portfolio Tabs, and the window's callout counts them. Whoever imports a File Tab picks its Portfolio in the importer.
- Use it to get everything written when a folder mixes files with and without Portfolios, for example a whole download folder.

### Why this decision

- File Tabs are opt-in, so a Batch with missing Portfolios is never imported into the wrong place by accident; the default is still to ask or stop.
- Earlier versions guessed: Course Tabs for Batches with no Portfolio, and a For Review tab for stragglers. Both produced tabs that could be imported into the wrong place. Partners send one file per Course with its Portfolio, so a missing Portfolio is a question for a person, asked before anything is written.

## One File per Portfolio

- `--file-per-tab` (the window's "A separate file per Portfolio") writes each tab as its own workbook, named after the full Portfolio (not limited to 31 characters). Characters Windows or macOS reject in file names (`/ \ : * ? " < > |`) become `_`.
- Each workbook has its own Change Log: entries for its own rows, entries for the Partner Workbooks and sheets that fed it, and skipped workbooks and sheets, which fed no file and so appear in every one.
- The folder sits inside the Batch folder. The tool reads only files directly in the Batch folder, so the output is never read back as input.
- The command line writes into an existing folder, replacing files with the same names. The window asks first (see below).

## Window

`wrangler-gui.py` (tkinter, part of Python) is a front end, opened with `One45 Schedule Wrangler.command`, which builds `.venv` on first open.

- **First open:** shows how-to instructions once per person (marker in `~/Library/Application Support/One45 Schedule Wrangler/`, `%APPDATA%` on Windows). The **How to use** button shows them again.
- **Remembers** the last folder and output choice in the same place, falling back to `~/Downloads` and one file.
- **Existing output:** if the file or folder this run would write already exists, asks **Replace it / Keep the old one / Cancel**. Keeping renames it to `... (previous YYYY-MM-DD HHMM)`, which still contains `-batch-import`, so it's never read as a Partner Workbook (a plain rename like `old.xlsx` would be). Replacing a folder happens only once the Portfolio questions are answered, so cancelling keeps the old files.
- **Callout:** after a run, a plain-language note when rows are flagged red, dates or times couldn't be read, or Portfolios span more than one term.
- **Open:** opens the workbook, or the folder for one file per Portfolio.
- Runs in a background thread so the window stays responsive. Mac now; the code avoids Mac-only paths so Windows needs only a launcher.

## Date/Time Normalization

Readable variants are fixed; anything else passes through unchanged and is listed in the summary under "Values left unchanged (could not be read)". Those values are not flagged.

### Time (`Start Time`, `End Time`)

- Accepts time/datetime cells, Excel day fractions, `9:00 AM`, `9:00AM`, `9am`, `9:00 a.m.`, `noon`, `13:30`, `13:30:00`, and military `0900`/`930` (text or whole numbers).
- Writes real Excel time values with `hh:mm` display format (24-hour).

### Date (`Section Date`)

- Accepts date/datetime cells, Excel serial day numbers, `yyyymmdd` (text or number), ISO and US numeric formats, and month-name formats such as `May 5, 2026` and `5-May-2026`.
- Writes real date values with `yyyymmdd` display format.

### Why this decision

- Import failures are frequently caused by text-like date/time fields.
- Fixing what can be read saves manual cleanup; guessing at what can't be read would hide problems.

## Flagged Cells

- Only one condition is flagged red: an End Time that is not after its Start Time. Both cells are flagged, and the row is counted in the summary.
- These need a person's judgment: the right time has to be inferred or confirmed with the Partner.
- Semicolons are not flagged. They only matter for objective/mapping imports, which this tool does not handle.

## Change Log Tab

Every Batch Import workbook ends with a **Change Log** tab: one row per change, with `Source File | Source Sheet | Source Row | Tab | Tab Row | Column | Change | Original | New`. It is never imported.

| Level | Changes recorded |
|---|---|
| Workbook / sheet | Workbook skipped (could not open); sheet skipped (mapping sheet, no matching headers, no Portfolio or Course Name column, could not read values); formulas replaced with computed values or left as-is (count per sheet) |
| Column | Portfolio column removed; header renamed to the import header; column dropped (no matching import header); column added (blank) |
| Workbook | Portfolio filled in (by `--portfolio` or the window) |
| Row / cell | Time fixed; date fixed; could not read (left unchanged); flagged End Time not after Start Time; row skipped (hidden in source) |

- A time or date counts as fixed only when the source was text or a number. Real date/time cells only change type (`datetime` to `date`) and are not logged, so a clean file logs only its column changes.
- Row entries carry the tab and row they landed on, so a person can go straight from the log to the cell.
- Formulas are logged as a count per sheet, not per cell.

### Why this decision

- The Batch Import replaces the Partner's values silently; the log lets whoever imports it, or the Partner, see and check each change without diffing the files.

## Run Summary

The summary reports the run type, every tab (`title <- kind: full name (rows)`), invalid time ranges, hidden rows skipped, unreadable time/date values (first 20), the Change Log entry count, and a warning when Portfolio Tabs name more than one term (e.g. `Summer 2026` and `Spring 2026`, matched on season + year). The term warning never blocks the run.

## Safety Behaviors

- Writes nothing while any row is missing a Portfolio (except a single-Course Batch).
- Skips unreadable/corrupt workbooks with warnings.
- Skips Excel lock files (`~$`), the output path, and prior outputs.
- Fails if no `.xlsx` files remain after filtering, or if no rows are collected.

## Key Tunables

- `--input-dir`, `--output`: where to read and write.
- `--file-per-tab`: one workbook per Portfolio in a folder.
- `--portfolio`: Portfolio for every blank-Portfolio row.
- `--tab-contains`: tab-name substring tried first (all sheets remain candidates).
- `--fuzzy-threshold`: match strictness (`0..1`).
- `--header-scan-rows`: how far down to search for the header row.
- `--min-header-matches`: minimum confidence gate for header row selection.
- `--skip-formula-materialization`, `--skip-hidden-rows`.

## Known Limitations

- Multi-row/merged complex header structures can still be ambiguous.
- Very unusual header text can map poorly unless the threshold/aliases are adjusted.
- Portfolio name variants beyond case/whitespace (`Yr 1` vs `Year 1`) become separate tabs.
- The window needs a Python with a working Tk. The python.org installer includes one; the Command Line Tools `python3` may not.
- Source cell formatting is not preserved (by design; output is normalized import data and the source file is preserved).
- Mapping Sheets (objective/mapping uploads) are out of scope.

## Why This Is Not a General ETL Framework

This script is intentionally task-focused for repeatable schedule-import prep. The goal is reliability and operator simplicity, not maximum configurability.
