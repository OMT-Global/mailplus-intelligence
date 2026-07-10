# CI Validation

MailPlus Intelligence uses two validation lanes so PR checks stay cheap while deeper fixture checks remain available on `main`, nightly, and manual dispatch.

## Fast validation

Run locally with:

```bash
bash scripts/ci/run-fast-checks.sh
```

Fast validation is the required PR lane. It must stay shell-safe for `[self-hosted, synology, shell-only, private]` runners and must not require Docker, service containers, browser infrastructure, live MailPlus access, or operator credentials.

The fast lane currently checks:

- Python 3.12 runtime availability.
- Repository secret patterns through `scripts/check-detect-secrets.sh --all-files`.
- Unit tests with `PYTHONPATH=src python -m unittest discover -s tests -v`.

## Extended validation

Run locally with:

```bash
bash scripts/ci/run-extended-validation.sh
```

Extended validation runs the fast lane first, then adds fixture-oriented regression checks that can grow beyond the PR budget. It is wired for `main`, nightly, and manual workflow runs. Changes to packaging, source, tests, fixtures, scripts, workflows, or documented contracts trigger this lane after merge to `main`.

The extended lane currently checks:

- Everything in fast validation.
- The complete classification, semantic-contract, and noise-suppression fixture evaluator.
- Exact non-empty corpus counts, stable fixture identifiers, and overall pass state.
- False-promotion and false-suppression counts in the printed and JSON evaluation report.

Future fixture evaluation suites belong here unless they are cheap enough to run on every PR and remain shell-safe.
