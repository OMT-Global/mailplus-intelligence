#!/usr/bin/env bash
set -euo pipefail
bash scripts/ci/run-fast-checks.sh

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN=python3.12
else
  PYTHON_BIN=python3
fi

PYTHONPATH=src "$PYTHON_BIN" -m unittest tests.test_metadata_fixtures -v
