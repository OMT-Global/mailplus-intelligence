# Security Policy

## Supported Versions

This project is pre-1.0. Security fixes are applied to the default branch.

## Reporting A Vulnerability

Please do not open public issues for suspected vulnerabilities, exposed secrets,
or privacy-sensitive data handling problems.

Report security concerns through GitHub private vulnerability reporting when
available for this repository. If private reporting is unavailable, contact the
repository owner with a minimal description of the issue and the affected
version or commit.

Expected response: the maintainer will acknowledge a complete report within
seven calendar days and will provide a remediation or disclosure plan once the
impact is understood. Please include enough reproduction detail to verify the
issue without including live credentials, raw mail, mailbox exports, or other
private payloads.

## Data Handling Scope

MailPlus Intelligence must not store raw mail bodies, attachment payloads,
credential material, session state, mailbox exports, or local runtime caches in
the repository. See `docs/privacy-redaction-boundaries.md` for the project data
boundary and redaction rules.
