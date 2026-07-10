# Changelog

All notable changes to MailPlus Intelligence are documented here.

The format follows Keep a Changelog, and this project uses the versioning
policy in [docs/versioning.md](docs/versioning.md).

## [Unreleased]

- Publication of the prepared v0.1.1 patch remains gated on the other Phase A
  release blockers tracked by issue #98.

## [0.1.1] - 2026-07-10 (proposed)

### Fixed

- Package all three SQL migrations in wheels and source distributions so a
  clean installation can initialize an empty SQLite database.
- Load migrations through installed-package resources instead of assuming a
  filesystem-relative source checkout.

### Changed

- Release validation now checks wheel and source-distribution contents, rebuilds
  a wheel from the source distribution, and exercises the installed `mpi` CLI
  through migration, fixture seed, search, queue inspection, and dry-run export.

### Release status

- The proposed release tag is `v0.1.1`. It has not been published and remains
  blocked on the other Phase A issues linked from #98.
- This patch supersedes the unusable `v0.1.0` artifact history without moving or
  deleting the public `v0.1.0` tag.

## [0.1.0] - 2026-05-23

> **Known release limitation:** the public `v0.1.0` tag points to a
> documentation-only commit that predates `pyproject.toml` and the `src/`
> package. It is not an installable software release. The tag is retained
> unchanged as public history; use `v0.1.1` once that patch is published.

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
