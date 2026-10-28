# One45 Schedule Wrangler

One45 Schedule Wrangler turns the schedule workbooks a Partner sends into one Batch Import workbook formatted for the One45 schedule importer. Terms are defined in [GLOSSARY.md](GLOSSARY.md); design decisions are in [DESIGN.md](DESIGN.md).

It reduces manual cleanup by:

- Combining a Batch of Partner Workbooks into one Batch Import, one tab per Portfolio, so each Portfolio is a single import
- Or writing a separate workbook per Portfolio (`--file-per-tab`)
- Checking a single Partner Workbook on its own (a Check Run)
- Stopping, with a list of workbooks, when rows have no Portfolio (the window asks which Portfolio they belong to)
- Standardizing columns to the importer's headers and dropping the `portfolio` column
- Materializing formula-based cells using their cached computed values
- Fixing readable time and date variants (`9:00AM`, `0900`, `May 5, 2026`, Excel serial dates)
- Flagging rows whose End Time is not after the Start Time
- Recording every change it made in a Change Log tab (never imported)

## Run (window, Mac)

Double-click **One45 Schedule Wrangler.command** in Finder. The first open sets up `.venv` (Python 3 from python.org is required) and shows how-to instructions; the **How to use** button shows them again. Choose the Batch folder, pick one file or a file per Portfolio, then **Make Batch Import**.

If macOS blocks the file the first time, right-click it and choose **Open**.

## Run (command line)

```bash
./setup-venv.sh        # one-time, or after a Python upgrade
./run.sh --input-dir ~/path/to/batch --output ~/master.xlsx
./run.sh --input-dir ~/path/to/batch --file-per-tab
./run.sh --input-dir ~/path/to/batch --portfolio "Summer 2026, MED 4"   # fill blank Portfolios
./run.sh --input-dir ~/path/to/batch --unassigned-file-tabs              # or give those files their own tab
```

See `create-master-schedule-workbook.py --help` for all flags.

## Test

```bash
.venv/bin/python -m unittest discover -s tests
```

The window tests (`tests/test_gui_window.py`) open the real window and click through it, so they are skipped unless you ask for them. `GUI_SHOTS` saves a screenshot of each dialog; on macOS the terminal needs Screen Recording permission (System Settings > Privacy & Security) or the images come out blank.

```bash
GUI_TESTS=1 .venv/bin/python -m unittest discover -s tests
GUI_TESTS=1 GUI_SHOTS=/tmp/wrangler-shots .venv/bin/python -m unittest discover -s tests -p test_gui_window.py
```
