from __future__ import annotations

import unittest

from mailplus_intelligence.doctor import format_doctor_report, run_fixture_doctor


class FixtureDoctorTests(unittest.TestCase):
    def test_fixture_doctor_passes_with_live_credentials_gated(self) -> None:
        report = run_fixture_doctor()

        statuses = {check.name: check.status for check in report.checks}
        self.assertEqual(statuses["runtime"], "ok")
        self.assertEqual(statuses["storage"], "ok")
        self.assertEqual(statuses["manifest"], "ok")
        self.assertEqual(statuses["fixtures"], "ok")
        self.assertEqual(statuses["schema"], "ok")
        self.assertEqual(statuses["live-mailplus"], "gated")
        self.assertIn(statuses["llm"], {"ok", "gated"})
        self.assertTrue(report.ok)

    def test_fixture_doctor_output_names_gated_live_access(self) -> None:
        output = format_doctor_report(run_fixture_doctor())

        self.assertIn("live MailPlus credentials intentionally unavailable", output)
        self.assertIn("llm", output)
        self.assertIn("result: ok", output)


if __name__ == "__main__":
    unittest.main()
