# Quickstart

This walkthrough uses the synthetic fixture corpus only. It does not connect to
live MailPlus, IMAP, wiki, memory, or reminder surfaces.

## Setup

```bash setup-prerequisite
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Confirm the local fixture-mode environment:

```bash fixture-smoke
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
- gated: live-configured: missing required variables: MAILPLUS_HOST, MAILPLUS_USER, MAILPLUS_TOKEN
- gated: live-reachable: not checked because live configuration is absent
- gated: live-authenticated: not checked because live configuration is absent
- gated: live-sync-capable: not available; the live adapter currently returns a stub batch
result: ok
```

For machine-readable output, run:

```bash fixture-smoke
mpi doctor --json
```

The JSON response includes `ok` and a `checks` array. Each check has `name`,
`status`, `message`, and an optional `next_step`.

## Seed A Local Database

Use a file-backed database so queue decisions and sync state persist:

```bash fixture-smoke
mpi seed --db ./mpi.db --from-fixtures fixtures/mailplus_metadata
```

Expected shape:

```text
Seeded fixture corpus: inserted=8, skipped=0, queued=4, queue_skipped=0.
```

Re-running the command is safe; indexed messages and deterministic queue items
are skipped when they already exist.

## Search And Inspect

```bash fixture-smoke
mpi search --db ./mpi.db --keyword Atlas
```

Expected shape:

```text
2026-01-05T15:02:00Z  <thread-a-003@example.test>  Re: Project Atlas kickoff
  locator: fixture-export-003 / uid=1002
```

Inspect the reconstructed thread:

```bash fixture-smoke
mpi thread thread-a --db ./mpi.db
```

Expected shape:

```text
Thread: thread-a  (3 messages)
  2026-01-05T15:02:00Z  <thread-a-003@example.test>  Re: Project Atlas kickoff
```

## Review Queue

List candidates:

```bash fixture-smoke
mpi queue list --db ./mpi.db
```

Expected shape:

```text
[candidate]  <artifact-id>  <artifact-type>  <thread-key>
```

Inspect one artifact:

```bash fixture-smoke
ARTIFACT_ID="$(
  mpi queue list --db ./mpi.db --json |
    python -c 'import json, sys; print(json.load(sys.stdin)[0]["artifact_id"])'
)"
mpi queue inspect "$ARTIFACT_ID" --db ./mpi.db
```

Approve one artifact:

```bash fixture-smoke
ARTIFACT_ID="$(
  mpi queue list --db ./mpi.db --json |
    python -c 'import json, sys; print(json.load(sys.stdin)[0]["artifact_id"])'
)"
mpi queue approve "$ARTIFACT_ID" --db ./mpi.db --notes "Looks correct from fixture metadata"
```

## Dry-Run Export

Export approved or corrected candidates into inspectable files:

```bash fixture-smoke
mpi export --db ./mpi.db --output ./out
```

Expected shape:

```text
Dry-run export: 1 artifact(s) → out
  memory/thread-summaries/<artifact-id>.md
```

Production writes to wiki, `memory/`, and reminders are not enabled in v0.1.
Review the generated files and `out/export-manifest.json` before any future live
promotion work.
