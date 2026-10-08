# SpecForge Core Product Specification v0.1.0-alpha.4

Status: Draft  

## 1. Product Definition
SpecForge Core is a vendor-neutral specification, governance and traceability framework for AI-assisted software development. The repository is persistent project context; conversations and AI sessions are temporary work sessions. AI providers are interchangeable execution engines around a repository-owned engineering system.

## 2. Problem Statement
AI-assisted development is often trapped in temporary conversational context. Requests arrive from multiple sources, may be ambiguous or contradictory, and ordinary source control records changed bytes without reliably recording request provenance, interpretation, approval, product intent, implementation attempts, validation, or release rationale.

## 3. Foundational Principles
1. Repository as Persistent Context.
2. Specification as Product Intent.
3. Repository Completeness: everything required to continue correctly must exist in the repository or stable repository references.
4. Forensic Traceability: the repository must preserve enough evidence to reconstruct how and why the current state arose.
5. Human Product Authority: AI may analyse and propose but may not silently invent material product behaviour.
6. Vendor Neutrality: no AI vendor is part of the Core contract.

## 4. Canonical Development Pipeline
REQUEST SOURCE -> INTAKE -> NORMALISATION -> CANONICAL CHANGE -> CLASSIFICATION -> CLARIFICATION (when required) -> IMPACT ANALYSIS -> PROPOSAL -> APPROVAL (when required) -> AUTHORITATIVE SPECIFICATION -> IMPLEMENTATION -> VALIDATION -> TESTING -> SOURCE REVISION -> BUILD -> RELEASE -> ENVIRONMENT / DISTRIBUTION.

## 5. Product Objectives
Core shall support repository discovery, session independence, multi-AI and multi-developer handover, multi-source intake, canonical changes, ambiguity handling, specification authority, impact analysis, approval, independent specification/release versioning, traceability, reproducibility, historical reconstruction, emergency workflow, domain packs, generic environments and repository-complete handover.

## 6. Non-Objectives for Core v0.1
Core is not an AI model, IDE, source-control system, project manager, email client, spreadsheet application, issue tracker, SaaS product, GUI, autonomous production operator, CI/CD replacement, domain-knowledge package, mandatory branching model, provider-specific ingestion system, or fully autonomous release authority. Semantic conflict detection and rich provider integrations are deferred.

## 7. Layered Architecture
1. Core: universal schemas, rules, workflows and validation.
2. Domain Packs: specialist vocabulary and domain rules.
3. Integration / Intake Adapters: external request-source translation.
4. Tooling: validators, editors, trace tools and future Studio capabilities.

## 8. Repository Contract
Every SpecForge project requires `SPECFORGE.md` as the human/AI entry point and `specforge.yaml` as the machine-readable manifest.

## 9. Bootstrap Protocol
A fresh session reads `SPECFORGE.md`, loads `specforge.yaml`, resolves the authoritative specification and data model, reads applicable rules/workflows, inspects open changes, decisions and recent forensic history, then acts only within current authority.

## 10. Project Manifest
The manifest identifies Core/data-model versions, project identity, authoritative specification, repository paths, domain packs and policy. Paths are repository-relative and must be valid or explicitly external stable references.

## 11. Request Sources
Requests may originate from conversation, email, spreadsheet, CSV, document, issue tracker, support ticket, form, API, telemetry, monitoring, manual entry or other adapters.

## 12. Intake
Intake preserves source provenance before interpretation. Source evidence must remain distinguishable from the canonical change produced from it.

## 13. Normalisation
Normalisation may infer structure, classification and obvious mappings. It must not invent material product behaviour. Ambiguity that could affect behaviour enters clarification.

## 14. Canonical Change Record
Material work is represented by a stable change identity containing request interpretation, classification, lifecycle status, provenance, relationships, impact analysis, proposal, approval, implementation, requirement and release links.

## 15. Change Provenance
A change retains references to its originating source or sources sufficient to explain what initiated it.

