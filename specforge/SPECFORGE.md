# SpecForge Project Entry Point

This repository uses SpecForge project format 1.

## Default experience

SpecForge is invisible by default. A user should work in ordinary project language and should not need to understand CHG/PROP/APR identifiers, hashes, lifecycle states or evidence structures.

A fresh human or AI session MUST:
1. Read `specforge/project.yaml` and resolve the installed Core, packs and project authority.
2. Load Core rules, schemas, workflows and tooling through manifest paths.
3. Run `specforge/core/tools/specforge-experience-preflight.py --root . --json`. If it reports a project-local runtime, stop managed work and use or establish execution tooling outside the managed project before continuing.
4. For ordinary operation, run `specforge/core/tools/specforge-managed.py guide --root . --request "<ordinary request>" --json`. The guide is read-only and derives the next valid action from canonical repository state. `bootstrap`, `summary`, `progress` and the authority-bearing managed commands remain available for expert/internal use.
5. If managed state is `needs_project_definition`, ask the user what they are trying to achieve and clarify only materially consequential ambiguity before ordinary material work begins. Establish a lightweight project definition, normally `PROJECT.md`.
6. If managed state is `ready_for_work`, remain in managed mode for the rest of the session. Subsequent material requests automatically follow SpecForge governance without the user having to ask.
7. Inspect non-terminal changes, current proposals, approvals, implementation evidence, relevant decisions and forensic corrections before continuing existing work. After any interruption, run `specforge/core/tools/specforge-status.py --continuation <CHG> --root . --json` before repeating a lifecycle action.
8. Treat repository state, never prior chat or AI memory, as continuation authority.
9. Before material implementation, establish the governed proposal internally. Present only the concise material substance to the user via `specforge-managed.py present`; do not expose governance mechanics unless asked.
10. Treat conversational approval as authority only after the exact current proposal has been presented. Use `specforge-managed.py approval` to verify presentation/digest continuity before relying on approval.
11. Request canonical lifecycle transitions through existing SpecForge tooling. Candidate A does not weaken or replace Core governance gates.
    Before any managed material edit, run `specforge-managed.py implementation-authority --root . --change CHG-... --proposal PROP-... --json` and require `permitted: true`. Recheck after any proposal identity change. Presentation alone does not authorise implementation. Keep presented controlled-v3 proposals unchanged; a material revision requires a new proposal revision, presentation and approval. Use effective approval from canonical evidence rather than rewriting the proposal's approval-bound status.
12. Record actual system-clock interaction phase boundaries with `specforge-observe.py`; never invent, estimate or backfill timing evidence.
13. Use progressive disclosure: ordinary users see decisions and useful outcomes; project managers can request `specforge-managed.py summary` for concise or full audit detail. For substantial work, use `specforge-managed.py progress` to surface evidence-backed stage progress without exposing low-value governance mechanics.
14. Prefer the smallest useful product scope. Do not add extra deliverables, metadata, specification rewrites or version bumps unless they are required by the user's intent or by a deterministic governance rule.
15. Do not explain governance to an ordinary user when a plain decision question is sufficient. For example, ask `Shall I make this change?`, not `Your selected workflow requires approval...`.
16. Never modify `specforge/core/` or installed pack/framework material as an incidental repair inside an ordinary project change. A framework defect is a separate framework problem and requires separate project-manager authority.
17. Do not create project-local Python environments, dependency caches or tool runtimes as part of ordinary bootstrap. If an execution environment is required, prefer an existing/shared environment outside the managed project. Runtime/tooling infrastructure is not project material.
18. Interaction instrumentation is observational. Record each phase boundary at the time it occurs. Repeated phases must be distinguishable by an attempt identifier rather than producing ambiguous duplicate marks.
19. A requested final artifact is project material by intent. External tool/runtime/output locations may be used for temporary staging, but they never declassify a final deliverable. Before final delivery, retain a canonical governed copy at a path classified as project material.
20. After checkpoint acceptance has completed the governed change, call `specforge-managed.py finish --session <session> --change <change> --deliverable <project-path> ... --project-definition-action updated|unchanged --json`. Do not present substantive work as finally complete unless this gate permits delivery.
21. When a guarded interaction ends legitimately without final delivery, call `specforge-managed.py close --session <session> --reason "<reason>" --json` so the repository records an explicit non-delivery closure rather than an unexplained abandoned completion path.
22. When the request changes the authorised project outcome, bring the project definition forward within the approved change and use `--project-definition-action updated`. Initial project-definition creation from an undefined state remains part of managed bootstrap; later outcome changes must be governed.

