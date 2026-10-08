# SpecForge Core Product Specification 0.1.0-alpha.11

Alpha.11 makes the distributed Core regression suite project-independent.

Core regression tests must carry or generate every governed reference record required by their assertions. Installed tests must not depend on fixed change, proposal, approval or implementation identifiers from the host project's history.

Portable regression fixtures are created as fresh project-format-1 SpecForge projects. They copy only the installed Core and generate synthetic governed records using the same canonical schemas, exact proposal digests, approval rules and immutable source-revision semantics as normal projects.

The authorization, managed-upgrade, lifecycle and source-revision regression suites must run unchanged when Core is installed in the SpecForge Core development repository, Batty Joe or a minimal independent project with no Core-development CHG-10xx history.

The portability regression statically rejects distributed tests that reintroduce fixed Core-development change identifiers and dynamically installs Core into a minimal host before rerunning the affected suites.

Alpha.11 preserves the alpha.10 durable material-authority model and bounded managed-upgrade authority. Project format remains 1 and the canonical data model remains 0.1.0-alpha.3.
