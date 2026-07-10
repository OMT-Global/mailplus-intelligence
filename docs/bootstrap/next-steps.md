# Next Steps

- Treat the Python 3.12 package, SQLite fixture runtime, and CI scripts as the
  established baseline; update `project.bootstrap.yaml` before changing their
  governance contract.
- Run `bash scripts/ci/run-fast-checks.sh` before each PR. It includes the
  executable quickstart/runbook smoke contract and requires no live credentials.
- Periodically verify CODEOWNERS, environment reviewers, runner labels, and the
  required `CI Gate` check against `docs/bootstrap/onboarding.md`.
- Re-run `bootstrap plan --manifest ./project.bootstrap.yaml` after major
  manifest changes to confirm intended drift.
- Finish the remaining Phase A blockers in issue #98 before claiming a live or
  production-verified MailPlus capability.