## 16. Change Record History
Completed historical meaning is not silently rewritten. Corrections are appended through revisions, correction records or forensic events.

## 17. Change Status
Lifecycle state is explicit and machine-readable. Terminal historical states remain queryable.

## 18. Change Classification
Core supports generic classifications such as feature, defect, specification defect, refactor, tooling/infrastructure, documentation, security, operational and emergency change, with project/domain extension permitted.

## 19. Clarification
When material ambiguity exists, implementation must not proceed until the ambiguity is resolved by authorised input or explicit project policy.

## 20. Requirements
Requirements have stable identities and lifecycle states. They express authoritative product intent and may be introduced or changed through approved changes.

## 21. Requirement History
Historical requirements never disappear. Lifecycle includes proposed, active, deprecated, superseded and withdrawn. Supersession links preserve navigability.

## 22. Acceptance Criteria
Acceptance criteria have stable identities, may be embedded for authoring convenience, and remain independently referenceable. Given/When/Then is the preferred Core representation.

## 23. Impact Analysis
Before material implementation, SpecForge records affected requirements, components, artifacts, tests, compatibility, migration, risks and overlapping changes as applicable.

## 24. Change Relationships
Changes may depend on, conflict with, relate to, supersede, parent or contain child changes. One change may affect several requirements.

## 25. Proposal Revisions
A proposal is the exact proposed interpretation and scope of a change. Material modification creates a new proposal revision rather than silently altering an approved revision.

## 26. Approval
Approval is attributable, timestamped, mechanism-neutral and scoped to one immutable proposal revision. Evidence is retained where available. Material proposal changes invalidate prior approval for implementation.

## 27. Approval Policy
Core supports Controlled, Trusted and Advisory modes. Controlled is the default. Controlled mode requires approval before implementation of material proposals.

## 28. Source of Truth
The approved authoritative specification wins when request sources disagree. Conflict triggers clarification/change workflow rather than silent reconciliation.

## 29. Specification / Implementation Discrepancy
If specification and code disagree, SpecForge raises a discrepancy. It must not silently delete code behaviour or alter the specification merely to legitimise existing code.

## 30. Specification Versioning
Specification versions represent product intent and use semantic versioning conventions appropriate to intent change. They are not build numbers.

## 31. Specification / Release Independence
Multiple software releases may implement the same specification version. Specification and software-release versions are independent identities.

## 32. Implementation Attempts
Meaningful implementation attempts, including meaningful failures, are preserved. Core does not require retention of every transient generated byte.

## 33. AI Requirement Authority
AI may propose requirements. Creation or modification of authoritative requirements follows the project's approval policy.

## 34. AI Architectural Authority
AI may make minor implementation decisions within approved intent. Significant architectural decisions require authorised approval or explicit policy and become decision records.

## 35. Decision Records
Significant architectural/product engineering decisions use stable ADR identities and preserve context, decision, rationale, status and relationships.

## 36. Artifact Management
Changes identify expected and affected artifacts. Generated artifacts do not supersede authoritative specification unless policy explicitly says so.

## 37. Artifact Ownership
Core distinguishes authoritative, generated, derived and evidential artifacts so generated output cannot quietly become product authority.

## 38. Testing Traceability
Tests should link to requirements, acceptance criteria, changes or implementation attempts where meaningful. Passing tests do not themselves authorise product behaviour.

## 39. Validation
Validation checks structural/schema correctness, referential integrity, policy conformance and other machine-checkable repository invariants.

## 40. Development Run-Book
The repository must permit reconstruction of the meaningful sequence from request through interpretation, approval, implementation, validation and delivery.

## 41. Historical State Reconstruction
Meaningful historical project states should be reconstructable conceptually. Core v0.1 may use Git plus SpecForge records/events rather than storing full snapshots.

## 42. Source-Control Strategy
Core does not prescribe Git branching strategy. Projects, organisations or domain packs may.

## 43. Release
A release is a declared software version linked to the implemented changes, specification version, build/source evidence and deployments where applicable.

