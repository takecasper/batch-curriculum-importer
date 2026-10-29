#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# In a checkout the venv sits next to the scripts. The app bundle passes its
# own location under ~/Library/Application Support as $VENV_DIR and the
# python.org Python it found as $PYTHON.
VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/.venv}"
PYTHON="${PYTHON:-python3}"

# A venv whose interpreter was removed (e.g. a Python upgrade) or that was
# built from a Python without Tkinter (the window needs it) is rebuilt.
if [[ ! -x "$VENV_DIR/bin/python" ]] || ! "$VENV_DIR/bin/python" -c 'import tkinter' 2>/dev/null; then
  "$PYTHON" -m venv --clear "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"

# In a git checkout, run ./check.sh before every commit. Checked via .git so a
# copy without git never calls git (which prompts for an install on macOS).
# Never fatal: the launcher calls this script, and the app doesn't need ruff.
if [[ -e "$SCRIPT_DIR/.git" ]]; then
  "$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements-dev.txt" \
    || echo "Could not install dev tools (ruff); ./check.sh will ask again."
  git -C "$SCRIPT_DIR" config core.hooksPath .githooks || true
fi

echo "Virtual environment ready: $VENV_DIR"
if [[ "$VENV_DIR" == "$SCRIPT_DIR/.venv" ]]; then
  echo "Run the tool with: $SCRIPT_DIR/run.sh"
fi
