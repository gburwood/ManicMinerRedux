# SpecForge Core Canonical Data Model v0.1.0-alpha.2

Status: Draft

## 1. Normative Basis
This model succeeds `specforge-core-canonical-data-model-0.1.0-alpha.1.md`. The canonical entity identities and relationships defined in alpha.1 remain normative except where this document explicitly extends repository location, project discovery or integrity semantics.

## 2. Identity Is Independent of Path
Canonical IDs such as `CHG-1006`, `PROP-1006-02`, `APR-1007`, `IMP-1006-01` and `EVT-100051` identify entities. Repository paths are storage locations and MAY change during an authorised project-format migration without changing entity identity or historical relationships.

## 3. PROJECT / Manifest
Project format 1 uses `specforge/project.yaml` as the machine-readable project manifest.

Required top-level concepts:

```yaml
specforge:
  project_format: 1
  core_version: 0.1.0-alpha.5
  data_model_version: 0.1.0-alpha.2
project:
  id: PRJ-0001
  name: Example
specification:
  product_specification: ./path
  canonical_data_model: ./path
  current_version: 0.1.0-alpha.5
paths:
  core: ./specforge/core
  packs: ./specforge/packs
  changes: ./specforge/changes
  decisions: ./specforge/decisions
  history: ./specforge/history
  evidence: ./specforge/evidence
ownership:
  framework_owned: []
  project_owned: []
packs: []
policy: {}
```

Repository-local paths resolve from the governed repository root.

## 4. Version Dimensions
`core_version`, `project_format`, `data_model_version` and installed pack versions are independent identifiers. Compatibility is explicit rather than inferred from lexical version ordering.

## 5. Governance Record Roots
For project format 1, canonical governance records are discovered from manifest-declared governance roots. Core defaults are:

- `specforge/changes/`
- `specforge/decisions/`
- `specforge/history/`
- `specforge/evidence/`

Product YAML outside those roots is not a canonical governance record merely because it contains an `id` property.

## 6. Framework Ownership
Framework-owned artifacts are replaceable by a compatible managed Core/pack upgrade according to manifest ownership metadata. Project-owned records are persistent and may be changed by framework lifecycle operations only through an explicit migration step whose permitted mutations are declared.

## 7. Migration Records
A migration step has a stable step identity and declares at minimum:

```yaml
id: MIG-example
source:
  project_format: 1
target:
  project_format: 2
handler: implementation_key
```

Legacy formats that predate explicit `project_format` MAY be identified by a deterministic tuple such as layout plus Core version.

Migration planning resolves a deterministic path through declared steps before mutation. Unknown, unsupported or ambiguous paths are blockers.

## 8. Canonical Governed-Artifact Bytes
For integrity digests of governed text artifacts, canonical bytes are UTF-8 after removal of an optional UTF-8 BOM and normalisation of CRLF/CR line endings to LF. No YAML parse/reserialise step is part of canonical integrity calculation.

`SHA-256(canonical_bytes(proposal_revision))` is the approval-integrity identity used by Controlled-mode exact proposal approval.

## 9. Compatibility With Historical Approval Evidence
Historical approval digests produced from LF repository bytes remain valid because LF input is unchanged by canonicalisation. A Windows working tree containing CRLF materialisation of the same proposal yields the same canonical digest.

## 10. Current State, Events and Git
The alpha.1 model remains unchanged: current canonical records describe current governed state, forensic events preserve meaningful transitions and Git/source control preserves immutable byte revisions. Project format 1 does not introduce a duplicate mutable state database.

## 11. Nested Projects
A descendant repository subtree containing `specforge/project.yaml` or legacy `specforge.yaml` is an independent SpecForge project boundary and is excluded from the parent project's canonical-record discovery.

## 12. Repository-Only Continuation
A canonical change that is not terminal MUST expose enough repository evidence to identify its current impact analysis, proposal, approvals, implementation attempts and lifecycle state. Material continuation authority may not depend on prior AI conversation or memory.

## 13. Version
Current canonical data model: `0.1.0-alpha.2`.