When ambiguity exists, prefer the smallest useful clarification. The goal is fuzzy intent in, enlightened user out.

Framework-owned material is beneath `specforge/core/` and `specforge/packs/`. Project-owned governance state is beneath `specforge/changes/`, `specforge/decisions/`, `specforge/history/` and `specforge/evidence/`.

Candidate Core distributions, including conventional staging beneath `specforge-dist/<core-version>/`, are installation/migration inputs only. They are not installed project authority and MUST be ignored by normal project and governance-record discovery.

## Guided non-expert operation

`specforge-managed.py guide --root . --request "<ordinary request>" --json` is the normal front door
for a host that should not need lifecycle identifiers or command sequencing. Its stable
`guided_non_expert_v1` contract reports state, internal next action, human-decision requirement,
blocker codes, resolved change/session and concise user-facing text.

The guide is read-only. It may route to new-work start, unambiguous continuation, proposal approval,
implementation/validation, checkpoint preparation, checkpoint acceptance or terminal completion, but
it cannot manufacture or consume human authority. Ambiguous or external continuation fails closed.
Proposal approval and checkpoint acceptance remain separate human boundaries. Expert forensic detail
continues to come from the existing status, summary and progress interfaces.
## Alpha.20 prospective finalisation

When the current proposal explicitly qualifies for exact-candidate finalisation, present the ordinary
proposal plus the concise option to **Approve and finalise**. Treat that phrase as prospective
conditional human authority, never as an early checkpoint acceptance. Use
`specforge-managed.py approval ... --finalise` to capture `PFA-NNNN`. Only after implementation,
required validation and a matching single-change checkpoint may
`specforge-checkpoint.py finalise ... --authority PFA-NNNN` derive the actual checkpoint acceptance.
If exact matching fails, surface the normal checkpoint acceptance decision to the user.

## Alpha.21 controlled_v3

New managed controlled work created under alpha.21 uses `controlled_v3`. The managed layer owns
proposal approval chronology, request-bound session guard v2, project-definition reconciliation,
clarification evidence and direct checkpoint-acceptance proof.

Use `specforge-managed.py begin --request "<request>"` for substantive work. Use the managed
clarification commands for material questions. Before approval, prepare and bind any required
`PROJECT.md` reconciliation. Record proposal approval through the managed approval command.

A plain approval authorises implementation only. If no prospective finalisation authority exists,
the checkpoint must later be presented and accepted through a distinct `CAP-NNNN` proof before
`finalise-direct` may complete it. `Approve and finalise` remains the explicit PFA one-prompt path.
Historical controlled_v1/v2 and completion-guard-v1 records retain their original semantics.

## Alpha.22 fresh-project and managed-definition hardening

For a fresh Core alpha.22 project, initialise deterministic governance-tier state before establishing
the first trusted material baseline:

`python -B specforge/core/tools/specforge-governance-tier.py initialize --root . --json`

This fresh initializer is deliberately separate from historical change-authorised `activate`. It is
valid only before governed CHG/APR/IMP/CHK/ACC/PFA/CAP history or a trusted material baseline exists.
It records `fresh_project_bootstrap_v1` provenance, an empty grandfather set and the normal
digest-anchored `deterministic_tier_v1` project state. Existing activated projects continue to use
their historical activation evidence unchanged. Upgrades never auto-initialise an existing project.

New managed sessions use completion guard v3. `PROJECT.md` format v2 owns one explicit
`SPECFORGE-MANAGED-DEFINITION` region containing the authoritative human-readable purpose/status
and request/change binding. Preparation approval-binds the complete resulting file SHA-256. User prose
outside that region is retained and is not semantically classified. Historical guard-v1/v2 receipts
remain valid, while every new completion or non-delivery receipt uses the exact version of its session
guard.



