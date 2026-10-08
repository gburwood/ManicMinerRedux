# SpecForge Core Product Specification v0.1.0-alpha.7

Status: Draft

## 1. Normative Basis
This specification succeeds `specforge-core-product-spec-0.1.0-alpha.6.md`. Alpha.6 remains normative except where explicitly superseded or extended below.

## 2. Legacy Framework Retirement
A successful migration from a supported legacy layout to project format 1 MUST retire obsolete framework-owned material from the legacy project root when ownership can be positively established for the detected source version.

Directory names alone are not sufficient proof of framework ownership. Migration definitions MUST declare the legacy framework surfaces they understand. Within a declared framework surface, a file may be retired when the target distribution contains the corresponding framework artifact or when the file is an explicitly declared legacy framework authority with a deterministic target replacement.

Unrelated project-owned files sharing directories such as `docs/`, `tests/`, `tools/` or `workflows/` MUST be preserved.

## 3. Framework Authority Rebinding
When a legacy project points at a framework-owned authority, such as a canonical data model document in the legacy root layout, migration MUST rebind that authority to the installed target Core when the target equivalent is deterministic.

Product specification authority remains project-owned and MUST NOT be rewritten by this framework cleanup rule.

## 4. Transactional Cleanup
Legacy framework retirement is part of the migration transaction. Retired artifacts MUST be recoverable if a later migration step fails. Successful migration MUST leave the project independent of both legacy root framework artifacts and candidate distribution staging.

Migration evidence SHOULD identify retired framework artifacts and project-owned legacy files preserved during cleanup.

## 5. External Acceptance
The real Batty Joe alpha.3 repository is the external acceptance case for this behaviour. After migration, Batty Joe MUST retain project identity, authoritative product specification, governance and forensic history while obsolete root SpecForge framework artifacts are absent. Mixed legacy directories containing Batty Joe-owned material MUST preserve that material.

## 6. Version
Current Core product specification: `0.1.0-alpha.7`.
Current project format: `1`.
Current canonical data model: `0.1.0-alpha.2`.
