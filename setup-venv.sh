#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# A venv whose interpreter was removed (e.g. a Python upgrade) is rebuilt.
if [[ ! -x "$VENV_DIR/bin/python" ]] || ! "$VENV_DIR/bin/python" -c '' 2>/dev/null; then
  python3 -m venv --clear "$VENV_DIR"
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
echo "Run the tool with: $SCRIPT_DIR/run.sh"
