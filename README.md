# One45 Schedule Wrangler

One45 Schedule Wrangler prepares partner-provided schedule workbooks for the One45 schedule importer. It consolidates multiple per-Course uploads into an import-ready batch, normalizes headers and date/time values, removes structural incompatibilities, and isolates records requiring manual review.

Terminology is defined in [GLOSSARY.md](GLOSSARY.md). Architectural decisions and technical trade-offs are documented in [DESIGN.md](DESIGN.md). The import columns and their One45 rules are in [IMPORT-FORMAT.md](IMPORT-FORMAT.md).

---

## What It Does

- **Batch Consolidation:** Combines multiple Partner Workbooks into a single Batch Import workbook, partitioned into one Portfolio Tab per target Portfolio.
- **Split Output Mode:** Optionally outputs individual workbooks per Portfolio into a target directory (`--file-per-tab`).
- **Sheet Qualification & Pre-filtering:** Automatically ignores temporary Excel lock files (`~$*`) and prior outputs. Finds each sheet's header row using fuzzy header scoring against canonical One45 import headers, then skips Mapping Sheets (the header row or a title row above it names `objective` or `objectives`), sheets that don't qualify, and sheets that lack both `portfolio` and `Course Name` columns.
- **Formula Materialization:** Replaces Excel formulas with their cached static values to prevent calculation errors in downstream import engines.
- **Header Normalization:** Standardizes varying partner header syntax to canonical One45 importer headers and strips the `portfolio` column (which causes native import rejection).
- **Date & Time Coercion:** Standardizes text and numeric dates and times into native Excel serial values formatted as `yyyymmdd` and `hh:mm` (24-hour).
- **Formative/Summative Casing:** Rewrites `formative`, `SUMMATIVE` and similar to the importer's `Formative` / `Summative`.
- **Validation Flagging:** Formats conflicting intervals where `End Time <= Start Time` with red cell fills for human verification.
- **Full Change Auditing:** Appends a non-imported `Change Log Tab` recording every file, sheet, column, and row-level transformation.

---

## Requirements & Environment

- macOS. The code avoids Mac-only paths, but Windows has no launcher yet.
- Python 3.9+ with Tkinter support (standard python.org distribution).
- Shell scripts handle virtual environment provisioning automatically.

Execution is strictly isolated within a local `.venv` managed by `setup-venv.sh`.

---

## Quick Start (GUI)

1. Place the Partner Workbooks into a single folder. Do not use subfolders.
2. Double-click `One45 Schedule Wrangler.command` (macOS). The local environment will initialize automatically on first run. If macOS blocks the file the first time, right-click it and choose **Open**.
3. Click **Choose folder...** and select the input folder containing the source files.
4. Choose the output format:
   - **One file, a tab per Portfolio:** Writes `<folder>-batch-import.xlsx` in the source folder.
   - **A separate file per Portfolio:** Writes individual workbooks inside a new `<folder>-batch-import/` directory.
5. Click **Make Batch Import**.
   - If workbooks lack Portfolio designations, the UI will prompt you to assign a Portfolio, route them to individual File Tabs, or cancel.
6. Click **Open Batch Import** (or **Open folder**) to inspect the output.

The **How to use** button shows the instructions again.

---

## CLI Usage

Run via the virtual environment wrapper:

```bash
./setup-venv.sh        # one-time, or after a Python upgrade
./run.sh --input-dir ~/path/to/batch --output ~/batch-import.xlsx
./run.sh --input-dir ~/path/to/batch --file-per-tab
./run.sh --input-dir ~/path/to/batch --portfolio "Summer 2026, MED 4"   # fill blank Portfolios
./run.sh --input-dir ~/path/to/batch --unassigned-file-tabs              # or give those files their own tab
```

### Options

| Flag | Argument | Description |
| :--- | :--- | :--- |
| `--input-dir` | `<path>` | Directory containing Partner Workbooks. Defaults to `schedule-workbooks/` next to the script, falling back to `~/Downloads`. |
| `--output` | `<path>` | Destination for the Batch Import. Defaults to `<input-dir>/<input-dir-name>-batch-import.xlsx`; with `--file-per-tab` it is the output folder. |
| `--file-per-tab` | None | Writes individual workbooks per Portfolio into an output folder rather than a single multi-tab workbook. |
| `--portfolio` | `<string>` | Global override to populate all empty Portfolio cells across the Batch. |
| `--unassigned-file-tabs` | None | Routes rows lacking a Portfolio to dedicated File Tabs named after the source workbook instead of halting. |
| `--tab-contains` | `<string>` | Tries sheets whose name contains this text first; other sheets are still processed if their headers qualify. |
| `--fuzzy-threshold` | `<0.0–1.0>` | Minimum match confidence for header detection (default: 0.72). |
| `--header-scan-rows` | `<int>` | Maximum row depth to evaluate when locating headers (default: 30). |
| `--min-header-matches` | `<int>` | Minimum valid schedule headers required to qualify a sheet (default: 3). |
| `--skip-formula-materialization` | None | Skips cached formula conversion and leaves raw formulas in place. |
| `--skip-hidden-rows` | None | Excludes rows explicitly marked as hidden in source workbooks. |

`./run.sh --help` lists the same flags.

---

## Pre-Import QA Checklist

Before uploading the generated files into One45:

- **Resolve Red Flagged Cells:** Filter for red highlighted cells in Start Time and End Time. These indicate records where End Time is earlier than or equal to Start Time. Correct the times or confirm values with the Partner.
- **Review the Change Log Tab:** Check the final Change Log Tab to verify dropped columns, coerced dates, and skipped sheets.
- **Do Not Import the Change Log:** Upload only the Portfolio Tabs (or File Tabs/Course Tabs). Exclude the Change Log Tab from the import sequence.
- **Target Container Matching:** Ensure each tab or file is imported into its exact matching Portfolio in One45.

---

## Known Constraints

- **Mapping Sheets:** Mapping Sheets (objectives and competency uploads) are not processed by this tool. A sheet whose header row, or a title row above it, contains the word `objective` or `objectives` is skipped and logged as `Sheet skipped (mapping sheet)`. Data rows are not checked, so a Session named "Learning Objectives Review" is imported normally.
- **Ambiguous Portfolios:** The Wrangler will never guess a Portfolio for multi-Course Batches. If files lack Portfolios and `--portfolio` or `--unassigned-file-tabs` is not provided, processing halts before writing.
- **Visual Styles:** Source fonts, borders, and fills are intentionally discarded; output tables are clean data grids formatted strictly for import safety.

---

## Test

```bash
./check.sh             # lint (ruff) and every test; run before committing
```

In a git checkout, `./setup-venv.sh` installs ruff from `requirements-dev.txt` and turns on the `.githooks/pre-commit` hook, which runs `./check.sh` on every commit. Besides behavior, the tests check that the code and docs avoid GLOSSARY.md's multi-word "Do Not Use" terms and that every quoted button name in the How to use text exists in the window.

The window tests (`tests/test_gui_window.py`) open the real window and click through it, so they are skipped unless you ask for them. `GUI_SHOTS` saves a screenshot of each dialog; on macOS the terminal needs Screen Recording permission (System Settings > Privacy & Security) or the images come out blank.

```bash
GUI_TESTS=1 .venv/bin/python -m unittest discover -s tests
GUI_TESTS=1 GUI_SHOTS=/tmp/wrangler-shots .venv/bin/python -m unittest discover -s tests -p test_gui_window.py
```
