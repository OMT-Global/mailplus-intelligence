"""Explicit, transient source-text fetch boundary for selected messages.

This module deliberately has no database dependency and no sync integration.
Callers must select one exact locator and a narrow purpose before a backend may
return source text.  The returned buffer is short-lived; durable artifacts use
only a hash-shaped evidence reference and the original metadata locator.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Protocol

from .semantic_contract import SemanticArtifact


ALLOWED_FETCH_PURPOSES = frozenset({"extraction", "review"})
ALLOWED_DATA_CLASSES = frozenset({"minimized-source"})
TRANSIENT_EXTRACTOR_VERSION = "transient-source-extractor-v1"
TRANSIENT_RULE_VERSION = "transient-source-rules-v1"


class SourceFetchError(RuntimeError):
    """Base error for the opt-in source-fetch boundary."""


class SourceFetchNotFound(SourceFetchError):
    """The requested exact locator does not exist in this backend."""


class SourceFetchMoved(SourceFetchError):
    """A known locator is no longer present at its expected mailbox location."""


class SourceFetchAmbiguous(SourceFetchError):
    """A request was not sufficiently exact to identify one source message."""


class SourceFetchCredentialGated(SourceFetchError):
    """A live backend needs an explicitly approved credential configuration."""


class SourceFetchBackendUnavailable(SourceFetchError):
    """A source backend could not safely complete the selected fetch."""


class SourceFetchPolicyError(SourceFetchError):
    """The operator request is outside the transient-source policy."""


class TransientSourceDisposed(SourceFetchError):
    """A caller tried to use a buffer after its disposal boundary."""


@dataclass(frozen=True)
class SourceLocator:
    """The exact metadata identity required for a source fetch."""

    export_id: str
    uid: str
    account: str
    mailbox: str
    folder_path: str
    message_id: str | None = None
    thread_key: str | None = None

    def __post_init__(self) -> None:
        required = (self.export_id, self.uid, self.account, self.mailbox, self.folder_path)
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise SourceFetchAmbiguous("source fetch requires a complete exact metadata locator")

    def as_artifact_locator(self) -> dict[str, str]:
        return {
            "locator_export_id": self.export_id,
            "locator_uid": self.uid,
            "account": self.account,
            "mailbox": self.mailbox,
            "folder": self.folder_path,
        }


@dataclass(frozen=True)
class SourceFetchRequest:
    """An operator-selected fetch request; selection is never inferred."""

    locator: SourceLocator
    purpose: str
    allowed_data_class: str = "minimized-source"

    def __post_init__(self) -> None:
        if self.purpose not in ALLOWED_FETCH_PURPOSES:
            raise SourceFetchPolicyError("source fetch purpose must be extraction or review")
        if self.allowed_data_class not in ALLOWED_DATA_CLASSES:
            raise SourceFetchPolicyError("source fetch data class is not permitted")


class SourceFetchBackend(Protocol):
    def fetch_exact(self, locator: SourceLocator) -> str: ...


@dataclass
class FixtureSourceBackend:
    """Synthetic-only fake backend used by tests and operator-safe fixtures."""

    records: Mapping[SourceLocator, str]
    unavailable: bool = False
    moved: frozenset[SourceLocator] = frozenset()
    requests: list[SourceLocator] = field(default_factory=list)

    def fetch_exact(self, locator: SourceLocator) -> str:
        self.requests.append(locator)
        if self.unavailable:
            raise SourceFetchBackendUnavailable("fixture source backend is unavailable")
        if locator in self.moved:
            raise SourceFetchMoved("selected source locator has moved; refresh metadata first")
        try:
            return self.records[locator]
        except KeyError as exc:
            same_export = [item for item in self.records if item.export_id == locator.export_id]
            if same_export:
                raise SourceFetchMoved("selected source locator no longer matches mailbox metadata") from exc
            raise SourceFetchNotFound("selected source locator was not found") from exc


class LiveSourceBackend:
    """A deliberate dependency seam; live body fetch is unavailable until #106."""

    def fetch_exact(self, locator: SourceLocator) -> str:
        del locator
        raise SourceFetchCredentialGated(
            "live source fetch is credential-gated and unavailable until the approved IMAP adapter is configured"
        )


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|password|authorization)\s*[:=]\s*[^\s]+"
)
_SENSITIVE_LINK = re.compile(
    r"https?://[^\s<>()]+(?:reset|recover|magic|oauth|token|checkout|invoice|payment|tracking)[^\s<>()]*",
    re.IGNORECASE,
)
_URL_WITH_QUERY = re.compile(r"https?://[^\s<>()?]+\?[^\s<>()]+", re.IGNORECASE)
_SIGNATURE = re.compile(r"(?ms)^--\s*$.*\Z")
_QUOTED_HISTORY = re.compile(r"(?ms)^On .+?wrote:\s*.*\Z|^>.*(?:\n>.*)*")
_WHITESPACE = re.compile(r"[ \t]+")


