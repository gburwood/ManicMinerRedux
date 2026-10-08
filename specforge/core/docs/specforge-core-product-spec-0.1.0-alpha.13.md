# SpecForge Core Product Specification 0.1.0-alpha.13

Alpha.13 makes managed Core upgrades reproducible and fully verifiable in external Git projects.

This specification succeeds `specforge-core-product-spec-0.1.0-alpha.12.md`. Alpha.12 and its normative predecessor chain remain authoritative except where extended below.

A project-format-1 manifest may declare a `packs` collection whose directory is absent when the installed pack list is empty. It may also declare a `decisions` collection whose directory is absent when no decision records exist. Because Git does not preserve empty directories, these absent roots are equivalent to empty collections and must not by themselves fail repository validation.

An absent collection must still fail closed when the manifest declares installed material beneath it or canonical records reference required material that cannot be resolved. Required non-collection authorities, framework paths and populated governance roots remain mandatory.

Distributed Core regression tests must be executable independently of the installing project's identity, change numbering, historical records, normative document size and repository-specific example layout. Tests that require governed state must construct explicit portable synthetic fixtures.

Repository completeness is determined from resolvable authoritative documents, explicit normative predecessor chains, non-empty content and the absence of stub or non-authoritative declarations. A Core-specific minimum byte count must not be imposed on an external product specification.

The portability regression gate must execute every other shipped `run-*-tests.py` runner inside an independent minimal project. A managed-upgrade fixture shaped like the Batty Joe external trial must prove that an alpha.8 project can install the current Core, preserve project-owned state, validate after a fresh Git checkout and retain bounded upgrade authority until acceptance.

Existing authorization, transactional rollback, source-revision, lifecycle, migration and repository-completeness protections remain authoritative.

Project format remains 1 and the canonical data model remains 0.1.0-alpha.3.
