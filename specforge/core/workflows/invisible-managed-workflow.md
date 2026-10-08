# Invisible Managed Workflow — Candidate A

Status: experimental candidate behaviour. This workflow sits above the existing SpecForge lifecycle; it does not replace governance gates.

## Product principle

SpecForge is invisible by default. It surfaces only when the user must resolve material ambiguity, make a meaningful product decision or provide authority. The framework should take the fastest valid path and expose governance mechanics only when requested or when a blocker needs project-manager attention.

## Managed bootstrap

A successful Core bootstrap is necessary but not sufficient to start ordinary managed work.

Run:

```text
specforge-managed.py bootstrap --root . --json
```

The managed state is one of:

- `ready_for_work` — Core is ready and an explicit project definition exists.
- `needs_project_definition` — Core is ready but the project has no explicit human-readable intent anchor. Ask one concise question such as “What are you trying to achieve?” Do not begin material implementation yet.
- `blocked` — Core readiness failed. Keep blocker detail internal by default and surface a concise explanation to the user; provide full details to the project manager on request.

When definition is needed, progressively clarify only decisions that materially affect the intended result. Do not conduct a questionnaire for harmless details. Create the project definition only after the user's intent is sufficiently clear.

Default definition anchor: `PROJECT.md`.

## Guided non-expert front door

For ordinary operation, prefer the read-only guided entry point:

```text
specforge-managed.py guide --root . --request "<ordinary request>" --json
```

The `guided_non_expert_v1` result separates machine routing from user-facing language. It reports
the current state, the internal next action, whether a human decision is required, deterministic
blocker codes and the resolved change/session when known. The guide does not create approvals,
implementation authority, checkpoint acceptance or lifecycle transitions.

If exactly one current non-terminal change is unambiguous, the guide resumes it from canonical
repository continuation without asking the user for an identifier. If several plausible changes
exist, or the requested change is not in the current workspace, it fails closed rather than choosing
a lineage. A host may then select the intended change internally and call the guide again.

At proposal approval and checkpoint acceptance boundaries, surface the returned plain-language
`user_message`. During authorised implementation, validation and checkpoint preparation, continue
automatically and tell the user that no response is required. Existing `summary`, `progress`,
`present`, `approval`, `implementation-authority`, `checkpoint-present` and `checkpoint-acceptance`
commands remain the canonical expert and authority-bearing mechanisms.
## Managed interaction start

For every new substantive user request, the first managed action is:

```text
specforge-managed.py begin --root . --json
```

Keep the returned `session` for the entire interaction. If the client already has a stable session identifier it may pass `--session <id>`; repeating `begin` with that same id is idempotent and does not create a second `request_received` mark.

Do not do substantive research, analysis, design, proposal preparation or implementation before `begin`. Do not invent or backfill an earlier request timestamp. Proposal presentation fails closed unless its session was begun.

## Fuzzy in, enlightened out

User requests may begin informal, incomplete or fuzzy. The managed workflow must not silently convert material ambiguity into design decisions.

- Infer harmless details when reversal is cheap and no material product choice is hidden.
- Ask concise clarification when different interpretations would materially change the result.
- Keep ambiguity visible until resolved.
- Do not expose lifecycle terminology merely because clarification is needed.

## Invisible proposal presentation

Governance records may be detailed internally. The ordinary user should see a short description of the material change, not CHG/PROP identifiers, hashes, schema fields or validation recipes.

After an exact proposal exists, use:

```text
specforge-managed.py present --proposal PROP-... --change CHG-... --session SESSION-... --summary "<concise material change>" --json
```

Show the returned `user_prompt` verbatim or equivalently. Do not record approval before the proposal has been presented.

Typical user experience:

> I’ll add a ten-question revision quiz and a separate answer key. The rest of the report will stay unchanged.
>
> Shall I make this change?

## Informed conversational approval

A response such as “Yes please”, “Approved” or “Go ahead” may be valid conversational approval only after the exact current proposal has been presented.

Before creating or relying on an approval record, use:

```text
specforge-managed.py approval --proposal PROP-... --change CHG-... --decision approved --text "<user response>" --json
```

The command fails closed when:

- the proposal was never presented;
- the proposal bytes changed after presentation;
- the proposal no longer exists; or
- the decision/evidence is missing.

The returned informed-approval proof supplements existing Core approval evidence. Candidate A does not yet alter the canonical approval schema or approval gate; mechanical integration with the gate is intentionally deferred until the interaction contract has been dogfooded.

