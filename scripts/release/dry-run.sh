#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
cd "$ROOT_DIR"

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

RELEASE_WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mailplus-release.XXXXXX")"
trap 'rm -rf "$RELEASE_WORK_DIR"' EXIT
RELEASE_TOOLS_DIR="$RELEASE_WORK_DIR/release-tools"
"$PYTHON_BIN" -m venv "$RELEASE_TOOLS_DIR"
BUILD_PYTHON="$RELEASE_TOOLS_DIR/bin/python"
"$BUILD_PYTHON" -m pip install \
  --disable-pip-version-check \
  --no-cache-dir \
  "build==1.5.0"
echo "Using isolated release frontend: $("$BUILD_PYTHON" -m build --version)"

"$PYTHON_BIN" - "$PACKAGE_VERSION" <<'PY'
from pathlib import Path
import re
import sys

version = sys.argv[1]
changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
if re.search(rf"^## \[{re.escape(version)}\]", changelog, flags=re.MULTILINE) is None:
    raise SystemExit(f"CHANGELOG.md has no release-notes section for {version}")
PY

if [[ "$RUN_FAST_CHECKS" == "1" ]]; then
  bash scripts/ci/run-fast-checks.sh
fi

BUILD_SOURCE_DIR="$RELEASE_WORK_DIR/source"
DIRECT_DIST_DIR="$RELEASE_WORK_DIR/direct-dist"
SDIST_EXTRACT_DIR="$RELEASE_WORK_DIR/sdist"
FROM_SDIST_DIST_DIR="$RELEASE_WORK_DIR/from-sdist-dist"

"$PYTHON_BIN" - "$ROOT_DIR" "$BUILD_SOURCE_DIR" <<'PY'
from pathlib import Path
import shutil
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
destination.mkdir(parents=True)

for filename in ("pyproject.toml", "README.md", "LICENSE"):
    shutil.copy2(source / filename, destination / filename)
for directory in ("src", "tests"):
    shutil.copytree(
        source / directory,
        destination / directory,
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "*.pyc"),
    )
PY

rm -rf "$DIST_DIR"
"$BUILD_PYTHON" -m build --wheel --outdir "$DIRECT_DIST_DIR" "$BUILD_SOURCE_DIR"
"$BUILD_PYTHON" -m build --sdist --outdir "$DIRECT_DIST_DIR" "$BUILD_SOURCE_DIR"

shopt -s nullglob
DIRECT_WHEELS=("$DIRECT_DIST_DIR"/*.whl)
SDISTS=("$DIRECT_DIST_DIR"/*.tar.gz)
if [[ "${#DIRECT_WHEELS[@]}" -ne 1 || "${#SDISTS[@]}" -ne 1 ]]; then
  echo "expected exactly one wheel and one sdist in $DIRECT_DIST_DIR" >&2
  exit 1
fi
DIRECT_WHEEL="${DIRECT_WHEELS[0]}"
SDIST="${SDISTS[0]}"

"$PYTHON_BIN" scripts/release/validate_artifacts.py "$DIRECT_WHEEL" "$SDIST"

SDIST_SOURCE_DIR="$("$PYTHON_BIN" - "$SDIST" "$SDIST_EXTRACT_DIR" <<'PY'
from pathlib import Path, PurePosixPath
import sys
import tarfile

sdist = Path(sys.argv[1])
destination = Path(sys.argv[2])
destination.mkdir(parents=True)

with tarfile.open(sdist, mode="r:gz") as archive:
    members = archive.getmembers()
    roots = {
        PurePosixPath(member.name).parts[0]
        for member in members
        if PurePosixPath(member.name).parts
    }
    if len(roots) != 1:
        raise SystemExit(f"sdist must have exactly one archive root, found: {sorted(roots)}")
    archive.extractall(destination, filter="data")

print(destination / roots.pop())
PY
)"

"$BUILD_PYTHON" -m build --wheel --outdir "$FROM_SDIST_DIST_DIR" "$SDIST_SOURCE_DIR"
FROM_SDIST_WHEELS=("$FROM_SDIST_DIST_DIR"/*.whl)
if [[ "${#FROM_SDIST_WHEELS[@]}" -ne 1 ]]; then
  echo "expected exactly one wheel rebuilt from $SDIST" >&2
  exit 1
fi
FROM_SDIST_WHEEL="${FROM_SDIST_WHEELS[0]}"

"$PYTHON_BIN" scripts/release/validate_artifacts.py "$FROM_SDIST_WHEEL"

echo "Smoke-testing direct wheel: $(basename "$DIRECT_WHEEL")"
"$PYTHON_BIN" scripts/release/smoke_installed_wheel.py \
  "$DIRECT_WHEEL" \
  --project-root "$ROOT_DIR" \
  --expected-version "$PACKAGE_VERSION"

echo "Smoke-testing wheel rebuilt from sdist: $(basename "$FROM_SDIST_WHEEL")"
"$PYTHON_BIN" scripts/release/smoke_installed_wheel.py \
  "$FROM_SDIST_WHEEL" \
  --project-root "$ROOT_DIR" \
  --expected-version "$PACKAGE_VERSION"

mkdir -p "$DIST_DIR"
cp "$DIRECT_WHEEL" "$SDIST" "$DIST_DIR/"

(
  cd "$DIST_DIR"
  find . -maxdepth 1 -type f -print0 | sort -z | xargs -0 shasum -a 256 > "$RELEASE_WORK_DIR/SHA256SUMS"
)
cp "$RELEASE_WORK_DIR/SHA256SUMS" "$DIST_DIR/SHA256SUMS"

echo "Built release artifacts for $RELEASE_TAG:"
ls -1 "$DIST_DIR"
echo "Validated wheel rebuilt from sdist: $(basename "$FROM_SDIST_WHEEL")"
