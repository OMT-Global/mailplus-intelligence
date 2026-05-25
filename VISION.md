# MailPlus Intelligence Vision

Version: 0.1

MailPlus Intelligence is a privacy-aware analysis layer for Synology MailPlus data, focused on useful local intelligence rather than cloud-dependent mailbox automation.

It should help the operator understand mail patterns, threads, references, and governance-relevant signals while keeping fixture-bound tests and private data boundaries explicit.

## Who It Serves

- The operator managing Synology-hosted mail.
- Agents repairing parsing, threading, and governance workflows.
- Future users who need local mail intelligence without handing over mailbox contents.

## Product Principles

- Fixture-bound validation is the default proof path.
- Malformed references and edge cases should become tests.
- Public readiness requires careful separation from live private mail.
- Threading behavior must be explainable and inspectable.
- Governance docs should match the code's actual privacy boundary.

## Near-Term Direction

- Harden threading and malformed-reference handling.
- Keep offline fixtures representative and safe.
- Separate governance checkout work from live MailPlus integration work.
- Improve public-readiness docs and validation gates.

## Non-Goals

- Do not depend on live private mail for routine tests.
- Do not expose mailbox content in docs, logs, or generated artifacts.
- Do not turn local intelligence into cloud mailbox surveillance.
