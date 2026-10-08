# SpecForge Core Product Specification 0.1.0-alpha.24

This candidate succeeds alpha.23 and adds stage-aware managed progress visibility without changing
project format 1 or the canonical data model, which remains 0.1.0-alpha.10.

## Managed progress

Core exposes `managed_progress_v1` through the managed interaction layer. Progress is observational
and read-only. It does not create authority, advance lifecycle state, modify evidence or replace the
canonical continuation engine.

`specforge-managed.py progress CHG-... --session SESSION-... --root . --json` returns:

- meaningful completed stages
- current activity
- observer activity used as evidence
- the next lifecycle or human boundary
- blocker state
- a concise `user_message`
- a default long-wait heartbeat target

Canonical continuation owns lifecycle truth. Observer marks may enrich that truth with active-work and
sub-stage detail but cannot override a terminal state, blocker or current human decision boundary.

## Observer current activity

Observer summaries expose deterministic `current_activity` derived from recorded phase marks. The
supported active states cover clarification wait, approval wait, productive work, implementation,
product validation, SpecForge validation and legacy validation.

Where an active phase has a valid start timestamp, elapsed seconds are reported from the system clock.
If timing evidence is unavailable, the value is reported as unavailable rather than estimated.

An observer mark may carry a concise evidence-backed `note`. A repeated validation-start mark may
therefore identify a known sub-stage such as a completed immutable-lineage check followed by repository
integrity. Progress consumers must not invent detail that is absent from observer or repository evidence.

## User-facing progress contract

Substantial work should surface progress after meaningful phase transitions. During one genuinely long
external validation or tool wait, the default heartbeat target is approximately 60 seconds whenever the
execution host has control to report.

A blocking host or external tool may prevent an update at the target interval. That is not a governance
failure. The host should report the current evidence-backed state promptly when control returns.

Progress messages must not invent ETAs, claim unobserved completion or devolve into repetitive
low-information heartbeats. Ordinary messages hide CHG, PROP, APR, event and hash identifiers unless
an identifier is required for the user's immediate decision or the user requests audit detail.

Approval and checkpoint acceptance are explicitly human decision boundaries. They are not described as
active implementation. A completed change is terminal and must not imply that processing continues.

## Read-only guarantee

Progress queries must not mutate project material, governance records, history, evidence, authority or
observer metrics. This property is regression-tested alongside interruption/resume behaviour.

## Portability

Managed progress is derived from generic lifecycle and observer semantics. It must not depend on
Candidate A change numbers, event ranges, branch names or host-project fixtures. The complete
portability suite executes managed-progress regressions in an external-shaped copied Core.

## Compatibility

Alpha.23 lifecycle-efficiency behaviour, controlled_v3 chronology, continuation, managed completion
guard v3, PROJECT.md format v2, PFA/CAP semantics, deterministic governance tiers and existing observer
telemetry remain compatible. Existing repositories require no data-model migration.
