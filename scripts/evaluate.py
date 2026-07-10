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
from collections import Counter
from pathlib import Path
from typing import Any


class FixtureCorpusError(ValueError):
    """Raised when a required evaluation corpus is absent or malformed."""


def _load_collection(path: Path, key: str, id_key: str, label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FixtureCorpusError(f"Required {label} fixture corpus is missing: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureCorpusError(f"Could not load {label} fixture corpus {path}: {exc}") from exc

    collection = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(collection, list) or not collection:
        raise FixtureCorpusError(
            f"Required {label} fixture collection '{key}' is missing or empty: {path}"
        )
    if not all(isinstance(item, dict) for item in collection):
        raise FixtureCorpusError(f"Every {label} fixture must be an object: {path}")

    identifiers = [str(item.get(id_key, "")).strip() for item in collection]
    if any(not identifier for identifier in identifiers):
        raise FixtureCorpusError(f"Every {label} fixture must define a stable '{id_key}'")
    duplicates = sorted(identifier for identifier, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        raise FixtureCorpusError(
            f"Duplicate {label} fixture identifiers for '{id_key}': {', '.join(duplicates)}"
        )
    return collection


def _load_classification_fixtures(fixtures_dir: Path) -> list[dict[str, Any]]:
    cases_path = fixtures_dir / "classification" / "cases.json"
    return _load_collection(cases_path, "cases", "id", "classification")


def _load_semantic_fixtures(fixtures_dir: Path) -> list[dict]:
    sem_dir = fixtures_dir / "semantic"
    paths = sorted(sem_dir.glob("*.json")) if sem_dir.is_dir() else []
    if not paths:
        raise FixtureCorpusError(f"Required semantic fixture corpus is missing: {sem_dir}")

    artifacts: list[dict[str, Any]] = []
    for path in paths:
        artifacts.extend(_load_collection(path, "artifacts", "artifact_id", "semantic"))

    identifiers = [str(artifact["artifact_id"]) for artifact in artifacts]
    duplicates = sorted(identifier for identifier, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        raise FixtureCorpusError(
            f"Duplicate semantic artifact identifiers across fixture files: {', '.join(duplicates)}"
        )
    return artifacts


def _load_noise_suppression_fixtures(fixtures_dir: Path) -> list[dict[str, Any]]:
    path = fixtures_dir / "noise_suppression" / "messages.json"
    return _load_collection(path, "messages", "fixture_id", "noise-suppression")


def evaluate_classification(cases: list[dict[str, Any]]) -> list[dict]:
    from mailplus_intelligence.classifier import classify_metadata

    results = []
    for case in cases:
        subject = case.get("subject", "")
        sender = case.get("from", "")
        expected_lane = case.get("lane", "")
        result = classify_metadata(subject, sender)
        passed = result.lane == expected_lane
        results.append({
            "case_id": case.get("id", "?"),
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
    if not fixtures_dir.is_dir():
        raise FixtureCorpusError(f"Fixtures directory not found: {fixtures_dir}")

    classification_cases = _load_classification_fixtures(fixtures_dir)
    semantic_artifacts = _load_semantic_fixtures(fixtures_dir)
    suppression_messages = _load_noise_suppression_fixtures(fixtures_dir)

    classification_results = evaluate_classification(classification_cases)
    semantic_results = evaluate_semantic_contract(semantic_artifacts)
    suppression_results = evaluate_noise_suppression(suppression_messages)

    def _summary(results: list[dict], group_field: str, group_name: str) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        failed = total - passed
        groups: dict[str, dict[str, int]] = {}
        for result in results:
            group = str(result.get(group_field, "unknown"))
            counts = groups.setdefault(group, {"total": 0, "passed": 0, "failed": 0})
            counts["total"] += 1
            if result.get("passed"):
                counts["passed"] += 1
            else:
                counts["failed"] += 1
        return {"total": total, "passed": passed, "failed": failed, group_name: groups}

    classification_summary = _summary(classification_results, "expected", "by_lane")
    classification_summary.update({
        "false_promotions": sum(
            1
            for result in classification_results
            if result["expected"] == "ignore_noise" and result["actual"] != "ignore_noise"
        ),
        "false_suppressions": sum(
            1
            for result in classification_results
            if result["expected"] != "ignore_noise" and result["actual"] == "ignore_noise"
        ),
    })

    suppression_summary = _summary(suppression_results, "expected", "by_action")
    suppression_summary.update({
        "false_promotions": sum(
            1
            for result in suppression_results
            if result["expected"] == "suppress" and result["actual"] != "suppress"
        ),
        "false_suppressions": sum(
            1
            for result in suppression_results
            if result["expected"] != "suppress" and result["actual"] == "suppress"
        ),
    })

    all_results = classification_results + semantic_results + suppression_results
    overall_passed = all(r.get("passed", True) for r in all_results)

    return {
        "overall_passed": overall_passed,
        "classification": {
            "summary": classification_summary,
            "cases": classification_results,
        },
        "semantic_contract": {
            "summary": _summary(semantic_results, "artifact_type", "by_artifact_type"),
            "cases": semantic_results,
        },
        "noise_suppression": {
            "summary": suppression_summary,
            "cases": suppression_results,
        },
    }


def _print_report(report: dict) -> None:
    status = "PASS" if report["overall_passed"] else "FAIL"
    print(f"Evaluation result: {status}")
    for section in ("classification", "semantic_contract", "noise_suppression"):
        s = report[section]["summary"]
        print(f"  {section}: {s['passed']}/{s['total']} passed", end="")
        if "false_promotions" in s:
            print(
                f"; false promotions={s['false_promotions']}; "
                f"false suppressions={s['false_suppressions']}",
                end="",
            )
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
        for group_name in ("by_lane", "by_artifact_type", "by_action"):
            for group, counts in sorted(s.get(group_name, {}).items()):
                print(
                    f"    {group}: {counts['passed']}/{counts['total']} passed"
                    f"; failed={counts['failed']}"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MailPlus Intelligence evaluation harness")
    parser.add_argument("--fixtures-dir", default="fixtures", help="Path to fixtures/ directory")
    parser.add_argument("--report-json", help="Write JSON report to this path")
    args = parser.parse_args(argv)

    fixtures_dir = Path(args.fixtures_dir)
    if not fixtures_dir.exists():
        print(f"Fixtures directory not found: {fixtures_dir}", file=sys.stderr)
        return 1

    try:
        report = run_evaluation(fixtures_dir)
    except FixtureCorpusError as exc:
        print(f"Evaluation fixture error: {exc}", file=sys.stderr)
        return 1

    if args.report_json:
        Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report written to {args.report_json}")

    _print_report(report)
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
