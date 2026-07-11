# Operations Runbooks

Operational procedures for sync, extraction, and job lifecycle management.
All live MailPlus/DSM work is **credential-gated** — do not proceed past the marked stop conditions without explicit operator approval.

---

## 1. Fixture dry-run smoke test

Verify the environment is healthy before any sync work.

```bash fixture-smoke
python -m mailplus_intelligence.doctor
# or via the CLI:
mpi doctor --project-root .
```

Expected output: fixture checks are `ok`; live configuration, reachability,
authentication, and sync capability are reported separately and remain `gated`.

**Stop condition:** if `runtime`, `storage`, `manifest`, `fixtures`, or `schema` checks report `fail`, resolve before continuing.

---

## 2. Incremental sync — fixture mode

Run an offline incremental sync against the fixture corpus.

```bash fixture-smoke
# Apply schema and ingest fixture messages into a local database
python - <<'EOF'
from mailplus_intelligence.sqlite import connect_sqlite
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sync import sync_from_fixture_corpus

conn = connect_sqlite("mailplus.db")
apply_all_migrations(conn)
result = sync_from_fixture_corpus(conn, "fixtures/mailplus_metadata")
print(
    f"Inserted: {result.inserted}  Updated: {result.updated}  "
    f"Unchanged: {result.unchanged}  Rejected: {result.rejected}  "
    f"Failed: {result.failed}"
)
conn.close()
EOF

# Exercise the supported CLI path and create its fixture checkpoint and queue.
mpi seed --db mailplus.db --from-fixtures fixtures/mailplus_metadata
```

Idempotent: re-running reports exact normalized messages as `unchanged`, matched
only by `locator_export_id`. Changed metadata under that identity is `updated`;
other constraint collisions are `failed`.

**Checkpoint behavior:** the `sync_checkpoints` table records `source_name`,
`cursor`, and `last_success_at`. Record writes and cursor advancement commit
atomically only when every input is inserted, updated, or unchanged. Fatal mapper
rejects are returned as privacy-safe quarantine metadata and retain the prior
cursor for repair and replay.

---

## 3. Backfill vs incremental sync

| Mode | When to use | Behavior |
|------|-------------|----------|
| Fixture replay | Local setup or regression testing | Replays the synthetic corpus idempotently from the beginning |
| Live incremental | Future recurring runs | `contract-only`; no live transport currently consumes a checkpoint cursor |

The following SQL is a manual recovery operation, not part of the executable
fixture smoke. Back up the database and obtain operator approval before clearing
a checkpoint:

```sql
DELETE FROM sync_checkpoints WHERE source_name = 'your-source';
```

---

## 4. Checkpoint resume and replay

Fixture mode records a checkpoint for inspection but replays the bounded corpus
from the beginning. A real cursor-resuming live loop is not implemented. If a
fixture run is interrupted:

1. The `sync_checkpoints` row retains the last successful cursor.
2. Inspect `rejections` and `write_errors`; correct the source record without
   copying raw body or attachment content into logs.
3. Re-run the documented `mpi seed` command for the same fixture batch.
4. Idempotent writes and atomic rollback make the bounded fixture corpus safe to
   replay without manual partial-row cleanup.

To inspect checkpoint state:

```bash fixture-smoke
mpi sync checkpoint --db mailplus.db --source fixture-corpus
```

---

## 5. Live MailPlus sync — CREDENTIAL-GATED

**Stop condition:** do not run live sync without operator approval and explicit credential provisioning.

Required environment variables (never commit to repo):

```bash live-manual
export MAILPLUS_HOST=imap.example.invalid
export MAILPLUS_USER=operator@example.invalid
read -r -s -p "MailPlus token: " MAILPLUS_TOKEN
export MAILPLUS_TOKEN
```

The runtime reads only the invoking process environment; it does not load
configuration files automatically. Once the variables are present,
`live-configured` reports `ok`. Reachability, authentication, and sync capability
remain `gated` until a real read-only transport and explicit probes exist.

