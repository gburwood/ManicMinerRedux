# SpecForge Core Product Specification v0.1.0-alpha.5

Status: Draft

## 1. Normative Basis
This specification succeeds `specforge-core-product-spec-0.1.0-alpha.4.md`. Sections 1-80 of alpha.4 remain normative except where explicitly superseded or extended below. The alpha.4 document remains repository history and MUST NOT be rewritten to make the new architecture appear retrospective.

## 2. Product Definition
SpecForge Core remains a vendor-neutral specification, governance and traceability framework for AI-assisted development. Repository evidence is persistent project context. Conversations, agent memory and vendor-specific sessions are not authority.

## 3. Project Boundary
A project using project format 1 has one deterministic SpecForge boundary at `specforge/` beneath the governed repository root.

The required entry point is `specforge/SPECFORGE.md` and the machine-readable project manifest is `specforge/project.yaml`.

A fresh human or AI session given only repository access and the instruction to read `specforge/SPECFORGE.md` MUST be able to discover all Core authority, installed packs, product authority, non-terminal governed work, relevant decisions and lifecycle readiness without prior conversation history.

## 4. Ownership Model
Project format 1 distinguishes replaceable framework material from persistent project state.

Framework-owned material:
- `specforge/core/`
- installed framework material beneath `specforge/packs/` according to pack metadata

Project-owned governance state:
- `specforge/project.yaml`
- `specforge/changes/`
- `specforge/decisions/`
- `specforge/history/`
- `specforge/evidence/`
- governed product specifications, source and assets except where the project explicitly declares a SpecForge-Core self-hosting authority beneath `specforge/core/`

Framework upgrade MUST NOT silently replace project-owned governance state or governed product artifacts.

## 5. Independent Version Dimensions
SpecForge records at least these independent compatibility dimensions:

1. `core_version`: installed Core release.
2. `project_format`: repository architecture/serialization contract.
3. pack versions: installed extension releases.

A Core release MAY advance without a project-format migration when the installed project format remains compatible. A project-format change requires an explicit migration path.

## 6. Project Manifest
`specforge/project.yaml` identifies project format, Core version, data-model version, project identity, authoritative specification, Core/tooling paths, governance-state paths, installed packs, ownership and policy.

All repository-local paths are resolved from the governed repository root, not from the physical location of an executing tool.

## 7. Bootstrap Protocol
A compliant bootstrap performs, in order:

1. Read `specforge/SPECFORGE.md`.
2. Discover `specforge/project.yaml`.
3. Resolve project-format version and installed Core version.
4. Resolve compatible Core authority.
5. Load Core rules, schemas, workflows and tooling contract.
6. Resolve installed packs, versions, precedence and declared extensions.
7. Locate the authoritative governed-product specification and canonical data model.
8. Discover every non-terminal governed change and current proposal, approval and implementation evidence.
9. Inspect relevant decisions and forensic history.
10. Validate repository/project boundaries.
11. Evaluate lifecycle readiness.
12. Report project identity, authority, current work and permitted next actions before governed mutation.

## 8. Session Independence
Material continuation knowledge required to resume governed development MUST NOT exist solely in AI conversation history, AI memory, proprietary vendor state or another ephemeral channel.

If a session creates or materially changes governed state, enough repository evidence MUST exist for a later compliant session with no shared chat context to identify the exact current state and permitted next action.

## 9. Managed Framework Lifecycle
Core and packs are installed framework components with explicit versions and ownership metadata.

Upgrade operates automatically only within declared framework-owned boundaries unless an explicit migration step authorises a project-owned mutation.

Upgrade/migration MUST be diagnosable, version-aware and history-preserving. Unsafe or ambiguous operations fail closed without destructive mutation and return machine-readable blockers.

## 10. Project-Format Migration Contract
Migration support is declared by source project format/version and target project format/version. It MUST NOT be implemented solely as a one-off converter from the immediately previous Core release.

A supported migration MAY be direct or a deterministic chain of supported migration steps. Each step declares source, target, prerequisites, owned mutations, validation and failure behaviour.

Migration planning occurs before mutation and returns either one deterministic path or explicit blockers. Unknown, unsupported or ambiguous source formats are refused without mutation.

Where practical, migration is idempotent. Re-running migration against an already-current project returns a safe no-op/already-current result and MUST NOT duplicate or corrupt canonical state.

Stable canonical entity identities survive authorised physical relocation. Paths are storage locations, not entity identities.

## 11. Supported Initial Migrations
The alpha.5 implementation MUST support the real legacy-root alpha.4 repository and at least one additional older supported legacy layout. The implementation MUST demonstrate that migration selection is version-driven rather than a hard-coded alpha.4 case.

The first external migration proof after Core completion is Batty Joe. Its frozen failed Copilot branch is forensic evidence and MUST NOT be rewritten by the Core migration.

## 12. Canonical Governed-Artifact Representation
Integrity-sensitive governed text artifacts use canonical UTF-8 bytes with:

- optional UTF-8 BOM removed;
- CRLF and CR line endings normalised to LF;
- all other textual content preserved.

The canonicalisation contract is versioned, deterministic and testable. It MUST NOT parse and reserialise YAML merely to calculate approval integrity because that could erase formatting/comment distinctions or silently alter text semantics.

## 13. Approval Integrity
Controlled-mode approval binds to the SHA-256 digest of the canonical governed-artifact representation of the exact proposal revision.

Equivalent proposal text materialised with different supported operating-system line endings MUST produce the same digest. Any material or semantic content change MUST change the digest and invalidate prior approval for the modified revision.

## 14. Record Discovery
Project format 1 discovers canonical governance records only from declared governance roots such as changes, decisions, history and evidence. Product-specific YAML elsewhere in the repository is not treated as Core governance merely because it contains an `id` field or resides beneath a generic directory name.

Nested SpecForge projects remain independent project boundaries.

## 15. Pack Contract Extension
Installed packs declare identity, version, location, compatibility, precedence and extensions. Pack rules MUST NOT weaken Core authority, approval integrity, repository completeness or forensic traceability invariants.

## 16. Tool/API Boundary
Validator, lifecycle, status, trace, migration, future CLI/MCP/IDE integrations and AI clients consume the same project manifest and ownership contract. No client owns hidden authoritative lifecycle state.

An agent may request a lifecycle transition. SpecForge determines whether it is permitted.

## 17. Historical Compatibility
Completed CHG-1000 through CHG-1005 retain the meaning they had under their governing historical Core versions. Migration may relocate their files but MUST NOT fabricate, delete or semantically rewrite their canonical history.

Legacy-root layout support in tooling is transitional compatibility for migration and diagnostics. Project format 1 is the authoritative target architecture introduced by alpha.5.

## 18. Alpha.5 Foundational Tests
Alpha.5 tests MUST include:

- fresh-session bootstrap from `specforge/SPECFORGE.md` only;
- framework/project ownership separation;
- alpha.4 legacy-root migration;
- at least one older supported-layout migration fixture;
- chained migration planning using declared steps;
- unsupported/unknown migration refusal without mutation;
- migration idempotence/already-current behaviour;
- canonical digest equality across LF/CRLF/CR equivalents;
- digest change after material proposal edit;
- validator/lifecycle/status/trace operation through project-format manifest paths;
- product-specific generic directories not mistaken for Core governance;
- full existing regression suite after migration.

## 19. Version
Current Core product specification: `0.1.0-alpha.5`.
Current project format: `1`.
