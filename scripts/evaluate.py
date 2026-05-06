#!/usr/bin/env python3
"""Fixture-based evaluation and regression harness for classification and extraction.

Usage:
    python scripts/evaluate.py [--fixtures-dir FIXTURES_DIR] [--report-json PATH]

Exit code:
    0  All fixture expectations pass
    1  One or more regressions detected
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_classification_fixtures(fixtures_dir: Path) -> tuple[list[dict], list[dict]]:
    cases_path = fixtures_dir / "classification" / "cases.json"
    if not cases_path.exists():
        return [], []
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    return payload.get("cases", []), payload.get("expected", [])


def _load_semantic_fixtures(fixtures_dir: Path) -> list[dict]:
    sem_dir = fixtures_dir / "semantic"
    if not sem_dir.exists():
        return []
    artifacts = []
    for path in sorted(sem_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            artifacts.extend(data)
        else:
            artifacts.append(data)
    return artifacts


def evaluate_classification(cases: list[dict[str, Any]]) -> list[dict]:
    from mailplus_intelligence.classifier import classify_metadata

    results = []
    for case in cases:
        subject = case.get("subject", "")
        sender = case.get("sender", "")
        expected_lane = case.get("expected_lane", "")
        result = classify_metadata(subject, sender)
        passed = result.lane == expected_lane
        results.append({
            "case_id": case.get("case_id", "?"),
            "subject": subject,
            "sender": sender,
            "expected": expected_lane,
            "actual": result.lane,
            "passed": passed,
            "reason_code": result.reason_code,
        })
    return results


def evaluate_semantic_contract(artifacts: list[dict[str, Any]]) -> list[dict]:
    from mailplus_intelligence.semantic_contract import validate_semantic_artifact

    results = []
    for artifact in artifacts:
        errors = validate_semantic_artifact(artifact)
        results.append({
            "artifact_id": artifact.get("artifact_id", "?"),
            "artifact_type": artifact.get("artifact_type", "?"),
            "passed": len(errors) == 0,
            "errors": errors,
        })
    return results


def evaluate_noise_suppression(messages: list[dict[str, Any]]) -> list[dict]:
    from mailplus_intelligence.suppression import classify_noise_suppression

    results = []
    for msg in messages:
        expected_action = msg.get("expected_action")
        if expected_action is None:
            continue
        decision = classify_noise_suppression(msg)
        passed = decision.action == expected_action
        results.append({
            "fixture_id": msg.get("fixture_id", "?"),
            "expected": expected_action,
            "actual": decision.action,
            "passed": passed,
            "family": decision.family,
        })
    return results


def run_evaluation(fixtures_dir: Path) -> dict:
    classification_cases, _ = _load_classification_fixtures(fixtures_dir)
    semantic_artifacts = _load_semantic_fixtures(fixtures_dir)

    meta_messages_path = fixtures_dir / "mailplus_metadata" / "messages.json"
    meta_messages: list[dict] = []
    if meta_messages_path.exists():
        payload = json.loads(meta_messages_path.read_text(encoding="utf-8"))
        meta_messages = list(payload.get("messages", []))

    classification_results = evaluate_classification(classification_cases)
    semantic_results = evaluate_semantic_contract(semantic_artifacts)
    suppression_results = evaluate_noise_suppression(meta_messages)

    def _summary(results: list[dict]) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        failed = total - passed
        return {"total": total, "passed": passed, "failed": failed}

    all_results = classification_results + semantic_results + suppression_results
    overall_passed = all(r.get("passed", True) for r in all_results)

    return {
        "overall_passed": overall_passed,
        "classification": {
            "summary": _summary(classification_results),
            "cases": classification_results,
        },
        "semantic_contract": {
            "summary": _summary(semantic_results),
            "cases": semantic_results,
        },
        "noise_suppression": {
            "summary": _summary(suppression_results),
            "cases": suppression_results,
        },
    }


def _print_report(report: dict) -> None:
    status = "PASS" if report["overall_passed"] else "FAIL"
    print(f"Evaluation result: {status}")
    for section in ("classification", "semantic_contract", "noise_suppression"):
        s = report[section]["summary"]
        print(f"  {section}: {s['passed']}/{s['total']} passed", end="")
        if s["failed"]:
            print(f"  ← {s['failed']} FAILED")
            for case in report[section]["cases"]:
                if not case.get("passed"):
                    cid = case.get("case_id") or case.get("artifact_id") or case.get("fixture_id")
                    exp = case.get("expected") or case.get("errors")
                    act = case.get("actual") or ""
                    print(f"    FAIL [{cid}] expected={exp} actual={act}")
        else:
            print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MailPlus Intelligence evaluation harness")
    parser.add_argument("--fixtures-dir", default="fixtures", help="Path to fixtures/ directory")
    parser.add_argument("--report-json", help="Write JSON report to this path")
    args = parser.parse_args(argv)

    fixtures_dir = Path(args.fixtures_dir)
    if not fixtures_dir.exists():
        print(f"Fixtures directory not found: {fixtures_dir}", file=sys.stderr)
        return 1

    report = run_evaluation(fixtures_dir)

    if args.report_json:
        Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report written to {args.report_json}")

    _print_report(report)
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