## 44. Release Reproducibility
Released versions should be reproducible from repository evidence where technically possible.

## 45. Change Consolidation
Related requests may be consolidated when provenance and individual intent remain traceable.

## 46. Changes Across Releases
If delivery of one requested outcome spans several releases, the normal model is parent/child changes so each delivered unit has clear completion and release evidence.

## 47. Batch Intake
Core supports normalising multiple incoming requests while preserving each source's provenance and avoiding silent loss or merging of contradictory intent.

## 48. Automated Development
Automation may execute approved workflow steps subject to policy. Automation does not remove authority boundaries or forensic obligations.

## 49. Emergency Change Workflow
Emergency fixes may abbreviate pre-work but require retrospective reconciliation of specification, tests, change rationale and approval.

## 50. Workflow Override
Humans may deliberately bypass normal workflow where policy allows, but the override, actor, reason, scope and consequences must be visible and forensic.

## 51. Environments
Core understands generic environments and promotion/deployment relationships without prescribing DEV/UAT/PROD or another topology.

## 52. Environment Traceability
Where deployments are tracked, a user should be able to determine what release/build/source revision reached an environment and when.

## 53. Session Independence
No AI session is authoritative memory. A fresh authorised session must be able to resume from repository state.

## 54. Multi-Developer Operation
Different humans and AI vendors may work against the same repository contract. Git/source control is the handover mechanism; SpecForge records preserve engineering meaning.

## 55. Authority Hierarchy
Approved authoritative specification outranks conflicting request sources. Approved proposal scope governs implementation. Project policy governs permitted autonomy. Generated implementation cannot silently redefine intent.

## 56. Forensic Event Model
Meaningful lifecycle transitions are append-oriented forensic events. Events identify actor, timestamp, event type, primary entity, related entities and relevant before/after state.

## 57. Actor Model
Actors may be human, AI, automated_system, external_system or unknown. Identity should be as specific as available without fabricating unavailable personal data.

## 58. Trivial Change Policy
Not every textual code edit requires a canonical change. Projects may exempt non-material formatting, spelling or equivalent edits. Material behaviour, defects, significant refactors, infrastructure and releases remain traceable.

## 59. Domain Pack Contract
Domain packs extend Core vocabulary, schemas, rules, workflows and tools under explicit namespaces without weakening Core authority and traceability invariants.

## 60. Intake Adapter Contract
Adapters translate external sources into intake/canonical structures while preserving provenance. Provider-specific mechanics remain outside Core.

## 61. Core v0.1 Deliverables
Core v0.1 targets bootstrap instructions, manifest, complete normative documentation, JSON Schemas, source-of-truth rules, repository-completeness rules, forensic-traceability rules, versioning rules, amend-specification workflow, implementation workflow, defect workflow, emergency workflow, validator, validator tests, examples, canonical change/requirement/approval/decision/implementation/release/event schemas, and executable bootstrap/trace/status tooling as the alpha evolves.

## 62. Proof of Concept A: Session Independence
A fresh AI session given only the repository and bootstrap instruction can identify the project, authority, current state and permitted next action.

## 63. Proof of Concept B: Batch Intake
Multiple requests can be ingested and normalised without losing provenance or silently reconciling contradictions.

## 64. Proof of Concept C: Defect
A defect can be traced from report through impact, approved resolution, implementation and validation.

## 65. Proof of Concept D: Ambiguity
Material ambiguity blocks implementation until clarified or explicitly authorised.

## 66. Proof of Concept E: Forensic Reconstruction
The repository can answer why behaviour exists, who approved it, what was tried, what passed, and what source/release delivered it.

## 67. Proof of Concept F: Historical Requirement
Deprecated/superseded requirements remain traversable and explain prior behaviour.

## 68. Proof of Concept G: Emergency Change
An emergency fix can proceed under abbreviated policy and later be reconciled without erasing the exceptional path.

