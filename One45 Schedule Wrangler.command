#!/usr/bin/env bash
# Double-click in Finder to open the One45 Schedule Wrangler window.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Return to close."
  exit 1
fi

# First open (or after a Python upgrade): build the private environment.
if [[ ! -x "$VENV_PY" ]] || ! "$VENV_PY" -c 'import openpyxl, tkinter' 2>/dev/null; then
  echo "Setting up One45 Schedule Wrangler (first open only)..."
  "$SCRIPT_DIR/setup-venv.sh"
fi

exec "$VENV_PY" "$SCRIPT_DIR/wrangler-gui.py"
