#!/usr/bin/env bash
set -euo pipefail

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN=python3.12
else
  PYTHON_BIN=python3
fi

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required")
PY

bash scripts/check-detect-secrets.sh --all-files
bash scripts/ci/check-ci-contract.sh
PYTHONPATH=src "$PYTHON_BIN" scripts/ci/docs_smoke.py
PYTHONPATH=src "$PYTHON_BIN" -m unittest discover -s tests -v
