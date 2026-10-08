# SpecForge Core Product Specification 0.1.0-alpha.23

This candidate succeeds alpha.22 and reduces dogfood execution amplification without weakening the
controlled_v3 authority model. Project format remains 1 and the canonical data model remains
0.1.0-alpha.10.

## Dogfood lifecycle efficiency

Dogfood Development treats orchestration efficiency as a quality attribute. Coherent governance
bookkeeping may be committed atomically when every mutation is already authorised within the same
lifecycle phase. Proposal approval and checkpoint acceptance remain separate human decisions and may
never be predicted, pre-created or collapsed.

Product smoke is triggered by explicit material paths. Governance, history and evidence bookkeeping
that is outside the material boundary does not by itself launch product smoke. Sensitive framework,
governance and CI changes may still escalate to full repository validation.

## Stable revision evidence

Candidate A provides a stable evidence workflow using full Git history. It can inspect baseline and
candidate material identities, verify immutable static lineage and optionally run the full portability
and repository-validation suites. Evidence gathering must not require a temporary edit to the workflow
being measured.

## Continuation after interruption

`specforge-status.py --continuation CHG-... --json` derives the current lifecycle boundary from
canonical repository records. It reports current status, proposal, effective approval, latest
implementation, checkpoint state, blockers and the next governed action. It is read-only and fails
closed on ambiguous or inconsistent state.

Managed project-manager summaries expose the same continuation result so a fresh interaction can
resume without reusing chat memory as authority or repeating an already-recorded human decision.

## Execution telemetry

Observer marks retain their existing productive-work, SpecForge-management and user-wait semantics.
When Git heads were observed at phase boundaries, summaries additionally report repository
amplification: total commits plus material-changing, governance/evidence-only, other non-material and
unclassified commits in the observed range. Repeated validation attempts are reported separately
without changing span-based time accounting.

## Compatibility

Alpha.22 fresh-project governance initialization, managed completion guard v3, PROJECT.md format v2,
controlled_v3 approval chronology, PFA and CAP semantics remain unchanged. Existing canonical
governance records require no migration.