## 69. Initial Success Criteria
A project is successful when a fresh session can bootstrap without conversation history; material work follows explicit authority; canonical references validate; meaningful failures remain visible; source/release evidence is traversable; and the repository can explain current behaviour and prior decisions.

## 70. Foundational Product Tests
Core tests should cover bootstrap completeness, schema validity, referential integrity, nested-project isolation, proposal/approval binding, discrepancy visibility, immutable/revisioned history, failed-attempt preservation, trace reconstruction and emergency reconciliation.

## 71. Deferred Capabilities
Semantic conflict detection, rich GUI/Studio, provider-specific adapters, autonomous orchestration, advanced CI/CD integrations and domain-specific editors are deferred until Core contracts are stable.

## 72. Accepted Architectural Decisions
AD-001 Completed change history is not silently rewritten.  
AD-002 Specification versions represent product intent, not builds.  
AD-003 Multiple releases may implement the same specification version.  
AD-004 Approval applies to a specific proposal revision and is attributable and traceable.  
AD-005 Requirement history is explicitly preserved beyond Git history.  
AD-006 AI may infer structure/classification, not material behaviour.  
AD-007 Human workflow override is permitted but forensically recorded.  
AD-008 Trivial non-material edits may be exempt from canonical change records.  
AD-009 A change may affect multiple requirements but normally completes in one release; multi-release delivery normally uses child changes.  
AD-010 Approved authoritative specification prevails where sources disagree.  
AD-011 Core does not prescribe a Git branching strategy.  
AD-012 Releases should be reproducible where technically possible.  
AD-013 Meaningful historical development states should be reconstructable.  
AD-014 Meaningful failed attempts are preserved without retaining every transient byte.  
AD-015 AI may propose requirements; authority depends on approval policy.  
AD-016 Significant architecture decisions require authority or explicit policy.  
AD-017 Spec/code disagreement creates a discrepancy requiring resolution.  
AD-018 Historical requirements do not disappear.  
AD-019 Emergency changes require retrospective reconciliation.  
AD-020 Core understands generic environments without prescribing topology.

## 73. Version
Current Core product specification: `0.1.0-alpha.4`.


## 74. Executable Lifecycle Authority
In Controlled mode, lifecycle advancement is a requested operation rather than an agent-owned state mutation. An agent, human-facing integration, or automation may request a transition; SpecForge evaluates the configured prerequisites and determines whether it is permitted. Refusal does not mutate authoritative lifecycle state.

## 75. Approval Integrity Gate
A material Controlled-mode transition requiring approval must resolve an approved human-authorised approval record for the current exact proposal revision. The approval binds to a deterministic SHA-256 digest of that proposal revision. Changed proposal content invalidates the approval for advancement. AI-authored assertions that a human approved work are not authority unless backed by a valid approval record/evidence permitted by project policy.

## 76. Validation and Test Gate
Completion requires structurally valid canonical records, resolvable required references, and configured change-specific validation and test evidence. Required checks have explicit `passed`, `failed`, or `blocked`/`unavailable` outcomes. A blocked, unavailable, missing, or failed mandatory check cannot satisfy a passing gate.

## 77. Source Revision Gate
Completion of governed implementation requires immutable source-revision evidence where source control is applicable. A passed implementation attempt without its required resulting revision is not sufficient evidence for completion.

## 78. Bootstrap Readiness
Core tooling provides an executable bootstrap-readiness check. It verifies discovery of the manifest, authoritative specification and data model, applicable rules/workflows, project boundary and current lifecycle evidence before governed mutation. A readiness failure is an explicit blocker, not an inferred success.

## 79. Prospective Enforcement
Lifecycle gates introduced in alpha.4 apply prospectively to changes opting into or created under the strengthened enforcement contract. Earlier completed history is not silently rewritten or automatically invalidated; deficiencies may be reported diagnostically.

## 80. Tool/API Boundary
Lifecycle enforcement belongs to reusable Core tooling rather than an IDE or AI-vendor integration. IDE, MCP, CLI and agent clients request operations through the same governance contract.
