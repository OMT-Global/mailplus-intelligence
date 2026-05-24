# Contributing

Thanks for helping improve MailPlus Intelligence.

## Development Setup

Use Python 3.12 or newer:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Run the fast validation gate before opening a pull request:

```bash
bash scripts/ci/run-fast-checks.sh
```

## Pull Requests

- Keep changes focused and reviewable.
- Add or update tests for interactive, branching, or operator-facing behavior.
- Keep `CI Gate` passing.
- Do not include generated databases, local caches, runtime auth, mailbox
  exports, raw message bodies, attachment payloads, or machine-local files.

## Privacy And Fixtures

Fixtures and examples must be synthetic or fully redacted. Use reserved domains
such as `example.com` or `example.test`, and avoid values that identify real
people, accounts, hosts, messages, or credentials.

Review `docs/privacy-redaction-boundaries.md` before adding data fixtures,
semantic outputs, logs, or documentation examples.

## Good First Issues

Good newcomer tasks are tracked with the
[`good first issue` label](https://github.com/OMT-Global/mailplus-intelligence/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
Prefer fixture-mode changes, docs clarifications, or tests that do not require
live MailPlus credentials.
