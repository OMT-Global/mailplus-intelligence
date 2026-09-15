# Extended validation trust boundary

Recovery of PR #138; not a blanket public-label substitution.

- All PR execution remains hosted. Release job also stays hosted; no release is dispatched by recovery.
- Existing Linux slot 05 is shared with Flow only through group 11 (`linux-flow-trusted`). No extra runners, admission or resource changes.
- Group 11 must allow exactly the retained Flow selector plus `OMT-Global/mailplus-intelligence/.github/workflows/extended-trusted.yml@d08b5ee74df3eb6d016e9e4aa267acc4bcafd154`. Remove MailPlus from every other public-enabled runner group (currently 4 and 9). Never relax selector restrictions.
- Callee rejects other repositories and PR events. Main push/nightly/manual runs use the triggering main SHA. The exact recovery branch dispatch checks out fixed base `8e485e5c96c47d7a13e4d09cf98fe5a091ce6895`; it is bootstrap evidence, not tests of the changed PR head.
- PR hosted CI validates the new head. Post-merge main native validation must be collected separately, after JT approval; no success inferred in advance.
- No inputs or inherited secrets, checkout credentials disabled. Current main action pins and app/CI/infra filters preserved verbatim.
- Preserve `refs/heads/pheidon/source-mailplus-extended-d08b5ee7` at the immutable callee source. Squash merge does NOT retain source ancestry; do not delete the retained ref.
- A different-caller-ref negative control proves pre-job caller rejection, not a real fork trial. Server-side allowlists must exclude alternate persistent runner paths.
- The whole-callee digest guard detects event/checkout/runner/command edits; source, caller pin, group selector and digest require coordinated independent review when changed.
- Check names and commands remain; the gate now rejects unexpected skipped jobs and failures. Only filter-selected skips are valid.
- Renewed sole-owner JT approval is a final merge gate. PR #138 remains open until replacement outcome and remaining scope are reconciled.

The caller annotation `v1` denotes this first internal trust-contract revision; execution always binds the full SHA, not a mutable version tag.
