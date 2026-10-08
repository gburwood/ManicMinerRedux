# SpecForge Core Product Specification 0.1.0-alpha.18

This candidate specification introduces domain-neutral checkpoints as an additive evaluation boundary. It succeeds alpha.17, whose normative predecessor chain remains authoritative except where extended here.

## Checkpoints
A checkpoint identifies an explicit set of governed changes and binds that set to one exact canonical candidate material identity. The checkpoint is an evaluation boundary, not a domain-specific work cadence, test phase, publication action or release.

Individual changes establish intent, approval, implementation evidence and proportionate scoped assurance. A governed change may enter `ready_for_checkpoint` when those change-local obligations are satisfied. Checkpoint creation or validation does not complete the change.

## Candidate identity
The candidate material identity and included-change digest are immutable for acceptance purposes. If either changes, prior validation or acceptance does not apply. Revised material is represented by a successor checkpoint rather than mutation of an evaluated candidate.

Checkpoint and acceptance records are governance bookkeeping and may live beneath the configured history root, so recording them does not change the material identity they attest to.

## Validation and acceptance
Validation evidence is attached to the exact checkpoint candidate. Whole-project or otherwise expensive assurance may therefore run once at checkpoint scope rather than redundantly for every included change.

Acceptance is a separate immutable authority record binding the decision, actor, provenance mechanism, exact checkpoint, exact candidate material and exact included-change digest. Successful acceptance may complete all eligible included changes transactionally. Rejected or superseded checkpoints leave their changes available to a successor checkpoint.

Acceptance has no implicit release, publication, deployment or environment meaning.

## Pack assurance integration
Packs may expose the `assurance_profiles` extension. Profiles contribute machine-readable validation and acceptance requirement identifiers. Requirements compose additively and deterministically in pack precedence order. Packs may add obligations but may not remove or downgrade Core or project-policy obligations. Domain-specific language and procedures belong in packs.

## Compatibility
Checkpoint policy is optional by default. Existing projects and historical records remain valid without migration. Projects may require checkpoint use through project policy. Project format remains 1.
