#!/usr/bin/env bash
# Lint and run the tests. The pre-commit hook (.githooks/pre-commit) runs this.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
VENV_PY=".venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing .venv. Run ./setup-venv.sh first."
  exit 1
fi

if ! "$VENV_PY" -m ruff --version >/dev/null 2>&1; then
  echo "ruff is not installed in .venv. Run ./setup-venv.sh first."
  exit 1
fi
"$VENV_PY" -m ruff check .
"$VENV_PY" -m unittest discover -s tests
