# SpecForge Core Canonical Data Model v0.1.0-alpha.7

This model succeeds v0.1.0-alpha.6 and adds checkpoint records, checkpoint acceptance records and assurance profiles.

## Checkpoint
Canonical ID: `CHK-NNNN`. A checkpoint contains a non-empty unique `included_changes` set, its deterministic SHA-256 digest, an exact candidate material identity, validation evidence and optional acceptance linkage. Status is `candidate`, `under_validation`, `accepted`, `rejected` or `superseded`.

The change-set digest is SHA-256 over lexically sorted change IDs joined by LF with a final LF, prefixed by `sha256:`.

## Checkpoint acceptance
Canonical ID: `ACC-NNNN`. An acceptance record binds a decision to one checkpoint, one exact candidate material identity and one exact included-change digest, together with actor, timestamp and provenance mechanism.

## Change lifecycle
`ready_for_checkpoint` is a post-implementation, pre-completion state. It means the change has valid authority, a passed implementation and required change-scoped assurance. It does not mean an aggregate candidate has been accepted.

## Assurance profiles
An assurance profile has an ID, version and additive validation and/or acceptance requirement sets. Installed packs may contribute profiles through `assurance_profiles`. Project checkpoint policy and pack profiles merge monotonically.

## Completion
A checkpoint completion operation verifies included changes, exact candidate material, required validation evidence and exact acceptance binding before updating the checkpoint and eligible changes. It fails closed and rolls back attempted file updates if a completion write fails.

Project format remains 1.
