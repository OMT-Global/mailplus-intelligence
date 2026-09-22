#!/usr/bin/env python3
"""Exercise the operator workflow from a clean installed wheel."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
import venv
from pathlib import Path


class SmokeFailure(RuntimeError):
    """Raised when an installed-wheel smoke step fails."""


def _run(command: list[str], label: str, *, echo: bool = True) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        output = "\n".join(
            part.rstrip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        raise SmokeFailure(f"{label} failed with exit {completed.returncode}:\n{output}")
    output = completed.stdout.strip()
    if echo and output:
        print(output)
    return output


def smoke_wheel(wheel: Path, project_root: Path, expected_version: str) -> None:
    """Install and exercise one wheel in an isolated temporary environment."""

    wheel = wheel.resolve()
    project_root = project_root.resolve()
    if not wheel.is_file():
        raise SmokeFailure(f"wheel does not exist: {wheel}")
    expected_schema_version = len(
        tuple((project_root / "src" / "mailplus_intelligence" / "migrations").glob("*.sql"))
    )
    if expected_schema_version < 1:
        raise SmokeFailure("source tree has no migration resources to validate")

    with tempfile.TemporaryDirectory(prefix="mailplus-wheel-smoke-") as temporary:
        work_dir = Path(temporary)
        environment = work_dir / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / "bin" / "python"
        mpi = environment / "bin" / "mpi"

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(wheel),
            ],
            "wheel installation",
            echo=False,
        )

        version_output = _run([str(mpi), "--version"], "mpi --version")
        expected_output = f"mpi {expected_version}"
        if version_output != expected_output:
            raise SmokeFailure(
                f"installed CLI version mismatch: expected {expected_output!r}, got {version_output!r}"
            )

        _run(
            [str(mpi), "doctor", "--project-root", str(project_root)],
            "mpi doctor",
        )

        database = work_dir / "mpi.db"
        migration_program = textwrap.dedent(
            """
            import sys
            from mailplus_intelligence import apply_all_migrations, connect_sqlite, current_schema_version

            connection = connect_sqlite(sys.argv[1])
            try:
                apply_all_migrations(connection)
                version = current_schema_version(connection)
            finally:
                connection.close()
            expected_version = int(sys.argv[2])
            if version != expected_version:
                raise SystemExit(f"expected schema user_version={expected_version}, got {version}")
            print(f"schema user_version={version}")
            """
        )
        _run(
            [str(python), "-c", migration_program, str(database), str(expected_schema_version)],
            "empty database migration",
        )

        fixture_dir = project_root / "fixtures" / "mailplus_metadata"
        _run(
            [
                str(mpi),
                "--db",
                str(database),
                "seed",
                "--from-fixtures",
                str(fixture_dir),
            ],
            "fixture seed",
        )

        search_output = _run(
            [
                str(mpi),
                "--db",
                str(database),
                "--json",
                "search",
                "--keyword",
                "Atlas",
            ],
            "fixture search",
            echo=False,
        )
        search_results = json.loads(search_output)
        if not search_results:
            raise SmokeFailure("fixture search returned no results")
        print(f"fixture search returned {len(search_results)} result(s)")

        queue_output = _run(
            [str(mpi), "--db", str(database), "queue", "--json", "list"],
            "queue list",
            echo=False,
        )
        queue_items = json.loads(queue_output)
        if not queue_items:
            raise SmokeFailure("fixture seed produced an empty review queue")
        artifact_id = str(queue_items[0]["artifact_id"])
        expected_revision = str(queue_items[0]["revision"])
        print(f"queue contains {len(queue_items)} candidate(s)")

        _run(
            [str(mpi), "--db", str(database), "queue", "inspect", artifact_id],
            "queue inspect",
        )
        _run(
            [
                str(mpi),
                "--db",
                str(database),
                "queue",
                "approve",
                artifact_id,
                "--reviewer",
                "installed-wheel-smoke",
                "--expected-revision",
                expected_revision,
                "--notes",
                "installed-wheel smoke approval",
            ],
            "queue approval",
        )

        export_dir = work_dir / "export"
        _run(
            [str(mpi), "--db", str(database), "export", "--output", str(export_dir)],
            "dry-run export",
        )
        manifest_path = export_dir / "export-manifest.json"
        if not manifest_path.is_file():
            raise SmokeFailure("dry-run export did not create export-manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dry_run") is not True or int(manifest.get("artifact_count", 0)) < 1:
            raise SmokeFailure(f"invalid dry-run export manifest: {manifest}")
        for artifact in manifest["artifacts"]:
            if not (export_dir / artifact["target_path"]).is_file():
                raise SmokeFailure(
                    f"dry-run export omitted artifact file: {artifact['target_path']}"
                )

        print(
            f"installed-wheel smoke passed: {wheel.name}; "
            f"schema={expected_schema_version}, search={len(search_results)}, queue={len(queue_items)}, "
            f"exports={manifest['artifact_count']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)

    try:
        smoke_wheel(args.wheel, args.project_root, args.expected_version)
    except (SmokeFailure, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"installed-wheel smoke failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
