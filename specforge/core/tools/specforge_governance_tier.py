#!/usr/bin/env python3
"""Deterministic governance-tier floor for SpecForge Core (CHG-1016).

Ports the proven Batty Joe CHG-0012 classifier's proven pieces (tier ranking, highest-
tier-wins, fail-upward-on-unmatched, fail-closed-on-evaluation-failure) but reuses Core's
own existing governance-bookkeeping/distribution/transient exclusions directly instead of
reimplementing a second material-scope definition.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
from pathlib import Path
import subprocess

import yaml

from specforge_project import (
    GIT_REVISION_RE,
    SNAPSHOT_REVISION_RE,
    approval_gate,
    canonical_artifact_bytes,
    canonical_artifact_digest,
    configured_path,
    git_worktree_root,
    is_distribution_path,
    is_governance_bookkeeping_path,
    is_transient_material_path,
    load_yaml,
    proposal_ever_human_approved,
    read_material_manifest,
    read_project_governance_tier_state,
)
from specforge_project import allocate_next_event_id  # noqa: F401 (re-exported for the CLI)

TIERS = ("LOW", "MEDIUM", "HIGH")
TIER_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
GIT_STATUSES = {"A", "M", "D", "R", "C", "T", "U", "X", "B"}
DECLARED_SCOPE_OPERATIONS = {"add", "modify", "delete", "rename", "copy"}
OPERATION_TO_STATUS = {"add": "A", "modify": "M", "delete": "D", "rename": "R", "copy": "C"}
ACTIVATION_OWNED_PATHS = {"specforge/project.yaml", "specforge/evidence/governance-tier-grandfather.yaml"}


class GovernanceTierError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm(path) -> str:
    path = str(path).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _evidence_root(layout) -> Path:
    paths = layout.manifest.get("paths") or {}
    return (layout.root / paths.get("evidence", "specforge/evidence")).resolve()


def _history_events_root(layout) -> Path:
    paths = layout.manifest.get("paths") or {}
    return (layout.root / paths.get("history", "specforge/history")).resolve() / "events"


def _default_policy_path(layout) -> Path:
    return layout.core_root / "policy" / "governance-tier-policy.yaml"


def _write_event(layout, event_type, entity, related, evidence) -> str:
    event_id = allocate_next_event_id(layout)
    event = {
        "id": event_id,
        "timestamp": _now_iso(),
        "actor": {"type": "automated_system", "id": "specforge-governance-tier"},
        "event_type": event_type,
        "entity": entity,
        "related": related,
        "evidence": evidence,
    }
    event_path = _history_events_root(layout) / f"{event_id}.yaml"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text(yaml.safe_dump(event, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    return event_id


# --------------------------------------------------------------------------
# Policy loading and per-path classification
# --------------------------------------------------------------------------

def load_policy(path) -> dict:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise GovernanceTierError(f"policy_load_failed:{exc}") from exc
    if not isinstance(data, dict):
        raise GovernanceTierError("policy_invalid:not_mapping")
    tiers = data.get("tiers")
    if not isinstance(tiers, dict) or set(tiers) != set(TIERS):
        raise GovernanceTierError("policy_invalid:tiers")
    try:
        ranks = {name: int(tiers[name]) for name in TIERS}
    except Exception as exc:
        raise GovernanceTierError("policy_invalid:tier_rank") from exc
    if not (ranks["LOW"] < ranks["MEDIUM"] < ranks["HIGH"]):
        raise GovernanceTierError("policy_invalid:tier_order")
    default = (data.get("defaults") or {}).get("unmatched_tier")
    if default not in TIERS:
        raise GovernanceTierError("policy_invalid:unmatched_tier")
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise GovernanceTierError("policy_invalid:rules")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise GovernanceTierError("policy_invalid:rule_not_mapping")
        rid, tier, globs = rule.get("id"), rule.get("tier"), rule.get("globs")
        if not isinstance(rid, str) or not rid or rid in seen:
            raise GovernanceTierError("policy_invalid:rule_id")
        seen.add(rid)
        if tier not in TIERS or not isinstance(globs, list) or not globs or not all(isinstance(g, str) and g for g in globs):
            raise GovernanceTierError(f"policy_invalid:rule:{rid}")
        statuses = rule.get("statuses")
        if statuses is not None:
            if not isinstance(statuses, list) or not statuses or not all(isinstance(s, str) and s in GIT_STATUSES for s in statuses):
                raise GovernanceTierError(f"policy_invalid:statuses:{rid}")
    return data


def _matches(path, pattern) -> bool:
    return fnmatch.fnmatchcase(_norm(path), _norm(pattern))


def _within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _host_semantic_matches(path: str, layout) -> list[tuple[str, str]]:
    candidate=(layout.root/path).resolve()
    matches=[]
    protected=[
        configured_path(layout,"tools","specforge/core/tools"),
        configured_path(layout,"schemas","specforge/core/schemas"),
        configured_path(layout,"rules","specforge/core/rules"),
        configured_path(layout,"workflows","specforge/core/workflows"),
        configured_path(layout,"packs","specforge/packs"),
        layout.core_root/"policy", layout.core_root/"migrations",
        layout.core_root/"core.yaml", layout.core_root/"package.yaml",
        layout.manifest_path, layout.governance_root/"SPECFORGE.md",
    ]
    if any(candidate==root.resolve() or (root.is_dir() and _within(candidate,root)) for root in protected):
        matches.append(("protected_project_authority","HIGH"))

    specification=layout.manifest.get("specification") or {}
    for key in ("product_specification","canonical_data_model"):
        value=specification.get(key)
        if isinstance(value,str) and value.strip() and candidate==(layout.root/value).resolve():
            matches.append(("authoritative_project_specification","HIGH"))

    host=(layout.manifest.get("governance_tier") or {}).get("host_classification") or {}
    if not isinstance(host,dict):
        raise GovernanceTierError("host_classification_invalid:not_mapping")
    authoritative=host.get("authoritative_globs") or []
    ordinary=host.get("ordinary_globs") or []
    ordinary_tier=host.get("ordinary_tier","LOW")
    if authoritative and (not isinstance(authoritative,list) or not all(isinstance(x,str) and x for x in authoritative)):
        raise GovernanceTierError("host_classification_invalid:authoritative_globs")
    if ordinary and (not isinstance(ordinary,list) or not all(isinstance(x,str) and x for x in ordinary)):
        raise GovernanceTierError("host_classification_invalid:ordinary_globs")
    if ordinary_tier not in TIERS:
        raise GovernanceTierError("host_classification_invalid:ordinary_tier")
    if any(_matches(path,pattern) for pattern in authoritative):
        matches.append(("host_authoritative_material","HIGH"))
    if any(_matches(path,pattern) for pattern in ordinary):
        matches.append(("host_ordinary_material",ordinary_tier))
    return matches


def classify_entries(entries, policy, layout) -> dict:
    ranks = {k: int(v) for k, v in policy["tiers"].items()}
    material = []
    for raw in entries:
        path = _norm(str(raw.get("path") or ""))
        status = str(raw.get("status") or "").upper()[:1]
        if not path:
            raise GovernanceTierError("diff_entry_missing_path")
        if status not in GIT_STATUSES:
            raise GovernanceTierError(f"diff_entry_invalid_status:{path}:{status}")
        candidate = layout.root / path
        if is_governance_bookkeeping_path(candidate, layout):
            continue
        if is_distribution_path(candidate, layout.root):
            continue
        if is_transient_material_path(candidate, layout):
            continue
        material.append({"path": path, "status": status})

    if not material:
        return {
            "classification": "BLOCKED",
            "material_paths": [],
            "matched_rules": [],
            "path_results": [],
            "blocker": "no_material_paths_after_exclusions",
        }

    default_tier = policy["defaults"]["unmatched_tier"]
    overall_tier, overall_rank = None, -1
    all_rules = []
    path_results = []
    dedup = {(e["path"], e["status"]): e for e in material}
    for _, entry in sorted(dedup.items()):
        path, status = entry["path"], entry["status"]
        semantic_matches=_host_semantic_matches(path,layout)
        matches = [rid for rid,_ in semantic_matches]
        best_tier, best_rank = None, -1
        for rid,tier in semantic_matches:
            rank=ranks[tier]
            if rank>best_rank:
                best_tier,best_rank=tier,rank
        for rule in policy["rules"]:
            statuses = rule.get("statuses")
            if statuses is not None and status not in statuses:
                continue
            if any(_matches(path, pattern) for pattern in rule["globs"]):
                matches.append(rule["id"])
                rank = ranks[rule["tier"]]
                if rank > best_rank:
                    best_tier, best_rank = rule["tier"], rank
        if best_tier is None:
            best_tier, best_rank = default_tier, ranks[default_tier]
            matches = [f"default_unmatched_{default_tier.lower()}"]
        if best_rank > overall_rank:
            overall_tier, overall_rank = best_tier, best_rank
        all_rules.extend(matches)
        path_results.append({"path": path, "status": status, "tier": best_tier, "matched_rules": matches})

    return {
        "classification": overall_tier,
        "material_paths": [item["path"] for item in path_results],
        "matched_rules": sorted(set(all_rules)),
        "path_results": path_results,
        "blocker": None,
    }


# --------------------------------------------------------------------------
# Declared scope (proposal-time, closed vocabulary)
# --------------------------------------------------------------------------

def validate_declared_scope(declared_scope) -> list:
    if not isinstance(declared_scope, list) or not declared_scope:
        raise GovernanceTierError("declared_scope_invalid:missing_or_empty")
    entries = []
    for item in declared_scope:
        if not isinstance(item, dict):
            raise GovernanceTierError("declared_scope_invalid:entry_not_mapping")
        operation = item.get("operation")
        if operation not in DECLARED_SCOPE_OPERATIONS:
            raise GovernanceTierError(f"declared_scope_invalid:operation:{operation}")
        status = OPERATION_TO_STATUS[operation]
        if operation in ("rename", "copy"):
            from_path, to_path = item.get("from"), item.get("to")
            if not isinstance(from_path, str) or not from_path or not isinstance(to_path, str) or not to_path:
                raise GovernanceTierError("declared_scope_invalid:rename_copy_missing_from_to")
            entries.append({"path": from_path, "status": status})
            entries.append({"path": to_path, "status": status})
        else:
            path = item.get("path")
            if not isinstance(path, str) or not path:
                raise GovernanceTierError("declared_scope_invalid:missing_path")
            entries.append({"path": path, "status": status})
    return entries


# --------------------------------------------------------------------------
# Real-diff (completion-time) entries: Git and provider-neutral snapshot
# --------------------------------------------------------------------------

def _git(layout, *args) -> str:
    try:
        result = subprocess.run(["git", "-C", str(layout.root), *args], capture_output=True, text=True, timeout=60)
    except Exception as exc:
        raise GovernanceTierError(f"git_execution_failed:{exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise GovernanceTierError(f"git_failed:{' '.join(args)}:{detail}")
    return result.stdout


def _parse_name_status(text) -> list:
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        raw_status = fields[0].strip()
        status = raw_status[:1].upper()
        if status not in GIT_STATUSES:
            raise GovernanceTierError(f"git_diff_unknown_status:{raw_status}")
        if status in {"R", "C"}:
            if len(fields) != 3:
                raise GovernanceTierError(f"git_diff_malformed_rename_copy:{line}")
            entries.append({"path": _norm(fields[1]), "status": status})
            entries.append({"path": _norm(fields[2]), "status": status})
        else:
            if len(fields) != 2:
                raise GovernanceTierError(f"git_diff_malformed_entry:{line}")
            entries.append({"path": _norm(fields[1]), "status": status})
    return entries


def _digest_of(value):
    match = SNAPSHOT_REVISION_RE.fullmatch(str(value).strip().lower())
    return match.group(1) if match else None


def _snapshot_diff_entries(before_entries, after_entries) -> list:
    """Provider-neutral add/modify/delete/rename/copy candidates, failing upward on ambiguity.

    Rename requires a vanished source (structurally impossible otherwise), so R-candidates
    only appear when the diff has at least one deleted path. Copy does not require a vanished
    source (`a.txt` unchanged, `b.txt` added with edited/copied content is a legitimate copy
    with no deletion anywhere), and with only before/after path+hash manifests there is no way
    to rule that out for any added path — an information-theoretic limit, not a gap to code
    around with heuristic similarity. So every added path unconditionally also gets a `C`
    candidate; only the deliberate, documented tradeoff is that pure-addition diffs are no
    longer provably free of C-status matches (they remain provably free of R-status matches,
    since nothing vanished).
    """
    before_digest = {e["path"]: e["sha256"] for e in before_entries}
    after_digest = {e["path"]: e["sha256"] for e in after_entries}
    before_paths = set(before_digest)
    after_paths = set(after_digest)

    deleted_paths = before_paths - after_paths
    added_paths = after_paths - before_paths
    persisting_paths = before_paths & after_paths

    entries = []
    for path in sorted(persisting_paths):
        if before_digest[path] != after_digest[path]:
            entries.append({"path": path, "status": "M"})

    for path in sorted(deleted_paths):
        entries.append({"path": path, "status": "D"})
        if added_paths:
            entries.append({"path": path, "status": "R"})

    for path in sorted(added_paths):
        entries.append({"path": path, "status": "A"})
        entries.append({"path": path, "status": "C"})
        if deleted_paths:
            entries.append({"path": path, "status": "R"})

    return entries


def actual_diff_entries(layout, provider, before, after) -> list:
    if provider == "git":
        if git_worktree_root(layout) is None:
            raise GovernanceTierError("actual_diff_provider_unavailable:git")
        text = _git(layout, "diff", "--name-status", "-C", "--find-copies-harder", str(before), str(after), "--")
        return _parse_name_status(text)
    if provider == "specforge_snapshot":
        before_digest = _digest_of(before)
        after_digest = _digest_of(after)
        if not before_digest or not after_digest:
            raise GovernanceTierError("snapshot_revision_identity_invalid")
        before_manifest = read_material_manifest(layout, before_digest)
        if before_manifest is None:
            raise GovernanceTierError("snapshot_before_manifest_missing")
        after_manifest = read_material_manifest(layout, after_digest)
        if after_manifest is None:
            raise GovernanceTierError("snapshot_after_manifest_missing")
        return _snapshot_diff_entries(before_manifest["entries"], after_manifest["entries"])
    raise GovernanceTierError(f"actual_diff_provider_unsupported:{provider}")


# --------------------------------------------------------------------------
# Policy archiving
# --------------------------------------------------------------------------

def archive_policy(layout, policy_path) -> str:
    digest = canonical_artifact_digest(Path(policy_path))
    archive_root = _evidence_root(layout) / "governance-tier-policy"
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / f"{digest}.yaml"
    if not target.is_file():
        target.write_text(canonical_artifact_bytes(Path(policy_path)).decode("utf-8"), encoding="utf-8", newline="\n")
    return digest


def verify_policy_archive(layout, digest):
    target = _evidence_root(layout) / "governance-tier-policy" / f"{digest}.yaml"
    if not target.is_file():
        return None
    if canonical_artifact_digest(target) != digest:
        return None
    try:
        return load_policy(target)
    except GovernanceTierError:
        return None


# --------------------------------------------------------------------------
# Preparation (before any human approval; its own committed governance action)
# --------------------------------------------------------------------------

def prepare(layout, recs, proposal_id) -> dict:
    if proposal_id not in recs:
        return {"prepared": False, "blockers": ["proposal_missing"]}
    proposal, proposal_path = recs[proposal_id]
    change_id = proposal.get("change")
    if change_id not in recs:
        return {"prepared": False, "blockers": ["change_missing"]}
    chg, _chg_path = recs[change_id]

    declared_profile = (chg.get("governance") or {}).get("lifecycle_enforcement")
    if declared_profile not in ("controlled_v2", "controlled_v3"):
        return {"prepared": False, "blockers": ["change_not_declared_controlled_v2_or_v3"]}

    state = read_project_governance_tier_state(layout)
    if state["status"] != "active" or state["effective_lifecycle_profile"] != "controlled_v2":
        return {"prepared": False, "blockers": ["project_not_active_for_controlled_v2"]}

    if not approval_gate(layout, recs, chg):
        return {"prepared": False, "blockers": ["proposal_already_validly_approved"]}
    if proposal_ever_human_approved(recs, proposal_id):
        return {"prepared": False, "blockers": ["proposal_previously_human_approved"]}

    policy_path = _default_policy_path(layout)
    try:
        entries = validate_declared_scope(proposal.get("declared_scope"))
        policy = load_policy(policy_path)
        classification = classify_entries(entries, policy, layout)
        if classification.get("blocker"):
            raise GovernanceTierError(classification["blocker"])
    except GovernanceTierError as exc:
        return {"prepared": False, "blockers": [str(exc)]}

    digest = archive_policy(layout, policy_path)
    proposal.setdefault("governance_tier", {})
    proposal["governance_tier"]["policy_digest"] = digest
    proposal["governance_tier"]["calculated_minimum"] = classification["classification"]
    proposal_path.write_text(
        yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )

    event_id = _write_event(
        layout,
        "governance_tier_prepared",
        {"type": "proposal", "id": proposal_id},
        {"change": change_id},
        {"policy_digest": digest, "calculated_minimum": classification["classification"]},
    )

    return {
        "prepared": True,
        "blockers": [],
        "policy_digest": digest,
        "calculated_minimum": classification["classification"],
        "event": event_id,
    }


def stale_policy_check(layout, proposal) -> list:
    recorded = (proposal.get("governance_tier") or {}).get("policy_digest")
    if not recorded:
        return ["governance_tier_not_prepared"]
    try:
        current_digest = canonical_artifact_digest(_default_policy_path(layout))
    except Exception as exc:
        return [f"policy_load_failed:{exc}"]
    return [] if current_digest == recorded else ["stale_policy_digest"]


def floor_check(layout, proposal) -> list:
    governance_tier = proposal.get("governance_tier") or {}
    policy_digest = governance_tier.get("policy_digest")
    requested = governance_tier.get("requested")
    if not policy_digest:
        return ["governance_tier_not_prepared"]
    if requested not in TIERS:
        return ["governance_tier_requested_missing_or_invalid"]
    policy = verify_policy_archive(layout, policy_digest)
    if policy is None:
        return ["governance_tier_policy_archive_invalid_or_missing"]
    try:
        entries = validate_declared_scope(proposal.get("declared_scope"))
        classification = classify_entries(entries, policy, layout)
        if classification.get("blocker"):
            raise GovernanceTierError(classification["blocker"])
    except GovernanceTierError as exc:
        return [f"declared_scope_invalid_or_unclassifiable:{exc}"]
    minimum = classification["classification"]
    if TIER_ORDER[requested] < TIER_ORDER[minimum]:
        return ["governance_tier_floor_violation"]
    return []


# --------------------------------------------------------------------------
# Fresh-project initialization (pre-history, pre-baseline only)
# --------------------------------------------------------------------------

def initialize_fresh_project(layout, recs) -> dict:
    """Initialize deterministic governance-tier state before the first governed project baseline."""
    state = read_project_governance_tier_state(layout)
    if state["status"] == "corrupted":
        return {"initialized": False, "blockers": ["governance_tier_activation_state_corrupted"]}
    if state["status"] != "not_activated":
        return {"initialized": False, "blockers": [f"project_already_{state['status']}"]}

    governed_prefixes = ("CHG-", "APR-", "IMP-", "CHK-", "ACC-", "PFA-", "CAP-")
    existing = sorted(rid for rid in recs if str(rid).startswith(governed_prefixes))
    if existing:
        return {
            "initialized": False,
            "blockers": ["fresh_project_governed_history_exists"],
            "existing_records": existing,
        }

    authority_path = _evidence_root(layout) / "material-authority.yaml"
    if authority_path.is_file():
        return {"initialized": False, "blockers": ["fresh_project_trusted_material_baseline_exists"]}

    evidence_path = _evidence_root(layout) / "governance-tier-grandfather.yaml"
    if evidence_path.exists():
        return {"initialized": False, "blockers": ["fresh_project_governance_tier_evidence_already_exists"]}

    evidence = {
        "version": 1,
        "captured_at": _now_iso(),
        "provenance": "fresh_project_bootstrap_v1",
        "proposal_digests": [],
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        yaml.safe_dump(evidence, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )
    grandfather_digest = canonical_artifact_digest(evidence_path)

    manifest_path = layout.manifest_path
    manifest = load_yaml(manifest_path)
    manifest["governance_tier"] = {
        "enforcement_profile": "deterministic_tier_v1",
        "grandfather_digest": grandfather_digest,
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )

    event_id = _write_event(
        layout,
        "governance_tier_initialized",
        {"type": "project", "id": "governance_tier"},
        {"bootstrap": "fresh_project_bootstrap_v1"},
        {
            "grandfather_digest": grandfather_digest,
            "proposal_count": 0,
            "provenance": "fresh_project_bootstrap_v1",
        },
    )
    return {
        "initialized": True,
        "blockers": [],
        "grandfather_digest": grandfather_digest,
        "proposal_count": 0,
        "provenance": "fresh_project_bootstrap_v1",
        "event": event_id,
    }


# --------------------------------------------------------------------------
# Activation (authorized, provider-neutral, one-time per project)
# --------------------------------------------------------------------------

def activate(layout, recs, authorizing_change_id) -> dict:
    if authorizing_change_id not in recs:
        return {"activated": False, "blockers": ["authorizing_change_missing"]}
    auth_chg, _ = recs[authorizing_change_id]

    blockers = []
    if approval_gate(layout, recs, auth_chg):
        blockers.append("authorizing_change_not_validly_approved")

    state = read_project_governance_tier_state(layout)
    declared_profile = (auth_chg.get("governance") or {}).get("lifecycle_enforcement")
    if declared_profile != state["effective_lifecycle_profile"]:
        blockers.append("authorizing_change_profile_mismatch")

    auth_proposal_id = (auth_chg.get("proposal") or {}).get("current")
    auth_proposal = recs.get(auth_proposal_id)
    if auth_proposal is None:
        blockers.append("authorizing_proposal_missing")
    else:
        artifacts_expected = auth_proposal[0].get("artifacts_expected") or {}
        declared_paths = set()
        for value in artifacts_expected.values():
            if isinstance(value, list):
                declared_paths.update(str(v) for v in value)
        if not ACTIVATION_OWNED_PATHS.issubset(declared_paths):
            blockers.append("authorizing_proposal_scope_insufficient")

    if blockers:
        return {"activated": False, "blockers": sorted(set(blockers))}

    if state["status"] != "not_activated":
        return {"activated": False, "blockers": [f"project_already_{state['status']}"]}

    proposal_digests = []
    for rid, item in recs.items():
        if not rid.startswith("CHG-"):
            continue
        candidate, _path = item
        if (candidate.get("governance") or {}).get("lifecycle_enforcement") != "controlled_v1":
            continue
        if approval_gate(layout, recs, candidate):
            continue
        candidate_proposal_id = (candidate.get("proposal") or {}).get("current")
        if candidate_proposal_id not in recs:
            continue
        proposal_digests.append(canonical_artifact_digest(recs[candidate_proposal_id][1]))
    proposal_digests = sorted(set(proposal_digests))

    grandfather_evidence = {
        "version": 1,
        "captured_at": _now_iso(),
        "authorizing_change": authorizing_change_id,
        "proposal_digests": proposal_digests,
    }
    evidence_path = _evidence_root(layout) / "governance-tier-grandfather.yaml"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        yaml.safe_dump(grandfather_evidence, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )
    grandfather_digest = canonical_artifact_digest(evidence_path)

    manifest_path = layout.manifest_path
    manifest = load_yaml(manifest_path)
    manifest["governance_tier"] = {
        "enforcement_profile": "deterministic_tier_v1",
        "grandfather_digest": grandfather_digest,
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )

    event_id = _write_event(
        layout,
        "governance_tier_activated",
        {"type": "project", "id": "governance_tier"},
        {"authorizing_change": authorizing_change_id},
        {"grandfather_digest": grandfather_digest, "proposal_count": len(proposal_digests)},
    )

    return {
        "activated": True,
        "blockers": [],
        "grandfather_digest": grandfather_digest,
        "proposal_count": len(proposal_digests),
        "event": event_id,
    }


# --------------------------------------------------------------------------
# Completion-time dual-policy classification against the verified integration endpoint
# --------------------------------------------------------------------------

def _integrated_endpoint(implementation):
    integration = implementation.get("integration") or {}
    provider = integration.get("provider")
    endpoint = integration.get("integrated_revision")
    if not endpoint:
        material = integration.get("integrated_material") or {}
        endpoint = material.get("revision")
    return provider, endpoint


def completion_tier(layout, recs, implementation) -> dict:
    proposal_id = implementation.get("proposal")
    if proposal_id not in recs:
        return {"valid": False, "blockers": ["governed_proposal_missing"]}
    proposal, _ = recs[proposal_id]
    governance_tier = proposal.get("governance_tier") or {}
    requested = governance_tier.get("requested")
    policy_digest = governance_tier.get("policy_digest")
    if requested not in TIERS or not policy_digest:
        return {"valid": False, "blockers": ["governed_tier_unresolved"]}

    archived_policy = verify_policy_archive(layout, policy_digest)
    if archived_policy is None:
        return {"valid": False, "blockers": ["governance_tier_policy_archive_invalid_or_missing"]}

    try:
        current_policy = load_policy(_default_policy_path(layout))
    except GovernanceTierError as exc:
        return {"valid": False, "blockers": [str(exc)]}

    source_revision = implementation.get("source_revision") or {}
    before = source_revision.get("before")
    provider, after = _integrated_endpoint(implementation)
    if not before or not provider or not after:
        return {"valid": False, "blockers": ["completion_tier_endpoint_unresolved"]}

    try:
        entries = actual_diff_entries(layout, provider, before, after)
        archived_result = classify_entries(entries, archived_policy, layout)
        current_result = classify_entries(entries, current_policy, layout)
    except GovernanceTierError as exc:
        return {"valid": False, "blockers": [str(exc)]}

    if archived_result.get("blocker") or current_result.get("blocker"):
        return {"valid": False, "blockers": [archived_result.get("blocker") or current_result.get("blocker")]}

    archived_tier = archived_result["classification"]
    current_tier = current_result["classification"]
    effective_actual = archived_tier if TIER_ORDER[archived_tier] >= TIER_ORDER[current_tier] else current_tier

    blockers = []
    if TIER_ORDER[effective_actual] > TIER_ORDER[requested]:
        blockers.append("governance_tier_escalation")

    return {
        "valid": True,
        "blockers": blockers,
        "requested": requested,
        "effective_actual": effective_actual,
        "archived_tier": archived_tier,
        "current_tier": current_tier,
    }
