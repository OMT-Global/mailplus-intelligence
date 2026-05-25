# Quickstart

This walkthrough uses the synthetic fixture corpus only. It does not connect to
live MailPlus, IMAP, wiki, memory, or reminder surfaces.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Confirm the local fixture-mode environment:

```bash
mpi doctor
```

Expected shape:

```text
MailPlus Intelligence fixture doctor
- ok: runtime: python 3.12; expected >=3.12
- ok: storage: selected storage engine: sqlite
- ok: manifest: project.bootstrap.yaml present
- ok: fixtures: loaded metadata fixture corpus with 8 messages
- ok: schema: metadata schema user_version=1
- gated: live-mailplus: live MailPlus credentials intentionally unavailable in fixture mode
result: ok
```

For machine-readable output, run:

```bash
mpi doctor --json
```

The JSON response includes `ok` and a `checks` array. Each check has `name`,
`status`, `message`, and an optional `next_step`.

## Seed A Local Database

Use a file-backed database so queue decisions and sync state persist:

```bash
mpi --db ./mpi.db seed --from-fixtures fixtures/mailplus_metadata
```

Expected shape:

```text
Seeded fixture corpus: inserted=8, skipped=0, queued=4, queue_skipped=0.
```

Re-running the command is safe; indexed messages and deterministic queue items
are skipped when they already exist.

## Search And Inspect

```bash
mpi --db ./mpi.db search --keyword Atlas
```

Expected shape:

```text
2026-01-05T15:02:00Z  <thread-a-003@example.test>  Re: Project Atlas kickoff
  locator: fixture-export-003 / uid=1002
```

Inspect the reconstructed thread:

```bash
mpi --db ./mpi.db thread thread-a
```

Expected shape:

```text
Thread: thread-a  (3 messages)
  2026-01-05T15:02:00Z  <thread-a-003@example.test>  Re: Project Atlas kickoff
```

## Review Queue

List candidates:

```bash
mpi --db ./mpi.db queue list
```

Expected shape:

```text
[candidate]  <artifact-id>  thread_summary  thread-a
```

Inspect one artifact:

```bash
mpi --db ./mpi.db queue inspect <artifact-id>
```

Approve one artifact:

```bash
mpi --db ./mpi.db queue approve <artifact-id> --notes "Looks correct from fixture metadata"
```

## Dry-Run Export

Export approved or corrected candidates into inspectable files:

```bash
mpi --db ./mpi.db export --output ./out
```

Expected shape:

```text
Dry-run export: 1 artifact(s) -> out
  memory/thread-summaries/<artifact-id>.md
```

Production writes to wiki, `memory/`, and reminders are not enabled in v0.1.
Review the generated files and `out/export-manifest.json` before any future live
promotion work.
