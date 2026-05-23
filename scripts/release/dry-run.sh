#!/usr/bin/env bash
set -euo pipefail

RUN_FAST_CHECKS=1
for arg in "$@"; do
  case "$arg" in
    --skip-fast-checks)
      RUN_FAST_CHECKS=0
      ;;
    *)
      echo "usage: $0 [--skip-fast-checks]" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN=python3.12
  else
    PYTHON_BIN=python3
  fi
fi

PACKAGE_VERSION="$("$PYTHON_BIN" - <<'PY'
from pathlib import Path
import tomllib

project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
print(project["version"])
PY
)"
RELEASE_TAG="${RELEASE_TAG:-v$PACKAGE_VERSION}"

if [[ "$RELEASE_TAG" != "v$PACKAGE_VERSION" ]]; then
  echo "release tag $RELEASE_TAG does not match pyproject.toml version $PACKAGE_VERSION" >&2
  exit 1
fi

if [[ "$RUN_FAST_CHECKS" == "1" ]]; then
  bash scripts/ci/run-fast-checks.sh
fi

"$PYTHON_BIN" - <<'PY'
import importlib.util
import sys

if importlib.util.find_spec("build") is None:
    raise SystemExit("python -m build is unavailable; install it with: python -m pip install build")
PY

rm -rf dist
"$PYTHON_BIN" -m build

(
  cd dist
  find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS
)

echo "Built release artifacts for $RELEASE_TAG:"
ls -1 dist
