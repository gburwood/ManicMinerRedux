# SpecForge Core Product Specification v0.1.0-alpha.8

Status: Draft

## 1. Normative Basis
This specification succeeds `specforge-core-product-spec-0.1.0-alpha.7.md`. Alpha.7 remains normative except where explicitly superseded or extended below.

## 2. Immutable Material Revision Contract
A controlled change MUST NOT complete merely because an implementation record contains a non-empty `source_revision.after` value.

Every implementation attempt used to support controlled completion MUST identify an immutable before and after material state through a supported revision provider. The provider is an implementation detail; the policy contract is that the implemented material state is immutably identifiable and verifiable.

For a material implementation, the after state MUST differ from the before state. Unsupported, unavailable or unverifiable provider evidence MUST NOT be silently treated as passing completion evidence.

## 3. Provider Selection
An explicitly declared supported provider takes precedence.

Git MAY be inferred only when the SpecForge project root itself is the relevant Git worktree root. A project nested beneath an unrelated parent Git repository MUST NOT inherit that parent repository as its revision provider.

When no supported external revision provider applies, SpecForge MUST use its deterministic content-snapshot provider.

## 4. Git Provider
Git-backed material revisions MUST resolve to commit objects. For a material implementation, `before` and `after` MUST NOT resolve to the same commit. `before` MUST be an ancestor of `after`; when repository history is available, `after` MUST be on the current project lineage.

At transition to `completed`, SpecForge MUST verify that current project material is captured by the declared `after` commit. Tracked, staged, unstaged and untracked material differences are blockers. Governance-only bookkeeping under manifest-declared changes, decisions, history and evidence roots does not itself invalidate capture.

## 5. SpecForge Snapshot Provider
Projects without a supported external source-control provider MUST remain fully governable.

The SpecForge snapshot provider MUST calculate a deterministic cryptographic digest from a canonical manifest of material project paths and file-content digests. Path representation and ordering MUST be canonical. Filesystem timestamps, directory enumeration order and platform-specific path separators MUST NOT affect the resulting snapshot identity.

Material includes product source and assets, authoritative product specifications, `specforge/project.yaml`, installed Core and packs and other project-owned material. Only manifest-declared governance bookkeeping roots and explicitly defined transient/non-material artifacts may be excluded.

The snapshot provider MUST NOT inherit Git ignore semantics merely because Git is installed or an unrelated parent directory is a Git repository.

At transition to `completed`, the current material snapshot MUST equal the declared immutable `after` snapshot.

## 6. Static Validation
Static repository validation MUST validate the structure and consistency of immutable revision evidence without requiring today's project tree to equal a historical implementation state.

When the relevant external provider and history are available, static validation SHOULD verify object existence and lineage. Absence of provider history in an exported or disposable repository copy does not invalidate otherwise structurally valid historical evidence. Obviously contradictory evidence, such as equal before/after immutable revisions for a material implementation, remains invalid.

Historical records from earlier Core revisions are not rewritten solely to adopt alpha.8 provider metadata.

## 7. Material Revision Tooling
Core provides revision tooling to capture the current immutable material state. Git-backed projects capture the current commit only when project material is represented by that commit. Unmanaged projects capture a deterministic SpecForge content snapshot.

Lifecycle policy consumes provider-neutral verification results; provider-specific mechanics remain behind the material revision boundary.

## 8. Version
Current Core product specification: `0.1.0-alpha.8`.
Current project format: `1`.
Current canonical data model: `0.1.0-alpha.3`.
