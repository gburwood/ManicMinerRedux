# SpecForge Core Canonical Data Model v0.1.0-alpha.6

## 1. Normative Basis

This model succeeds `specforge-core-canonical-data-model-0.1.0-alpha.5.md`. Alpha.5 and its normative predecessor chain remain authoritative except where extended below.

## 2. Optional material contract

A project-format-1 manifest MAY contain a `material` object. Its first defined profile is:

```yaml
material:
  mode: explicit_v1
  roots:
    - ./src
    - ./README.md
```

For `explicit_v1`, `roots` is a non-empty list of unique project-relative path declarations. A declared file or directory is project material; descendants of a declared directory inherit material classification.

Absence of `material` is semantically significant: it selects the legacy compatibility behaviour of the installed Core version. It is not equivalent to an empty explicit root set. An explicit_v1 declaration with missing or empty roots is invalid.

## 3. Material classification state

Every path considered by an explicit_v1 material operation has one of three states:

- `material`: positively covered by a valid declared material root.
- `non_material`: deterministically owned by Core as execution/runtime, governance bookkeeping, source-control/distribution/nested-project infrastructure, or a structural container required to reach classified descendants.
- `unclassified`: neither material nor non-material.

Core-owned `non_material` classification has precedence over project declarations. A material root may not be the project root, resolve outside the project, duplicate/equivalently repeat another root, redundantly overlap another material root, or encompass a deterministic Core-owned non-material root.

A structural parent directory may be `non_material` solely because it contains separately classified descendants. This classification does not propagate to arbitrary siblings: an otherwise unknown child remains `unclassified`.

## 4. Fail-closed invariant

`unclassified` is never treated as an implicit ignore and never treated as implicit material. Material snapshot capture, Git transition verification and material authorization MUST refuse an explicit_v1 state containing an unclassified project path and provide deterministic project-relative evidence.

An active governed implementation cannot authorize an unclassified path. Classification of project scope therefore precedes authorization of changes within that scope.

For Git-backed projects, current boundary validity is evaluated across the project state as well as the material delta from the trusted revision, so pre-existing tracked unknown paths cannot escape classification merely because they are unchanged in the current diff.

## 5. Shared classifier invariant

Core exposes one path-classification implementation for snapshot, source-revision and authorization consumers. Provider-specific code may obtain deltas differently, but it MUST consume the shared material/non-material/unclassified result rather than maintain an independent ignore vocabulary.

## 6. Runtime and experience separation

Runtime/execution paths may be classified `non_material` independently of an experience policy that forbids their presence in a managed project. Material identity answers whether a path contributes to governed project material; experience preflight answers whether the workflow should permit that infrastructure to exist locally. These are distinct contracts.

## 7. Version

Core version: `0.1.0-alpha.17`.

Canonical data model: `0.1.0-alpha.6`.

Project format remains `1`.
