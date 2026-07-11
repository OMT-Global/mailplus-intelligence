"""Operator CLI — search, thread inspection, queue review, export, and doctor subcommands."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sqlite3
import sys
from pathlib import Path


_COMMON_FLAG_OPTIONS = frozenset({"--json", "--version"})
_SENSITIVE_OPTION_NAME = re.compile(
    r"(?i)^--?[a-z0-9_-]*(?:token|password|passcode|secret|credential|api[_-]?key)"
    r"[a-z0-9_-]*$|^--?mailplus_(?:host|user|mailbox)$"
)
_SENSITIVE_OPTION_VALUE = re.compile(
    r"(?i)(--?[a-z0-9_-]*(?:token|password|passcode|secret|credential|api[_-]?key)"
    r"[a-z0-9_-]*|--?mailplus_(?:host|user|mailbox))"
    r"(?:(\s*[:=]\s*)|(\s+))"
    r"(\"[^\"]*\"|'[^']*'|[^\s,}]+)"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:[a-z0-9_-]*(?:token|password|passcode|secret|credential|"
    r"api[_-]?key)[a-z0-9_-]*|mailplus_(?:host|user|mailbox))[\"']?)"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,}]+)"
)
_CREDENTIAL_URL = re.compile(r"(?i)https?://[^\s/:]+:[^@\s/]+@[^\s]+")


def _sanitize_sensitive_argv(argv: list[str]) -> list[str]:
    """Replace whole secret-shaped argv values before argparse can render them."""

    sanitized: list[str] = []
    redact_next = False
    for argument in argv:
        if redact_next:
            sanitized.append("<redacted>")
            redact_next = False
            continue

        option, separator, _ = argument.partition("=")
        if not separator:
            option, separator, _ = argument.partition(":")
        if separator and _SENSITIVE_OPTION_NAME.fullmatch(option):
            sanitized.append(f"{option}{separator}<redacted>")
            continue
        if _SENSITIVE_OPTION_NAME.fullmatch(argument):
            sanitized.append(argument)
            redact_next = True
            continue
        sanitized.append(argument)
    return sanitized


def _normalize_common_options(argv: list[str]) -> list[str]:
    """Allow common options before or after commands and nested subcommands."""

    common: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            remaining.extend(argv[index:])
            break
        if argument in _COMMON_FLAG_OPTIONS:
            common.append(argument)
            index += 1
            continue
        if argument == "--db":
            common.append(argument)
            index += 1
            if index < len(argv):
                common.append(argv[index])
                index += 1
            continue
        if argument.startswith("--db="):
            common.append(argument)
            index += 1
            continue
        remaining.append(argument)
        index += 1
    return common + remaining


def _get_db_path(args: argparse.Namespace) -> str:
    return getattr(args, "db", None) or ":memory:"


def _redact_error_message(message: str) -> str:
    """Remove secret-shaped values before an operator diagnostic is emitted."""

    redacted = _SENSITIVE_OPTION_VALUE.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2) or match.group(3)}<redacted>"
        ),
        message,
    )
    redacted = _SENSITIVE_ASSIGNMENT.sub(r"\1\2<redacted>", redacted)
    return _CREDENTIAL_URL.sub("<redacted credential URL>", redacted)


def _emit_error(args: argparse.Namespace, message: str) -> None:
    message = _redact_error_message(message)
    if getattr(args, "json", False):
        print(json.dumps({"ok": False, "error": message}), file=sys.stderr)
    else:
        print(message, file=sys.stderr)


def _setup_db(db_path: str):
    from .schema import apply_all_migrations
    from .sqlite import connect_sqlite

    conn = connect_sqlite(db_path)
    apply_all_migrations(conn)
    return conn


def _warn_if_ephemeral_db(args: argparse.Namespace) -> None:
    if getattr(args, "json", False):
        return
    if getattr(args, "db", ":memory:") != ":memory:":
        return
    if getattr(args, "command", None) in {"search", "thread", "queue", "export", "sync", "seed"}:
        print(
            "warning: --db :memory: does not persist approvals, queue decisions, or sync state; use --db ./mpi.db.",
            file=sys.stderr,
        )


def _runtime_configuration_errors() -> tuple[type[BaseException], ...]:
    errors: list[type[BaseException]] = []
    try:
        from .live_adapter import LiveAdapterNotConfigured

        errors.append(LiveAdapterNotConfigured)
    except ImportError:
        pass

    try:
        from .llm_extractor import LLMNotAvailable  # type: ignore[attr-defined]

        errors.append(LLMNotAvailable)
    except (ImportError, AttributeError):
        pass

    return tuple(errors)


# ── search ────────────────────────────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> int:
    from .index_writer import search_messages

    conn = _setup_db(args.db)
    try:
        results = search_messages(
            conn,
            sender=args.sender,
            subject_keyword=args.keyword,
            folder=args.folder,
            has_attachments=True if args.has_attachments else None,
            attachment_name_contains=args.attachment_name,
            attachment_mime_type=args.attachment_type,
            date_from=args.date_from,
            date_to=args.date_to,
            thread_key=args.thread,
            limit=args.limit,
        )
    finally:
        conn.close()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print("No results.")
            return 0
        for row in results:
            print(f"{row.get('sent_at','?')}  {row.get('message_id','?')}  {row.get('subject','?')}")
            print(f"  locator: {row.get('locator_export_id','?')} / uid={row.get('locator_uid','?')}")
    return 0


# ── thread ────────────────────────────────────────────────────────────────────

def cmd_thread(args: argparse.Namespace) -> int:
    from .index_writer import search_messages

    conn = _setup_db(args.db)
    try:
        results = search_messages(conn, thread_key=args.thread_id, limit=200)
    finally:
        conn.close()

    if not results:
        _emit_error(args, f"No messages found for thread '{args.thread_id}'.")
        return 1

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"Thread: {args.thread_id}  ({len(results)} messages)")
        for row in results:
            print(f"  {row.get('sent_at','?')}  {row.get('message_id','?')}  {row.get('subject','?')}")
    return 0


# ── queue ─────────────────────────────────────────────────────────────────────

def cmd_queue(args: argparse.Namespace) -> int:
    from .queue import decide, get_item, get_queue, get_review_history

    conn = _setup_db(args.db)
    try:
        if args.queue_action == "list":
            items = get_queue(conn, status=args.status, artifact_type=args.type, limit=args.limit)
            if args.json:
                print(json.dumps([i.__dict__ for i in items], indent=2))
            else:
                if not items:
                    print("Queue is empty.")
                for item in items:
                    print(f"[{item.review_status}] {item.artifact_id}  {item.artifact_type}  {item.source_thread_key}")
                    print(f"  {item.summary[:80]}")

        elif args.queue_action in {"approve", "reject", "defer", "rollback"}:
            decision_map = {
                "approve": "approved",
                "reject": "rejected",
                "defer": "deferred",
                "rollback": "rollback_needed",
            }
            decision = decision_map[args.queue_action]
            try:
                decide(
                    conn,
                    args.artifact_id,
                    decision,
                    reviewer_notes=args.notes,
                    reviewer_identity=args.reviewer,
                    expected_revision=args.expected_revision,
                )
            except (KeyError, ValueError) as exc:
                _emit_error(args, f"queue decision failed: {exc}")
                return 2
            if args.json:
                print(json.dumps({"artifact_id": args.artifact_id, "decision": decision}))
            else:
                print(f"{decision}: {args.artifact_id}")

        elif args.queue_action == "correct":
            try:
                decide(
                    conn,
                    args.artifact_id,
                    "corrected",
                    reviewer_notes=args.notes,
                    corrected_summary=args.corrected_summary,
                    reviewer_identity=args.reviewer,
                    expected_revision=args.expected_revision,
                )
            except (KeyError, ValueError) as exc:
                _emit_error(args, f"queue decision failed: {exc}")
                return 2
            if args.json:
                print(json.dumps({"artifact_id": args.artifact_id, "decision": "corrected"}))
            else:
                print(f"corrected: {args.artifact_id}")

        elif args.queue_action == "inspect":
            item = get_item(conn, args.artifact_id)
            if item is None:
                _emit_error(args, f"Not found: {args.artifact_id}")
                return 1
            if args.json:
                print(json.dumps(item.__dict__, indent=2))
            else:
                print(f"artifact_id:    {item.artifact_id}")
                print(f"type:           {item.artifact_type}")
                print(f"status:         {item.review_status}")
                print(f"revision:       {item.revision}")
                print(f"thread:         {item.source_thread_key}")
                print(f"confidence:     {item.confidence}")
                print(f"provenance:     {item.provenance} / {item.extractor_version}")
                print(f"summary:        {item.summary}")
                if item.corrected_summary:
                    print(f"corrected:      {item.corrected_summary}")
                print(f"locators:       {item.source_locators}")

        elif args.queue_action == "history":
            events = get_review_history(conn, args.artifact_id)
            if args.json:
                print(json.dumps([event.__dict__ for event in events], indent=2))
            else:
                if not events:
                    print(f"No review history: {args.artifact_id}")
                for event in events:
                    print(
                        f"r{event.artifact_revision} {event.prior_status} -> "
                        f"{event.new_status} by {event.reviewer_identity} at {event.occurred_at}"
                    )
        else:
            _emit_error(args, "Usage: mpi queue {list|inspect|history|approve|reject|defer|rollback|correct}")
            return 1
    finally:
        conn.close()

    return 0


# ── export ────────────────────────────────────────────────────────────────────

def cmd_export(args: argparse.Namespace) -> int:
    from .exporters import export_approved_candidates
    from .queue import get_queue

    output_dir = Path(args.output)
    conn = _setup_db(args.db)
    try:
        approved = get_queue(conn, status="approved") + get_queue(conn, status="corrected")
        artifacts = (
            export_approved_candidates(
                approved,
                output_dir,
                connection=conn,
                dry_run=True,
            )
            if approved
            else []
        )
    finally:
        conn.close()

    if args.json:
        print(json.dumps({
            "dry_run": True,
            "artifact_count": len(artifacts),
            "artifacts": [
                {"artifact_id": a.artifact_id, "target_path": a.target_path}
                for a in artifacts
            ],
            "output": str(output_dir),
        }, indent=2))
    else:
        if not artifacts:
            print("No approved candidates to export.")
        else:
            print(f"Dry-run export: {len(artifacts)} artifact(s) -> {output_dir}")
            for artifact in artifacts:
                print(f"  {artifact.target_path}")
    return 0


# ── seed ──────────────────────────────────────────────────────────────────────

def cmd_seed(args: argparse.Namespace) -> int:
    from .extractor import extract_from_corpus
    from .fixtures import load_metadata_fixture_corpus
    from .queue import enqueue_candidate
    from .sync import sync_from_fixture_corpus
    from .threading import reconstruct_fixture_threads

    conn = _setup_db(args.db)
    try:
        result = sync_from_fixture_corpus(conn, args.from_fixtures)
        corpus = load_metadata_fixture_corpus(args.from_fixtures)
        threads = reconstruct_fixture_threads(corpus.messages)
        candidates = extract_from_corpus(threads, corpus.messages)

        queued = 0
        skipped = 0
        for candidate in candidates:
            try:
                enqueue_candidate(conn, candidate.__dict__)
                queued += 1
            except sqlite3.IntegrityError:
                skipped += 1
    finally:
        conn.close()

    if args.json:
        print(json.dumps({
            "success": result.success,
            "inserted": result.inserted,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "rejected": result.rejected,
            "failed": result.failed,
            "queued": queued,
            "queue_skipped": skipped,
        }, indent=2))
    else:
        print(
            "Seeded fixture corpus: "
            f"inserted={result.inserted}, updated={result.updated}, "
            f"unchanged={result.unchanged}, rejected={result.rejected}, "
            f"failed={result.failed}, "
            f"queued={queued}, queue_skipped={skipped}."
        )
    return 0 if result.success else 1


# ── sync ─────────────────────────────────────────────────────────────────────


def cmd_sync(args: argparse.Namespace) -> int:
    from .scheduler import get_job_status, list_jobs
    from .sync import get_checkpoint

    conn = _setup_db(args.db)
    try:
        if args.sync_action == "status":
            if args.job:
                status = get_job_status(conn, args.job)
                if status is None:
                    _emit_error(args, f"No job registered: {args.job}")
                    return 1
                jobs = [status]
            else:
                jobs = list_jobs(conn)
            if args.json:
                print(json.dumps([j.__dict__ for j in jobs], indent=2))
            else:
                if not jobs:
                    print("No sync jobs registered.")
                for j in jobs:
                    lock_str = f"LOCKED by {j.lock_holder}" if j.locked else "unlocked"
                    print(f"{j.job_name}  [{lock_str}]")
                    print(f"  last run:     {j.last_run_at or 'never'}")
                    print(f"  last success: {j.last_success_at or 'never'}")

        elif args.sync_action == "checkpoint":
            source = args.source or "fixture-corpus"
            cp = get_checkpoint(conn, source)
            if cp is None:
                _emit_error(args, f"No checkpoint for source: {source}")
                return 1
            if args.json:
                print(json.dumps(cp, indent=2))
            else:
                print(f"source:         {cp.get('source_name')}")
                print(f"cursor:         {cp.get('cursor') or '(none)'}")
                print(f"last attempt:   {cp.get('last_attempt_at') or 'never'}")
                print(f"last success:   {cp.get('last_success_at') or 'never'}")
        else:
            _emit_error(args, "Usage: mpi sync {status|checkpoint}")
            return 1
    finally:
        conn.close()
    return 0


# ── doctor ────────────────────────────────────────────────────────────────────

def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import format_doctor_report, run_fixture_doctor

    report = run_fixture_doctor(args.project_root or ".")
    if args.json:
        print(json.dumps(
            {"ok": report.ok, "checks": [c.__dict__ for c in report.checks]},
            indent=2,
        ))
    else:
        print(format_doctor_report(report))
    return 0 if report.ok else 1


# ── parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="mpi",
        description="MailPlus Intelligence operator CLI",
    )
    parser.add_argument("--db", default=":memory:", help="Path to SQLite database (default: :memory:)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    # search
    sp = sub.add_parser("search", help="Search indexed messages")
    sp.add_argument("--sender", help="Filter by sender email substring")
    sp.add_argument("--keyword", help="Filter by subject keyword")
    sp.add_argument("--folder", help="Filter by folder path substring")
    sp.add_argument("--has-attachments", action="store_true", default=None)
    sp.add_argument("--attachment-name", dest="attachment_name", help="Attachment filename contains")
    sp.add_argument("--attachment-type", dest="attachment_type", help="Attachment MIME type (exact)")
    sp.add_argument("--date-from", dest="date_from", help="Sent on or after (ISO 8601)")
    sp.add_argument("--date-to", dest="date_to", help="Sent on or before (ISO 8601)")
    sp.add_argument("--thread", help="Filter by thread key")
    sp.add_argument("--limit", type=int, default=50)

    # thread
    tp = sub.add_parser("thread", help="Inspect a reconstructed thread")
    tp.add_argument("thread_id", help="Thread key")

    # queue
    qp = sub.add_parser("queue", help="Review promotion queue")
    qa = qp.add_subparsers(dest="queue_action")
    ql = qa.add_parser("list", help="List queue items")
    ql.add_argument("--status", help="Filter by review_status")
    ql.add_argument("--type", help="Filter by artifact_type")
    ql.add_argument("--limit", type=int, default=100)
    qa.add_parser("inspect").add_argument("artifact_id")
    qa.add_parser("history").add_argument("artifact_id")
    for name in ("approve", "reject", "defer", "rollback"):
        action = qa.add_parser(name)
        action.add_argument("artifact_id")
        action.add_argument("--reviewer", required=True)
        action.add_argument("--expected-revision", type=int, required=True)
        action.add_argument("--notes", required=name == "rollback")
    cc = qa.add_parser("correct")
    cc.add_argument("artifact_id")
    cc.add_argument("--corrected-summary", dest="corrected_summary", required=True)
    cc.add_argument("--reviewer", required=True)
    cc.add_argument("--expected-revision", type=int, required=True)
    cc.add_argument("--notes")

    # export
    ep = sub.add_parser("export", help="Dry-run export of approved candidates")
    ep.add_argument("--output", default="./export-artifacts", help="Output directory")

    # seed
    seedp = sub.add_parser("seed", help="Seed a local DB from fixture metadata")
    seedp.add_argument(
        "--from-fixtures",
        dest="from_fixtures",
        default="fixtures/mailplus_metadata",
        help="Fixture corpus directory",
    )

    # sync
    syp = sub.add_parser("sync", help="Sync job status and checkpoint inspection")
    sya = syp.add_subparsers(dest="sync_action")
    ss = sya.add_parser("status", help="List scheduler job statuses")
    ss.add_argument("--job", help="Filter by job name")
    sc = sya.add_parser("checkpoint", help="Show sync checkpoint for a source")
    sc.add_argument("--source", help="Source name (default: fixture-corpus)")

    # doctor
    dp = sub.add_parser("doctor", help="Run fixture-mode preflight checks")
    dp.add_argument("--project-root", dest="project_root", default=".")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    normalized_arguments = _normalize_common_options(_sanitize_sensitive_argv(arguments))
    json_requested = "--json" in arguments
    parse_stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(parse_stderr):
            args = parser.parse_args(normalized_arguments)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        redacted_diagnostic = _redact_error_message(parse_stderr.getvalue())
        if json_requested:
            diagnostic = redacted_diagnostic.strip().splitlines()
            message = diagnostic[-1] if diagnostic else "invalid command-line arguments"
            prefix = f"{parser.prog}: error: "
            if message.startswith(prefix):
                message = message[len(prefix):]
            print(
                json.dumps({"ok": False, "error": _redact_error_message(message)}),
                file=sys.stderr,
            )
            return int(exc.code) if isinstance(exc.code, int) else 2
        print(redacted_diagnostic, file=sys.stderr, end="")
        raise
    _warn_if_ephemeral_db(args)

    try:
        if args.command == "search":
            return cmd_search(args)
        elif args.command == "thread":
            return cmd_thread(args)
        elif args.command == "queue":
            return cmd_queue(args)
        elif args.command == "export":
            return cmd_export(args)
        elif args.command == "seed":
            return cmd_seed(args)
        elif args.command == "doctor":
            return cmd_doctor(args)
        elif args.command == "sync":
            return cmd_sync(args)
        else:
            if args.json:
                _emit_error(args, "a command is required")
            else:
                parser.print_help()
            return 1
    except FileNotFoundError as exc:
        _emit_error(
            args,
            f"error: file not found: {exc}. Check the fixture path or database parent directory.",
        )
        return 2
    except sqlite3.OperationalError as exc:
        _emit_error(
            args,
            f"error: sqlite operation failed: {exc}. Check that the database parent directory exists.",
        )
        return 2
    except (KeyError, ValueError) as exc:
        _emit_error(args, f"error: {exc}")
        return 2
    except _runtime_configuration_errors() as exc:
        _emit_error(args, f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
