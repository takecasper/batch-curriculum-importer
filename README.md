# One45 Schedule Wrangler

the One45 Schedule Wrangler prepares all course schedule worksheets for the One45 curriculum importer at once. It processes each individual course curriculum by surfacing hidden data and formulas, normalizing headers, converting date and time formats, and highlighting cells that require manual review. The tool then consolidates these individual files into a single master workbook with dedicated tabs for each portfolio, allowing you to run one import per portfolio instead of one per course.

For project terminology, see GLOSSARY.md. Architectural decisions and technical trade-offs are documented in DESIGN.md, and importer column rules are detailed in IMPORT-FORMAT.md.

---

## Core Capabilities

* **Batch Consolidation:** Merges multiple Partner worksheets into a single workbook. All individual course files are organized by the portfolio they are imported into. 
* **Split Output Mode:** Need separate files? Use `--file-per-tab` to output individual workbooks per Portfolio into a designated target directory.
* **Pre-filtering & Sheet Discrimination:** Every sheet's header row is compared against canonical One45 headers, safely skipping Mapping Sheets (where the header or title row mentions `objective` or `objectives`), other non curriculum worksheet related sheets, and sheets missing both `portfolio` and `Course Name`.
* **Formula Materialization:** Replaces fragile Excel formulas with their cached static values to prevent calculation failures in downstream import engines.
* **Header Normalization:** Maps wild-card partner header syntax to canonical One45 headers and strips the native `portfolio` column (which otherwise triggers import rejection).
* **Date & Time Coercion:** Forces text and numeric dates/times into strict, native Excel serial values formatted as `yyyymmdd` and `hh:mm` (24-hour).
* **Formative/Summative Casing:** Standardizes variations like `formative` or `SUMMATIVE` to the importer-required `Formative` / `Summative`.
* **Validation Flagging:** Visually flags impossible intervals (where `End Time <= Start Time`) with a red cell fill so human reviewers can easily spot them.
* **Full Change Auditing:** Generates a `Change Log Tab` that records every file, sheet, column, and row-level transformation applied during the run.

---

## Requirements & Environment

