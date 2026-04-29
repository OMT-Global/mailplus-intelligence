# Bootstrap Onboarding

Use this checklist after the first bootstrap render or whenever `project.bootstrap.yaml` changes in a way that affects GitHub policy, environments, or home-profile sync.

## Project

- Product name: `MailPlus Intelligence`
- Repository: `OMT-Global/mailplus-intelligence`
- Manifest: `project.bootstrap.yaml`

## Repo Governance

- Confirm branch protection or rulesets on `main` require one approval, code owner review, and approval from someone other than the most recent pusher.
- Confirm branch protection points at the `CI Gate` status.
- Confirm `delete branch on merge` and `allow auto-merge` are enabled.




## Environments

- `dev`: open by default for rapid iteration.
- `stage`: one reviewer required and self-review blocked.
- `prod`: one reviewer required, self-review blocked, deployments limited to `main`.

## Runner Policy

- Shell-safe jobs may use `[self-hosted, synology, shell-only, private]`.
- Docker, service-container, browser, and `container:` workloads stay on GitHub-hosted runners.
- Keep PR checks cheap. Add heavy validation to `scripts/ci/run-extended-validation.sh` instead of the PR lane.


## Home Profiles

- Run `bootstrap apply home --manifest ./project.bootstrap.yaml` after reviewing the bundled profile content.
- The bootstrap manages portable Codex and Claude assets only. Auth, sessions, caches, and machine-local state stay unmanaged.

## OpenClaw Skill

- If local OpenClaw skills are installed, use the `omt-bootstrap` skill for manifest upgrades, plan/apply flows, and v1-to-v2 normalization guidance.

## Claude Setup

- First-party Claude web sessions should use `bash scripts/claude-cloud/setup.sh` in `claude.ai/code`.
- Interactive Claude work is prepared through `.devcontainer/devcontainer.json`.
- GitHub-hosted Claude automation lives in `.github/workflows/claude.yml` and is intentionally separate from the required PR checks.
- Finish GitHub-side auth by running `/install-github-app` in Claude Code or adding `ANTHROPIC_API_KEY` as a repo secret.
