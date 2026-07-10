#!/usr/bin/env bash
set -euo pipefail

assert_contains() {
  local file="$1"
  local expected="$2"

  if ! grep -F -- "$expected" "$file" >/dev/null 2>&1; then
    echo "Expected $file to contain: $expected" >&2
    exit 1
  fi
}

assert_contains scripts/ci/run-fast-checks.sh "scripts/check-detect-secrets.sh --all-files"
assert_contains scripts/ci/run-fast-checks.sh "-m unittest discover -s tests -v"
assert_contains scripts/ci/run-extended-validation.sh "bash scripts/ci/run-fast-checks.sh"
assert_contains scripts/ci/run-extended-validation.sh "scripts/evaluate.py"
assert_contains scripts/ci/run-extended-validation.sh "--report-json"
assert_contains docs/bootstrap/ci-validation.md "Fast validation"
assert_contains docs/bootstrap/ci-validation.md "Extended validation"
