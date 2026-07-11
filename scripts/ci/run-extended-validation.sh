#!/usr/bin/env bash
set -euo pipefail
bash scripts/ci/run-fast-checks.sh

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN=python3.12
else
  PYTHON_BIN=python3
fi

REPORT_PATH="${TMPDIR:-/tmp}/mailplus-intelligence-evaluation.json"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PYTHON_BIN" scripts/evaluate.py \
  --fixtures-dir fixtures \
  --report-json "$REPORT_PATH"

echo "Evaluation report: $REPORT_PATH"
