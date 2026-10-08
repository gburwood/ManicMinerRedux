#!/usr/bin/env python3
"""Executable lifecycle gates for SpecForge Controlled mode."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import re
import os
import subprocess
import sys

try:
    import yaml
except ImportError:
    print(json.dumps({"permitted": False, "blockers": ["PyYAML unavailable"]}))
    sys.exit(2)

from specforge_project import (
    approval_gate,
    canonical_artifact_digest,
    discover_layout,
    iter_record_files,
    load_yaml,
    material_snapshot,
    read_project_governance_tier_state,
    relative,
    verify_source_revision,
)
from specforge_integration import (
    PROFILE as INTEGRATION_PROFILE,
    verified_material_bridge,
    verify_integration_evidence,
)
from specforge_governance_tier import completion_tier, floor_check, stale_policy_check
from specforge_authority import evaluate as evaluate_material_authority


RECONCILIATION_CONTEXT_ONLY = "context_only"
RECONCILIATION_DURABLE_UPDATE = "durable_update"
SUPPORTED_RECONCILIATION_MODES = {RECONCILIATION_CONTEXT_ONLY, RECONCILIATION_DURABLE_UPDATE}


def _alpha_revision(value):
    match=re.search(r"-alpha\.(\d+)$",str(value or ""))
    return int(match.group(1)) if match else None

def _reconciliation_scope_paths(proposal):
    out=set()
    for item in proposal.get("declared_scope") or []:
        if not isinstance(item,dict): continue
        for key in ("path","to"):
            value=item.get(key)
            if isinstance(value,str) and value.strip(): out.add(value.strip().replace("\\","/").lstrip("./"))
    return out

def _reconciliation_blockers(layout,recs,chg):
    if (chg.get("governance") or {}).get("lifecycle_enforcement")!="controlled_v3": return []
    proposal_id=(chg.get("proposal") or {}).get("current")
    item=recs.get(str(proposal_id))
    if not item: return ["current_proposal_missing"]
    proposal=item[0]; binding=proposal.get("project_definition_reconciliation") or {}
    if not binding: return []
    mode=binding.get("mode")
    if mode is None:
        revision=_alpha_revision(proposal.get("proposed_specification_version"))
        if revision is not None and revision>=26: return ["project_definition_reconciliation_mode_missing"]
        mode=RECONCILIATION_DURABLE_UPDATE
    if mode not in SUPPORTED_RECONCILIATION_MODES: return ["project_definition_reconciliation_mode_unknown"]
    path=str(binding.get("path") or "").replace("\\","/").lstrip("./")
    scope=_reconciliation_scope_paths(proposal)
    if mode==RECONCILIATION_CONTEXT_ONLY:
        blockers=[]
        if path in scope: blockers.append("project_definition_context_only_in_scope")
        target=(layout.root/str(binding.get("path") or "PROJECT.md")).resolve()
        if not target.is_file(): blockers.append("project_definition_missing")
        elif hashlib.sha256(target.read_bytes()).hexdigest()!=binding.get("sha256"): blockers.append("project_definition_context_digest_changed")
        return blockers
    return [] if path in scope else ["project_definition_not_in_approved_scope"]


def records(layout):
    out = {}
    for path in iter_record_files(layout):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id"):
            out[str(data["id"])] = (data, path)
    return out


def manifest_path(layout, key, default=None):
    paths = layout.manifest.get("paths") or {}
    value = paths.get(key, default)
    if not value:
        return None
    return (layout.root / value).resolve()


def _python_env():
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def material_revision_profile(layout):
    core = layout.core_root / "core.yaml"
    try:
        data = load_yaml(core)
    except Exception:
        return None
    return ((data or {}).get("material_revision") or {}).get("verification_profile")


def _requires_fresh_governance_tier(layout):
    """Alpha.22+ managed/activated controlled_v3 projects require integrity-anchored tier state."""
    try:
        core = load_yaml(layout.core_root / "core.yaml")
    except Exception:
        return False
    integrity = (core or {}).get("managed_interaction_integrity") or {}
    if integrity.get("profile") != "controlled_v3":
        return False
    experience = layout.manifest.get("experience") or {}
    managed_project = experience.get("profile") == "invisible_managed_v1"
    activation_declared = "governance_tier" in layout.manifest
    if not managed_project and not activation_declared:
        return False
    version = str((core or {}).get("core_version") or "")
    marker = "-alpha."
    if marker not in version:
        return True
    try:
        return int(version.rsplit(marker, 1)[1]) >= 22
    except (TypeError, ValueError):
        return False


def bootstrap(root, validation_change=None):
    blockers = []
    details = {}
    try:
        layout = discover_layout(root)
    except Exception as exc:
        return {"ready": False, "blockers": [f"project_discovery_failed:{exc}"], "details": details}

    details["project_format_mode"] = layout.mode
    details["manifest"] = relative(layout, layout.manifest_path)
    sf = layout.manifest.get("specforge") or {}
    details["core_version"] = sf.get("core_version")
    details["project_format"] = sf.get("project_format")
    details["material_revision_profile"] = material_revision_profile(layout)

    try:
        material_authority = evaluate_material_authority(layout)
    except Exception as exc:
        material_authority = {
            "valid": False,
            "authorized": False,
            "blockers": ["material_authority_evaluation_failed"],
            "details": {"error": str(exc)},
        }
    details["material_authority"] = material_authority
    material_reconciliation = (material_authority.get("details") or {}).get("reconciliation") or {}
    if material_reconciliation:
        details["material_reconciliation"] = material_reconciliation
        blockers.append("material_reconciliation_required")
        blockers.extend(material_authority.get("blockers") or [])

    if _requires_fresh_governance_tier(layout):
        tier_state = read_project_governance_tier_state(layout)
        details["governance_tier"] = {
            "status": tier_state.get("status"),
            "enforcement_profile": tier_state.get("tier_enforcement_profile"),
        }
        if tier_state.get("status") == "not_activated":
            blockers.append("governance_tier_not_initialized")
        elif tier_state.get("status") != "active":
            blockers.append("governance_tier_activation_state_corrupted")
        elif tier_state.get("tier_enforcement_profile") != "deterministic_tier_v1":
            blockers.append("governance_tier_profile_mismatch")

    if layout.mode == "project_format_1":
        entry = layout.root / "specforge" / "SPECFORGE.md"
        if not entry.is_file(): blockers.append("missing:specforge/SPECFORGE.md")
    else:
        entry = layout.root / "SPECFORGE.md"
        if not entry.is_file(): blockers.append("missing:SPECFORGE.md")

    specification = layout.manifest.get("specification") or {}
    for key in ("product_specification", "canonical_data_model"):
        value = specification.get(key)
        target = (layout.root / value).resolve() if value else None
        if not target or not target.is_file(): blockers.append(f"missing_authority:{key}")

    required_paths = ["rules", "workflows", "changes", "history"]
    installed_packs = layout.manifest.get("packs") or []
    if layout.mode == "project_format_1": required_paths += ["core", "packs", "decisions", "evidence"]
    for key in required_paths:
        target = manifest_path(layout, key)
        if target and target.exists():
            continue
        if key == "decisions":
            continue
        if key == "packs" and not installed_packs:
            continue
        blockers.append(f"missing_path:{key}")

    if layout.mode == "project_format_1":
        pack_tool = layout.tool_root / "specforge-pack.py"
        if not pack_tool.is_file():
            blockers.append("pack_resolver_missing")
        else:
            result = subprocess.run(
                [sys.executable, "-B", str(pack_tool), "--root", str(layout.root), "--json"],
                capture_output=True,
                text=True,
                env=_python_env(),
            )
            try: pack_details = json.loads(result.stdout or "{}")
            except Exception: pack_details = {"permitted": False, "blockers": ["pack_resolver_output_invalid"]}
            details["packs"] = pack_details
            if result.returncode or not pack_details.get("permitted"):
                blockers += ["pack:" + x for x in pack_details.get("blockers", ["validation_failed"])]

    validator = layout.tool_root / "validate-specforge.py"
    if not validator.is_file():
        blockers.append("validator_missing")
    else:
        try:
            command = [sys.executable, "-B", str(validator), str(layout.root)]
            if validation_change:
                command += ["--change", str(validation_change)]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                env=_python_env(),
            )
            details["repository_validation"] = {"status": "passed" if result.returncode == 0 else "failed", "output": (result.stdout + result.stderr).strip()}
            if result.returncode: blockers.append("repository_validation_failed")
        except Exception as exc:
            details["repository_validation"] = {"status": "blocked", "reason": str(exc)}
            blockers.append("repository_validation_blocked")

    return {"ready": not blockers, "blockers": sorted(set(blockers)), "details": details}


def _active_profile_and_v2_extras(layout, recs, chg, raw_profile):
    """The controlled_v2 fresh-approval-only checks, run at target=='approved' for every
    controlled change regardless of declared profile.

    Applies the active-profile/grandfather rule uniformly first (a v2-active project must
    refuse a fresh, ungrandfathered controlled_v1 declaration just as much as a mismatched
    v2 one); only once that profile is accepted, and only if it is controlled_v2, does
    preparation completeness / staleness / the floor additionally apply. Never re-run for
    any later transition (in_progress, implemented, validated, completed).
    """
    blockers = []
    state = read_project_governance_tier_state(layout)
    if state["status"] == "corrupted":
        return ["governance_tier_activation_state_corrupted"]

    proposal_id = (chg.get("proposal") or {}).get("current")
    proposal_digest = None
    if proposal_id in recs:
        try:
            proposal_digest = canonical_artifact_digest(recs[proposal_id][1])
        except Exception:
            proposal_digest = None
    grandfathered = proposal_digest is not None and proposal_digest in state["grandfather_digests"]

    successor_v3 = (
        raw_profile == "controlled_v3"
        and state["effective_lifecycle_profile"] == "controlled_v2"
    )
    if raw_profile != state["effective_lifecycle_profile"] and not grandfathered and not successor_v3:
        return ["governance_tier_profile_mismatch"]

    if raw_profile not in ("controlled_v2", "controlled_v3"):
        return blockers

    if proposal_id not in recs:
        return ["current_proposal_missing"]
    proposal, _ = recs[proposal_id]
    if not (proposal.get("governance_tier") or {}).get("policy_digest"):
        return ["governance_tier_not_prepared"]
    blockers += stale_policy_check(layout, proposal)
    blockers += floor_check(layout, proposal)
    return blockers


def _implementation_verification(layout, implementation, historical_terminal):
    source_revision = implementation.get("source_revision") or {}
    integration = implementation.get("integration") or {}
    declared_profile = integration.get("profile") or source_revision.get("verification_profile")
    current_profile = material_revision_profile(layout)
    material_effects = source_revision.get("material_effects", True) is not False

    if historical_terminal:
        if integration.get("profile") == INTEGRATION_PROFILE:
            return verify_integration_evidence(layout, implementation, mode="static")
        return verify_source_revision(
            layout,
            source_revision,
            mode="static",
            require_provider=False,
        )

    if current_profile == INTEGRATION_PROFILE:
        if not material_effects:
            return verify_source_revision(
                layout,
                source_revision,
                mode="transition",
                require_provider=True,
            )
        if declared_profile != INTEGRATION_PROFILE or integration.get("profile") != INTEGRATION_PROFILE:
            return {
                "valid": False,
                "blockers": ["integration_evidence_required_by_current_material_profile"],
                "details": {"required_profile": INTEGRATION_PROFILE, "declared_profile": declared_profile},
            }
        return verify_integration_evidence(layout, implementation, mode="transition")

    return verify_source_revision(
        layout,
        source_revision,
        mode="transition",
        require_provider=True,
    )


def _parse_time(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _controlled_v3_approval_time(layout, recs, chg):
    if (chg.get("governance") or {}).get("lifecycle_enforcement") != "controlled_v3":
        return None
    proposal_id = (chg.get("proposal") or {}).get("current")
    if proposal_id not in recs:
        return None
    actual = canonical_artifact_digest(recs[proposal_id][1])
    for approval_id in chg.get("approvals") or []:
        item = recs.get(str(approval_id))
        if not item:
            continue
        approval = item[0]
        evidence = approval.get("evidence") or {}
        if (
            approval.get("decision") == "approved"
            and approval.get("proposal") == proposal_id
            and (approval.get("actor") or {}).get("type") == "human"
            and (evidence.get("proposal_digest") or (approval.get("scope") or {}).get("proposal_sha256")) == actual
        ):
            return _parse_time(approval.get("timestamp"))
    return None


def _controlled_v3_implementation_chronology_blockers(layout, recs, chg, implementation):
    if (chg.get("governance") or {}).get("lifecycle_enforcement") != "controlled_v3":
        return []
    approved_at = _controlled_v3_approval_time(layout, recs, chg)
    if approved_at is None:
        return ["controlled_v3_approval_time_missing"]
    started_at = _parse_time(implementation.get("started_at"))
    if started_at is None:
        return ["controlled_v3_implementation_start_missing"]
    if started_at < approved_at:
        return ["controlled_v3_implementation_predates_approval"]
    return []


def _passed_implementation_record(implementation):
    if implementation.get("outcome") != "passed":
        return False
    checks = implementation.get("validation_checks") or []
    required = [item for item in checks if item.get("required")]
    if not required or any(item.get("status") != "passed" for item in required):
        return False
    tests = implementation.get("tests") or {}
    return tests.get("status") == "passed" or (
        isinstance(tests.get("passed"), list) and tests.get("passed") and not tests.get("failed")
    )


def _successor_drift_only(verification):
    blockers = set(verification.get("blockers") or [])
    return bool(blockers) and blockers.issubset({"uncaptured_material_changes", "integrated_material_not_current"})


def _governed_successor_material_chain(layout, recs, source_implementation):
    """Prove later project material through unique completed governed successor bridges.

    The chain starts at the independently recomputed integrated material of the implementation
    being completed. Each hop must be a different completed controlled change with an exact
    human approval, a passed implementation bound to that approved proposal, and independently
    valid immutable integration evidence. Ambiguity or any unexplained final material fails closed.
    """
    source_bridge = verified_material_bridge(layout, source_implementation)
    if not source_bridge.get("valid"):
        return {
            "valid": False,
            "blockers": ["governed_successor_source_bridge_invalid"] + (source_bridge.get("blockers") or []),
            "chain": [],
        }

    try:
        current_material = material_snapshot(layout)["revision"]
    except Exception as exc:
        return {
            "valid": False,
            "blockers": ["governed_successor_current_material_unavailable"],
            "chain": [],
            "details": {"reason": str(exc)},
        }

    accepted = source_bridge.get("end_material")
    if accepted == current_material:
        return {
            "valid": True,
            "blockers": [],
            "start_material": accepted,
            "current_material": current_material,
            "chain": [],
        }

    candidates = []
    source_change = source_implementation.get("change")
    for change_id, item in recs.items():
        candidate_change = item[0]
        if not str(change_id).startswith("CHG-") or change_id == source_change:
            continue
        if candidate_change.get("status") != "completed":
            continue
        profile = (candidate_change.get("governance") or {}).get("lifecycle_enforcement")
        if profile not in ("controlled_v1", "controlled_v2", "controlled_v3"):
            continue
        if approval_gate(layout, recs, candidate_change):
            continue

        proposal_id = (candidate_change.get("proposal") or {}).get("current")
        for implementation_id in (candidate_change.get("implementation") or {}).get("attempts") or []:
            record = recs.get(str(implementation_id))
            if not record:
                continue
            implementation = record[0]
            if implementation.get("proposal") != proposal_id or not _passed_implementation_record(implementation):
                continue
            bridge = verified_material_bridge(layout, implementation)
            if not bridge.get("valid"):
                continue
            candidates.append({
                "change": change_id,
                "implementation": implementation_id,
                "start_material": bridge.get("start_material"),
                "end_material": bridge.get("end_material"),
                "provider": bridge.get("provider"),
            })

    chain = []
    visited = set()
    max_hops = len(candidates) + 1
    for _ in range(max_hops):
        matches = [
            item for item in candidates
            if item["start_material"] == accepted
            and (item["change"], item["implementation"]) not in visited
        ]
        if len(matches) > 1:
            return {
                "valid": False,
                "blockers": ["governed_successor_material_chain_ambiguous"],
                "start_material": source_bridge.get("end_material"),
                "current_material": current_material,
                "accepted_material": accepted,
                "chain": chain,
                "candidates": matches,
            }
        if not matches:
            return {
                "valid": False,
                "blockers": ["governed_successor_material_chain_incomplete"],
                "start_material": source_bridge.get("end_material"),
                "current_material": current_material,
                "accepted_material": accepted,
                "chain": chain,
            }

        next_item = matches[0]
        if not next_item.get("end_material") or next_item["end_material"] == accepted:
            return {
                "valid": False,
                "blockers": ["governed_successor_material_chain_no_progress"],
                "start_material": source_bridge.get("end_material"),
                "current_material": current_material,
                "accepted_material": accepted,
                "chain": chain,
            }

        visited.add((next_item["change"], next_item["implementation"]))
        chain.append(next_item)
        accepted = next_item["end_material"]
        if accepted == current_material:
            return {
                "valid": True,
                "blockers": [],
                "start_material": source_bridge.get("end_material"),
                "current_material": current_material,
                "accepted_material": accepted,
                "chain": chain,
            }

    return {
        "valid": False,
        "blockers": ["governed_successor_material_chain_cycle_or_limit"],
        "start_material": source_bridge.get("end_material"),
        "current_material": current_material,
        "accepted_material": accepted,
        "chain": chain,
    }


def checkpoint_readiness_gate(layout, recs, chg):
    blockers = approval_gate(layout, recs, chg)
    attempts = (chg.get("implementation") or {}).get("attempts") or []
    if not attempts:
        return blockers + ["implementation_attempt_missing"]
    eligible = []
    source_blockers = []
    for implementation_id in attempts:
        if implementation_id not in recs:
            continue
        implementation, _ = recs[implementation_id]
        if not _passed_implementation_record(implementation):
            continue
        chronology = _controlled_v3_implementation_chronology_blockers(layout, recs, chg, implementation)
        if chronology:
            source_blockers += chronology
            continue
        verification = _implementation_verification(layout, implementation, historical_terminal=True)
        if not verification.get("valid"):
            source_blockers += verification.get("blockers") or []
            continue
        if (chg.get("governance") or {}).get("lifecycle_enforcement") in ("controlled_v2", "controlled_v3"):
            tier_result = completion_tier(layout, recs, implementation)
            if not tier_result.get("valid") or tier_result.get("blockers"):
                source_blockers += tier_result.get("blockers") or ["governance_tier_completion_check_failed"]
                continue
        eligible.append(implementation_id)
    if not eligible:
        blockers += source_blockers
        blockers.append("passed_implementation_with_required_scoped_assurance_missing")
    return blockers


def completion_gate(layout, recs, chg):
    blockers = approval_gate(layout, recs, chg)
    ready = bootstrap(layout.root, validation_change=chg.get("id"))
    if not ready["ready"]: blockers += ["bootstrap:" + item for item in ready["blockers"]]
    attempts = (chg.get("implementation") or {}).get("attempts") or []
    if not attempts: return blockers + ["implementation_attempt_missing"]

    historical_terminal = chg.get("status") == "completed"
    passed = []
    source_blockers = []
    for implementation_id in attempts:
        if implementation_id not in recs: continue
        implementation, _ = recs[implementation_id]
        if not _passed_implementation_record(implementation):
            continue
        chronology = _controlled_v3_implementation_chronology_blockers(layout, recs, chg, implementation)
        if chronology:
            source_blockers += chronology
            continue

        verification = _implementation_verification(layout, implementation, historical_terminal)
        if (
            not verification.get("valid")
            and not historical_terminal
            and _successor_drift_only(verification)
        ):
            successor_chain = _governed_successor_material_chain(layout, recs, implementation)
            if successor_chain.get("valid"):
                verification = {
                    "valid": True,
                    "blockers": [],
                    "details": {"governed_successor_material_chain": successor_chain},
                }
            else:
                verification = {
                    "valid": False,
                    "blockers": successor_chain.get("blockers") or ["governed_successor_material_chain_failed"],
                    "details": {"governed_successor_material_chain": successor_chain},
                }

        if not verification.get("valid"):
            source_blockers += verification.get("blockers") or []
            for path in (verification.get("details") or {}).get("material_differences") or []:
                source_blockers.append("uncaptured_material_path:" + path)
            continue

        if (chg.get("governance") or {}).get("lifecycle_enforcement") in ("controlled_v2", "controlled_v3"):
            tier_result = completion_tier(layout, recs, implementation)
            if not tier_result.get("valid") or tier_result.get("blockers"):
                source_blockers += tier_result.get("blockers") or ["governance_tier_completion_check_failed"]
                continue

        passed.append(implementation_id)

    if not passed:
        blockers += source_blockers
        blockers.append("passed_implementation_with_required_evidence_and_source_revision_missing")
    return blockers


def decision(root, change_id, target):
    try: layout = discover_layout(root)
    except Exception as exc: return {"permitted": False,"change": change_id,"target": target,"blockers": [f"project_discovery_failed:{exc}"]}
    recs = records(layout)
    if change_id not in recs: return {"permitted": False,"change": change_id,"target": target,"blockers": ["change_missing"]}
    chg, _ = recs[change_id]
    raw_profile = (chg.get("governance") or {}).get("lifecycle_enforcement")
    governed = raw_profile in ("controlled_v1", "controlled_v2", "controlled_v3")
    blockers = []
    if raw_profile and not governed:
        blockers.append(f"unsupported_lifecycle_enforcement:{raw_profile}")
    if governed:
        if target in ("approved", "in_progress", "implemented", "validated", "ready_for_checkpoint", "completed"): blockers += approval_gate(layout, recs, chg)
        if target in ("in_progress", "implemented", "validated", "ready_for_checkpoint", "completed"): blockers += _reconciliation_blockers(layout, recs, chg)
        if target == "approved": blockers += _active_profile_and_v2_extras(layout, recs, chg, raw_profile)
        if target == "ready_for_checkpoint": blockers = checkpoint_readiness_gate(layout, recs, chg)
        if target == "completed": blockers = completion_gate(layout, recs, chg)
    return {"permitted": not blockers,"change": change_id,"current": chg.get("status"),"target": target,"governed": governed,"project_format_mode": layout.mode,"blockers": sorted(set(blockers))}


def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="cmd", required=True)
    bp = sub.add_parser("bootstrap"); bp.add_argument("--root", default="."); bp.add_argument("--json", action="store_true")
    tp = sub.add_parser("transition"); tp.add_argument("change"); tp.add_argument("--to", required=True); tp.add_argument("--root", default="."); tp.add_argument("--json", action="store_true")
    args = parser.parse_args(); root = Path(args.root).resolve()
    out = bootstrap(root) if args.cmd == "bootstrap" else decision(root, args.change, args.to)
    if args.json: print(json.dumps(out, indent=2))
    else:
        state = "READY" if out.get("ready") else ("PERMITTED" if out.get("permitted") else "REFUSED")
        print(state + "\n" + "\n".join(" - " + item for item in out.get("blockers", [])))
    ok = out.get("ready", out.get("permitted", False)); sys.exit(0 if ok else 1)

if __name__ == "__main__": main()