## Pre-edit implementation authority

Before every managed material implementation phase, require a successful exact-current-proposal check:

```text
specforge-managed.py implementation-authority --root . --change CHG-... --proposal PROP-... --json
```

Proceed only when `permitted` is true, and request the normal lifecycle implementation transition.
Neither proposal presentation nor setting the change status supplies approval authority. The managed
project-definition application uses this same gate before writing project material.

For controlled-v3 work, retain the exact proposal bytes after presentation, including its document
status. Canonical APR evidence determines effective approval; do not update proposal status or approval
lists to mirror that evidence. A material revision requires a new proposal id/revision, a new
presentation and fresh approval. The managed presentation command refuses changed content under a
previously presented controlled-v3 proposal identity.

## Progressive disclosure

Default user view:

- what will change;
- any material clarification required;
- the approval question;
- useful result/completion message;
- a concise explanation of blockers only when necessary.

Default project-manager view:

```text
specforge-managed.py summary CHG-... --detail minimal --json
```

This should answer what changed, why, current status, authority and implementation outcome without requiring forensic detail.

`--detail standard` exposes record references. `--detail full` may expose raw canonical records for audit/debugging.

## Instrumentation

Record actual system-clock phase boundaries with `specforge-observe.py`. Do not invent, estimate or backfill timestamps.

Use `specforge-managed.py begin` as the required first managed action. It records `request_received` immediately and returns the stable interaction session. Keep using that session after a CHG id exists; later `--change` summaries can then include the earlier no-change request mark. When substantial useful work happens before implementation, such as research, investigation, design, analysis or prototyping, bracket that work with `productive_work_started` and `productive_work_completed`. These marks are observational only and may overlap proposal and lifecycle events.

Bracket deliverable/content quality checks with `product_validation_started` / `product_validation_completed`; they count as productive work. Bracket SpecForge framework validation with `specforge_validation_started` / `specforge_validation_completed`; it counts as SpecForge management. Use legacy `validation_started` / `validation_completed` only when the distinction is unavailable.

Recommended phases:

- `request_received`
- `clarification_requested`
- `clarification_resolved`
- `productive_work_started`
- `productive_work_completed`
- `proposal_preparation_started`
- `proposal_presented`
- `approval_received`
- `implementation_started`
- `implementation_completed`
- `product_validation_started`
- `product_validation_completed`
- `specforge_validation_started`
- `specforge_validation_completed`
- `validation_started` / `validation_completed` (legacy fallback)
- `change_completed`

Example:

```text
specforge-managed.py begin --session SESSION-42 --json
specforge-observe.py mark implementation_started --change CHG-0003 --session SESSION-42 --json
specforge-observe.py summary --change CHG-0003 --json
```

Metrics are observational evidence. They do not grant authority and must not change lifecycle decisions.


## Final delivery boundary

Requested final artifacts are project material by intent. An agent may use external runtime, conversion, browser-download or output directories as temporary staging areas, but location does not grant a governance exemption. Before a substantive artifact is presented as final, a canonical copy must exist at a path classified as project material.

A session begun by alpha.19 records a completion-guard marker beneath `specforge/evidence/managed-sessions/`. Historical sessions without that marker retain their earlier semantics.

After the governed change has been accepted through a checkpoint and is `completed`, run:

```text
specforge-managed.py finish --session SESSION-... --change CHG-... \
  --deliverable outputs/report.pdf --deliverable outputs/research-pack.pdf \
  --project-definition-action updated --json
```

The gate fails closed unless the original managed session is guarded and traceable, the referenced change is completed, informed conversational approval exists for the exact proposal, accepted checkpoint authority is bound to the change, every final deliverable exists inside the project and classifies as project material, and the project-definition declaration is truthful.

If an already-defined project's authorised outcome changed, the definition must have changed and must be inside the approved proposal scope. Initial definition from an undefined state remains a bootstrap concern.

A successful gate writes a durable JSON completion receipt containing the session, change, proposal digest, checkpoint and acceptance identities and SHA-256 identity of every final artifact. Only then should the agent describe the work as finally complete or hand over those artifacts.

If an interaction legitimately ends without a final deliverable, close it explicitly:

```text
specforge-managed.py close --session SESSION-... --reason "<why no final delivery occurred>" --json
```

