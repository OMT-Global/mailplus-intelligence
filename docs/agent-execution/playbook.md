# Agent Execution Playbook

This playbook defines the default execution contract for agent work in MailPlus Intelligence. It exists to keep issue work reviewable, credentials out of scope, and PR evidence consistent with the repo bootstrap policy.

## Scope

- Work one GitHub issue per branch and one branch per PR.
- Keep each branch focused on the governing issue named in the PR.
- Prefer documentation, manifests, templates, and shell-safe CI changes until the repo has an approved runtime surface.
- Do not batch unrelated issue fixes, repo cleanup, dependency updates, package changes, runtime changes, or test rewrites into the same branch.

For issue #18, the owned surface is this agent execution playbook and any minimal README navigation needed to find it.

## Branch Naming

Use a branch name that identifies the agent owner, issue number, and short slug:

```text
codex/issue-18-agent-execution-playbook
```

Default pattern:

```text
codex/issue-<issue-number>-<short-kebab-slug>
```

Rules:

- Start from an up-to-date `main` unless the user explicitly provides another base.
- Do not work directly on `main` or `master`; repo hooks block those commits.
- Do not reuse a branch for a different issue after a PR is opened.
- If a branch already contains unrelated edits, create a fresh worktree or stop and ask before mixing scope.

## Worktree Usage

Use a separate worktree when the main checkout is dirty, another agent is active in the same files, or multiple issues are being handled in parallel.

Suggested setup:

```bash
git fetch origin --prune
git worktree add ../mailplus-intelligence-issue-18 origin/main
cd ../mailplus-intelligence-issue-18
git checkout -b codex/issue-18-agent-execution-playbook
```

Before editing, capture the state:

```bash
git status -sb
git branch --show-current
```

Do not delete another agent's worktree or revert edits that are not yours.

## Execution Checklist

1. Read `AGENTS.md`, `project.bootstrap.yaml`, and the relevant docs before editing.
2. Confirm the issue scope and expected files.
3. Create or switch to a feature branch.
4. Keep write scope to the issue-owned files.
5. Run the local validation commands that match the touched surface.
6. Open a PR that references the governing issue and includes exact evidence.
7. Watch the required PR checks until `CI Gate` reports success, or record the concrete blocker.

## Validation Commands

For documentation-only changes, run:

```bash
git diff --check
bash scripts/ci/run-fast-checks.sh
bash scripts/check-detect-secrets.sh --all-files
git status -sb
```

If the issue changes bootstrap-managed policy or CI configuration, also run a bootstrap plan before any apply step:

```bash
bootstrap plan --manifest ./project.bootstrap.yaml
```

Use `apply` only after the plan is reviewed and the user expects provisioning changes.

Do not introduce package-manager, runtime, or test commands for docs-only work. Add those commands only when the issue actually owns package, runtime, or test files.

## PR Evidence

Every PR should include:

- Summary of what changed.
- Governing issue, using `Closes #<number>` or `Refs #<number>` as appropriate.
- Changed path list.
- Exact validation commands and their results.
- Bootstrap governance note when `project.bootstrap.yaml`, CI, environments, hooks, or managed home-profile files are involved.
- Notes about any skipped validation, with the reason.

For CI evidence, report job names rather than only saying "CI passed." The required PR signal is `CI Gate`.

## CI Gate Expectations

The PR lane is intentionally cheap and shell-safe. `CI Gate` aggregates:

- `Detect Relevant Changes`
- `Fast Checks`
- `Validate Secrets`

The gate treats upstream `success` and `skipped` as acceptable. A failing `CI Gate` usually means one of the upstream jobs failed first; inspect that job before changing code.

Shell-safe jobs may run on `[self-hosted, synology, shell-only, private]`. Any job requiring Docker, service containers, browser infrastructure, or `container:` must stay on GitHub-hosted runners and should not be added to the fast PR lane casually.

If a runner is offline or checks remain queued, record it as a CI infrastructure blocker. Do not churn docs or code to mask runner availability problems.

## Live MailPlus, DSM, and NAS Stop Conditions

Stop and ask before any work requires live credentials or direct access to MailPlus, DSM, or the NAS.

Blocked surfaces include:

- Real MailPlus mailbox sync, export, deletion, or mutation.
- DSM API authentication against a live host.
- Direct NAS shell access, privileged commands, or `sudo`.
- Use of `SUDO_PASS`, `BW_SESSION`, API tokens, session cookies, SSH keys, or machine-local env files.
- Copying auth state, caches, sessions, or secrets into docs, fixtures, memory, or home profiles.

Acceptable work before explicit approval includes:

- Documentation.
- Static templates.
- Redacted examples.
- Fixture shapes with fake data.
- Local shell-safe validation.
- Bootstrap `plan` output that does not provision or authenticate.

When blocked, report the exact missing credential or access path and stop. Do not attempt fallback probing against live DSM, MailPlus, or NAS surfaces.

## Closeout Checklist

Before handing off:

- `git status -sb` shows only intended files changed.
- No package, runtime, or test files were touched unless the issue owns them.
- Validation commands and results are captured.
- PR body names the governing issue and exact evidence.
- `CI Gate` is green, or the remaining blocker is explicitly classified.
