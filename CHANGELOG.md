# Changelog

## Unreleased

### Added

- The MIT license, in `LICENSE` and the package metadata.

## 0.3.0 - 2026-11-09

### Changed

- When no python.org Python is installed, the app offers the newest Python release that has a macOS installer instead of a fixed 3.13.17, falling back to 3.14.10 if python.org can't be read. The download is opened only if it carries the Python Software Foundation's Apple Developer ID signature.
- Python 3.10 or newer is required (was 3.9, which reached end-of-life in October 2025). The app skips a python.org 3.9 and offers the download instead.
- Releases ship the app as `One45-Schedule-Wrangler-<version>.zip`, built by the new `build.sh`, instead of the source zip. The app can live anywhere, such as the Applications folder.

### Fixed

- A downloaded `One45 Schedule Wrangler.app` no longer stops with "needs the rest of its folder". macOS runs a downloaded app from a read-only copy of the `.app` alone (App Translocation), so the app now carries `wrangler.py`, `wrangler_gui.py`, `setup-venv.sh` and `requirements.txt` inside it and keeps its private environment in `~/Library/Application Support/One45 Schedule Wrangler/` instead of next to the app.

## 0.2.0 - 2026-10-28

### Changed

- The double-click launcher is `One45 Schedule Wrangler.app`, with its own icon, in place of `One45 Schedule Wrangler.command`. It no longer opens a Terminal window; messages are dialogs and notifications. It uses only python.org's Python (the `.command` took any `python3` on PATH, which Finder does not provide).

### Added

- When no python.org Python is installed, the app offers to download the Python 3.13.17 installer (checksum verified) and opens it.

## 0.1.0 - 2026-10-28

First release of One45 Schedule Wrangler: the `wrangler.py` CLI, the `wrangler_gui.py` window with its double-click launcher, and the docs (README, DESIGN, GLOSSARY, IMPORT-FORMAT). The entries below are changes made before this release, since the first commit.

### Fixed

- A Schedule Sheet with "objective" in a Session Name (such as "Learning Objectives Review") is no longer skipped as a Mapping Sheet; only the header row and title rows above it are checked.

### Added

- `Session Formative/Summative` values in any casing are rewritten to `Formative` or `Summative` and logged in the Change Log.
- IMPORT-FORMAT.md documents the 19 import columns, their exact headers and One45's rules.

### Changed

- The scripts are now `wrangler.py` (was `create-master-schedule-workbook.py`) and `wrangler_gui.py` (was `wrangler-gui.py`). `run.sh` and the double-click launcher are unchanged to use. `pip install .` now provides a `one45-schedule-wrangler` command instead of `create-master-schedule-workbook.py`.