## Alpha.23 dogfood lifecycle efficiency

When Dogfood Development is installed, optimise repository and CI orchestration without weakening
Core authority. Batch coherent bookkeeping only within one already-authorised phase. Human proposal
approval and checkpoint acceptance remain distinct temporal boundaries.

Product smoke is triggered by material paths, not governance/evidence-only bookkeeping. Immutable
revision evidence uses the stable Candidate A evidence workflow with full-history checkout; never edit
the workflow under test merely to capture its evidence.

Continuation after timeout or session loss is read-only and repository-derived. Use
`specforge-status.py --continuation CHG-... --json`; if it reports blocked, resolve the canonical
inconsistency instead of guessing or repeating a prior human decision.

## Alpha.24 managed progress visibility

Core alpha.24 adds `managed_progress_v1`. The read-only
`specforge-managed.py progress CHG-... --session SESSION-... --json` command combines canonical
continuation with observer evidence to report completed stages, current activity, the next meaningful
boundary and concise user-facing progress text.

For substantial work, surface progress at meaningful phase changes. When one external validation or
tool operation remains active for a long period, target a progress update about every 60 seconds when
the host has control. If the host is blocked inside the operation, report immediately when control
returns instead of inventing intermediate activity.

Observer notes may provide evidence-backed sub-stage detail such as a completed immutable-lineage
check followed by repository-integrity validation. Never invent ETAs, never claim an unobserved stage
has completed and avoid low-information heartbeat spam. Canonical continuation overrides stale
observer state after interruption. Completed changes are terminal and must not be described as still
processing.

## Alpha.25 bounded integrity validation

Core alpha.25 separates routine integrity from exhaustive history reconstruction.

Normal lifecycle transitions use `specforge-integrity.py auto`. When a valid integrity receipt exists,
the routine path verifies Git ancestry, the canonical-record delta, affected reference/authority
closure, inventory accounting, identifier maxima and touched registry partitions. It does not enumerate
or schema-validate unchanged historical YAML.

The integrity state is written to `specforge/evidence/integrity/state.json` after successful validation
and committed as a state-only integrity receipt. The receipt commit cryptographically anchors the state
to the exact validated parent revision. A later change must descend from that receipt.

Any uncertainty fails closed into `full_integrity_v1`. Deep-audit triggers include missing/corrupt
state, non-descendant history, changes to validator/schema/policy semantics, unexpected modification or
deletion of immutable historical records, accounting mismatch and an expired full-audit age.

Dogfood performs an exhaustive full-history audit monthly. The default warning age is 35 days and the
maximum accepted age is 45 days. Projects may configure these values under `policy.integrity`.

Full and incremental validation publish machine-readable phase/counter progress. Managed progress should
prefer those live counters over generic heartbeat prose and must never invent percentages or ETAs.

## Alpha.26 host portability contract
Project-format paths are authoritative wherever a path key exists. Incremental integrity, upgrade evidence and related governance tooling must not assume the conventional `specforge/...` layout when the manifest declares another location. Host projects may opt into `governance_tier.host_classification` with `authoritative_globs`, `ordinary_globs` and `ordinary_tier`; these semantics can classify host application material proportionately but can never lower protected Core, schema, policy, workflow, pack, project-manifest or authoritative-specification surfaces. Continuation tooling may discover nonterminal governed work on other refs and report candidates, but it must fail closed rather than silently switching when the current workspace does not contain the change.

## Alpha.26 execution-channel capability reporting

Hosts must not assume that the active interaction channel can perform every assurance action. Before depending on a host-only capability such as workflow dispatch, use:

`python -B specforge/core/tools/specforge-managed.py capabilities --root . --require workflow_dispatch --json`

The command implements `execution_channel_capabilities_v1`. Capabilities are available only when the host explicitly advertises them through `SPECFORGE_EXECUTION_CAPABILITIES` or equivalent `--available` arguments. Missing required capabilities return `permitted: false`, a non-zero exit status and deterministic blockers such as `execution_channel_capability_unavailable:workflow_dispatch`.

Capability absence is an execution blocker, not validation success. Do not manufacture, infer or cache capability merely because a repository contains a workflow definition. Re-run capability preflight when the active host/channel changes.
