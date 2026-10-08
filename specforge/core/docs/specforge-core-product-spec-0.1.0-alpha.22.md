# SpecForge Core Product Specification 0.1.0-alpha.22

This candidate succeeds alpha.21 and hardens controlled_v3 using the failures reproduced by School
Project 13. It does not change proposal, checkpoint or prospective-finalisation authority semantics.

## Fresh-project governance-tier initialization

A fresh project has a dedicated `specforge-governance-tier.py initialize` operation. It is separate
from the historical change-authorised `activate` operation and is permitted only before governed
CHG/APR/IMP/CHK/ACC/PFA/CAP history and before a trusted material baseline exists.

Successful fresh initialization writes the normal integrity-anchored deterministic-tier state:
`deterministic_tier_v1`, `fresh_project_bootstrap_v1` provenance and an empty grandfather proposal
set. Partial, corrupted or already-active state fails closed. Existing historically activated projects
are not rewritten and upgrades do not silently initialize previously unactivated projects.

Alpha.22 controlled_v3 bootstrap is not ready until that anchored state is valid. A fresh distribution
therefore initializes governance tier before finalizing its first trusted Git/material baseline.

## controlled_v3 chronology correction

The lifecycle implementation imports `datetime as dt` directly. controlled_v3 approval and
implementation timestamps are parsed by production lifecycle code. Implementation before the exact
valid approval remains prohibited.

## Managed session guard v3

New managed sessions use completion guard v3. Both delivered and non-delivery completion receipts use
a `receipt_version` exactly equal to the session guard version. Historical guard-v1/v2 evidence
retains its original meaning.

## PROJECT.md format v2

The human-readable project definition has one explicitly marked SpecForge-managed definition region.
That region owns the authoritative current purpose and status as well as the request digest and governed
change identity. No natural-language keyword blacklist or semantic classifier is used for arbitrary
user prose.

For guard-v3 reconciliation, preparation rewrites the complete managed region and persists the complete
prepared PROJECT.md bytes in evidence. The proposal binds the resulting SHA-256, request digest, change
id and definition-format version. Application refuses changed prepared bytes or a mismatching proposal
binding. Final delivery verifies the complete resulting file identity and managed-region binding.

An unmarked alpha.21 project definition is migrated on first guard-v3 reconciliation. Pre-existing
non-managed prose is retained as background context, but it no longer supplies the authoritative
managed Purpose or Current status.

## Compatibility

Project format remains 1. Existing deterministic-tier activations, alpha.21 controlled_v3 authority
records, PFA/CAP semantics and historical completion guard v1/v2 receipts remain valid.