Repository validation applies the guard only to sessions carrying the alpha.19 marker. It rejects School-Project-10-style completion evidence with no governed change, and rejects completed governed work that has neither a final-delivery receipt nor an explicit non-delivery closure. In-progress or ready-for-checkpoint changes may still be validated before final delivery.

## Candidate A boundary

This candidate intentionally does not implement proportional testing or governance ceremony. Those belong to the Fastest Valid Path candidate. Candidate A is about managed-session persistence, project intent, informed conversational approval, progressive disclosure and measurable interaction latency.

## Prospective exact-candidate finalisation

Core alpha.20 supports an opt-in one-prompt path when the proposal fully determines the eventual
project-material candidate. A proposal may declare `exact_candidate_finalisation.eligible: true`
only when every material add/modify path has an exact SHA-256 identity and every material deletion is explicit.

When eligible, proposal presentation explains that the user may say **“Approve and finalise”**.
Record that response with:

```text
specforge-managed.py approval --proposal PROP-... --change CHG-... --decision approved \
  --text "Approve and finalise" --finalise --json
```

This creates normal informed-approval evidence plus an immutable `PFA-NNNN` prospective authority.
It does not create checkpoint acceptance. The PFA binds the actual human decision time, exact
proposal digest, pre-change material baseline and deterministic projected material candidate.

After implementation and checkpoint verification, a matching single-change checkpoint may consume
the PFA:

```text
specforge-checkpoint.py finalise CHK-... --authority PFA-... --root . --json
```

Automatic finalisation fails closed if proposal bytes changed, material drift occurred, checkpoint
membership differs, the candidate material identity differs, assurance requirements changed or the
PFA was already consumed. When it succeeds, SpecForge creates the real `ACC-NNNN` at that later
finalisation time using an automated-system actor under the earlier human authority, then completes
the checkpoint transaction normally. If any exact-candidate condition is not met, ask for ordinary
post-checkpoint human acceptance instead.

## Alpha.21 managed interaction integrity

Core alpha.21 uses managed session guard v2 for new substantive interactions. Begin the interaction
with the actual request text so Core can retain only its SHA-256 identity:

```text
specforge-managed.py begin --request "<user request>" --session SESSION-... --json
```

If material ambiguity requires a question, use the managed clarification path before surfacing it:

```text
specforge-managed.py clarify --session SESSION-... --question "<question>" --json
specforge-managed.py resolve-clarification --session SESSION-... --clarification CLR-... --response "<user response>" --json
```

Proposal presentation fails while a recorded clarification is unresolved.

For substantive final delivery, prepare the expected `PROJECT.md` reconciliation before proposal
approval:

```text
specforge-managed.py prepare-definition --session SESSION-... --change CHG-... --summary "<current work>" --json
```

Copy the returned `proposal_binding` into the proposal's
`project_definition_reconciliation` field and include `PROJECT.md` in declared material scope.
The prepared file remains non-material until authorised implementation. During implementation apply it
with:

```text
specforge-managed.py apply-definition --session SESSION-... --change CHG-... --json
```

For controlled_v3, proposal approval must be recorded through `specforge-managed.py approval`.
That command creates the canonical APR using the actual received timestamp and informed-approval
proof. Do not hand-author a controlled-v3 APR.

If no PFA was granted, checkpoint acceptance is a separate human decision after the checkpoint exists:

```text
specforge-managed.py checkpoint-present --checkpoint CHK-... --session SESSION-... --json
specforge-managed.py checkpoint-acceptance --checkpoint CHK-... --session SESSION-... --text "<user reply>" --json
specforge-checkpoint.py finalise-direct CHK-... --proof CAP-... --root . --json
```

The resulting CAP is distinct from proposal approval even when both user replies happen to be
identical text such as "Yes". A valid PFA remains the only one-prompt finalisation path.

## Alpha.22 fresh project and definition contract

Before a fresh alpha.22 project records its first trusted material baseline, run the governance-tier
`initialize` operation. Do not substitute historical `activate`: fresh initialization is only for
a project with no governed CHG/APR/IMP/CHK/ACC/PFA/CAP history and no material authority.

New managed interactions use completion guard v3. The authoritative project definition is the complete
SpecForge-managed definition region in `PROJECT.md`, not isolated sentences elsewhere in the file.
Prepare the whole region before approval, bind the complete prepared file SHA-256 plus request digest,
change id and definition format version in the proposal, and apply those exact bytes during authorised
implementation. Preserve user-authored content outside the managed region. When migrating an unmarked
alpha.21 definition, retain its earlier prose as background context rather than treating it as current
purpose/status.

