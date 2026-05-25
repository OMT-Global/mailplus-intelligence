"""Tests for llm_extractor.py using cassette playback (no live API calls)."""

from __future__ import annotations

import json
import unittest

from mailplus_intelligence.extractor import ExtractionCandidate
from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.llm_extractor import (
    DEFAULT_LLM_MODEL,
    LLMNotAvailable,
    LLMUsageStats,
    extract_corpus_with_llm,
    extract_with_llm,
    resolve_llm_model,
)
from mailplus_intelligence.threading import reconstruct_fixture_threads


FIXTURE_DIR = "fixtures/mailplus_metadata"


def _build_cassette(thread_id: str, artifacts: list[dict]) -> dict[str, str]:
    return {thread_id: json.dumps(artifacts)}


class LLMExtractorCassetteTests(unittest.TestCase):
    def setUp(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        self.threads = reconstruct_fixture_threads(corpus.messages)
        self.messages = list(corpus.messages)

    def test_cassette_hit_returns_candidates(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        cassette = _build_cassette(
            thread.thread_id,
            [{"artifact_type": "thread_summary", "summary": "Test summary.",
              "confidence": "high", "review_status": "candidate"}],
        )
        result = extract_with_llm(thread, self.messages, cassette=cassette)
        self.assertTrue(result.cassette_hit)
        self.assertGreaterEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].provenance, "llm")
        self.assertEqual(result.candidates[0].summary, "Test summary.")

    def test_cassette_miss_raises_without_credentials(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        # A non-matching cassette key forces a live API call, which fails without
        # credentials.  Verify the right error is raised rather than a silent pass.
        with self.assertRaises(LLMNotAvailable) as raised:
            extract_with_llm(thread, self.messages, cassette={"other-thread": "[]"})
        self.assertTrue(
            "mailplus-intelligence[llm]" in str(raised.exception)
            or "ANTHROPIC_API_KEY" in str(raised.exception)
        )

    def test_corpus_cassette_aggregates_across_threads(self) -> None:
        cassette: dict[str, str] = {}
        for t in self.threads:
            cassette[t.thread_id] = json.dumps(
                [{"artifact_type": "thread_summary", "summary": f"Summary for {t.thread_id}.",
                  "confidence": "medium", "review_status": "candidate"}]
            )
        result = extract_corpus_with_llm(self.threads, self.messages, cassette=cassette)
        self.assertGreaterEqual(len(result.candidates), 1)
        for c in result.candidates:
            self.assertEqual(c.provenance, "llm")

    def test_invalid_json_response_falls_back_gracefully(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        cassette = {thread.thread_id: "not valid json {{ }}"}
        result = extract_with_llm(thread, self.messages, cassette=cassette)
        self.assertGreaterEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].artifact_type, "thread_summary")

    def test_usage_stats_accumulate_across_corpus(self) -> None:
        cassette: dict[str, str] = {}
        for t in self.threads:
            cassette[t.thread_id] = json.dumps(
                [{"artifact_type": "thread_summary", "summary": "S",
                  "confidence": "low", "review_status": "candidate"}]
            )
        result = extract_corpus_with_llm(self.threads, self.messages, cassette=cassette)
        # Cassette calls don't increment API token stats, but calls counter stays 0.
        self.assertEqual(result.usage.calls, 0)

    def test_noise_threads_skipped(self) -> None:
        # Build a synthetic message in noise lane.
        messages = [
            {
                "fixture_id": "msg-noise-001",
                "message_id": "<noise-001@example.test>",
                "subject": "Daily digest for you",
                "from": "no-reply@newsletter.example.com",
                "to": ["operator@example.test"],
                "date": "2026-01-01T00:00:00Z",
                "mailbox": "operator@example.test",
                "folder": "Inbox",
                "locator": {"uid": "99", "account": "fixture-account"},
                "attachments": [],
            }
        ]
        from mailplus_intelligence.threading import reconstruct_fixture_threads as rft

        for thread in rft(messages):
            result = extract_with_llm(thread, messages, cassette={})
            self.assertEqual(result.candidates, [])

    def test_model_resolution_prefers_argument_then_environment(self) -> None:
        self.assertEqual(resolve_llm_model("claude-test"), "claude-test")

        import os

        old = os.environ.get("MAILPLUS_LLM_MODEL")
        try:
            os.environ["MAILPLUS_LLM_MODEL"] = "claude-env"
            self.assertEqual(resolve_llm_model(), "claude-env")
        finally:
            if old is None:
                os.environ.pop("MAILPLUS_LLM_MODEL", None)
            else:
                os.environ["MAILPLUS_LLM_MODEL"] = old

        self.assertEqual(resolve_llm_model(), old or DEFAULT_LLM_MODEL)


if __name__ == "__main__":
    unittest.main()
