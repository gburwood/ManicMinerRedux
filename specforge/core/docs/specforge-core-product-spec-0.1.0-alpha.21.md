# SpecForge Core Product Specification 0.1.0-alpha.21

This candidate succeeds alpha.20 and closes the three managed-interaction integrity gaps reproduced by
School Project 12.

## controlled_v3

New alpha.21 managed controlled changes use `controlled_v3`. Historical controlled_v1/v2 records
retain their earlier semantics.

A controlled_v3 proposal approval is valid only when the canonical APR is bound to the exact current
proposal digest and to the actual informed-approval proof received after proposal presentation. Its
timestamp is the proof's real received time. An implementation attempt may not start before that
approval.

## Independent direct checkpoint acceptance

Plain proposal approval authorises implementation only. When no prospective finalisation authority
(PFA) exists, final checkpoint acceptance is a second interaction after the checkpoint exists and is
verified.

The managed checkpoint presentation records the exact checkpoint candidate and included-change digest.
The human reply creates canonical `CAP-NNNN` checkpoint-acceptance proof. CAP binds the checkpoint,
candidate material identity, included-change digest, human actor, presentation, session and actual
acceptance time.

`specforge-checkpoint.py finalise-direct` consumes CAP exactly once, creates the canonical human
`ACC-NNNN` at the CAP acceptance time, accepts the checkpoint, completes its changes and advances
trusted material authority atomically.

The same literal response, for example "Yes", may validly appear in proposal approval and checkpoint
acceptance. Independence is proved by distinct presentations, evidence identities and chronology, not
by comparing strings.

PFA remains the deliberate one-prompt exception. A PFA-derived ACC continues to be created later by
the automated finaliser after the exact candidate exists.

## Managed session guard v2

New substantive managed sessions bind the user request by SHA-256 without requiring raw request text
to be persisted. The guard also records the session-start PROJECT.md identity and current-work
binding.

For new substantive delivery, PROJECT.md contains a human-readable machine-verifiable current-work
block that binds the request digest and governed change. When an update is required, the expected
PROJECT.md is prepared in non-material evidence before proposal approval, its SHA-256 is bound by the
proposal and it is applied only during authorised implementation.

Final delivery verifies the actual PROJECT.md content. An agent declaration of "unchanged" is
insufficient when the session-start current-work binding is stale.

## Clarification state

Material clarification is first-class managed interaction state. The managed clarify command records
`clarification_requested` before the question is surfaced. Resolution records
`clarification_resolved` for the same stable clarification id. Proposal presentation fails while a
recorded clarification remains open. A controlled_v3 change that declares clarification required must
have resolved evidence before proposal presentation.

Clarification evidence is observational only and grants no authority.

## Compatibility

Existing alpha.20 PFA behaviour, controlled_v1/v2 lifecycle records, direct historical ACC records and
completion-guard-v1 sessions remain valid and are not rewritten. Project format remains 1.
