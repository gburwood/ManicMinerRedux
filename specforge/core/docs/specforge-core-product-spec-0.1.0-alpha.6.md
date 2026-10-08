# SpecForge Core Product Specification v0.1.0-alpha.6

Status: Draft

## 1. Normative Basis
This specification succeeds `specforge-core-product-spec-0.1.0-alpha.5.md`. Alpha.5 remains normative except where explicitly superseded or extended below.

## 2. Distribution Is Not Project State
A SpecForge Core distribution is an installation, migration or upgrade input. It is not authoritative project state.

The installed project remains identified by its authoritative project metadata. For project format 1 this is `specforge/project.yaml`. For a supported legacy project this is the legacy project authority until migration completes.

Candidate distributions MAY be staged beneath a conventional directory such as `specforge-dist/<core-version>/`. Normal project discovery, record discovery and nested-project discovery MUST ignore candidate distribution content as project state.

## 3. Candidate Distribution Contract
A candidate Core distribution declares machine-readable package metadata including:

- package type;
- package/Core version;
- compatible project formats;
- migration registry location or equivalent migration capability.

The package version MUST agree with the Core payload version. A mismatch fails closed before project mutation.

A distribution may be represented as a package root containing `package.yaml` and `core/`, or as a development/source Core payload carrying equivalent package metadata. This convenience does not grant project authority to the package.

## 4. Target-Version Tooling
Migration and upgrade tooling MUST be executable from the target candidate distribution. A project MUST NOT be required to overwrite its installed `specforge/` tree merely to obtain tooling capable of understanding the target release.

The target distribution supplies the migration registry and replacement framework payload. The source project supplies project identity, current format/version and persistent project-owned governance state.

## 5. Source-State Detection
Source identity is determined from project authorities, not from the target distribution.

If both legacy and project-format authorities claim the same project outside excluded distribution roots and authority cannot be proven unambiguously, migration or upgrade MUST fail closed with a machine-readable ambiguity blocker.

The presence of a candidate distribution beneath `specforge-dist/` MUST NOT cause a legacy project to be classified as already migrated.

## 6. Migration Behaviour
Planning is read-only and reports:

- detected source authority and version;
- candidate distribution identity and version;
- target project format;
- resolved deterministic migration path;
- blockers.

Applying a supported legacy migration installs the target distribution's Core payload into `specforge/core/`, relocates only authorised project governance state and preserves governed product specifications and project identity.

A failed or refused migration leaves the previous project authority recoverable and does not silently replace project-owned history.

## 7. Core Upgrade Behaviour
For a project-format-1 project, a compatible Core upgrade may replace declared framework-owned Core material while preserving project-owned governance state and the project format.

The candidate distribution may be removed after successful migration or upgrade. No authoritative state required for subsequent bootstrap may depend on the staging directory.

## 8. Repository Cleanliness
A staged candidate distribution beneath the conventional `specforge-dist/` root may remain untracked while migration or upgrade cleanliness checks evaluate the source project. Other uncommitted project changes continue to block mutation.

## 9. External Migration Proof
Batty Joe's real legacy alpha.3 project is the first external migration acceptance case. Planning MUST detect alpha.3 legacy state even when alpha.6 candidate tooling is staged beside it. Migration MUST preserve existing canonical identities, governance history and incomplete or failed work including CHG-0007.

## 10. Version
Current Core product specification: `0.1.0-alpha.6`.
Current project format: `1`.
