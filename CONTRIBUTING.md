# Contributing

Contributions should start from a GitHub issue that is assigned or explicitly enabled by Pheidon. Keep changes scoped to that issue, work on a feature branch, and link the issue from the pull request.

## Local Setup

- Install dependencies for the selected stack before changing code.
- Enable repo hooks with `git config core.hooksPath .githooks`; they block direct commits to `main` and catch committed runtime env files.
- Use `project.bootstrap.yaml` as the source of truth for governance, CI, environments, and bootstrap-managed guidance files.

## Change Expectations

- Keep implementation changes minimal and relevant to the governing issue.
- Add or update tests for interactive, branching, or operator-facing behavior changes.
- Keep fast PR checks cheap and shell-safe; move heavyweight validation to `scripts/ci/run-extended-validation.sh`.
- Do not commit real secrets, runtime auth, generated credentials, caches, or machine-local env files.

## Validation

- Run the relevant local checks before opening a PR.
- For this bootstrap contract, the required PR check surface is `CI Gate`.
- Document any skipped checks in the PR with a concrete reason.

## Pull Requests

- Use `.github/PULL_REQUEST_TEMPLATE.md`.
- Link the governing issue with a closing keyword when the PR should close it.
- PR authors may not approve their own PRs.
- A healthy PR should converge toward auto-merge after required checks pass or are intentionally skipped, approvals are satisfied, and no blocking review state remains.
- When GitHub plan limits make auto-merge unavailable for a private repo, use the fallback merge-readiness policy: required checks pass or are intentionally skipped, approvals and conversation resolution are satisfied, no blocking review state remains, and a maintainer performs the merge manually.
