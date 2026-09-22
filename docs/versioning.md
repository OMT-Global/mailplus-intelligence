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

The prepared package version is `0.1.1`, and its release tag is `v0.1.1`. The
Phase A release gates in issue #98 are complete. Create the immutable tag from
the release-preparation merge commit to trigger the GitHub Release workflow.

## v0.1.0 Limitation

The public `v0.1.0` tag is historical but not installable. It points to a
documentation-only commit from before the repository contained
`pyproject.toml`, the `src/mailplus_intelligence` package, or buildable release
artifacts. Do not delete, move, or recreate that tag. The prepared `v0.1.1`
patch is the first package release candidate intended to provide working wheel
and source-distribution artifacts.

## Release Notes

Every release should update `CHANGELOG.md` with operator-facing changes, known
stubs, and any compatibility notes. Commit-level detail belongs in the GitHub
history, not the changelog. The release workflow uses the matching version
section in `CHANGELOG.md` as the GitHub release notes, so the package version,
changelog heading, and proposed tag must agree before tagging.
