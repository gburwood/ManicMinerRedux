# SpecForge Core Product Specification 0.1.0-alpha.10

Alpha.10 persists a trusted material baseline under project-owned evidence. Material drift is checked against that baseline rather than current HEAD, so committing an unapproved edit does not make it trusted.

Approved implementation attempts must begin from the trusted baseline. Retrospective authorization of pre-existing material drift is refused.

Managed Core upgrades establish a bounded upgrade operation before mutation. That operation covers Core replacement and the manifest Core-version rebind only. Product material remains outside upgrade scope.

After validated material is committed, `specforge-authorization.py accept` advances the trusted baseline. Git-backed projects use commits and unmanaged projects use deterministic SpecForge snapshots. Project format remains 1 and the canonical data model remains 0.1.0-alpha.3.
