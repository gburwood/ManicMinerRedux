# SpecForge Core Product Specification 0.1.0-alpha.12

Alpha.12 makes managed Core upgrade cleanup transactional.

This specification succeeds `specforge-core-product-spec-0.1.0-alpha.8.md`. Alpha.8 and its normative predecessor chain remain authoritative except where extended below. This document also incorporates the intervening alpha.9, alpha.10 and alpha.11 deltas so that the current authority has one explicit repository-complete normative chain.

Alpha.9 requires material implementation to have an active implementation attempt bound to the current exactly approved proposal and a verifiable pre-implementation material state. Alpha.10 persists the trusted material baseline in project-owned evidence, blocks retrospective authorization and adds bounded managed Core upgrade authority. Alpha.11 requires distributed Core regression tests to use portable synthetic governance fixtures rather than host-project history.

Before managed upgrade authority is established, the upgrader must capture whether the material-authority record exists and preserve its exact bytes when present. It must also preserve the exact pre-upgrade manifest and any pre-existing evidence file that the operation could replace.

Rollback scratch storage and the Core backup must be created outside the project repository tree. Replacement must copy the candidate Core from that external scratch-backed transaction without relying on cross-filesystem rename semantics.

If any failure occurs after upgrade authority has been established, the upgrader must restore the installed Core tree and `specforge/project.yaml` to their exact pre-upgrade state. It must restore `material-authority.yaml` byte-for-byte when the file existed before the attempt or remove it when it did not. Failed upgrades must not retain newly established `core_upgrade` authority or partial upgrade evidence.

Successful upgrades continue to preserve project-owned state and upgrade evidence. Their bounded `core_upgrade` authority remains active until `specforge-authorization.py accept` advances the trusted material baseline.

The upgrade regression suite must cover successful upgrades, failure after authority establishment with existing authority, failure when authority was initially absent and external scratch placement. Authorization, lifecycle, source-revision, portability and full repository validation behaviour remains unchanged.

Project format remains 1 and the canonical data model remains 0.1.0-alpha.3.
