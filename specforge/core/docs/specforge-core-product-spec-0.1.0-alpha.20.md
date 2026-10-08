# SpecForge Core Product Specification 0.1.0-alpha.20

This candidate succeeds alpha.19 and adds prospective exact-candidate finalisation authority.

## One-prompt exact-candidate finalisation

A human may explicitly approve a presented proposal and grant prospective authority to finalise it
without a second checkpoint prompt only when the entire eventual project-material state is
deterministically known. The ordinary phrase **Approve and finalise** is the reference interaction.

The authority is recorded as `PFA-NNNN`, not as checkpoint acceptance. PFA records the actual human
decision time, exact proposal digest, presentation and informed-approval evidence, pre-implementation
material baseline, exact projected material candidate and then-current acceptance requirements.

## Exact-candidate eligibility

The proposal must declare `exact_candidate_finalisation.eligible: true`. Every material add or
modify operation in declared scope must have one exact SHA-256 identity in
`prepared_artifacts`. Material deletions must be explicit. V1 refuses ambiguous material rename,
copy, wildcard or dynamic operations.

Core calculates the projected material candidate with the same canonical path/hash manifest algorithm
used by `specforge_snapshot`. The whole candidate, not merely the listed deliverables, is therefore
bound by the human authority.

## Finalisation

After implementation, validation and creation of a single-change checkpoint, the PFA may be consumed
only if the checkpoint candidate revision and file count exactly match the projected candidate, the
proposal digest remains current, all normal checkpoint gates pass, acceptance requirements are
unchanged and the authority has not been consumed before.

Successful consumption creates the real `ACC-NNNN` at finalisation time. Its actor is an automated
SpecForge finaliser acting under the immutable human PFA. The ACC preserves the human principal and
grant timestamp as provenance but does not claim a second human action occurred.

ACC creation, checkpoint acceptance, change completion and trusted-material advancement are one
fail-closed transaction. If any prospective condition fails, Core falls back to ordinary explicit
post-checkpoint human acceptance.

## Compatibility

Direct checkpoint acceptance remains supported. Alpha.19 and older historical ACC records are not
reinterpreted. Managed completion receipts continue to bind the resulting checkpoint and acceptance.
Project format remains 1.
