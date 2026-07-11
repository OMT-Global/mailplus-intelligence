#!/usr/bin/env python3
"""Validate migration resources in MailPlus Intelligence release archives."""

from __future__ import annotations

import argparse
import sys
import tarfile
import zipfile
from pathlib import Path


REQUIRED_MIGRATIONS = (
    "001_metadata_schema_v0.sql",
    "002_attachment_metadata.sql",
    "003_cache_and_queue.sql",
    "004_semantic_provenance_review.sql",
)


class ArtifactValidationError(RuntimeError):
    """Raised when a release artifact omits a required package resource."""


def _require_nonempty(resources: dict[str, bytes], artifact: Path) -> None:
    missing = [name for name in REQUIRED_MIGRATIONS if name not in resources]
    if missing:
        rendered = ", ".join(f"migrations/{name}" for name in missing)
        raise ArtifactValidationError(
            f"{artifact.name} is missing required migration resources: {rendered}"
        )

    empty = [name for name, content in resources.items() if not content.strip()]
    if empty:
        rendered = ", ".join(f"migrations/{name}" for name in empty)
        raise ArtifactValidationError(
            f"{artifact.name} contains empty migration resources: {rendered}"
        )


def validate_wheel(path: Path) -> None:
    """Validate migration package data in a wheel archive."""

    try:
        with zipfile.ZipFile(path) as archive:
            resources: dict[str, bytes] = {}
            for name in REQUIRED_MIGRATIONS:
                member = f"mailplus_intelligence/migrations/{name}"
                try:
                    resources[name] = archive.read(member)
                except KeyError:
                    continue
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArtifactValidationError(f"cannot read wheel {path}: {exc}") from exc

    _require_nonempty(resources, path)


def validate_sdist(path: Path) -> None:
    """Validate migration package data in a source distribution."""

    try:
        with tarfile.open(path, mode="r:gz") as archive:
            members = {member.name: member for member in archive.getmembers() if member.isfile()}
            resources: dict[str, bytes] = {}
            for name in REQUIRED_MIGRATIONS:
                suffix = f"/src/mailplus_intelligence/migrations/{name}"
                matches = [member for member in members if f"/{member}".endswith(suffix)]
                if len(matches) != 1:
                    continue
                handle = archive.extractfile(members[matches[0]])
                if handle is not None:
                    resources[name] = handle.read()
    except (OSError, tarfile.TarError) as exc:
        raise ArtifactValidationError(f"cannot read sdist {path}: {exc}") from exc

    _require_nonempty(resources, path)


def validate_artifact(path: Path) -> None:
    """Validate one supported release artifact."""

    if not path.is_file():
        raise ArtifactValidationError(f"release artifact does not exist: {path}")
    if path.name.endswith(".whl"):
        validate_wheel(path)
        return
    if path.name.endswith(".tar.gz"):
        validate_sdist(path)
        return
    raise ArtifactValidationError(f"unsupported release artifact: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify required migration resources in wheels and source distributions."
    )
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args(argv)

    try:
        for artifact in args.artifacts:
            validate_artifact(artifact)
            migrations = ", ".join(REQUIRED_MIGRATIONS)
            print(f"validated {artifact.name}: {migrations}")
    except ArtifactValidationError as exc:
        print(f"artifact validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
