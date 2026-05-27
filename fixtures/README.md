# Fixtures

All fixtures in this tree are synthetic, metadata-only or derived-output examples. Do not add real MailPlus exports, raw message bodies, attachment payloads, credentials, live links, personal names, real domains, generated databases, caches, or logs.

Before extending a fixture corpus, review `docs/privacy-redaction-boundaries.md`, use reserved domains such as `example.com` or `example.test`, and run:

```bash
bash scripts/check-detect-secrets.sh --all-local
```
