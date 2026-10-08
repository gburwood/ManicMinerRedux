# SpecForge Core Canonical Data Model v0.1.0-alpha.10

This model succeeds v0.1.0-alpha.9.

## Fresh governance-tier bootstrap provenance

The existing digest-anchored governance-tier activation evidence shape remains authoritative. A fresh
project may record `provenance: fresh_project_bootstrap_v1` with an empty `proposal_digests` set.
The project manifest continues to bind the evidence by `grandfather_digest` and
`enforcement_profile: deterministic_tier_v1`.

Fresh initialization is pre-history and pre-material-authority only. It is not an approval, migration,
grandfather decision or substitute for historical change-authorised activation.

## Managed session guard v3

New `managed_interaction_session` evidence uses `completion_guard_version: 3`.
`managed_completion_receipt.receipt_version` MUST equal its originating guard version for delivered
and non-delivery outcomes. Versions 1 and 2 remain valid historical formats.

## Project definition format v2

`PROJECT.md` contains an explicitly delimited SpecForge-managed definition region with
`definition_format_version: 2`. The region carries authoritative human-readable Purpose and Current
status plus machine-verifiable `request_digest`, `change` and `status` fields.

Guard-v3 `project_definition_reconciliation` binds:
- the project-definition path;
- the SHA-256 of the complete prepared PROJECT.md file;
- the request digest;
- the governed change id; and
- `definition_format_version: 2`.

The prepared full file is retained as evidence. Content outside the managed region is non-managed
project prose and is preserved during reconciliation.

## Compatibility

APR, CAP, PFA, ACC and checkpoint models are unchanged from alpha.9. Historical completion guard v1/v2
and alpha.21 project-definition evidence retain their earlier interpretation.
