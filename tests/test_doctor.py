from __future__ import annotations

import os
import unittest
from unittest import mock

from mailplus_intelligence.doctor import format_doctor_report, run_fixture_doctor


class FixtureDoctorTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_fixture_doctor_passes_with_live_credentials_gated(self) -> None:
        report = run_fixture_doctor()

        statuses = {check.name: check.status for check in report.checks}
        self.assertEqual(statuses["runtime"], "ok")
        self.assertEqual(statuses["storage"], "ok")
        self.assertEqual(statuses["manifest"], "ok")
        self.assertEqual(statuses["fixtures"], "ok")
        self.assertEqual(statuses["schema"], "ok")
        self.assertEqual(statuses["live-configured"], "gated")
        self.assertEqual(statuses["live-reachable"], "gated")
        self.assertEqual(statuses["live-authenticated"], "gated")
        self.assertEqual(statuses["live-sync-capable"], "gated")
        self.assertIn(statuses["llm"], {"ok", "gated"})
        self.assertTrue(report.ok)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_fixture_doctor_output_names_gated_live_access(self) -> None:
        output = format_doctor_report(run_fixture_doctor())

        self.assertIn("live-configured", output)
        self.assertIn("live-reachable", output)
        self.assertIn("live-authenticated", output)
        self.assertIn("live-sync-capable", output)
        self.assertIn("llm", output)
        self.assertIn("result: ok", output)

    @mock.patch.dict(
        os.environ,
        {
            "MAILPLUS_HOST": "imap.example.invalid",
            "MAILPLUS_USER": "operator@example.invalid",
            "MAILPLUS_TOKEN": "synthetic-test-token",
        },
        clear=True,
    )
    def test_configuration_presence_does_not_claim_live_capability(self) -> None:
        report = run_fixture_doctor()
        checks = {check.name: check for check in report.checks}

        self.assertEqual(checks["live-configured"].status, "ok")
        self.assertEqual(checks["live-reachable"].status, "gated")
        self.assertEqual(checks["live-authenticated"].status, "gated")
        self.assertEqual(checks["live-sync-capable"].status, "gated")
        output = format_doctor_report(report)
        self.assertNotIn("imap.example.invalid", output)
        self.assertNotIn("operator@example.invalid", output)
        self.assertNotIn("synthetic-test-token", output)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_every_gated_live_check_has_a_concrete_next_step(self) -> None:
        live_checks = [
            check for check in run_fixture_doctor().checks if check.name.startswith("live-")
        ]

        self.assertTrue(live_checks)
        self.assertTrue(all(check.next_step for check in live_checks))

    @mock.patch.dict(
        os.environ,
        {
            "MAILPLUS_HOST": "imap.example.invalid",
            "MAILPLUS_USER": "operator@example.invalid",
            "MAILPLUS_TOKEN": "synthetic-test-token",
            "MAILPLUS_PAGE_SIZE": "invalid",
        },
        clear=True,
    )
    def test_invalid_optional_setting_is_not_reported_as_configured(self) -> None:
        report = run_fixture_doctor()
        checks = {check.name: check for check in report.checks}

        configured = checks["live-configured"]
        self.assertEqual(configured.status, "fail")
        self.assertIn("MAILPLUS_PAGE_SIZE", configured.message)
        self.assertNotIn("synthetic-test-token", configured.message)
        self.assertIn("Correct", configured.next_step or "")
        self.assertFalse(report.ok)

    @mock.patch.dict(
        os.environ,
        {"MAILPLUS_HOST": "imap.example.invalid"},
        clear=True,
    )
    def test_partial_live_configuration_fails_doctor(self) -> None:
        report = run_fixture_doctor()
        configured = next(check for check in report.checks if check.name == "live-configured")

        self.assertEqual(configured.status, "fail")
        self.assertFalse(report.ok)


if __name__ == "__main__":
    unittest.main()