def minimize_source_text(value: str) -> str:
    """Remove high-risk and unnecessary content before any extraction use."""

    if not isinstance(value, str):
        raise SourceFetchBackendUnavailable("source backend returned malformed text")
    minimized = _SIGNATURE.sub("", value)
    minimized = _QUOTED_HISTORY.sub("", minimized)
    minimized = _SECRET_ASSIGNMENT.sub("[REDACTED_SECRET]", minimized)
    minimized = _SENSITIVE_LINK.sub("[REDACTED_LINK]", minimized)
    minimized = _URL_WITH_QUERY.sub("[REDACTED_LINK]", minimized)
    lines = [_WHITESPACE.sub(" ", line).strip() for line in minimized.splitlines()]
    return "\n".join(line for line in lines if line).strip()


@dataclass
class TransientSource:
    """An in-memory source buffer with explicit best-effort disposal."""

    locator: SourceLocator
    purpose: str
    _buffer: bytearray = field(repr=False)
    _disposed: bool = field(default=False, init=False, repr=False)

    @property
    def text(self) -> str:
        if self._disposed:
            raise TransientSourceDisposed("transient source buffer has been disposed")
        return self._buffer.decode("utf-8")

    @property
    def minimized_text(self) -> str:
        return minimize_source_text(self.text)

    def dispose(self) -> None:
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self._buffer.clear()
        self._disposed = True

    def __enter__(self) -> "TransientSource":
        return self

    def __exit__(self, *_: object) -> None:
        self.dispose()


def fetch_selected_source(request: SourceFetchRequest, backend: SourceFetchBackend) -> TransientSource:
    """Fetch one selected source without storing, logging, or caching its text."""

    source = backend.fetch_exact(request.locator)
    return TransientSource(request.locator, request.purpose, bytearray(source.encode("utf-8")))


def evidence_reference(minimized_text: str) -> str:
    """Return a non-reversible reference suitable for durable provenance."""

    digest = hashlib.sha256(minimized_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def extract_minimized_source(source: TransientSource) -> list[SemanticArtifact]:
    """Produce review-required deterministic candidates from minimized evidence only.

    This intentionally does not invoke cloud or local models.  Existing model
    policy remains metadata-only; a later, separately approved provider-policy
    extension must opt in before any minimized source text can leave process.
    """

    minimized = source.minimized_text
    if not minimized:
        return []
    locator = source.locator
    lower = minimized.lower()
    artifact_type = "decision" if any(token in lower for token in ("decided", "decision", "approved")) else "obligation"
    signal = "decision" if artifact_type == "decision" else "possible commitment or follow-up"
    message_id = locator.message_id or f"<locator:{locator.export_id}>"
    thread_key = locator.thread_key or f"source:{locator.export_id}"
    return [
        SemanticArtifact(
            artifact_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"transient:{locator.export_id}:{evidence_reference(minimized)}")),
            artifact_type=artifact_type,
            source_thread_key=thread_key,
            source_message_ids=(message_id,),
            source_locators=(locator.as_artifact_locator(),),
            evidence_refs=(evidence_reference(minimized),),
            summary=f"Selected source contains a {signal}; review the original MailPlus message before acting.",
            confidence="low",
            review_status="review_needed",
            provenance="deterministic",
            extractor_version=TRANSIENT_EXTRACTOR_VERSION,
            model_version=None,
            rule_version=TRANSIENT_RULE_VERSION,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    ]
