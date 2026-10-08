# SpecForge Core Product Specification 0.1.0-alpha.17

Alpha.17 introduces an explicit, fail-closed definition of project material. It replaces the long-term assumption that project material can be defined safely as "everything except an ever-growing ignore list" while preserving that historical behaviour for projects that have not yet opted into the new contract.

This specification succeeds `specforge-core-product-spec-0.1.0-alpha.16.md`. Alpha.16 and its normative predecessor chain remain authoritative except where extended below.

## Explicit project-material boundary

Project-format-1 manifests may declare:

```yaml
material:
  mode: explicit_v1
  roots:
    - ./src
    - ./docs
    - ./README.md
```

When `material.mode` is `explicit_v1`, `material.roots` is the positive declaration of governed project material. A declared file is material. A declared directory and all of its descendants are material. This permits ordinary growth inside a governed source tree without requiring a manifest edit for every new file.

The project root itself may not be declared as a material root. Material roots must resolve inside the project and must not be duplicate/equivalent, redundantly overlap one another, or encompass deterministic Core-owned non-material infrastructure.

A project-format-1 manifest with no `material` section remains in legacy compatibility mode for this release. Installing alpha.17 alone therefore does not change an existing project's material identity or force a migration.

## Core-owned non-material infrastructure

Core, rather than each project, owns deterministic infrastructure classifications. Governance bookkeeping beneath the configured changes, decisions, history and evidence roots is non-material. Git metadata, distribution/nested-project boundaries and standard execution/runtime trees are also non-material.

The runtime classification currently includes `.specforge-runtime`, `.venv`, `venv`, `node_modules`, `__pycache__` and `.pytest_cache`, together with existing transient file rules. These names remain useful for legacy compatibility, but explicit_v1 correctness does not depend on predicting every possible future runtime directory: anything not positively declared material and not deterministically non-material is unclassified and fails closed.

Core-owned non-material classification takes precedence over project material declarations. A project cannot make governance bookkeeping or other deterministic infrastructure material by placing a broader root around it.

Structural directories that merely contain declared material and/or deterministic non-material descendants are containers, not material themselves. This allows a layout such as `specforge/core` (material) beside `specforge/history` (non-material) without forcing the whole `specforge` directory into either category. An unrelated new sibling beneath that container remains unclassified.

## Fail-closed unclassified state

The shared classifier has exactly three outcomes: `material`, `non_material` and `unclassified`.

An explicit_v1 project containing a path that is neither beneath a declared material root nor recognised by Core as non-material is invalid for material capture/transition purposes. Snapshot capture refuses with `unclassified_project_paths_present`. Git-backed transition verification and material authorization do the same and provide deterministic project-relative path evidence.

An active implementation does not authorize an unclassified path. The project must first make a deliberate classification decision. This prevents an implementation from silently expanding its own governed boundary simply by creating a new top-level directory.

Git-backed verification checks the current explicit boundary as a whole, not only changed or untracked paths. Consequently an already-tracked unknown path is still detected after explicit_v1 is enabled.

## One shared classifier

`specforge_project.py` is the single material-classification authority used by material snapshots, source-revision verification and material authorization. `specforge_authority.py` no longer carries a separate hard-coded material-ignore algorithm.

Snapshot and Git providers therefore answer the same conceptual question: which project paths are governed material, which are infrastructure, and which require an explicit decision before work can be accepted.

## Experience policy remains separate

Candidate A's experience preflight may still report that a project-local runtime is undesirable and direct the agent to use execution tooling outside the project. That is an experience/policy rule, not a material-identity rule. A runtime path can be mechanically non-material while its presence is independently prohibited by the managed-workflow experience policy.

## Version

Core version: `0.1.0-alpha.17`.

Canonical data model: `0.1.0-alpha.6`.

Project format remains `1`.
