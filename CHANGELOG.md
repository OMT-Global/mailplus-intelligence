# Changelog

All notable changes to MailPlus Intelligence are documented here.

The format follows Keep a Changelog, and this project uses the versioning
policy in [docs/versioning.md](docs/versioning.md).

## [Unreleased]

- Prepare public-release polish, release workflow, and repo metadata before the
  v0.1.0 visibility/tagging gate.

## [0.1.0] - 2026-05-23

### Added

- Canonical-store boundary and privacy/redaction rules for keeping MailPlus as
  the raw-message archive.
- Metadata fixture corpus, SQLite schema bootstrap, and index/search helpers.
- Deterministic thread reconstruction with confidence evidence.
- Classification lanes, noise suppression policy, and fixture coverage.
- Deterministic semantic extraction, LLM cassette playback, and optional live
  LLM extraction surface.
- Selected-message text cache policy, promotion queue, dry-run exporters, and
  scheduler locks.
- CLI commands for search, thread inspection, queue review, dry-run export,
  sync status, and doctor checks.
- Live adapter and raw-fetch interface stubs for future credential-gated Phase
  2 integration.

### Changed

- Public docs now call out fixture-mode support separately from live MailPlus
  and production export work.

### Security

- Added fixture/privacy boundaries and fast validation gates sized for a public
  repo before live MailPlus credential handling exists.
