#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"
TOOL="$SCRIPT_DIR/create-master-schedule-workbook.py"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing virtual environment at $SCRIPT_DIR/.venv"
  echo "Run: $SCRIPT_DIR/setup-venv.sh"
  exit 1
fi

exec "$VENV_PY" "$TOOL" "$@"
