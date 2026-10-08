# SpecForge Core Product Specification 0.1.0-beta.1

This release succeeds Core 0.1.0-alpha.25. Project format remains 1 and the canonical data model remains 0.1.0-alpha.10.

## Beta scope

0.1.0-beta.1 consolidates the validated closure stack represented by CHG-1045 and CHG-1053 through CHG-1059. The release promotion itself adds no new behavioural feature.

The beta includes:
- Windows/POSIX path and line-ending portability hardening, plus explicit fail-closed execution-channel capability reporting.
- Off-system material-change detection with additive keep, undo and set-aside recovery that does not manufacture retroactive approval.
- Bounded compatibility for explicitly enumerated historical governance evidence.
- Ordered stacked remediation authority for separately approved descendant material candidates, including dot-prefixed material-path preservation.
- Portable upgrade regression handling and visible progress for long full-history validation.
- Bounded historical integration verification cost while preserving canonical fail-closed semantics.
- Additive static-only forensic corrections for explicitly proven historical integration-evidence mismatches.

## Governance and integrity

Proposal approval and checkpoint acceptance remain separate human authority boundaries. Trusted material advances only through accepted checkpoint evidence. Routine integrity uses incremental_integrity_v1 when trust assumptions remain provable, while full_integrity_v1 performs exhaustive deep audit.

## Compatibility

- Core version: 0.1.0-beta.1
- Canonical data model: 0.1.0-alpha.10
- Project format: 1
- Material revision verification: immutable_material_v3
- Governance tier enforcement: deterministic_tier_v1
- Managed interaction integrity: controlled_v3

Historical versioned product specifications remain preserved.
