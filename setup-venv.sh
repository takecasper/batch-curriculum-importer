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

echo "Virtual environment ready: $VENV_DIR"
echo "Run the tool with: $SCRIPT_DIR/run.sh"