* **OS:** macOS 11 or later. (The codebase is platform-agnostic, but Windows currently lacks a native launcher).
* **Dependencies:** Python 3.10+ (with Tkinter) from [python.org](https://www.python.org/downloads/). If Python is missing, the app will automatically offer to download the latest signed release.
* **Isolation:** Execution is strictly isolated. Shell scripts provision a private virtual environment (`.venv` in a local checkout, or `~/Library/Application Support/One45 Schedule Wrangler/venv` for the standalone app).

---

## Installation

1. Navigate to the [latest release](https://github.com/takecasper/batch-curriculum-importer/releases/latest), download the `One45-Schedule-Wrangler-<version>.zip` attachment, and unzip it. You can place the resulting `One45 Schedule Wrangler.app` anywhere, including your Applications folder.
2. Double-click the app. On the first launch, macOS Gatekeeper will block it. Click **Done**, navigate to **System Settings > Privacy & Security**, scroll down to **Security**, click **Open Anyway**, and launch the app again. *(On macOS 14 or earlier: click **Cancel**, right-click the app, and choose **Open**).*
3. If Python is missing, the app will offer to fetch the newest version directly from python.org, verifying the Python Software Foundation signature. Follow the Apple installer prompts, then reopen the app.
4. The initial launch builds the app's private environment in `~/Library/Application Support/One45 Schedule Wrangler/` (this takes about a minute, tracked via a system notification). If it fails, a dialog will point you to the crash logs in `~/Library/Logs/One45 Schedule Wrangler/`.


---

## Quick Start (GUI)

1. Download all schedule upload files into a single folder with no subfolders.
2. Launch `One45 Schedule Wrangler.app`.
3. Click **Choose folder...** and select your input directory.
4. Select your output file preference.
5. Click **Make Batch Import**.
   - *If any workbooks are missing Portfolio designations, the UI will prompt you to manually assign a Portfolio, route them to individual File Tabs, or cancel.*
6. Click **Open Batch Import** (or **Open folder**) to review the generated files.
7. Review each tab in the master file:
   - Resolve any red-highlighted cells.
   - Audit and confirm transformations in the `Change Log` tab.
8. **Rotate Portfolio Tabs for Import:** The One45 curriculum importer only reads the leftmost tab in a workbook. After importing a portfolio, drag its tab to the far right, save the file, and re-upload the workbook to import the next portfolio in the sequence.

---

## Command Line Usage

CLI execution is handled via the virtual environment wrapper script:

```bash
# First-time setup (or after a Python version upgrade)
./setup-venv.sh

# Standard processing
./run.sh --input-dir ~/path/to/batch --output ~/batch-import.xlsx

# Split output mode
./run.sh --input-dir ~/path/to/batch --file-per-tab

# Populate blank Portfolios globally
./run.sh --input-dir ~/path/to/batch --portfolio "Summer 2026, MED 4"

# Route unassigned rows to dedicated File Tabs
./run.sh --input-dir ~/path/to/batch --unassigned-file-tabs

```

### CLI Flags

| Flag | Argument | Description |
| --- | --- | --- |
| `--input-dir` | `<path>` | Directory containing Partner Workbooks. Defaults to `schedule-workbooks/` next to the script, or `~/Downloads` if missing. |
| `--output` | `<path>` | Destination path. Defaults to `<input-dir>/<input-dir-name>-batch-import.xlsx`. When paired with `--file-per-tab`, this acts as the output directory. |
| `--file-per-tab` | *None* | Writes individual workbooks per Portfolio into an output folder rather than a multi-tab workbook. |
| `--portfolio` | `<string>` | Global override to populate all empty Portfolio cells across the entire Batch. |
| `--unassigned-file-tabs` | *None* | Routes rows lacking a Portfolio to dedicated File Tabs named after the source workbook instead of halting the process. |
| `--tab-contains` | `<string>` | Prioritizes processing sheets whose names contain this substring. Other sheets are still evaluated if their headers qualify. |
| `--fuzzy-threshold` | `<0.0–1.0>` | Minimum match confidence for header detection (Default: `0.72`). |
| `--header-scan-rows` | `<int>` | Maximum row depth to scan when hunting for the header row (Default: `30`). |
| `--min-header-matches` | `<int>` | Minimum valid schedule headers required to qualify a sheet for processing (Default: `3`). |
| `--skip-formula-materialization` | *None* | Skips cached formula conversion, leaving raw Excel formulas in place. |
| `--skip-hidden-rows` | *None* | Drops rows that were explicitly hidden in the source workbook. |

Run `./run.sh --help` to view this list in your terminal.

---

## Pre-Import QA Checklist

Run through these checks before feeding the Wrangler's output into One45:

**Resolve Red Flags:** Filter your sheets for red-filled cells in the Start Time and End Time columns. These indicate impossible temporal overlaps. Correct them or verify the intent with the Partner.

**Review the Audit Log:** Scan the Change Log Tab to confirm that dropped columns, date coercions, and skipped sheets align with your expectations.

**Rotate Portfolio Tabs for Import:** The One45 curriculum importer only reads the leftmost tab in a workbook. After importing a portfolio, drag its tab to the far right, save the file, and re-upload the workbook to import the next portfolio in the sequence.


---

## Known Constraints

* **Mapping Sheets Are Ignored:** The tool actively ignores objectives and competency uploads. If a sheet's header row (or a title row above it) contains `objective` or `objectives`, it is skipped and flagged as `Sheet skipped (mapping sheet)` in the log. Data rows are ignored during this check, so a session simply titled "Learning Objectives Review" will import safely.
* **Strict Portfolio Enforcement:** The Wrangler will never guess Portfolios for multi-Course batches. If files lack Portfolios and neither `--portfolio` nor `--unassigned-file-tabs` is provided, processing halts.
* **Visual Formatting is Dropped:** Source fonts, borders, custom colors, and fills are intentionally scrubbed. The output is a raw data grid optimized purely for import safety.

---

## Development & Testing

```bash
./check.sh             # Runs ruff linting and the full test suite. Run before every commit.
./build.sh             # Assembles dist/One45 Schedule Wrangler.app and its release zip.

```

The app bundle within the git checkout acts purely as a shell containing the launcher, icon, and `Info.plist`. Running `build.sh` populates it by copying `wrangler.py`, `wrangler_gui.py`, `setup-venv.sh`, and `requirements.txt` into the bundle. Always test the built app from `dist/`, not the raw checkout directory.

To cut a release, build from the tagged commit and attach the zip via the CLI:
`gh release upload <tag> "dist/One45-Schedule-Wrangler-<version>.zip"`

In a fresh checkout, running `./setup-venv.sh` automatically installs `ruff` from `requirements-dev.txt` and enables the `.githooks/pre-commit` hook, which enforces `./check.sh` on every commit. The test suite guarantees behavioral integrity, verifies that `GLOSSARY.md`'s "Do Not Use" terms are avoided, and ensures UI labels in the documentation perfectly match the application window.

### Testing the GUI

Window tests (`tests/test_gui_window.py`) launch the actual Tkinter window and simulate clicks. They are skipped by default. `GUI_SHOTS` saves a screenshot of every dialog state. *(Note: On macOS, your terminal emulator requires Screen Recording permissions in System Settings, otherwise screenshots render blank).*

```bash
GUI_TESTS=1 .venv/bin/python -m unittest discover -s tests
GUI_TESTS=1 GUI_SHOTS=/tmp/wrangler-shots .venv/bin/python -m unittest discover -s tests -p test_gui_window.py

```

---

## License

Available under the [MIT License](https://www.google.com/search?q=LICENSE). Copyright Acuity Insights Inc.
