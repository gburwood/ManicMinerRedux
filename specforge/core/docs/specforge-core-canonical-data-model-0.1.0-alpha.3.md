# SpecForge Core Canonical Data Model v0.1.0-alpha.3

Status: Draft

## 1. Normative Basis
This model succeeds `specforge-core-canonical-data-model-0.1.0-alpha.2.md`. Alpha.2 remains normative except where explicitly extended below.

## 2. Immutable Material Revision Evidence
`IMPLEMENTATION_ATTEMPT.source_revision` identifies immutable material states used as implementation evidence.

Provider-neutral conceptual fields are:

```yaml
source_revision:
  system: git | specforge_snapshot | <supported-provider>
  before: <immutable-revision-reference>
  after: <immutable-revision-reference>
  material_effects: true
```

`system` identifies provider mechanics, not governance semantics. A controlled completion requires verifiable immutable material evidence through a supported provider.

For a material implementation, `before` and `after` MUST identify different material states unless `material_effects: false` is explicitly justified by the governed change.

## 3. Git Revision Evidence
For `system: git`, `before` and `after` identify Git commit objects. When Git history is available, Core may validate object existence and required ancestry.

At completion-transition time, current material is compared with `after`. Differences confined to manifest-declared governance bookkeeping roots may remain pending. Other tracked, staged, unstaged or untracked differences are uncaptured material.

## 4. SpecForge Snapshot Evidence
For `system: specforge_snapshot`, immutable revision references use a SHA-256 content snapshot identity:

```text
sha256:<64 lowercase hexadecimal characters>
```

The digest represents a canonical manifest of material project paths and file-content SHA-256 values. Canonical path separators are `/`; entries are ordered lexically. Filesystem timestamps and directory enumeration order are not part of snapshot identity.

Snapshot scope excludes manifest-declared governance bookkeeping roots for changes, decisions, history and evidence. `specforge/project.yaml`, installed Core, installed packs, authoritative specifications and product material remain in scope.

## 5. Provider Availability and Historical Validation
Completion-transition verification is live and fail-closed: the selected provider must be available and the current material state must match the declared immutable `after` state.

Static validation is historical. It validates evidence consistency and uses provider history when available but does not require the present project material to equal an old implementation state. Exported repository copies lacking external provider metadata may retain valid historical evidence.

## 6. Governance Bookkeeping Boundary
The manifest-declared paths for changes, decisions, history and evidence are governance bookkeeping roots. Their mutation after material capture does not by itself alter the captured product/Core material revision.

This exclusion does not extend to `specforge/project.yaml`, Core, packs, authoritative product specifications or product source merely because those artifacts are SpecForge-related.

## 7. Provider Neutrality
Git and SpecForge snapshots implement the same immutable-material-revision concept. Future providers such as SVN or TFS may define equivalent immutable references and verification rules without changing lifecycle semantics.

## 8. Current State, Events and Source Control
Current canonical records describe current governed state. Forensic events preserve meaningful transitions. Revision providers preserve or identify immutable material states. These responsibilities remain separate.

## 9. Version
Current canonical data model: `0.1.0-alpha.3`.
