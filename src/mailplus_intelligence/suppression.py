"""Noise suppression rules for metadata-only MailPlus fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPRESSION_FAMILIES = {
    "newsletter_digest",
    "promotion",
    "receipt",
    "automation_status",
    "routine_bulk_notice",
    "no_reply_bulk",
}


@dataclass(frozen=True)
class SuppressionDecision:
    """Decision used to keep metadata searchable while gating extraction."""

    action: str
    family: str | None
    searchable_metadata: bool
    extraction_default: bool
    reasons: tuple[str, ...]


def classify_noise_suppression(message: dict[str, Any]) -> SuppressionDecision:
    """Classify whether a metadata-only message should be suppressed."""

    sender = str(message.get("from", "")).lower()
    subject = str(message.get("subject", "")).lower()
    folder = str(message.get("folder", "")).lower()
    labels = {str(label).lower() for label in message.get("labels", [])}
    headers = {
        str(key).lower(): str(value).lower()
        for key, value in dict(message.get("headers", {})).items()
    }
    flags = {str(flag).lower() for flag in message.get("flags", [])}

    if _has_human_project_signal(labels):
        return SuppressionDecision(
            action="allow",
            family=None,
            searchable_metadata=True,
            extraction_default=True,
            reasons=("human-project-context",),
        )

    if _has_explicit_review_signal(labels, flags):
        return _review_needed("explicit-importance-signal")

    if "list-unsubscribe" in headers or "list-id" in headers:
        if _contains_any(subject, ("newsletter", "digest", "roundup", "webinar")):
            return _suppress("newsletter_digest", "list-header-with-digest-subject")

    if _contains_any(sender, ("promo", "deals", "marketing")) or _contains_any(
        subject, ("sale", "discount", "limited time", "offer")
    ):
        return _suppress("promotion", "promotion-sender-or-subject")

    if "receipt" in labels or "receipts" in folder or "receipt" in subject:
        return _suppress("receipt", "receipt-label-folder-or-subject")

    if headers.get("auto-submitted") and _contains_any(
        subject, ("status", "resolved", "monitor", "ci", "build")
    ):
        return _suppress("automation_status", "automation-header-with-status-subject")

    if _contains_any(subject, ("login", "shipping", "account notice", "password reset")):
        return _suppress("routine_bulk_notice", "routine-notice-subject")

    if _contains_any(sender, ("no-reply", "noreply", "do-not-reply")) and (
        "bulk" in labels or "precedence" in headers and headers["precedence"] == "bulk"
    ):
        return _suppress("no_reply_bulk", "no-reply-bulk-signal")

    return SuppressionDecision(
        action="allow",
        family=None,
        searchable_metadata=True,
        extraction_default=True,
        reasons=(),
    )


def _suppress(family: str, reason: str) -> SuppressionDecision:
    return SuppressionDecision(
        action="suppress",
        family=family,
        searchable_metadata=True,
        extraction_default=False,
        reasons=(reason,),
    )


def _review_needed(reason: str) -> SuppressionDecision:
    return SuppressionDecision(
        action="review_needed",
        family=None,
        searchable_metadata=True,
        extraction_default=False,
        reasons=(reason,),
    )


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _has_human_project_signal(labels: set[str]) -> bool:
    return "project" in labels


def _has_explicit_review_signal(labels: set[str], flags: set[str]) -> bool:
    return bool(
        labels.intersection({"important", "needs-review", "financial", "legal"})
    ) or ("flagged" in flags)
