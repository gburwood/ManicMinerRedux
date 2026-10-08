# SpecForge Core Canonical Data Model v0.1.0-alpha.9

This model succeeds v0.1.0-alpha.8.

## controlled_v3 approval provenance

A controlled_v3 APR remains `APR-NNNN`, but its evidence includes the exact
`informed_approval_proof` path and `received_at`. APR timestamp equals that received time. The proof
binds the human actor, exact proposal digest, proposal presentation and decision.

Implementation chronology is constrained so a controlled_v3 implementation `started_at` cannot
precede the valid current-proposal approval.

## Checkpoint acceptance proof

Canonical ID: `CAP-NNNN`.

CAP is distinct from APR, PFA and ACC. It records direct human acceptance of an already-existing
checkpoint candidate and requires:

- checkpoint identity;
- exact candidate material provider, revision and file count;
- included-change digest;
- human actor;
- checkpoint-presentation evidence path and session;
- acceptance text;
- checkpoint presentation time;
- actual received time.

A CAP may be consumed once by a direct human ACC. The ACC declares
`authority.mode: direct_checkpoint_acceptance_v1` and references the CAP. PFA-derived automated ACC
uses the existing `prospective_exact_candidate_v1` authority mode and does not require CAP.

## Managed session guard v2

Guard v2 records a SHA-256 request identity and session-start project-definition identity. It also
records project-definition reconciliation state, including prepared non-material path and approved
SHA-256 when an update is required.

PROJECT.md current work is identified by the
`SPECFORGE-CURRENT-WORK:START/END` block and binds at least `request_digest` and `change`.

Managed clarification records use stable `CLR-NNNN` evidence identities. They are evidence rather
than canonical authority records.

Historical guard-v1 and controlled_v1/v2 records retain their previous interpretation.
