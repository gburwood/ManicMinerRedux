# SpecForge Core Canonical Data Model v0.1.0-alpha.4

Status: Draft

## 1. Normative Basis

This model succeeds `specforge-core-canonical-data-model-0.1.0-alpha.3.md`. Alpha.3 remains normative except where explicitly extended below.

## 2. Integration-aware implementation evidence

`IMPLEMENTATION_ATTEMPT.source_revision` continues to identify immutable implementation states:

```yaml
source_revision:
  system: git | specforge_snapshot | <supported-provider>
  before: <immutable-revision-reference>
  after: <immutable-revision-reference>
  material_effects: true
  verification_profile: immutable_material_v3
```

`before` and `after` retain implementation semantics. For a material change they MUST identify different material states, and provider-specific before-to-after lineage remains verifiable.

Alpha.4 adds optional `IMPLEMENTATION_ATTEMPT.integration` evidence. It is required for new controlled material completion under `immutable_material_v3`.

## 3. Integration evidence

Conceptual fields are:

```yaml
integration:
  profile: immutable_material_v3
  provider: git | specforge_snapshot | <supported-provider>
  target_ref: <accepted-target-ref>
  target_before: <immutable-target-revision>
  integrated_revision: <immutable-integrated-revision>
  implementation_material:
    provider: specforge_snapshot
    revision: sha256:<digest>
    file_count: <integer>
  integrated_material:
    provider: specforge_snapshot
    revision: sha256:<digest>
    file_count: <integer>
  verification:
    status: passed
    method: <deterministic-method-id>
```

The stored fields are evidence, not authority by themselves. Lifecycle and repository validation MUST recompute or independently verify applicable identities and provenance.

## 4. Canonical material identity

`implementation_material.revision` and `integrated_material.revision` use the existing SpecForge canonical material snapshot identity:

```text
sha256:<64 lowercase hexadecimal characters>
```

The digest is calculated from the canonical ordered manifest of material project-relative paths and file-content SHA-256 values.

Git commit material identity is derived by materialising the named commit and running the same project discovery/material snapshot boundary. A second path-scope or hashing definition MUST NOT be introduced.

## 5. Git integration provenance

For `provider: git`:

1. `target_before` MUST be captured from the accepted target reference before integration.
2. `integrated_revision` MUST descend from `target_before`.
3. `integrated_revision` MUST be on the accepted current project lineage when completion is evaluated.
4. Core MUST mechanically identify the target-line integration result, rather than trusting an arbitrary supplied commit.
5. The implementation and integrated material identities MUST be equal.

The reference algorithm walks the target's first-parent transition from `target_before` and selects the first target-line commit whose canonical material identity matches the implementation material.

At live completion, the Git working tree is captured against `integrated_revision` using provider-native Git diff semantics, including tracked, staged, unstaged and untracked material paths and the same governance-bookkeeping/transient exclusions as the canonical material boundary. Checkout-only normalization such as `core.autocrlf` MUST NOT be treated as material drift. Immutable commit-to-commit material identities remain byte-exact.

Normal merge, direct/fast-forward, squash and rebase topologies are therefore distinct source-control shapes behind one integration contract.

`source_revision.after` is not required to be an ancestor of `integrated_revision` for v3 squash/rebase integration. This does not relax `source_revision.before -> source_revision.after` implementation lineage.

## 6. Snapshot integration provenance

For `provider: specforge_snapshot`, direct integration is represented by the implementation `after` snapshot becoming the integrated snapshot:

```yaml
integrated_revision: sha256:<same-after-digest>
implementation_material:
  provider: specforge_snapshot
  revision: sha256:<same-after-digest>
integrated_material:
  provider: specforge_snapshot
  revision: sha256:<same-after-digest>
```

Material changes still require `before != after`, and completion requires current material to match the integrated identity.

## 7. Historical validation

Completed records governed by older material-revision profiles remain subject to those historical contracts.

For completed v3 Git evidence, the integrated commit and its canonical material identity are durable accepted-line evidence. Static validation may use the persisted implementation-material identity if the original squash/rebase source commit is no longer reachable, provided integrated evidence still verifies.

Static validation MUST NOT require current project material to equal a historical integrated state after later legitimate changes.

## 8. Accepted limitation

Canonical material identity proves content equality, not unique causal authorship. Target-line capture and first-parent discovery additionally prove that the accepted line advanced through a specific integrated state. These mechanisms do not prove that no independent process could have produced identical content.

## 9. Version

Current canonical data model: `0.1.0-alpha.4`.
