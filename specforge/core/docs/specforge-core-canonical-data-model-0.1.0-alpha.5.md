# SpecForge Core Canonical Data Model v0.1.0-alpha.5

## 1. Normative Basis

This model succeeds `specforge-core-canonical-data-model-0.1.0-alpha.4.md`. Alpha.4 and its normative predecessor chain remain authoritative except where extended below.

## 2. Governance tier

`LOW < MEDIUM < HIGH`, three ranks, no additional tiers. A `controlled_v2` proposal carries `governance_tier.requested` (one of the three), `governance_tier.policy_digest` (the canonical digest of the tier policy archived at preparation time), and non-authoritative `governance_tier.calculated_minimum` (evidence only, never itself a gating input — the governing minimum is always recomputed fresh from `declared_scope` against the digest-verified archived policy at the moment of a fresh-approval decision).

## 3. Declared scope

A proposal's `declared_scope` is a list of entries, each an `operation` from the closed set `add`, `modify`, `delete`, `rename`, `copy`, mirroring the Git status taxonomy (`A`/`M`/`D`/`R`/`C`) the classifier itself understands. `rename` and `copy` entries carry both `from` and `to` paths. A missing, empty, or malformed entry fails preparation closed; it is never treated as an empty scope defaulting to a permissive tier.

## 4. Tier-policy classification

A policy file declares tier ranks, a default `unmatched_tier`, and a list of rules, each an `id`, a `tier`, a list of path globs, and an optional list of restricting Git-status letters. For a material entry, the highest-ranked matching rule across the whole policy wins; an entry matched by no rule defaults to the policy's `unmatched_tier`; a policy load or evaluation failure blocks the transition rather than silently selecting a tier. Classification never depends on a change identifier, project name, or narrative judgement — only declared or actual material paths and statuses matched against general rules.

## 5. Policy archiving and dual-policy completion

Preparation archives the currently-installed policy's exact content, digest-addressed, under a project-owned evidence path excluded from ordinary material scope. Every use of an archived policy recomputes its digest from actual content and requires it to match both the archive's filename and the digest recorded on the proposal; a mismatch or missing archive fails closed. At completion, the real material difference is classified under both the archived approval-time policy and the currently-installed policy; the effective actual tier is the higher of the two, so a later, weaker policy amendment can never suppress an escalation the approval-time policy would have required.

## 6. Grandfather integrity anchor

A project's activation state lives in two project-owned locations that must agree: `governance_tier.enforcement_profile` and `governance_tier.grandfather_digest` in the project manifest, and a grandfather evidence file (excluded from ordinary material scope) whose recomputed canonical digest must equal that anchor. Three states: not activated (both manifest fields absent), active (both present and the anchor verifies), or corrupted (any other combination, including an unrecognised enforcement profile) — corrupted is never conflated with not-activated, since that would let deleting or corrupting the evidence file silently disable enforcement.

## 7. Provider-neutral material delta

For Git, the real diff between an implementation's immutable `before` state and the verified integrated revision uses Git's own rename/copy-aware `--name-status` diff. For a snapshot-provider project, a durable path/digest manifest is persisted at revision-capture time; completion recovers the manifests for both endpoints and derives add/modify/delete entries by comparison. Because content-digest equality is the only signal available, rename candidates require a vanished source path (structurally necessary for a rename); copy candidates apply to every added path unconditionally, since a copy does not require its source to vanish and no digest-only comparison can rule that out for any added file — an accepted, deliberate asymmetry favoring fail-upward correctness over precision.

## 8. Historical validation

Repository validation independently reconstructs, from durable records alone, the parts of the controlled_v2 approval contract that are statically reconstructable: exact human approval, a present and valid `policy_digest`, a present and structurally valid `declared_scope`, a matching archived policy, and `requested_tier` at or above the floor recomputed fresh from that archived policy — for every non-grandfathered `controlled_v2` change from `approved` through `completed`, catching a direct file edit that bypasses the lifecycle tool entirely. This static reconstruction deliberately does not re-run the current-policy staleness check, since policy drift after a valid approval is expected and handled by dual-policy completion, not by retroactively invalidating history.

## 9. Accepted limitation

The grandfather integrity anchor and policy-archive digest checks detect accidental drift, interrupted operations, and single-file tampering; they do not detect a coordinated edit of multiple related files made consistently with each other by an actor who already holds unrestricted repository write access — the same boundary every other digest-binding safeguard in Core already rests on. Snapshot-provider copy detection cannot distinguish a genuine copy from an unrelated new file sharing no content history; this is an information-theoretic limit of path+hash manifests, not a defect, and is resolved by failing upward rather than guessing.

## 10. Version

Core version: `0.1.0-alpha.15`.

Canonical data model: `0.1.0-alpha.5`.

Project format remains `1`.
