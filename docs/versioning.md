# Versioning

MailPlus Intelligence uses semantic versioning after public release.

## 0.x Policy

While the project is in `0.x`, breaking changes can ship in minor releases
when they are documented in `CHANGELOG.md`. Patch releases should remain
backward compatible unless a security fix requires otherwise.

## Source Of Truth

The package version is declared in `pyproject.toml` and exposed at runtime as
`mailplus_intelligence.__version__` through `importlib.metadata`. Do not copy
the version into README examples or docs unless the surrounding text is release
history.

## Release Notes

Every release should update `CHANGELOG.md` with operator-facing changes, known
stubs, and any compatibility notes. Commit-level detail belongs in the GitHub
history, not the changelog.
