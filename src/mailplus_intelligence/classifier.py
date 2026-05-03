"""Deterministic baseline classifier for metadata-only mail lanes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassificationResult:
    """Explainable classification decision."""

    lane: str
    confidence: str
    reason_code: str
    extraction_allowed: bool


NOISE_SUBJECT_TOKENS = (
    "newsletter",
    "off today",
    "receipt",
    "build succeeded",
    "daily digest",
    "shipping update",
    "webinar",
    "status page",
    "recommended articles",
    "login notice",
)

LANE_RULES = (
    ("vip", ("board follow-up", "decision today", "private admin", "review before filing", "intro request")),
    ("legal", ("contract redline", "filing", "nda", "compliance", "settlement", "legal")),
    ("travel", ("flight", "hotel", "rental car", "visa", "trip", "itinerary")),
    ("financial", ("invoice", "payment", "statement", "tax", "subscription", "billing")),
    ("project", ("project", "design review", "sprint", "api contract", "launch")),
    ("admin", ("access", "domain", "workspace", "security", "vendor onboarding")),
)


def classify_metadata(subject: str, sender: str = "") -> ClassificationResult:
    """Classify a message from safe metadata fields only."""

    haystack = f"{subject} {sender}".lower()

    if any(token in haystack for token in NOISE_SUBJECT_TOKENS) or "no-reply@" in haystack:
        return ClassificationResult("ignore_noise", "high", "noise_suppression", False)

    for lane, tokens in LANE_RULES:
        if any(token in haystack for token in tokens):
            return ClassificationResult(lane, "medium", f"{lane}_metadata_rule", True)

    return ClassificationResult("review_needed", "low", "no_rule_match", False)
