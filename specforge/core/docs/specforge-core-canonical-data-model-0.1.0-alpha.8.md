# SpecForge Core Canonical Data Model v0.1.0-alpha.8

This model succeeds v0.1.0-alpha.7 and adds prospective finalisation authority.

## Prospective finalisation authority

Canonical ID: `PFA-NNNN`.

A PFA is immutable human authority granted before implementation for one exact projected material
candidate. It is distinct from proposal approval (`APR`) and checkpoint acceptance (`ACC`).

Required bindings include:

- one `CHG` and its exact current `PROP`;
- the canonical SHA-256 proposal digest;
- human actor, actual grant timestamp and conversation provenance;
- the exact proposal presentation and informed-approval proof;
- exactly one governed change in `scope.change_set`;
- the pre-change material baseline identity;
- the projected `specforge_snapshot` candidate identity;
- the acceptance-requirement set in force when authority is granted.

## Derived checkpoint acceptance

A PFA does not identify or accept a future checkpoint. Once a matching checkpoint exists and passes
normal verification, Core may consume the PFA once and create a normal `ACC-NNNN`.

A PFA-derived ACC:

- is timestamped at actual finalisation time;
- uses `actor.type: automated_system`;
- declares `authority.mode: prospective_exact_candidate_v1`;
- references the PFA as its provenance source;
- preserves the original human principal and grant time;
- binds the exact checkpoint candidate and included-change digest exactly as direct acceptance does.

One PFA may produce at most one ACC. V1 supports only a single-change checkpoint. Any mismatch falls
back to direct human checkpoint acceptance.

## Existing records

Direct ACC records remain valid. No historical record is rewritten or retroactively converted to PFA
semantics. Project format remains 1.
