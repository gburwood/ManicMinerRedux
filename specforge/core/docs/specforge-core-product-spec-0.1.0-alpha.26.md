# SpecForge Core Product Specification 0.1.0-alpha.26

This candidate succeeds alpha.24 and adds bounded integrity validation without changing project format
1 or the canonical data model, which remains 0.1.0-alpha.10.

## Integrity profiles

Core exposes two complementary integrity profiles.

### incremental_integrity_v1

The routine path starts from a previously validated integrity receipt. It proves that the current Git
history descends from that receipt, compares the current semantic fingerprints with the trusted
validator/schema/policy fingerprints, derives canonical-record work from Git diff and validates only
the changed records plus the historical records required by their reference and authority closure.

Routine cost is therefore a function of the current delta and closure rather than total project
history.

### full_integrity_v1

The deep-audit path preserves exhaustive repository validation. It reconstructs canonical inventory
from repository reality, validates the complete record set and rebuilds the integrity state. It is
used for initialisation, scheduled deep audit and whenever incremental trust assumptions cannot be
proven.

## Integrity receipt state

The non-canonical project evidence file `specforge/evidence/integrity/state.json` records:

- the validated Git revision and tree
- Core and integrity profile versions
- validator, schema-set and governance-policy fingerprints
- total canonical-record count and counts by kind
- monotonic numeric maxima by record kind
- a 256-way digest-bound partition accumulator
- compact historical path exceptions
- consumed CAP/PFA authority ranges
- mutable active-lifecycle identifiers
- the most recent successful full-audit metadata
- metrics from the most recent validation

After validation, the state is committed in a state-only receipt commit whose parent is the validated
revision. The receipt commit therefore anchors the integrity state without requiring a self-referential
hash inside the state file.

Counts are guardrails rather than the trust root. Git ancestry/tree identity and digest-bound registry
accounting prevent a same-count historical substitution from being silently accepted.

## Routine delta validation

Incremental mode obtains canonical work from Git name-status diff between the validated revision and
the current revision. Added or modified records are schema-validated. References into unchanged
history are resolved directly against the trusted Git tree and only those closure records are parsed.

Modifying immutable historical authority or lifecycle records, deleting or renaming historical
records, changing identity, corrupting receipt state or changing validator/schema/policy semantics
causes a deep-audit escalation. Active lifecycle records recorded as mutable may advance through their
normal controlled states without forcing a history rebuild.

Replay-sensitive CAP/PFA consumption is carried forward in compact numeric ranges and checked on new
checkpoint acceptance.

## Scheduled deep audit

Dogfood runs `full_integrity_v1` monthly. Project policy contains a warning age and a maximum age for
the last successful full audit. A warning is visible before expiry. If the maximum age is exceeded,
routine validation cannot establish trust and `auto` requires the deep audit.

Validator, schema or governance-policy changes always require a successful full audit before the new
semantic baseline can be trusted.

## Machine-readable progress

Both profiles publish progress rows containing validation mode, phase, processed count, total when
known, elapsed seconds and current sub-stage.

`managed_progress_v1` consumes fresh integrity progress and surfaces actual validator state. Generic
heartbeat prose must not replace fresher counters or sub-stage evidence. Unknown totals remain unknown;
percentages and ETAs are never invented.

## Scalability requirement

A synthetic fixture representing at least 1,000,000 previously validated identities must demonstrate
that routine validation performs no full historical YAML scan and that index work is bounded by the
current delta and touched partitions.

Full/incremental parity fixtures cover duplicate identities, broken references, invalid approval
binding, CAP/PFA replay, completion without required evidence and governance-tier violations.

## Compatibility and upgrade

Alpha.24 repositories upgrade without rewriting historical lifecycle evidence. Because integrity
semantics change in alpha.25, the first alpha.25 validation is a full audit that establishes the first
incremental receipt. Existing material, controlled_v3 governance and managed_progress_v1 remain
compatible.


## Project-definition reconciliation modes

Guard-v3 project-definition reconciliation has two explicit modes. `context_only` binds the exact
authoritative `PROJECT.md` path and complete-file SHA-256 while keeping the durable definition outside
implementation scope. Current-work state is carried by guarded session evidence; no project-definition
apply operation exists in this mode. The durable digest is rechecked at presentation, approval, lifecycle
transition, continuation and completion.

`durable_update` preserves the prepared-complete-file model and requires `PROJECT.md` to be explicitly
in approved implementation scope. Historical records without a mode retain the earlier durable-update
interpretation. Unknown modes fail closed, and alpha.26+ reconciliation records require an explicit mode.