Completion and non-delivery receipts MUST use `receipt_version` equal to the originating session's
`completion_guard_version`. Historical guard v1/v2 evidence keeps its original interpretation.



## Alpha.23 dogfood lifecycle efficiency

Dogfood mode reduces orchestration without reducing assurance. Coherent bookkeeping inside one
already-authorised lifecycle phase may be committed atomically, but proposal approval and checkpoint
acceptance remain separate human boundaries.

Candidate A product smoke is material-path filtered. Immutable material comparison and full-history
evidence use the stable `.github/workflows/candidate-a-evidence.yml` workflow rather than temporary
workflow edits.

After interruption, obtain the canonical next action before doing anything else:

`specforge-status.py --continuation CHG-... --root . --json`

The continuation view is read-only. It derives proposal, approval, implementation and checkpoint state
from canonical records and fails closed on ambiguity. Manager summaries expose the same result.

Use `specforge-observe.py summary --change CHG-... --json` to inspect productive work, SpecForge
management, repeated validation attempts and repository commit amplification when Git evidence is
available.

## Alpha.24 managed progress visibility

For substantial or long-running managed work, progress is part of the user experience rather than
project authority. Obtain an evidence-backed snapshot with:

```text
specforge-managed.py progress CHG-... --session SESSION-... --root . --json
```

The command is read-only. It combines canonical continuation with observer state and returns
`completed_stages`, `current_activity`, `next_boundary` and a concise `user_message`. Canonical
continuation always wins if an older observer mark would imply a stale lifecycle state.

Surface useful progress after meaningful phase transitions. During one genuinely long external
validation or tool wait, target an update about every 60 seconds whenever the execution host has
control to report. A host or tool that blocks control for longer than that interval has not violated
governance; report the current state promptly when control returns.

When a validation sub-stage is known from evidence, record it in the observer mark `note` so progress
may distinguish completed checks from the currently running check. Never invent a sub-stage or ETA.
Do not emit repetitive heartbeats that add no information, and do not expose CHG/PROP/APR/event/hash
detail in ordinary progress prose unless the identifier is needed for the user's immediate decision
or the user asks for audit detail.

Approval and checkpoint acceptance are human decision boundaries, not active implementation. A
terminal completed change must be reported as complete and must not imply that background work
continues.

## Alpha.25 integrity execution

Use the bounded integrity command for routine managed work:

```text
specforge-integrity.py auto --root . --state-output <temporary-state> --json
```

A successful run produces the next integrity state without mutating canonical lifecycle authority.
Persist that state in a state-only receipt commit. The receipt's parent is the validated revision and
its Git identity anchors the integrity state for the next routine transition.

If incremental trust cannot be proven, `auto` escalates to `full_integrity_v1`. Do not suppress that
escalation. Validator/schema/policy changes, historical mutation, non-descendant history, invalid
accounting or an overdue deep audit all require the exhaustive path.

Dogfood runs a scheduled full audit monthly. Routine changes must not launch a full-history audit merely
because governance bookkeeping was appended.

While validation runs, managed progress should surface the freshest machine-readable validator
`mode`, `phase`, `processed`, `total`, elapsed time and sub-stage. If a total is unknown, report
the stage without manufacturing a percentage.

## Portable host-project resolution
Resolve schemas, evidence, upgrade state and governance bookkeeping from the active project manifest. Host projects may declare authoritative specification paths and explicit ordinary-material globs for proportionate governance. Protected framework and project-authority surfaces remain monotonic HIGH. Continuation discovery may report governed work on other repository refs, but must never switch workspace or choose among ambiguous candidates without an explicit human/ref selection.

## Execution-channel capability preflight

Before depending on a host-only assurance action, query the managed execution-channel capability contract rather than assuming the host can perform it.

`specforge-managed.py capabilities --root . --require <capability> --json` reports the required capability set, the capabilities explicitly advertised by the host and deterministic blockers for anything unavailable. Hosts may advertise capabilities through `SPECFORGE_EXECUTION_CAPABILITIES` or the equivalent `--available` arguments when invoking the check.

Capability reporting is evidence about the active execution channel only. It never converts an unavailable action into a passing validation result and never substitutes for the action itself. In particular, a host that cannot dispatch a required workflow must report `execution_channel_capability_unavailable:workflow_dispatch` and remain blocked rather than claiming assurance success.
