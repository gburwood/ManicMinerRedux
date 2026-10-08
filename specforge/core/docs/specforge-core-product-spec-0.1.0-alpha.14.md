# SpecForge Core Product Specification 0.1.0-alpha.14

Alpha.14 introduces integration-aware immutable material evidence for controlled completion.

This specification succeeds `specforge-core-product-spec-0.1.0-alpha.13.md`. Alpha.13 and its normative predecessor chain remain authoritative except where extended below.

## Integration-aware material completion

Controlled material implementations now distinguish the immutable implementation state from the immutable state accepted onto the project integration line.

`source_revision.before` and `source_revision.after` continue to describe implementation lineage. Their before-to-after relationship remains strict. Alpha.14 does not weaken implementation evidence in order to accommodate squash or rebase integration.

For changes governed by material-revision profile `immutable_material_v3`, completion additionally requires integration evidence that identifies the accepted target transition and proves canonical material equivalence between the validated implementation and the integrated project state.

For Git-backed projects, integration evidence records:

- the accepted target reference,
- the immutable target revision captured before integration,
- the mechanically discovered integrated revision on the target's first-parent transition,
- the canonical material identity of the implementation state,
- the canonical material identity of the integrated state, and
- the verification method/result.

The integrated revision must descend from the captured target state and must remain on the accepted current project lineage. A freely supplied commit identifier, merge message, pull-request label, actor assertion or boolean equivalence claim is not authoritative.

## Canonical material equivalence

Core computes the implementation and integrated material identities through the same deterministic SpecForge material-snapshot boundary used by existing immutable material evidence.

For Git revisions, Core materialises the named commit and evaluates it with the ordinary project discovery and material-snapshot rules. This prevents a second, divergent definition of material scope.

Manifest-declared changes, decisions, history and evidence roots remain governance bookkeeping and do not alter material identity. `specforge/project.yaml`, installed Core, installed packs, authoritative specifications and product material remain material.

A material mismatch fails closed.

For Git-backed live completion, working-tree capture is evaluated with Git's provider-native diff semantics against `integrated_revision`, including tracked, staged, unstaged and untracked material paths while applying the same governance-bookkeeping and transient exclusions. Checkout-only text normalization such as `core.autocrlf` therefore does not create false material drift. Cryptographic material identity between immutable implementation and integrated commits remains byte-exact.

## Merge, squash and rebase

Normal merges, direct/fast-forward integration, squash merges and rebased integration are supported when the target-line transition is mechanically observed and the canonical integrated material is identical to the validated implementation material.

For normal merge integration, the target-line merge commit is the integrated revision even when the reviewed source commit has the same material tree.

For squash or rebase integration, `source_revision.after` need not be an ancestor of the integrated revision. Instead, Core preserves implementation before-to-after lineage and separately proves target-line provenance plus material equivalence.

This separation removes the need for no-content ancestry-repair merges such as the repair required after the Batty Joe CHG-0012 squash incident.

## Target capture and provenance

Git integration begins by mechanically capturing the accepted target revision before integration. After integration, Core walks the target first-parent path from that captured revision and selects the first target-line commit whose canonical material identity equals the validated implementation material.

This prevents an arbitrary same-tree commit elsewhere in repository history from satisfying integration evidence merely because its content matches.

Content identity plus target-line capture proves that the accepted line advanced to a specific state containing the validated material. It does not claim unique causal derivation when an independent process could theoretically produce identical content. Stronger external provenance, such as signed Git or independently verified hosting-provider merge metadata, may be layered on later.

## Provider neutrality

Projects without Git remain supported through the SpecForge snapshot provider.

For a direct snapshot integration, the source `after` snapshot, integrated revision and integrated material identity are the same deterministic snapshot identity. Material changes must still advance the before-to-after state and current material must match the declared integrated identity at completion.

## Completion and static validation

Under `immutable_material_v3`, a controlled material change may reach `validated` before repository integration but may not reach `completed` until integration evidence is present and verifies successfully.

Completion is fail-closed when target capture is missing, revisions cannot be materialised, provenance is inconsistent, material differs, or the integrated revision is outside the accepted current lineage.

Static validation of completed v3 records recomputes durable integrated material when the provider is available. Persisted implementation-material identity remains historical source proof if a squash/rebase source commit later becomes unreachable after branch deletion or garbage collection.

Historical completed changes governed by earlier profiles remain valid under their applicable historical rules and are not rewritten solely to adopt v3 integration evidence.

## Version

Core version: `0.1.0-alpha.14`.

Canonical data model: `0.1.0-alpha.4`.

Project format remains `1`.
