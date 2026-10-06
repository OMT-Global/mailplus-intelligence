# Extended validation trust boundary

Recovery of PR #138; not a blanket public-label substitution.

- All PR execution remains hosted. Release job also stays hosted; no release is dispatched by recovery.
- Trusted extended jobs route only to `synology-public` with `[self-hosted, synology, shell-only, public]`. Never route this public repository to the private pool.
- JT reported changing group repository access to all repositories. Live public-repository enablement, runner membership/status and any workflow restrictions still require administrator verification or an actual assignment; this repository change does not modify fleet access settings.
- Callee rejects other repositories and PR events. Main push/nightly/manual runs use the triggering main SHA. The exact recovery branch dispatch checks out fixed base `8e485e5c96c47d7a13e4d09cf98fe5a091ce6895`; it is bootstrap evidence, not tests of the changed PR head.
- PR hosted CI validates the new head. Post-merge main native validation must be collected separately, after JT approval; no success inferred in advance.
- No inputs or inherited secrets, checkout credentials disabled. Current main action pins and app/CI/infra filters preserved verbatim.
- Preserve the source branch containing the new immutable callee commit. Squash merge does NOT retain source ancestry; do not delete that branch while the caller references its commit. The older retained source ref may still be used by historical runs.
- A different-caller-ref negative control proves pre-job caller rejection, not a real fork trial. Server-side allowlists must exclude alternate persistent runner paths.
- The whole-callee digest guard detects event/checkout/runner/command edits; source, caller pin and digest require coordinated independent review when changed.
- Check names and commands remain; the gate now rejects unexpected skipped jobs and failures. Only filter-selected skips are valid.
- Renewed sole-owner JT approval is a final merge gate. PR #138 remains open until replacement outcome and remaining scope are reconciled.

The caller annotation `v1` denotes this first internal trust-contract revision; execution always binds the full SHA, not a mutable version tag.
