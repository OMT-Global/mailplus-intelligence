"""Deterministic thread reconstruction for offline fixture records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReconstructedThread:
    """Thread grouping with confidence and basis evidence."""

    thread_id: str
    message_fixture_ids: tuple[str, ...]
    confidence: str
    basis: tuple[str, ...]


_SUBJECT_PREFIX_RE = re.compile(r"^(re|fw|fwd):\s*", re.IGNORECASE)


def _is_malformed_optional_message_id(value: Any) -> bool:
    return bool(value) and not str(value).startswith("<")


def normalize_subject(subject: str) -> str:
    """Normalize conservative reply/forward prefixes for subject fallback."""

    normalized = subject.strip()
    while True:
        stripped = _SUBJECT_PREFIX_RE.sub("", normalized).strip()
        if stripped == normalized:
            return stripped.lower()
        normalized = stripped


def reconstruct_fixture_threads(messages: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> tuple[ReconstructedThread, ...]:
    """Reconstruct fixture threads using explicit links before subject fallback."""

    by_message_id = {str(message["message_id"]): message for message in messages}
    parent: dict[str, str] = {
        str(message["fixture_id"]): str(message["fixture_id"]) for message in messages
    }

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    message_id_owner: dict[str, str] = {}
    bases: dict[str, set[str]] = {str(message["fixture_id"]): set() for message in messages}

    for message in messages:
        fixture_id = str(message["fixture_id"])
        message_id = str(message["message_id"])
        if message_id in message_id_owner:
            union(message_id_owner[message_id], fixture_id)
            bases[fixture_id].update({"duplicate-message-id", "locator-variant"})
        else:
            message_id_owner[message_id] = fixture_id
            bases[fixture_id].add("message-id")

        for linked_message_id in message.get("references", ()):
            linked = by_message_id.get(str(linked_message_id))
            if linked:
                union(str(linked["fixture_id"]), fixture_id)
                bases[fixture_id].add("references")

        if message.get("in_reply_to"):
            linked = by_message_id.get(str(message["in_reply_to"]))
            if linked:
                union(str(linked["fixture_id"]), fixture_id)
                bases[fixture_id].add("in-reply-to")

    subject_groups: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        subject_groups.setdefault(normalize_subject(str(message["subject"])), []).append(message)
    for group in subject_groups.values():
        if len(group) > 1:
            root = str(group[0]["fixture_id"])
            for message in group[1:]:
                fixture_id = str(message["fixture_id"])
                if (
                    not message.get("references")
                    and not message.get("in_reply_to")
                    and find(root) != find(fixture_id)
                ):
                    union(root, fixture_id)
                    bases[fixture_id].add("subject-fallback")

    grouped: dict[str, list[str]] = {}
    basis_by_root: dict[str, set[str]] = {}
    for message in messages:
        fixture_id = str(message["fixture_id"])
        root = find(fixture_id)
        grouped.setdefault(root, []).append(fixture_id)
        basis_by_root.setdefault(root, set()).update(bases[fixture_id])
        if any(_is_malformed_optional_message_id(value) for value in message.get("references", ())) or (
            _is_malformed_optional_message_id(message.get("in_reply_to"))
        ):
            basis_by_root[root].add("malformed-optional-headers")
        if str(message["subject"]).lower().startswith(("fw:", "fwd:")):
            basis_by_root[root].add("subject-forward-prefix")
            basis_by_root[root].add("distinct-message-id")

    threads: list[ReconstructedThread] = []
    for index, (root, fixture_ids) in enumerate(sorted(grouped.items(), key=lambda item: min(item[1])), start=1):
        basis = basis_by_root[root]
        if "malformed-optional-headers" in basis:
            confidence = "low"
        elif "subject-fallback" in basis or "subject-forward-prefix" in basis:
            confidence = "medium"
        else:
            confidence = "high"
        thread_hint = next(
            str(message.get("thread_hint", ""))
            for message in messages
            if str(message["fixture_id"]) == fixture_ids[0]
        )
        threads.append(
            ReconstructedThread(
                thread_id=thread_hint or f"thread-{index}",
                message_fixture_ids=tuple(fixture_ids),
                confidence=confidence,
                basis=tuple(sorted(basis)),
            )
        )

    return tuple(threads)
