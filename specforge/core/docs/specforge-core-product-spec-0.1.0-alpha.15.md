# SpecForge Core Product Specification 0.1.0-alpha.15

Alpha.15 introduces a deterministic, policy-driven minimum governance tier for controlled material changes.

This specification succeeds `specforge-core-product-spec-0.1.0-alpha.14.md`. Alpha.14 and its normative predecessor chain remain authoritative except where extended below.

## Governance-tier floor and escalate-only completion

A `controlled_v2` change carries a requested governance tier (`LOW`, `MEDIUM`, `HIGH`). Core calculates a minimum tier from the change's declared material scope at proposal time, and refuses a transition toward `approved` if the requested tier is below that freshly-recomputed minimum.

At completion, Core recomputes the actual tier from the real material difference between the implementation's immutable `before` state and the verified integrated state (per alpha.14's integration-aware completion, never the raw pre-integration branch), classified under both the policy archived at approval time and the currently-installed policy, taking the higher of the two. Completion is refused if the effective actual tier exceeds the governed tier from the exact approved proposal. A lower actual tier than governed is permitted and unremarkable; the governed tier itself is never automatically reduced, only escalated through a new approved proposal revision.

## Preparation, before approval, as its own governed action

A `controlled_v2` proposal must be explicitly prepared before any human approves it: Core evaluates the declared scope, archives the currently-installed tier policy by canonical digest, and freezes that digest into the proposal. This is its own recorded governance action, distinct from and strictly prior to approval, with its own forensic event, since approval binds to the proposal's on-disk bytes at the moment of approval. A fresh approval is refused if the currently-installed policy has drifted since preparation, requiring re-preparation; this staleness check applies only to granting a fresh approval, never to later transitions of an already-approved proposal. A proposal identity that has ever been human-approved can never be prepared again, even if its bytes were later tampered with — the recovery from stale policy after approval is a new proposal revision, never rewriting the approved one.

## Two independent profile namespaces

A change's `governance.lifecycle_enforcement` (`controlled_v1`/`controlled_v2`) and a project's `governance_tier.enforcement_profile` (the installed tier-calculation mechanism, e.g. `deterministic_tier_v1`) are distinct namespaces, never compared directly. Core derives an effective lifecycle profile from the project's activation state: not activated implies `controlled_v1`; activated with a supported tier-enforcement profile implies `controlled_v2`; an activated project with an unrecognised tier-enforcement profile is corrupted and fails closed. A `lifecycle_enforcement` value outside the supported set is refused, never silently ungoverned.

## Provider-neutral, authorization-gated activation

`controlled_v2` becomes effective for a project only through an explicit, one-time activation, authorized by an already human-approved change whose proposal declares scope over the activation-owned paths (the project manifest and the grandfather evidence file), verified by the same approval mechanism used everywhere else, before any write occurs. Activation enumerates the project's changes that already hold a valid approval under the pre-activation profile and captures their exact proposal digests into a durable grandfather evidence file, digest-anchored in the project's own manifest since the evidence path itself is excluded from ordinary material scope. A grandfathered change completes under its original profile with no tier floor; any new revision, or any new change, is a fresh-approval target under the newly effective profile. Activation must occur, and its resulting manifest write folded into frozen implementation material, before that authorizing change's own material identity is frozen and integrated — a post-integration activation is detected as ordinary uncaptured material drift by the same immutable-material verification alpha.14 already provides, with no new enforcement code required for that specifically.

## Provider-neutral completion classification

For Git-backed projects, the real material delta between the implementation boundary and the verified integrated revision is classified using Git's own rename/copy-aware diff. For provider-neutral snapshot projects, a durable path-level manifest is persisted whenever a snapshot revision is captured, enabling the same add/modify/delete/rename/copy classification without Git. Because a snapshot manifest cannot prove content similarity, rename candidates require a vanished source path and copy candidates apply to every added path unconditionally — failing upward on the genuine ambiguity rather than assuming the more lenient interpretation, so a status-sensitive policy can never be silently under-satisfied for lack of provenance.

## Version

Core version: `0.1.0-alpha.15`.

Canonical data model: `0.1.0-alpha.5`.

Project format remains `1`.
