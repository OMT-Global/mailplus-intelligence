"""Fixture-mode preflight checks for local agent work."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .fixtures import load_metadata_fixture_corpus
from .llm_extractor import resolve_llm_model
from .runtime import default_runtime_profile
from .schema import apply_schema_v0, current_schema_version
from .sqlite import connect_sqlite


@dataclass(frozen=True)
class DoctorCheck:
    """Single preflight check result."""

    name: str
    status: str
    message: str
    next_step: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    """Aggregated preflight report."""

    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.status in {"ok", "gated"} for check in self.checks)


def run_fixture_doctor(project_root: str | Path = ".") -> DoctorReport:
    """Run local fixture-mode readiness checks."""

    root = Path(project_root)
    checks: list[DoctorCheck] = []

    profile = default_runtime_profile()
    checks.append(
        DoctorCheck(
            "runtime",
            "ok" if sys.version_info >= (3, 12) else "fail",
            f"python {sys.version_info.major}.{sys.version_info.minor}; expected >=3.12",
            None if sys.version_info >= (3, 12) else "Install Python 3.12 or newer.",
        )
    )
    checks.append(
        DoctorCheck(
            "storage",
            "ok" if profile.storage_engine == "sqlite" else "fail",
            f"selected storage engine: {profile.storage_engine}",
            None if profile.storage_engine == "sqlite" else "Use the default SQLite runtime profile.",
        )
    )

    manifest = root / "project.bootstrap.yaml"
    checks.append(
        DoctorCheck(
            "manifest",
            "ok" if manifest.exists() else "fail",
            "project.bootstrap.yaml present" if manifest.exists() else "missing project.bootstrap.yaml",
            None if manifest.exists() else "Run doctor from the repository root.",
        )
    )

    fixture_dir = root / "fixtures" / "mailplus_metadata"
    try:
        corpus = load_metadata_fixture_corpus(fixture_dir)
        checks.append(
            DoctorCheck(
                "fixtures",
                "ok",
                f"loaded metadata fixture corpus with {len(corpus.messages)} messages",
            )
        )
    except Exception as exc:
        checks.append(
            DoctorCheck(
                "fixtures",
                "fail",
                f"fixture corpus unavailable: {exc}",
                "Confirm fixtures/mailplus_metadata exists or restore the fixture corpus.",
            )
        )

    try:
        connection = connect_sqlite()
        try:
            apply_schema_v0(connection)
            checks.append(
                DoctorCheck(
                    "schema",
                    "ok",
                    f"metadata schema user_version={current_schema_version(connection)}",
                )
            )
        finally:
            connection.close()
    except Exception as exc:
        checks.append(
            DoctorCheck(
                "schema",
                "fail",
                f"schema bootstrap failed: {exc}",
                "Check SQLite availability and repository migrations.",
            )
        )

    live_keys = ("MAILPLUS_HOST", "MAILPLUS_USER", "MAILPLUS_TOKEN")
    missing_live_keys = [key for key in live_keys if not os.environ.get(key)]
    checks.append(
        DoctorCheck(
            "live-mailplus",
            "gated" if missing_live_keys else "ok",
            (
                "live MailPlus credentials intentionally unavailable in fixture mode"
                if missing_live_keys
                else "live MailPlus credential environment is present"
            ),
            (
                "Set MAILPLUS_HOST, MAILPLUS_USER, and MAILPLUS_TOKEN only when testing live access."
                if missing_live_keys
                else None
            ),
        )
    )

    try:
        import anthropic  # noqa: F401

        sdk_available = True
    except ImportError:
        sdk_available = False

    api_key_present = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if sdk_available and api_key_present:
        llm_status = "ok"
        llm_message = f"LLM extraction available; model={resolve_llm_model()}"
    elif sdk_available:
        llm_status = "gated"
        llm_message = f"Anthropic SDK installed; ANTHROPIC_API_KEY missing; model={resolve_llm_model()}"
    else:
        llm_status = "gated"
        llm_message = f"Anthropic SDK not installed; deterministic extraction only; model={resolve_llm_model()}"
    checks.append(DoctorCheck("llm", llm_status, llm_message))

    return DoctorReport(tuple(checks))


def format_doctor_report(report: DoctorReport) -> str:
    """Render a compact operator-facing doctor report."""

    lines = ["MailPlus Intelligence fixture doctor"]
    for check in report.checks:
        lines.append(f"- {check.status}: {check.name}: {check.message}")
        if check.next_step:
            lines.append(f"  next: {check.next_step}")
    lines.append(f"result: {'ok' if report.ok else 'failed'}")
    return "\n".join(lines)


def main() -> int:
    """CLI entry point for fixture-mode preflight."""

    report = run_fixture_doctor()
    print(format_doctor_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
