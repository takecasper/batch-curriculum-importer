# Changelog

## 0.1.0 - 2026-10-28

First release of One45 Schedule Wrangler: the `wrangler.py` CLI, the `wrangler_gui.py` window with its double-click launcher, and the docs (README, DESIGN, GLOSSARY, IMPORT-FORMAT). The entries below are changes made before this release, since the first commit.

### Fixed

- A Schedule Sheet with "objective" in a Session Name (such as "Learning Objectives Review") is no longer skipped as a Mapping Sheet; only the header row and title rows above it are checked.

### Added

- `Session Formative/Summative` values in any casing are rewritten to `Formative` or `Summative` and logged in the Change Log.
- IMPORT-FORMAT.md documents the 19 import columns, their exact headers and One45's rules.

### Changed

- The scripts are now `wrangler.py` (was `create-master-schedule-workbook.py`) and `wrangler_gui.py` (was `wrangler-gui.py`). `run.sh` and the double-click launcher are unchanged to use. `pip install .` now provides a `one45-schedule-wrangler` command instead of `create-master-schedule-workbook.py`.
