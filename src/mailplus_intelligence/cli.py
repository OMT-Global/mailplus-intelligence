"""Operator CLI — search, thread inspection, queue review, export, and doctor subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _get_db_path(args: argparse.Namespace) -> str:
    return getattr(args, "db", None) or ":memory:"


def _setup_db(db_path: str):
    from .schema import apply_all_migrations
    from .sqlite import connect_sqlite

    conn = connect_sqlite(db_path)
    apply_all_migrations(conn)
    return conn


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
        print(f"No messages found for thread '{args.thread_id}'.")
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
    from .queue import decide, get_item, get_queue

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

        elif args.queue_action in {"approve", "reject", "defer"}:
            decision_map = {"approve": "approved", "reject": "rejected", "defer": "deferred"}
            decision = decision_map[args.queue_action]
            decide(conn, args.artifact_id, decision, reviewer_notes=args.notes)
            print(f"{decision}: {args.artifact_id}")

        elif args.queue_action == "correct":
            decide(conn, args.artifact_id, "corrected",
                   reviewer_notes=args.notes, corrected_summary=args.corrected_summary)
            print(f"corrected: {args.artifact_id}")

        elif args.queue_action == "inspect":
            item = get_item(conn, args.artifact_id)
            if item is None:
                print(f"Not found: {args.artifact_id}")
                return 1
            if args.json:
                print(json.dumps(item.__dict__, indent=2))
            else:
                print(f"artifact_id:    {item.artifact_id}")
                print(f"type:           {item.artifact_type}")
                print(f"status:         {item.review_status}")
                print(f"thread:         {item.source_thread_key}")
                print(f"confidence:     {item.confidence}")
                print(f"summary:        {item.summary}")
                if item.corrected_summary:
                    print(f"corrected:      {item.corrected_summary}")
                print(f"locators:       {item.source_locators}")
    finally:
        conn.close()

    return 0


# ── export ────────────────────────────────────────────────────────────────────

def cmd_export(args: argparse.Namespace) -> int:
    from .exporters import export_approved_candidates
    from .queue import get_queue

    conn = _setup_db(args.db)
    try:
        approved = get_queue(conn, status="approved") + get_queue(conn, status="corrected")
    finally:
        conn.close()

    if not approved:
        print("No approved candidates to export.")
        return 0

    output_dir = Path(args.output)
    artifacts = export_approved_candidates(approved, output_dir, dry_run=True)
    print(f"Dry-run export: {len(artifacts)} artifact(s) → {output_dir}")
    for a in artifacts:
        print(f"  {a.target_path}")
    return 0


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
                    print(f"No job registered: {args.job}")
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
                print(f"No checkpoint for source: {source}")
                return 1
            if args.json:
                print(json.dumps(cp, indent=2))
            else:
                print(f"source:         {cp.get('source_name')}")
                print(f"cursor:         {cp.get('cursor') or '(none)'}")
                print(f"last attempt:   {cp.get('last_attempt_at') or 'never'}")
                print(f"last success:   {cp.get('last_success_at') or 'never'}")
        else:
            print("Usage: mpi sync {status|checkpoint}")
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
    parser = argparse.ArgumentParser(
        prog="mpi",
        description="MailPlus Intelligence operator CLI",
    )
    parser.add_argument("--db", default=":memory:", help="Path to SQLite database (default: :memory:)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
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
    qp.add_argument("--json", action="store_true")
    qa = qp.add_subparsers(dest="queue_action")
    ql = qa.add_parser("list", help="List queue items")
    ql.add_argument("--status", help="Filter by review_status")
    ql.add_argument("--type", help="Filter by artifact_type")
    ql.add_argument("--limit", type=int, default=100)
    qa.add_parser("approve").add_argument("artifact_id")
    qa.add_parser("reject").add_argument("artifact_id")
    qa.add_parser("defer").add_argument("artifact_id")
    qa.add_parser("inspect").add_argument("artifact_id")
    for name in ("approve", "reject", "defer"):
        qa.choices[name].add_argument("--notes")
    cc = qa.add_parser("correct")
    cc.add_argument("artifact_id")
    cc.add_argument("--corrected-summary", dest="corrected_summary", required=True)
    cc.add_argument("--notes")

    # export
    ep = sub.add_parser("export", help="Dry-run export of approved candidates")
    ep.add_argument("--output", default="./export-artifacts", help="Output directory")

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
    args = parser.parse_args(argv)

    if args.command == "search":
        return cmd_search(args)
    elif args.command == "thread":
        return cmd_thread(args)
    elif args.command == "queue":
        return cmd_queue(args)
    elif args.command == "export":
        return cmd_export(args)
    elif args.command == "doctor":
        return cmd_doctor(args)
    elif args.command == "sync":
        return cmd_sync(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
