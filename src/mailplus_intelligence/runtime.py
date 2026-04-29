"""Runtime selection for the M0 package baseline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeProfile:
    """Concrete runtime decision for early MailPlus Intelligence work."""

    language: str
    python_version: str
    storage_engine: str
    live_mailplus_access: bool
    rationale: tuple[str, ...]


def default_runtime_profile() -> RuntimeProfile:
    """Return the selected non-live M0 runtime profile."""

    return RuntimeProfile(
        language="python",
        python_version="3.12",
        storage_engine="sqlite",
        live_mailplus_access=False,
        rationale=(
            "Python keeps indexing and extraction work close to the data tooling ecosystem.",
            "SQLite gives the metadata/thread index a local-first foundation before live sync.",
            "M0 intentionally excludes live MailPlus, DSM, and NAS access.",
        ),
    )
