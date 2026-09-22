"""Tests for llm_extractor.py using cassette playback (no live API calls)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mailplus_intelligence.extractor import ExtractionCandidate
from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.llm_extractor import (
    DEFAULT_LLM_MODEL,
    LLMEgressPolicyError,
    LLMProviderPolicy,
    LLMUsageStats,
    extract_corpus_with_llm,
    extract_with_llm,
    load_llm_provider_policy,
    resolve_llm_model,
)
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite
from mailplus_intelligence.threading import reconstruct_fixture_threads


FIXTURE_DIR = "fixtures/mailplus_metadata"


def _build_cassette(thread_id: str, artifacts: list[dict]) -> dict[str, str]:
    return {thread_id: json.dumps(artifacts)}


class _FakeMessagesClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            content=[SimpleNamespace(
                type="text",
                text=json.dumps([{
                    "artifact_type": "thread_summary",
                    "summary": "Pseudonymized summary.",
                    "confidence": "medium",
                    "review_status": "candidate",
                }]),
            )],
        )


class _FakeClient:
    def __init__(self, *, mode: str = "cloud", provider: str = "anthropic") -> None:
        self.provider_mode = mode
        self.provider_name = provider
        self.messages = _FakeMessagesClient()


class _IncompleteResponseMessagesClient(_FakeMessagesClient):
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[])


class _IncompleteResponseClient(_FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.messages = _IncompleteResponseMessagesClient()


class LLMExtractorCassetteTests(unittest.TestCase):
    def setUp(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        self.threads = reconstruct_fixture_threads(corpus.messages)
        self.messages = list(corpus.messages)
        self.tempdir = tempfile.TemporaryDirectory()
        self.audit_path = Path(self.tempdir.name) / "llm-audit.db"
        self.audit_connection = connect_sqlite(self.audit_path)
        apply_all_migrations(self.audit_connection)

    def tearDown(self) -> None:
        self.audit_connection.close()
        self.tempdir.cleanup()

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

    def test_cassette_miss_fails_closed_when_provider_policy_is_disabled(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        with self.assertRaises(LLMEgressPolicyError) as raised:
            extract_with_llm(thread, self.messages, cassette={"other-thread": "[]"})
        self.assertIn("disabled", str(raised.exception))

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

    def test_provider_policy_defaults_to_disabled(self) -> None:
        policy = load_llm_provider_policy({})
        self.assertEqual(policy.mode, "disabled")
        self.assertFalse(policy.cloud_opt_in)

    def test_cloud_mode_requires_explicit_opt_in(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=False,
        )
        with self.assertRaisesRegex(LLMEgressPolicyError, "CLOUD_OPT_IN"):
            extract_with_llm(
                thread,
                self.messages,
                client=_FakeClient(),
                provider_policy=policy,
                audit_connection=self.audit_connection,
            )

    def test_cloud_mode_requires_a_strong_pseudonymization_key(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="too-short",
        )
        with self.assertRaisesRegex(LLMEgressPolicyError, "at least 32"):
            extract_with_llm(
                thread,
                self.messages,
                client=_FakeClient(),
                provider_policy=policy,
                audit_connection=self.audit_connection,
            )

    def test_provider_policy_rejects_undeclared_data_class(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        client = _FakeClient()
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="synthetic-test-pseudonymization-key",
        )
        with self.assertRaisesRegex(LLMEgressPolicyError, "not authorized"):
            extract_with_llm(
                thread,
                self.messages,
                client=client,
                provider_policy=policy,
                data_classes=frozenset({"selected-text"}),
                audit_connection=self.audit_connection,
            )
        self.assertEqual(client.messages.calls, [])

    def test_cloud_request_pseudonymizes_metadata_and_persists_payload_free_audit(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        thread_messages = [
            message for message in self.messages if message["fixture_id"] in thread.message_fixture_ids
        ]
        client = _FakeClient()
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="synthetic-test-pseudonymization-key",
        )
        result = extract_with_llm(
            thread,
            self.messages,
            client=client,
            model="claude-test",
            provider_policy=policy,
            audit_connection=self.audit_connection,
        )
        self.assertTrue(result.candidates)

        context = client.messages.calls[0]["messages"][0]["content"][0]["text"]
        for message in thread_messages:
            self.assertNotIn(str(message.get("from", "")), context)
            self.assertNotIn(str(message.get("subject", "")), context)
            self.assertNotIn(str(message.get("folder", "")), context)
            self.assertNotIn(str(message.get("date", "")), context)
        self.assertIn("sender:", context)
        self.assertIn("subject:", context)
        self.assertIn("folder:", context)
        self.assertIn("date:", context)

        rows = self.audit_connection.execute(
            """
            SELECT request_id, thread_ref_hash, provider_mode, provider, model, data_classes, status
            FROM llm_egress_events ORDER BY id
            """
        ).fetchall()
        self.assertEqual([row["status"] for row in rows], ["authorized", "completed"])
        self.assertTrue(all(row["provider_mode"] == "cloud" for row in rows))
        self.assertTrue(all(row["provider"] == "anthropic" for row in rows))
        self.assertTrue(all(row["model"] == "claude-test" for row in rows))
        self.assertTrue(all(row["data_classes"] == '["metadata-redacted"]' for row in rows))
        self.assertEqual(len({row["request_id"] for row in rows}), 1)
        audit_text = repr([tuple(row) for row in rows])
        self.assertNotIn(thread_messages[0]["subject"], audit_text)
        self.assertNotIn(thread_messages[0]["from"], audit_text)

    def test_model_request_requires_durable_audit_connection(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="local",
            provider="local-test",
            allowed_data_classes=frozenset({"metadata"}),
        )
        with self.assertRaisesRegex(LLMEgressPolicyError, "audit connection"):
            extract_with_llm(
                thread,
                self.messages,
                client=_FakeClient(),
                provider_policy=policy,
            )

    def test_explicit_empty_data_classes_fail_closed(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="synthetic-test-pseudonymization-key",
        )
        with self.assertRaisesRegex(LLMEgressPolicyError, "at least one"):
            extract_with_llm(
                thread,
                self.messages,
                client=_FakeClient(),
                provider_policy=policy,
                data_classes=frozenset(),
                audit_connection=self.audit_connection,
            )

    def test_provider_policy_must_match_the_injected_client(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="synthetic-test-pseudonymization-key",
        )
        with self.assertRaisesRegex(LLMEgressPolicyError, "does not match"):
            extract_with_llm(
                thread,
                self.messages,
                client=_FakeClient(provider="openai"),
                provider_policy=policy,
                audit_connection=self.audit_connection,
            )

    def test_secret_shaped_audit_labels_fail_before_model_egress(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        cases = (
            (
                LLMProviderPolicy(
                    mode="local",
                    provider="token-production",
                    allowed_data_classes=frozenset({"metadata"}),
                ),
                _FakeClient(mode="local", provider="token-production"),
                "safe-model",
                frozenset({"metadata"}),
            ),
            (
                LLMProviderPolicy(
                    mode="local",
                    provider="local-test",
                    allowed_data_classes=frozenset({"metadata"}),
                ),
                _FakeClient(mode="local", provider="local-test"),
                "sk-ant-api03-placeholder",
                frozenset({"metadata"}),
            ),
            (
                LLMProviderPolicy(
                    mode="local",
                    provider="local-test",
                    allowed_data_classes=frozenset({"secret-metadata"}),
                ),
                _FakeClient(mode="local", provider="local-test"),
                "safe-model",
                frozenset({"secret-metadata"}),
            ),
        )
        for policy, client, model, data_classes in cases:
            with self.subTest(provider=policy.provider, model=model, classes=data_classes):
                with self.assertRaisesRegex(LLMEgressPolicyError, "safe for audit"):
                    extract_with_llm(
                        thread,
                        self.messages,
                        client=client,
                        model=model,
                        provider_policy=policy,
                        data_classes=data_classes,
                        audit_connection=self.audit_connection,
                    )
                self.assertEqual(client.messages.calls, [])
        self.assertEqual(
            self.audit_connection.execute("SELECT COUNT(*) FROM llm_egress_events").fetchone()[0],
            0,
        )

    def test_non_cassette_request_rejects_in_memory_audit_sink(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="synthetic-test-pseudonymization-key",
        )
        memory_connection = connect_sqlite()
        try:
            apply_all_migrations(memory_connection)
            with self.assertRaisesRegex(LLMEgressPolicyError, "file-backed"):
                extract_with_llm(
                    thread,
                    self.messages,
                    client=_FakeClient(),
                    provider_policy=policy,
                    audit_connection=memory_connection,
                )
        finally:
            memory_connection.close()

    def test_post_response_failure_records_a_terminal_failed_event(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="synthetic-test-pseudonymization-key",
        )
        with self.assertRaises(AttributeError):
            extract_with_llm(
                thread,
                self.messages,
                client=_IncompleteResponseClient(),
                provider_policy=policy,
                audit_connection=self.audit_connection,
            )
        rows = self.audit_connection.execute(
            "SELECT request_id, status FROM llm_egress_events ORDER BY id"
        ).fetchall()
        self.assertEqual([row["status"] for row in rows], ["authorized", "failed"])
        self.assertEqual(len({row["request_id"] for row in rows}), 1)

    def test_completed_audit_failure_records_a_terminal_failed_event(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="synthetic-test-pseudonymization-key",
        )
        self.audit_connection.execute(
            """
            CREATE TRIGGER reject_completed_egress_event
            BEFORE INSERT ON llm_egress_events
            WHEN NEW.status = 'completed'
            BEGIN
              SELECT RAISE(ABORT, 'simulated completed audit failure');
            END
            """
        )
        self.audit_connection.commit()

        with self.assertRaisesRegex(sqlite3.IntegrityError, "simulated completed audit failure"):
            extract_with_llm(
                thread,
                self.messages,
                client=_FakeClient(),
                provider_policy=policy,
                audit_connection=self.audit_connection,
            )
        rows = self.audit_connection.execute(
            "SELECT request_id, status FROM llm_egress_events ORDER BY id"
        ).fetchall()
        self.assertEqual([row["status"] for row in rows], ["authorized", "failed"])
        self.assertEqual(len({row["request_id"] for row in rows}), 1)

    def test_audit_events_survive_reopening_the_file_backed_database(self) -> None:
        thread = next(t for t in self.threads if t.thread_id)
        policy = LLMProviderPolicy(
            mode="cloud",
            provider="anthropic",
            allowed_data_classes=frozenset({"metadata-redacted"}),
            cloud_opt_in=True,
            pseudonymization_key="synthetic-test-pseudonymization-key",
        )
        extract_with_llm(
            thread,
            self.messages,
            client=_FakeClient(),
            provider_policy=policy,
            audit_connection=self.audit_connection,
        )
        self.audit_connection.close()
        self.audit_connection = connect_sqlite(self.audit_path)
        statuses = [
            row["status"]
            for row in self.audit_connection.execute(
                "SELECT status FROM llm_egress_events ORDER BY id"
            )
        ]
        self.assertEqual(statuses, ["authorized", "completed"])


if __name__ == "__main__":
    unittest.main()
