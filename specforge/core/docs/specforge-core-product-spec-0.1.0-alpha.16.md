# SpecForge Core Product Specification 0.1.0-alpha.16

Alpha.16 makes a project's declared Core/data-model/package identity mechanically verifiable
against reality, and makes the managed upgrade tool that installs a new Core itself compatible
with that verification.

This specification succeeds `specforge-core-product-spec-0.1.0-alpha.15.md`. Alpha.15 and its
normative predecessor chain remain authoritative except where extended below.

## Manifest/installed-Core consistency

A project's `specforge/project.yaml` declares `specforge.core_version` and
`specforge.data_model_version` as its claim about which Core it is running. Core now verifies
that claim: `specforge.core_version` must equal the actually-installed
`specforge/core/core.yaml`'s `core_version`, and `specforge.data_model_version` must equal that
same file's `data_model_version`. Independently, `specforge/core/package.yaml`'s declared
version must also equal the actually-installed `core.yaml`'s `core_version` -- a project manifest
that correctly matches `core.yaml` does not mask a `package.yaml` that has drifted from it. Both
checks are unconditional and universal, depending only on files inside Core's own installed
distribution, and apply identically to the self-hosted Core repository and to any downstream
project regardless of that project's own product.

## Self-referencing specification consistency

A project may make Core's own documentation its authoritative specification. When
`specification.product_specification` resolves to one of Core's own versioned product-spec docs
(matched by filename pattern under `specforge/core/docs/`, never by project identity), the
embedded filename version must agree with the declared `core_version`, and
`specification.current_version` must equal `core_version` -- the project's authoritative
specification is then literally Core's own, so its version identity tracks Core's. When
`specification.canonical_data_model` similarly resolves to one of Core's own versioned
canonical-data-model docs, its embedded filename version must agree with the declared
`data_model_version` alone; this rule never constrains or requires anything of
`current_version`. The two rules are independent by design: a project whose canonical data model
is Core's own but whose product specification is its own governed document (own product
specification, Core canonical data model, own `current_version`) is a supported, already-tested
shape, matching `specforge-migrate.py`'s own established rebind behaviour for the identical case.
An ordinary downstream project whose specification paths do not reference Core's own docs at all
is unaffected by either rule.

## Managed-upgrade compatibility with the installed-state contract

A managed Core upgrade (`specforge-upgrade.py`) now preflights the source project's own
installed-state coherence, evaluated strictly before upgrade authority is established and before
any mutation: the source's declared `core_version`, `data_model_version`, `package.yaml` version,
and any recognised self-referencing specification field's embedded version (and, for
`product_specification`, its `current_version` too) must already be mutually consistent, using
the identical predicate the manifest/installed-Core and self-referencing consistency checks use.
Any disagreement refuses the upgrade outright with a deterministic, actionable blocker -- an
already-drifted source is never silently healed into a validator-clean result with incorrect
provenance, and a stale self-referencing field is never silently repaired or treated as an
unrelated path.

Once the source state is confirmed consistent, the upgrade writes `data_model_version`
transactionally alongside `core_version`, inside the same manifest write and rollback boundary
core-version writes have always used. Each self-referencing specification field, independently,
is then either deterministically rebound to the candidate distribution's equivalently-versioned
doc, or, if the candidate lacks the expected doc, the whole upgrade is refused before any
mutation. An ordinary downstream project's own specification paths are never touched by a managed
upgrade.

## Controlled_v2 material-authorization

A change's material diff can only be committed when an active implementation authorizes it.
That authorization gate now recognises a closed, explicit set of supported lifecycle
profiles, `{controlled_v1, controlled_v2}`, rather than `controlled_v1` alone -- the first
ordinary `controlled_v2` change in a project can authorize its own material diff exactly as a
`controlled_v1` change always could. An unknown or unsupported lifecycle profile is never
treated as an active material authorization; extending the supported set is a deliberate,
explicit addition, never a wildcard or prefix match, so a future or malformed profile string
still fails closed by default.

Every requirement that already applied to a `controlled_v1` active implementation applies
identically to `controlled_v2`, unchanged: the implementation attempt must bind to the
change's current approved proposal (exact proposal id and an exact, digest-bound human
approval of that proposal's current bytes); the attempt's `source_revision.before` must match
the project's currently trusted material baseline exactly; and the attempt's declared material
provider must match the trusted baseline's provider. None of these bindings are loosened for
`controlled_v2` -- `controlled_v2` status alone, without a correctly bound, non-stale
implementation attempt, never authorizes a material diff, and an unauthorized material change
still fails closed with the affected paths named, exactly as it always has.

This behaviour is provider-neutral: a `controlled_v2` active implementation authorizes its
material diff identically whether the project is Git-backed (matched against the trusted Git
revision) or an unmanaged folder using the `specforge_snapshot` provider (matched against the
trusted snapshot digest). Multiple simultaneously active material authorizations for the same
project still fail closed exactly as before -- recognising `controlled_v2` does not relax that
mutual-exclusion requirement.

## Version

Core version: `0.1.0-alpha.16`.

Canonical data model: `0.1.0-alpha.5` (unchanged from alpha.15).

Project format remains `1`.
