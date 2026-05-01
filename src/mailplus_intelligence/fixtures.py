"""Fixture corpus helpers for offline MailPlus metadata work."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MetadataFixtureCorpus:
    """Loaded synthetic metadata fixture corpus."""

    version: int
    messages: tuple[dict[str, Any], ...]
    expected_threads: dict[str, Any]


def load_metadata_fixture_corpus(corpus_dir: str | Path) -> MetadataFixtureCorpus:
    """Load the privacy-safe metadata fixture corpus from ``corpus_dir``."""

    base = Path(corpus_dir)
    messages_path = base / "messages.json"
    expected_threads_path = base / "expected_threads.json"

    with messages_path.open(encoding="utf-8") as handle:
        messages_payload = json.load(handle)
    with expected_threads_path.open(encoding="utf-8") as handle:
        expected_threads_payload = json.load(handle)

    return MetadataFixtureCorpus(
        version=int(messages_payload["version"]),
        messages=tuple(messages_payload["messages"]),
        expected_threads=expected_threads_payload,
    )