The live adapter (`src/mailplus_intelligence/live_adapter.py`, planned in issue
#106) must pass the same interface contracts as the fixture backend before being
enabled.

---

## 6. Extraction job — fixture mode

Run classification and semantic extraction against indexed messages.

```bash fixture-smoke
# Classify all fixture messages
python - <<'EOF'
from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.classifier import classify_metadata

corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
for msg in corpus.messages:
    result = classify_metadata(msg["subject"], msg.get("from", ""))
    print(f"{msg['fixture_id']}  lane={result.lane}  confidence={result.confidence}")
EOF
```

---

## 7. Promotion queue review

Inspect and act on pending extraction candidates.

```bash fixture-smoke
read -r APPROVE_ID REJECT_ID DEFER_ID CORRECT_ID <<< "$(
  mpi queue list --db mailplus.db --json |
    python -c 'import json, sys; print(*(item["artifact_id"] for item in json.load(sys.stdin)[:4]))'
)"

# List all candidates
mpi queue list --db mailplus.db

# List only pending candidates
mpi queue list --db mailplus.db --status candidate

# Inspect a specific artifact
mpi queue inspect "$APPROVE_ID" --db mailplus.db

# Approve a candidate
mpi queue approve "$APPROVE_ID" --db mailplus.db \
  --reviewer operator@example.test --expected-revision 0 \
  --notes "Reviewed and confirmed"

# Reject a candidate
mpi queue reject "$REJECT_ID" --db mailplus.db \
  --reviewer operator@example.test --expected-revision 0 \
  --notes "False positive - automated notice"

# Defer for later review
mpi queue defer "$DEFER_ID" --db mailplus.db \
  --reviewer operator@example.test --expected-revision 0

# Apply a correction
mpi queue correct "$CORRECT_ID" --corrected-summary "Corrected text here" \
  --db mailplus.db --reviewer operator@example.test --expected-revision 0

# Inspect append-only review history
mpi queue history "$APPROVE_ID" --db mailplus.db
```

**Guardrail:** rejected and deferred candidates are never exported. Only `approved` and `corrected` items proceed to dry-run export.

---

## 8. Dry-run export

Generate inspectable artifacts from approved candidates without modifying production surfaces.

```bash fixture-smoke
mpi export --db mailplus.db --output ./export-artifacts
```

Review the generated files in `./export-artifacts/` before any live promotion. The manifest at `export-artifacts/export-manifest.json` lists every artifact with its rollback note.

**Rollback:** delete the artifact file named in `rollback_note` to revert a dry-run export entry.

---

## 9. Failure triage

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `schema` check fails | Migration not applied | Run `apply_all_migrations()` |
| `fixtures` check fails | Missing fixture files | Check `fixtures/mailplus_metadata/` |
| Sync reports all records unchanged | Exact normalized locator_export_ids already present | Normal for idempotent re-run |
| Sync reports rejected records | Fatal required metadata or shape error | Repair the quarantined fixture IDs and replay the same cursor |
| Sync reports failed records | Normalized validation, unrelated constraint, or child write failure | Inspect privacy-safe errors; the data and checkpoint were rolled back |
| Queue `decide` raises `KeyError` | Artifact ID not in database | Check artifact ID spelling |
| Export produces 0 artifacts | No approved/corrected items in queue | Approve candidates first |

---

## 10. Review-state inspection

Fixture mode stores queue decisions in `promotion_queue`. Inspect only the
privacy-safe review fields; do not print selected cached text or credential
values:

```bash fixture-smoke
python - <<'EOF'
import sqlite3

connection = sqlite3.connect("mailplus.db")
queries = (
    "SELECT artifact_id, review_status, revision, reviewer_identity, decided_at "
    "FROM promotion_queue ORDER BY queued_at DESC LIMIT 20",
    "SELECT artifact_id, artifact_revision, prior_status, new_status, "
    "reviewer_identity, occurred_at FROM review_events ORDER BY occurred_at DESC LIMIT 20",
    "SELECT artifact_id, artifact_revision, state, target_key, rollback_requested_at "
    "FROM export_outbox ORDER BY updated_at DESC LIMIT 20",
)
for query in queries:
    for row in connection.execute(query):
        print(row)
connection.close()
EOF
```

Review events are append-only and never contain raw message body content.
Legacy rows marked with `provenance='legacy'` remain auditable but are not
export eligible because the pre-v4 schema discarded required provenance.

---

## 11. Evaluation and regression

Run the offline evaluation harness before and after any extraction or classification change:

```bash fixture-smoke
python scripts/evaluate.py \
  --fixtures-dir fixtures \
  --report-json "${TMPDIR:-/tmp}/mailplus-eval-report.json"
```

A baseline report should be committed alongside any change to classification heuristics, suppression rules, or semantic contract.
