# SpecForge Core Product Specification v0.1.0-alpha.9

Status: Draft

## Controlled implementation authorization
Alpha.8 remains normative except where extended here.

In controlled mode, material implementation requires an active implementation attempt bound to the current exactly approved proposal and to a verifiable pre-implementation material state.

Before material files are changed, the implementation attempt must exist and record its starting material revision. Governance-only bookkeeping does not count as material mutation.

Repository validation must fail when material files differ and no active controlled implementation authorization exists. Git-backed projects compare against the authorized starting commit. Snapshot-backed projects bind the attempt to the deterministic starting snapshot.

Core provides `specforge-authorization.py` for this check, and canonical validation invokes it.

A fresh session must establish implementation authority and run the authorization guard before material mutation.

Project format remains `1`. Canonical data model remains `0.1.0-alpha.3`.
