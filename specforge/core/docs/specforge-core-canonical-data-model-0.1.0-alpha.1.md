# SpecForge Core Canonical Data Model v0.1.0-alpha.1

Compatible with SpecForge Core v0.1.0-alpha.4.  

## 1. Purpose
This model defines the canonical machine-readable entities and relationships required to represent SpecForge projects, product intent, requests, changes, approvals, implementation, validation, delivery and forensic history.

## 2. Model Principles
Stable identity; explicit relationships; append-oriented history; human and AI readability; repository portability; extensibility; no fabrication of unknown data.

## 3. Serialization
YAML is the default authoring representation. JSON Schema is the normative machine-validation mechanism. Timestamps use ISO 8601. Enumerations use `snake_case`. Canonical IDs use uppercase prefixes.

## 4. Canonical Entity Types
PROJECT, SPECIFICATION, REQUIREMENT, ACCEPTANCE_CRITERION, REQUEST_SOURCE, CHANGE, PROPOSAL, IMPACT_ANALYSIS, APPROVAL, DECISION, IMPLEMENTATION_ATTEMPT, TEST, VALIDATION, SOURCE_REVISION, BUILD, RELEASE, ENVIRONMENT, DEPLOYMENT, FORENSIC_EVENT.

## 5. Identifier Conventions
`PRJ-####`, `REQ-####`, `AC-####-##`, `CHG-####`, `PROP-####-##`, `IA-####-##`, `APR-####`, `ADR-####`, `IMP-####-##`, `TEST-####`, `VAL-####`, `BLD-####`, `REL-####`, `ENV-####`, `DEP-####`, `EVT-######`.

Identifiers are stable references. Renaming files must not silently change entity identity.

## 6. Actor
Actor types: `human`, `ai`, `automated_system`, `external_system`, `unknown`. Actor records should identify the actor as specifically as available without inventing unavailable identity.

## 7. PROJECT / Manifest
`specforge.yaml` identifies Core version, data-model version, project identity, authoritative specification location/version, repository paths, active domain packs and project policy. The manifest is discovery metadata, not a substitute for product specification.

## 8. SPECIFICATION
A specification version identifies an authoritative product-intent state. Specification identity/version is independent of build and release identity.

## 9. REQUIREMENT
A requirement has a stable `REQ` ID, title/statement, lifecycle status, provenance/change links and acceptance-criterion links. Lifecycle: `proposed`, `active`, `deprecated`, `superseded`, `withdrawn`.

## 10. ACCEPTANCE_CRITERION
Acceptance criteria have mandatory independent `AC` IDs even when embedded in requirement authoring. Preferred behavioural structure is Given/When/Then. Criteria may link to verification tests.

## 11. REQUEST_SOURCE
Request sources preserve origin and provenance. Generic source types include conversation, email, spreadsheet, csv, document, issue_tracker, support_ticket, form, api, telemetry, monitoring, manual and other.

## 12. CHANGE
A change contains stable ID, title, classification, status, priority, sources, normalised request, clarification state, relationships, current impact analysis, current proposal, approvals, implementation attempts, affected requirements, release completion and metadata.

## 13. Change Classification
Core classifications include feature, defect, specification_defect, refactor, tooling_infrastructure, documentation, security, operational and emergency, with controlled extension allowed.

## 14. Change Status
Status is explicit and lifecycle-aware. Implementations may extend the exact enumeration, but must distinguish proposed/approval states, active implementation/validation states, terminal completion and cancellation/rejection where applicable.

## 15. Clarification
Clarification records whether clarification is required, questions raised, authoritative answers and resolution evidence. Material ambiguity must remain visible.

## 16. IMPACT_ANALYSIS
An `IA` record belongs to one change/revision and records affected requirements, components, artifacts and tests plus compatibility, migration, risks, overlaps and summary.

## 17. PROPOSAL
A `PROP` record belongs to one change and numbered revision. It states proposed specification version, requirement/acceptance-criterion changes, behaviour summary, expected artifacts, constraints and approvals. Approved proposal meaning is immutable; material change creates a new revision.

## 18. APPROVAL
An `APR` record binds a decision to one exact proposal revision. It records change, proposal, decision, actor, timestamp, scope, mechanism/evidence and optional comment. Approval is invalid for materially modified proposal content.

## 19. DECISION
An `ADR` record captures significant architectural/engineering decisions, including context, decision, rationale, status and relationships.

## 20. IMPLEMENTATION_ATTEMPT
An `IMP` record belongs to a change and proposal, has an attempt number, actor/time, approach, source revision before/after, outcome, test/validation evidence and notes. Meaningful failed attempts remain historical evidence.

## 21. TEST
A `TEST` record, where canonicalised, identifies verification purpose and links to requirements, acceptance criteria, changes or attempts. Core may also reference executable tests without requiring every test to be a canonical entity in early alpha.

## 22. VALIDATION
A `VAL` record, where canonicalised, records validation scope, result, checks, actor/system, timestamp and related change/attempt/source evidence.

## 23. SOURCE_REVISION
A source revision reference identifies the exact source-control state, normally a full immutable commit identifier where available. Git history complements explicit SpecForge records.

## 24. BUILD
A `BLD` record identifies produced build/version, source revision, specification version, changes and reproducibility evidence.

## 25. RELEASE
A `REL` record identifies declared software release, specification version, included changes, build/source evidence, release time/status and deployment links.

