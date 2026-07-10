# Operations Runbooks

Operational procedures for sync, extraction, and job lifecycle management.
All live MailPlus/DSM work is **credential-gated** — do not proceed past the marked stop conditions without explicit operator approval.

---

## 1. Fixture dry-run smoke test

Verify the environment is healthy before any sync work.

```bash
python -m mailplus_intelligence.doctor
# or via the CLI:
mpi doctor --project-root .
```

Expected output: all checks `ok` except `live-mailplus` which shows `gated`.

**Stop condition:** if `runtime`, `storage`, `manifest`, `fixtures`, or `schema` checks report `fail`, resolve before continuing.

---

## 2. Incremental sync — fixture mode

Run an offline incremental sync against the fixture corpus.

```bash
# Apply schema and ingest fixture messages into a local database
python - <<'EOF'
from mailplus_intelligence.sqlite import connect_sqlite
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.mapper import map_fixture_messages
from mailplus_intelligence.index_writer import write_index_records

conn = connect_sqlite("mailplus.db")
apply_all_migrations(conn)
corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
result = map_fixture_messages(corpus.messages)
write_result = write_index_records(conn, result.records)
print(f"Inserted: {write_result.inserted}  Skipped: {write_result.skipped}  Errors: {write_result.errors}")
conn.close()
EOF
```

Idempotent: re-running skips already-indexed messages (matched by `locator_export_id`).

**Checkpoint behavior:** the `sync_checkpoints` table records `source_name`, `cursor`, and `last_success_at`. Update the cursor after each successful batch to support resume.

---

## 3. Backfill vs incremental sync

| Mode | When to use | Behavior |
|------|-------------|----------|
| Full backfill | First run or after schema migration | Processes all messages from the beginning |
| Incremental | Recurring runs | Processes only messages since last checkpoint cursor |

To force a backfill, clear or reset the checkpoint:

```sql
DELETE FROM sync_checkpoints WHERE source_name = 'your-source';
```

---

## 4. Checkpoint resume and replay

If a sync run is interrupted:

1. The `sync_checkpoints` row retains the last successful cursor.
2. Re-run the sync job — it will resume from that cursor.
3. Idempotent writes mean partial progress is safe to replay.

To inspect checkpoint state:

```bash
mpi doctor
# or query directly:
sqlite3 mailplus.db "SELECT * FROM sync_checkpoints;"
```

---

## 5. Live MailPlus sync — CREDENTIAL-GATED

**Stop condition:** do not run live sync without operator approval and explicit credential provisioning.

Required environment variables (never commit to repo):

```bash
export MAILPLUS_URL=https://your-nas/mail
export MAILPLUS_USERNAME=your-username
export MAILPLUS_PASSWORD=your-password
```

Once credentials are set, the doctor check `live-mailplus` will report `ok` instead of `gated`.

The live adapter (`src/mailplus_intelligence/live_adapter.py`, to be implemented per issue #71) must pass the same interface contracts as the fixture backend before being enabled.

---

## 6. Extraction job — fixture mode

Run classification and semantic extraction against indexed messages.

```bash
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

```bash
# List all candidates
mpi queue list --db mailplus.db

# List only pending candidates
mpi queue list --db mailplus.db --status candidate

# Inspect a specific artifact
mpi queue inspect <artifact-id> --db mailplus.db

# Approve a candidate
mpi queue approve <artifact-id> --db mailplus.db --notes "Reviewed and confirmed"

# Reject a candidate
mpi queue reject <artifact-id> --db mailplus.db --notes "False positive — automated notice"

# Defer for later review
mpi queue defer <artifact-id> --db mailplus.db

# Apply a correction
mpi queue correct <artifact-id> --corrected-summary "Corrected text here" --db mailplus.db
```

**Guardrail:** rejected and deferred candidates are never exported. Only `approved` and `corrected` items proceed to dry-run export.

---

## 8. Dry-run export

Generate inspectable artifacts from approved candidates without modifying production surfaces.

```bash
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
| Sync inserts 0 records | All locator_export_ids already present | Normal for idempotent re-run |
| Queue `decide` raises `KeyError` | Artifact ID not in database | Check artifact ID spelling |
| Export produces 0 artifacts | No approved/corrected items in queue | Approve candidates first |

---

## 10. Audit log review

All cache and queue operations emit audit events. Review with:

```bash
sqlite3 mailplus.db "SELECT * FROM text_cache ORDER BY cached_at DESC LIMIT 20;"
sqlite3 mailplus.db "SELECT artifact_id, review_status, revision, reviewer_identity, decided_at FROM promotion_queue ORDER BY queued_at DESC LIMIT 20;"
sqlite3 mailplus.db "SELECT artifact_id, artifact_revision, prior_status, new_status, reviewer_identity, occurred_at FROM review_events ORDER BY occurred_at DESC LIMIT 20;"
sqlite3 mailplus.db "SELECT artifact_id, artifact_revision, state, target_key, rollback_requested_at FROM export_outbox ORDER BY updated_at DESC LIMIT 20;"
```

Review events are append-only and never contain raw message body content.
Legacy rows marked with `provenance='legacy'` remain auditable but are not
export eligible because the pre-v4 schema discarded required provenance.

---

## 11. Evaluation and regression

Run the offline evaluation harness before and after any extraction or classification change:

```bash
python scripts/evaluate.py --fixtures-dir fixtures --report-json /tmp/eval-report.json
cat /tmp/eval-report.json
```

A baseline report should be committed alongside any change to classification heuristics, suppression rules, or semantic contract.
