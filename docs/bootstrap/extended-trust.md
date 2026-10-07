# Extended validation trust boundary

Recovery of PR #138; not a blanket public-label substitution.

- All PR execution remains hosted. Release job also stays hosted; no release is dispatched by recovery.
- Trusted extended jobs run on standard GitHub-hosted Ubuntu. These deterministic fixture checks require Bash, Git and Python 3.12; they do not need Synology, private-network access, live MailPlus credentials or specialized hardware.
- No runner-group membership, repository admission or workflow allowlist changes are required. Each hosted job gets an isolated ephemeral runner rather than persistent fleet state.
- Callee rejects other repositories and PR events. Main push/nightly/manual runs use the triggering main SHA. The exact recovery branch dispatch checks out fixed base `8e485e5c96c47d7a13e4d09cf98fe5a091ce6895`; it is bootstrap evidence, not tests of the changed PR head.
- PR hosted CI validates the new head. Post-merge main extended validation must be collected separately, after JT approval; no success inferred in advance.
- No inputs or inherited secrets, checkout credentials disabled. Current main action pins and app/CI/infra filters preserved verbatim.
- Preserve the source branch containing the new immutable callee commit. Squash merge does NOT retain source ancestry; do not delete that branch while the caller references its commit. The older retained source ref may still be used by historical runs.
- Repository/event guards remain in the reusable workflow; PR jobs remain in the separate hosted PR lane. No persistent self-hosted route is selected.
- The whole-callee digest guard detects event/checkout/runner/command edits; source, caller pin and digest require coordinated independent review when changed.
- Check names and commands remain; the gate now rejects unexpected skipped jobs and failures. Only filter-selected skips are valid.
- Renewed sole-owner JT approval is a final merge gate. PR #138 is merged; this change supersedes its runner route.

The caller annotation `v1` denotes this first internal trust-contract revision; execution always binds the full SHA, not a mutable version tag.