## 26. ENVIRONMENT
An `ENV` record identifies a generic deployment target/environment without Core prescribing topology names.

## 27. DEPLOYMENT
A `DEP` record links release/build to environment and records deployment time/status and evidence.

## 28. Emergency Change
Emergency records identify the exceptional workflow and required retrospective reconciliation. Emergency status does not erase normal traceability obligations.

## 29. Workflow Override
Override evidence records actor, reason, scope, time and the workflow/policy step bypassed.

## 30. FORENSIC_EVENT
An `EVT` record is append-oriented and contains stable event ID, ISO timestamp, actor, event type, primary entity, related entities and optional previous/resulting state. Corrections append new evidence rather than rewriting historical meaning.

## 31. Event Types
Core event vocabulary includes creation, proposal/revision, approval/rejection, implementation start/result, validation/test result, source revision, build, release, deployment, clarification, override, correction, cancellation and completion events, with controlled extension permitted.

## 32. Entity Relationships
Canonical relationships support forward and backward traversal:
REQUEST_SOURCE -> CHANGE -> IMPACT_ANALYSIS -> PROPOSAL -> APPROVAL -> SPECIFICATION -> REQUIREMENT -> ACCEPTANCE_CRITERION -> TEST -> IMPLEMENTATION_ATTEMPT -> SOURCE_REVISION -> BUILD -> RELEASE -> DEPLOYMENT -> ENVIRONMENT.
FORENSIC_EVENT links across the lifecycle rather than replacing current entity state.

## 33. Parent / Child Changes
Changes may parent child changes. Multi-release delivery should normally split into child changes so completion/release relationships remain unambiguous.

## 34. Domain Extensions
Domain-specific data belongs beneath explicit `extensions` namespaces or domain-pack schemas. Core identifiers/relationships remain valid independently of domain packs.

## 35. Unknown and Optional Data
Unknown information is omitted, null where schema permits, or explicitly marked unknown. AI/tools must not fabricate values merely to satisfy a schema.

## 36. File Naming and Layout
Canonical records should use their stable IDs as filenames where practical. Typical locations include `spec/requirements`, `changes`, `decisions`, `history/events`, `releases/builds`, `releases/environments` and `releases/deployments`. The manifest is the discovery authority for actual project paths.

## 37. Current State + Event History + Git History
SpecForge intentionally uses three complementary views:
1. Current entity state for efficient discovery.
2. Forensic event history for meaningful lifecycle reconstruction.
3. Git/source-control history for textual repository history.
No one layer replaces the others.

## 38. Rewind / Fast-Forward
A tool should be able to reconstruct meaningful project state around a change by combining current/historical canonical records, forensic events and source revisions. v0.1 does not require a full event-sourced database or snapshots of every state.

## 39. Minimum v0.1 Schema Set
Project Manifest, Requirement, Acceptance Criterion, Change, Impact Analysis, Proposal, Approval, Decision, Implementation Attempt, Release and Forensic Event are minimum canonical schema targets. Build, Environment and Deployment schemas support delivery traceability.

## 40. Validator Responsibilities
Validation includes required repository/bootstrap artifacts, manifest structure/path resolution, canonical ID recognition/uniqueness, JSON Schema conformance, project-boundary isolation and referential integrity where the model requires it. Errors identify affected file and reason.

## 41. Referential Integrity
References to canonical entities must resolve within the applicable project boundary unless the model/policy explicitly permits an external stable reference or temporarily unresolved early lifecycle reference.

## 42. Forensic Completeness
Projects may later define completeness levels, but Core's baseline requires enough evidence to traverse meaningful authority and delivery relationships without relying on chat memory.

## 43. Example Chain
`requests.xlsx row 18 -> CHG -> IA -> PROP -> APR -> SPEC -> REQ -> AC -> failed IMP -> passed IMP -> TEST/VAL -> git revision -> BLD -> REL -> DEP -> ENV`.

## 44. Model Boundary
The model captures meaningful engineering events, not surveillance exhaust. It does not require every prompt, keystroke, transient generated file or internal AI reasoning step.

## 45. Privacy and Data Minimisation
Store only provenance/actor data needed for engineering authority and traceability. Avoid unnecessary personal or sensitive data in canonical records.

## 46. Normative Relationship Rules
A proposal belongs to one change; an approval belongs to one exact proposal and corresponding change; an implementation attempt belongs to an approved/authorised proposal path; releases link delivered changes and source/build evidence; deployments link release/build to environment; events never silently replace current-state authority.

## 47. Data-Model Proof Test
Given a completed feature, a fresh AI/tool should be able to answer: why it exists, who approved it, which requirement/criteria define it, which tests/validation support it, which source revision implemented it, which release/deployment delivered it, what meaningful failures occurred, what prior behaviour existed and what original request initiated it.

## 48. Lifecycle Enforcement Evidence
A governed change may declare a lifecycle-enforcement profile. Approval evidence may include the deterministic proposal digest. Implementation attempts may carry structured test and validation-check results using `passed`, `failed`, `blocked`, or `unavailable`; blocked/unavailable evidence cannot be treated as passed. Transition tools return machine-readable gate decisions and do not mutate current state on refusal. Historical changes predating an enforcement profile remain valid historical evidence and may be diagnosed without rewriting.

## 49. Version
Canonical Data Model version: `0.1.0-alpha.1`.
