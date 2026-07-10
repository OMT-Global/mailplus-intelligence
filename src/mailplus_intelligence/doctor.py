"""Fixture-mode preflight checks for local agent work."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .fixtures import load_metadata_fixture_corpus
from .live_adapter import (
    LIVE_OPTIONAL_ENV_VARS,
    LIVE_REQUIRED_ENV_VARS,
    LiveAdapterNotConfigured,
    load_live_config,
)
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

    missing_live_keys = [
        key
        for key in LIVE_REQUIRED_ENV_VARS
        if not (os.environ.get(key) or "").strip()
    ]
    any_live_configuration = any(
        key in os.environ for key in (*LIVE_REQUIRED_ENV_VARS, *LIVE_OPTIONAL_ENV_VARS)
    )
    live_configuration_error: str | None = None
    if not missing_live_keys:
        try:
            load_live_config()
        except LiveAdapterNotConfigured as exc:
            live_configuration_error = str(exc)
    live_configured = not missing_live_keys and live_configuration_error is None
    live_configuration_status = (
        "ok" if live_configured else "fail" if any_live_configuration else "gated"
    )
    checks.append(
        DoctorCheck(
            "live-configured",
            live_configuration_status,
            (
                "required live process environment variables are present and locally parseable"
                if live_configured
                else (
                    f"missing required variables: {', '.join(missing_live_keys)}"
                    if missing_live_keys
                    else live_configuration_error or "live configuration is invalid"
                )
            ),
            (
                None
                if live_configured
                else (
                    "Export MAILPLUS_HOST, MAILPLUS_USER, and MAILPLUS_TOKEN in "
                    "the invoking process; files are not loaded automatically."
                    if missing_live_keys
                    else "Correct the named environment setting before retrying."
                )
            ),
        )
    )

    capability_reason = (
        "not checked; the live network transport is not implemented"
        if live_configured
        else (
            "not checked because live configuration is invalid or incomplete"
            if any_live_configuration
            else "not checked because live configuration is absent"
        )
    )
    checks.extend(
        (
            DoctorCheck(
                "live-reachable",
                "gated",
                capability_reason,
                "Use fixture mode until a credential-gated reachability probe is implemented.",
            ),
            DoctorCheck(
                "live-authenticated",
                "gated",
                capability_reason,
                (
                    "Do not infer authentication from variable presence; use a "
                    "future explicit live probe."
                ),
            ),
            DoctorCheck(
                "live-sync-capable",
                "gated",
                "not available; the live adapter currently returns a stub batch",
                "Use fixture seed and search workflows until read-only live sync is implemented.",
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
        llm_next_step = None
    elif sdk_available:
        llm_status = "gated"
        llm_message = (
            "Anthropic SDK installed; ANTHROPIC_API_KEY missing; "
            f"model={resolve_llm_model()}"
        )
        llm_next_step = (
            "Export ANTHROPIC_API_KEY only for an approved live LLM extraction run."
        )
    else:
        llm_status = "gated"
        llm_message = (
            "Anthropic SDK not installed; deterministic extraction only; "
            f"model={resolve_llm_model()}"
        )
        llm_next_step = (
            "Install the llm extra only when optional live LLM extraction is approved."
        )
    checks.append(DoctorCheck("llm", llm_status, llm_message, llm_next_step))

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
