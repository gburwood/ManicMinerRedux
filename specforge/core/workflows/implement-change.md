# Implement Change Workflow

1. Run executable bootstrap readiness.
2. Request implementation transition through the lifecycle gate.
3. Confirm exact current proposal has valid human-authorised approval and matching digest when Controlled mode requires it.
4. Record implementation attempt where meaningful.
5. Modify implementation within approved scope.
6. Run relevant change-specific tests and record `passed`, `failed`, `blocked`, or `unavailable`.
7. Run change-scoped SpecForge structural validation for ordinary governed work: `validate-specforge.py . --change CHG-...`. Use full `validate-specforge.py .` for bootstrap, explicit audits, or changes to validation/schema/governance rules themselves.
8. Record implementation outcome and immutable source revision when available.
9. Request completion through the lifecycle gate.
10. Complete only if every mandatory gate passes; otherwise retain current state and report machine-readable blockers.
11. Record forensic events and release traceability where applicable.

## controlled_v3 interaction authority

For Core alpha.21 managed work, do not create a controlled_v3 APR by hand. Present the exact proposal
through the managed workflow and record the user's reply with `specforge-managed.py approval`; the
tool binds the canonical APR to the actual informed-approval evidence and timestamp.

Implementation must not start before that approval exists. If the final candidate was not granted a
PFA, create and verify the checkpoint, present it to the human, capture a distinct CAP proof and use
`specforge-checkpoint.py finalise-direct`. Proposal approval cannot be recycled as checkpoint
acceptance.

Substantive final-delivery work must also reconcile the managed `PROJECT.md` current-work binding
and resolve all recorded clarifications before proposal presentation.
