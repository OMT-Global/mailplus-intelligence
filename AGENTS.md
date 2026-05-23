# AGENTS

- Always work on a feature branch. Hooks block commits to `main` and `master`; enable them with `git config core.hooksPath .githooks`.
- Stack baseline: Generic polyglot.
- Repo class: library.
- CI baseline: fast PR checks stay cheap and shell-safe; extended validation runs on `main`, nightly, or manual dispatch.
- Self-hosted runner policy: shell-safe jobs may use `[self-hosted, synology, shell-only, private]`; anything needing Docker, service containers, browser infra, or `container:` must stay on GitHub-hosted runners.
- Add or update tests for every interactive, branching, or operator-facing behavior change.
- Never commit real secrets, runtime auth, or machine-local env files. Use templates and GitHub environments instead.

## Local Conventions

- Keep scope tight and favor predictable templates over clever scaffolding.
- Treat `project.bootstrap.yaml` as the source of truth for repo governance, environments, CI policy, and home profile sync.
- If OpenClaw local skills are available, use the `omt-bootstrap` skill for manifest-first bootstrap work instead of rediscovering the workflow.
- Review `docs/bootstrap/onboarding.md` before first merge to confirm reviewers, runner labels, and environment gates match the project.
- The R1-R6 GitHub issues with the `release-v0.1` label drive the public v0.1.0 release.
