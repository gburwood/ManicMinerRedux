#!/usr/bin/env python3
"""Experimental invisible managed-workflow layer for SpecForge.

The layer does not replace Core governance. It controls when SpecForge should surface to a
human, creates a lightweight project-definition anchor when one is missing, records proposal
presentation evidence, verifies that later approval refers to something the user was actually
shown, and provides concise project-manager summaries.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid

import yaml

from specforge_project import (
    approval_gate,
    canonical_artifact_digest,
    classify_project_path,
    discover_layout,
    iter_record_files,
    load_yaml,
    material_snapshot,
    read_project_governance_tier_state,
    relative,
)
from specforge_authority import (
    apply_reconciliation_recovery,
    capture_reconciliation_observation,
    record_reconciliation_decision,
    repair_authority_bookkeeping,
)

PROFILE = "invisible_managed_v1"
GUIDE_PROFILE = "guided_non_expert_v1"
PROJECT_DEFINITION_DEFAULT = "PROJECT.md"
COMPLETION_GUARD_VERSION = 3
LEGACY_COMPLETION_GUARD_VERSIONS = (1, 2)
SUPPORTED_COMPLETION_GUARD_VERSIONS = LEGACY_COMPLETION_GUARD_VERSIONS + (COMPLETION_GUARD_VERSION,)
PROJECT_DEFINITION_FORMAT_VERSION = 2
RECONCILIATION_CONTEXT_ONLY = "context_only"
RECONCILIATION_DURABLE_UPDATE = "durable_update"
SUPPORTED_RECONCILIATION_MODES = (RECONCILIATION_CONTEXT_ONLY, RECONCILIATION_DURABLE_UPDATE)
MANAGED_DEFINITION_START = "<!-- SPECFORGE-MANAGED-DEFINITION:START -->"
MANAGED_DEFINITION_END = "<!-- SPECFORGE-MANAGED-DEFINITION:END -->"
CURRENT_WORK_START = "<!-- SPECFORGE-CURRENT-WORK:START -->"
CURRENT_WORK_END = "<!-- SPECFORGE-CURRENT-WORK:END -->"
EXECUTION_CAPABILITY_PROFILE = "execution_channel_capabilities_v1"
EXECUTION_CAPABILITIES_ENV = "SPECFORGE_EXECUTION_CAPABILITIES"


def execution_channel_capabilities(required: list[str] | None = None, advertised: list[str] | None = None) -> dict:
    """Report host-advertised execution capabilities without manufacturing assurance."""
    available = set()
    for raw in os.environ.get(EXECUTION_CAPABILITIES_ENV, "").split(","):
        value = raw.strip()
        if value:
            available.add(value)
    for raw in advertised or []:
        value = str(raw).strip()
        if value:
            available.add(value)
    required_set = sorted({str(item).strip() for item in (required or []) if str(item).strip()})
    capability_map = {name: name in available for name in sorted(available | set(required_set))}
    blockers = [f"execution_channel_capability_unavailable:{name}" for name in required_set if name not in available]
    return {
        "contract": EXECUTION_CAPABILITY_PROFILE,
        "permitted": not blockers,
        "required": required_set,
        "available": sorted(available),
        "capabilities": capability_map,
        "blockers": blockers,
        "source": {
            "environment": EXECUTION_CAPABILITIES_ENV,
            "host_advertised": True,
        },
    }


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def records(layout) -> dict:
    out = {}
    for path in iter_record_files(layout):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id"):
            out[str(data["id"])] = (data, path)
    return out


def evidence_root(layout) -> Path:
    paths = layout.manifest.get("paths") or {}
    return (layout.root / paths.get("evidence", "specforge/evidence")).resolve()


def _safe_session_name(session: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_identity(entries: dict[str, str]) -> dict:
    ordered = sorted((str(path).replace("\\", "/").lstrip("./"), str(digest).lower()) for path, digest in entries.items())
    manifest_bytes = "".join(f"{path}\0{digest}\n" for path, digest in ordered).encode("utf-8")
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return {"provider": "specforge_snapshot", "revision": f"sha256:{digest}", "file_count": len(ordered)}


def _checkpoint_acceptance_requirements(layout) -> tuple[list[str], list[str]]:
    policy = ((layout.manifest.get("policy") or {}).get("checkpoint") or {})
    requirements = []
    for item in policy.get("acceptance_required") or []:
        if item not in requirements:
            requirements.append(item)
    pack_tool = layout.tool_root / "specforge-pack.py"
    if not pack_tool.is_file():
        sibling = Path(__file__).resolve().parent / "specforge-pack.py"
        pack_tool = sibling if sibling.is_file() else pack_tool
    if not pack_tool.is_file():
        return requirements, ["pack_resolver_missing"]
    proc = subprocess.run([sys.executable, "-B", str(pack_tool), "--root", str(layout.root), "--json"], capture_output=True, text=True)
    try:
        result = json.loads(proc.stdout or "{}")
    except Exception:
        return requirements, ["pack_resolver_output_invalid"]
    if proc.returncode or not result.get("permitted"):
        return requirements, ["pack:" + str(x) for x in result.get("blockers") or ["validation_failed"]]
    for item in (result.get("assurance") or {}).get("acceptance_required") or []:
        if item not in requirements:
            requirements.append(item)
    return requirements, []


def _exact_candidate_projection(layout, proposal: dict) -> dict:
    config = proposal.get("exact_candidate_finalisation")
    if not isinstance(config, dict) or config.get("eligible") is not True:
        return {"eligible": False, "blockers": ["prospective_finalisation_not_declared"]}
    blockers = []
    try:
        baseline = material_snapshot(layout)
    except Exception as exc:
        return {"eligible": False, "blockers": [f"material_snapshot_unavailable:{exc}"]}
    baseline_entries = {item["path"]: item["sha256"] for item in baseline.get("entries") or []}
    prepared = {}
    for item in config.get("prepared_artifacts") or []:
        if not isinstance(item, dict):
            blockers.append("prepared_artifact_invalid"); continue
        path = str(item.get("path") or "").replace("\\", "/").lstrip("./")
        digest = str(item.get("sha256") or "").lower()
        if not path or not re.fullmatch(r"[a-f0-9]{64}", digest):
            blockers.append(f"prepared_artifact_invalid:{path or '<missing>'}"); continue
        if path in prepared:
            blockers.append(f"prepared_artifact_duplicate:{path}"); continue
        if classify_project_path(layout.root / path, layout) != "material":
            blockers.append(f"prepared_artifact_not_material:{path}"); continue
        prepared[path] = digest
    declared_material = {}
    declared_deletions = set()
    for item in proposal.get("declared_scope") or []:
        if not isinstance(item, dict): continue
        operation = item.get("operation")
        if operation in ("rename", "copy"):
            candidates = [item.get("from"), item.get("to")]
            if any(value and classify_project_path(layout.root / str(value), layout) == "material" for value in candidates):
                blockers.append(f"prospective_operation_unsupported:{operation}")
            continue
        path = str(item.get("path") or "").replace("\\", "/").lstrip("./")
        if not path: continue
        classification = classify_project_path(layout.root / path, layout)
        if classification == "unclassified":
            blockers.append(f"prospective_scope_unclassified:{path}"); continue
        if classification != "material": continue
        if operation in ("add", "modify"): declared_material[path] = operation
        elif operation == "delete": declared_deletions.add(path)
    prepared_paths=set(prepared); expected_paths=set(declared_material)
    for path in sorted(expected_paths-prepared_paths): blockers.append(f"prepared_artifact_missing:{path}")
    for path in sorted(prepared_paths-expected_paths): blockers.append(f"prepared_artifact_not_in_material_scope:{path}")
    configured_deletions={str(item).replace("\\","/").lstrip("./") for item in (config.get("deletions") or [])}
    for path in sorted(declared_deletions-configured_deletions): blockers.append(f"prepared_deletion_missing:{path}")
    for path in sorted(configured_deletions-declared_deletions): blockers.append(f"prepared_deletion_not_in_material_scope:{path}")
    candidate_entries=dict(baseline_entries)
    for path,operation in declared_material.items():
        exists=path in baseline_entries
        if operation=="add" and exists: blockers.append(f"prospective_add_already_exists:{path}")
        if operation=="modify" and not exists: blockers.append(f"prospective_modify_missing:{path}")
        if path in prepared: candidate_entries[path]=prepared[path]
    for path in declared_deletions:
        if path not in baseline_entries: blockers.append(f"prospective_delete_missing:{path}")
        candidate_entries.pop(path,None)
    acceptance_requirements, assurance_blockers = _checkpoint_acceptance_requirements(layout)
    blockers.extend(assurance_blockers)
    return {
        "eligible": not blockers, "blockers": sorted(set(blockers)),
        "baseline": {"provider": baseline.get("provider"), "revision": baseline.get("revision"), "file_count": baseline.get("file_count")},
        "projected_candidate": _snapshot_identity(candidate_entries),
        "acceptance_requirements": acceptance_requirements,
    }


def _explicit_finalisation_authority(text: str) -> bool:
    value=text.strip().lower()
    return bool(re.search(r"\bfinali[sz](?:e|ed|ation)\b", value) or "without another prompt" in value or "without asking again" in value)


def _history_root(layout) -> Path:
    value=(layout.manifest.get("paths") or {}).get("history","specforge/history")
    return (layout.root / value).resolve()


def _next_pfa_id(layout) -> str:
    highest=0
    for rid in records(layout):
        match=re.fullmatch(r"PFA-(\d+)",str(rid))
        if match: highest=max(highest,int(match.group(1)))
    return f"PFA-{highest+1:04d}"


def _atomic_yaml_updates(updates):
    backups = {}
    temps = {}
    try:
        for path, data in updates:
            path.parent.mkdir(parents=True, exist_ok=True)
            backups[path] = path.read_text(encoding="utf-8") if path.exists() else None
            fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
            os.close(fd)
            temp = Path(tmp)
            temp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
            temps[path] = temp
        replaced = []
        try:
            for path, _ in updates:
                os.replace(temps[path], path)
                replaced.append(path)
        except Exception:
            for path in replaced:
                if backups[path] is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.write_text(backups[path], encoding="utf-8", newline="\n")
            raise
    finally:
        for temp in temps.values():
            if temp.exists():
                temp.unlink()


def _sha256_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _request_identity(request_text: str) -> dict:
    return {
        "algorithm": "sha256",
        "digest": "sha256:" + _sha256_text(request_text),
        "bound_at": utc_now(),
    }


def _current_work_binding_from_text(text: str) -> dict | None:
    start = text.find(CURRENT_WORK_START)
    end = text.find(CURRENT_WORK_END)
    if start < 0 or end < 0 or end <= start:
        return None
    body = text[start + len(CURRENT_WORK_START):end].strip()
    values = {}
    for line in body.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    request_digest = values.get("request_digest")
    change = values.get("change")
    if not request_digest or not change:
        return None
    return {
        "request_digest": request_digest,
        "change": change,
        "summary": values.get("summary"),
    }


def _managed_definition_from_text(text: str) -> dict | None:
    start = text.find(MANAGED_DEFINITION_START)
    end = text.find(MANAGED_DEFINITION_END)
    if start < 0 or end < 0 or end <= start:
        return None
    body = text[start + len(MANAGED_DEFINITION_START):end].strip()
    values = {}
    for line in body.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"definition_format_version", "request_digest", "change", "status"}:
            values[key] = value.strip()
    try:
        version = int(values.get("definition_format_version"))
    except (TypeError, ValueError):
        return None
    return {
        "definition_format_version": version,
        "request_digest": values.get("request_digest") or None,
        "change": values.get("change") or None,
        "status": values.get("status") or None,
        "current_work": _current_work_binding_from_text(body),
    }


def _render_current_work_block(request_digest: str, change_id: str, summary: str) -> str:
    safe_summary = " ".join(summary.strip().split())
    return "\n".join([
        CURRENT_WORK_START,
        f"request_digest: {request_digest}",
        f"change: {change_id}",
        f"summary: {safe_summary}",
        CURRENT_WORK_END,
    ])


def _replace_current_work_block(text: str, block: str) -> str:
    start = text.find(CURRENT_WORK_START)
    end = text.find(CURRENT_WORK_END)
    if start >= 0 and end >= start:
        end += len(CURRENT_WORK_END)
        return text[:start].rstrip() + "\n\n" + block + "\n" + text[end:].lstrip()
    suffix = "" if text.endswith("\n") else "\n"
    return text + suffix + "\n## Current governed work\n\n" + block + "\n"


def _render_managed_definition_region(purpose: str, status_text: str, request_digest: str | None = None, change_id: str | None = None) -> str:
    lines = [
        MANAGED_DEFINITION_START,
        f"definition_format_version: {PROJECT_DEFINITION_FORMAT_VERSION}",
        f"request_digest: {request_digest or ''}",
        f"change: {change_id or ''}",
        "status: current",
        "",
        "## Purpose",
        "",
        purpose.strip(),
        "",
        "## Current status",
        "",
        status_text.strip(),
    ]
    if request_digest and change_id:
        lines += ["", _render_current_work_block(request_digest, change_id, purpose)]
    lines += [MANAGED_DEFINITION_END]
    return "\n".join(lines)


def _replace_managed_definition_region(text: str, region: str) -> str:
    start = text.find(MANAGED_DEFINITION_START)
    end = text.find(MANAGED_DEFINITION_END)
    if start >= 0 and end >= start:
        end += len(MANAGED_DEFINITION_END)
        return text[:start].rstrip() + "\n\n" + region + "\n" + text[end:].lstrip()

    # Alpha.21 and earlier project definitions did not own a complete human-readable region.
    # Preserve their bytes as background context rather than guessing which prose is user-authored.
    stripped = text.rstrip()
    title = ""
    remainder = stripped
    if stripped.startswith("# ") and "\n" in stripped:
        title, remainder = stripped.split("\n", 1)
    parts = []
    if title:
        parts += [title, "", region]
    else:
        parts.append(region)
    if remainder.strip():
        parts += [
            "",
            "## Initial/background context",
            "",
            "The following pre-v2 project-definition text is retained for context and is not the authoritative managed purpose or status.",
            "",
            remainder,
        ]
    return "\n".join(parts).rstrip() + "\n"


def clarification_root(layout) -> Path:
    return evidence_root(layout) / "clarifications"


def _clarifications(layout, session: str) -> list[tuple[dict, Path]]:
    root = clarification_root(layout)
    if not root.is_dir():
        return []
    out = []
    for path in root.glob("CLR-*.yaml"):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("session") == session:
            out.append((data, path))
    return sorted(out, key=lambda item: item[0].get("requested_at") or "")


def _open_clarifications(layout, session: str) -> list[str]:
    return [
        str(item.get("id"))
        for item, _ in _clarifications(layout, session)
        if not item.get("resolved_at")
    ]


def _next_clarification_id(layout) -> str:
    highest = 0
    root = clarification_root(layout)
    if root.is_dir():
        for path in root.glob("CLR-*.yaml"):
            match = re.fullmatch(r"CLR-(\d+)", path.stem)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"CLR-{highest + 1:04d}"


def request_clarification(layout, session: str, question: str, change_id: str | None = None) -> dict:
    if not interaction_started(layout, session):
        return {"recorded": False, "session": session, "blockers": ["interaction_session_not_started"]}
    if not question.strip():
        return {"recorded": False, "session": session, "blockers": ["clarification_question_missing"]}
    cid = _next_clarification_id(layout)
    target = clarification_root(layout) / f"{cid}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": cid,
        "type": "managed_clarification",
        "session": session,
        "change": change_id,
        "question": question.strip(),
        "question_sha256": _sha256_text(question.strip()),
        "requested_at": utc_now(),
        "resolved_at": None,
        "response_sha256": None,
    }
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    mark(layout.root, "clarification_requested", change=change_id, session=session, note=cid)
    return {
        "recorded": True,
        "clarification": cid,
        "session": session,
        "user_prompt": question.strip(),
        "record": relative(layout, target),
    }


def resolve_clarification(layout, session: str, clarification_id: str, response: str, change_id: str | None = None) -> dict:
    target = clarification_root(layout) / f"{clarification_id}.yaml"
    if not target.is_file():
        return {"resolved": False, "session": session, "blockers": ["clarification_missing"]}
    data = load_yaml(target)
    if data.get("session") != session:
        return {"resolved": False, "session": session, "blockers": ["clarification_session_mismatch"]}
    if data.get("resolved_at"):
        return {"resolved": True, "existing": True, "session": session, "clarification": clarification_id}
    if not response.strip():
        return {"resolved": False, "session": session, "blockers": ["clarification_response_missing"]}
    data["resolved_at"] = utc_now()
    data["response_sha256"] = _sha256_text(response.strip())
    target.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    mark(layout.root, "clarification_resolved", change=change_id or data.get("change"), session=session, note=clarification_id)
    return {"resolved": True, "existing": False, "session": session, "clarification": clarification_id, "record": relative(layout, target)}


def checkpoint_presentation_root(layout) -> Path:
    return evidence_root(layout) / "checkpoint-presentations"


def _checkpoint_presentations(layout, checkpoint_id: str, session: str | None = None) -> list[tuple[dict, Path]]:
    root = checkpoint_presentation_root(layout)
    if not root.is_dir():
        return []
    out = []
    for path in root.glob("CPRES-*.yaml"):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("checkpoint") != checkpoint_id:
            continue
        if session and data.get("session") != session:
            continue
        out.append((data, path))
    return sorted(out, key=lambda item: item[0].get("presented_at") or "")


def _checkpoint_tool(layout) -> Path | None:
    installed = layout.tool_root / "specforge-checkpoint.py"
    if installed.is_file():
        return installed
    sibling = Path(__file__).resolve().parent / "specforge-checkpoint.py"
    return sibling if sibling.is_file() else None


def present_checkpoint(layout, checkpoint_id: str, session: str) -> dict:
    if not interaction_started(layout, session):
        return {"presented": False, "session": session, "blockers": ["interaction_session_not_started"]}
    recs = records(layout)
    entry = recs.get(checkpoint_id)
    if not entry:
        return {"presented": False, "session": session, "blockers": ["checkpoint_missing"]}
    checkpoint, _ = entry
    if checkpoint.get("status") not in ("candidate", "under_validation"):
        return {"presented": False, "session": session, "blockers": ["checkpoint_not_awaiting_acceptance"]}
    tool = _checkpoint_tool(layout)
    if tool is None:
        return {"presented": False, "session": session, "blockers": ["checkpoint_tool_missing"]}
    proc = subprocess.run(
        [sys.executable, "-B", str(tool), "verify", checkpoint_id, "--root", str(layout.root), "--json"],
        capture_output=True,
        text=True,
    )
    try:
        verification = json.loads(proc.stdout or "{}")
    except Exception:
        verification = {}
    if proc.returncode or not verification.get("valid"):
        return {"presented": False, "session": session, "blockers": ["checkpoint_verification_failed"] + list(verification.get("blockers") or [])}
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    pid = f"CPRES-{stamp}"
    target = checkpoint_presentation_root(layout) / f"{pid}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": pid,
        "type": "checkpoint_presentation",
        "checkpoint": checkpoint_id,
        "session": session,
        "candidate": checkpoint.get("candidate"),
        "included_changes_digest": checkpoint.get("included_changes_digest"),
        "presented_at": utc_now(),
        "user_prompt": "The approved work is complete and verified. Finalise it?",
    }
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    mark(layout.root, "checkpoint_presented", session=session, note=pid)
    return {
        "presented": True,
        "checkpoint": checkpoint_id,
        "presentation": pid,
        "session": session,
        "user_prompt": payload["user_prompt"],
        "record": relative(layout, target),
    }


def _next_cap_id(layout) -> str:
    highest = 0
    for rid in records(layout):
        match = re.fullmatch(r"CAP-(\d+)", str(rid))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"CAP-{highest + 1:04d}"


def record_checkpoint_acceptance(layout, checkpoint_id: str, session: str, text: str, actor_id: str, actor_name: str | None) -> dict:
    if not text.strip():
        return {"permitted": False, "blockers": ["checkpoint_acceptance_text_missing"]}
    presentations = _checkpoint_presentations(layout, checkpoint_id, session)
    if not presentations:
        return {"permitted": False, "blockers": ["checkpoint_not_presented"]}
    presentation, presentation_path = presentations[-1]
    recs = records(layout)
    entry = recs.get(checkpoint_id)
    if not entry:
        return {"permitted": False, "blockers": ["checkpoint_missing"]}
    checkpoint, _ = entry
    candidate = (checkpoint.get("candidate") or {}).get("material") or {}
    shown = ((presentation.get("candidate") or {}).get("material") or {})
    if (
        candidate.get("revision") != shown.get("revision")
        or candidate.get("file_count") != shown.get("file_count")
        or checkpoint.get("included_changes_digest") != presentation.get("included_changes_digest")
    ):
        return {"permitted": False, "blockers": ["checkpoint_changed_since_presentation"]}
    cap_id = _next_cap_id(layout)
    history = _history_root(layout) / "acceptance-proofs"
    target = history / f"{cap_id}.yaml"
    actor = {"type": "human", "id": actor_id}
    if actor_name:
        actor["display_name"] = actor_name
    payload = {
        "id": cap_id,
        "checkpoint": checkpoint_id,
        "candidate": {"material": candidate},
        "included_changes_digest": checkpoint.get("included_changes_digest"),
        "actor": actor,
        "presentation": relative(layout, presentation_path),
        "session": session,
        "acceptance_text": text.strip(),
        "presented_at": presentation.get("presented_at"),
        "received_at": utc_now(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    mark(layout.root, "checkpoint_acceptance_received", session=session, note=cap_id)
    return {
        "permitted": True,
        "checkpoint": checkpoint_id,
        "proof": cap_id,
        "record": relative(layout, target),
        "received_at": payload["received_at"],
    }


def _next_apr_id(layout) -> str:
    highest = 0
    for rid in records(layout):
        match = re.fullmatch(r"APR-(\d+)", str(rid))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"APR-{highest + 1:04d}"


def session_guard_path(layout, session: str) -> Path:
    return evidence_root(layout) / "managed-sessions" / f"{_safe_session_name(session)}.json"


def completion_path(layout, session: str) -> Path:
    return evidence_root(layout) / "completions" / f"{_safe_session_name(session)}.json"


def _project_definition_identity(layout) -> dict:
    state = project_definition_state(layout)
    out = {"state": state.get("state"), "path": state.get("path")}
    if state.get("state") == "defined" and state.get("path"):
        target = (layout.root / state["path"]).resolve()
        if target.is_file():
            text = target.read_text(encoding="utf-8")
            out["sha256"] = _sha256_file(target)
            out["current_work"] = _current_work_binding_from_text(text)
            out["managed_definition"] = _managed_definition_from_text(text)
    return out

def _alpha_revision(value: str | None) -> int | None:
    text = str(value or "")
    marker = "-alpha."
    if marker not in text:
        return None
    try:
        return int(text.rsplit(marker, 1)[1])
    except (TypeError, ValueError):
        return None


def _proposal_requires_explicit_reconciliation_mode(proposal: dict | None) -> bool:
    if not isinstance(proposal, dict):
        return False
    revision = _alpha_revision(proposal.get("proposed_specification_version"))
    return revision is not None and revision >= 26


def _resolve_reconciliation_mode(binding: dict | None, proposal: dict | None = None) -> tuple[str | None, str | None]:
    binding = binding if isinstance(binding, dict) else {}
    mode = binding.get("mode")
    if mode is None:
        if _proposal_requires_explicit_reconciliation_mode(proposal):
            return None, "project_definition_reconciliation_mode_missing"
        return RECONCILIATION_DURABLE_UPDATE, None
    if mode not in SUPPORTED_RECONCILIATION_MODES:
        return None, "project_definition_reconciliation_mode_unknown"
    return str(mode), None


def _current_definition_digest(layout, path: str | None) -> str | None:
    if not path:
        return None
    target = (layout.root / str(path)).resolve()
    return _sha256_file(target) if target.is_file() else None


def _write_session_guard(layout, session: str, request_mark: dict | None, request_text: str, change_id: str | None) -> dict:
    target = session_guard_path(layout, session)
    target.parent.mkdir(parents=True, exist_ok=True)
    request = _request_identity(request_text)
    definition = _project_definition_identity(layout)
    binding = definition.get("current_work") or {}
    already_current = bool(
        change_id
        and binding.get("request_digest") == request["digest"]
        and binding.get("change") == change_id
    )
    payload = {
        "type": "managed_interaction_session",
        "session": session,
        "completion_guard_version": COMPLETION_GUARD_VERSION,
        "started_at": (request_mark or {}).get("timestamp") or utc_now(),
        "request": request,
        "project_definition": definition,
        "project_definition_reconciliation": {
            "required": not already_current,
            "change": change_id,
            "prepared_path": None,
            "prepared_sha256": None,
        },
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return payload

def _load_session_guard(layout, session: str) -> dict | None:
    target = session_guard_path(layout, session)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def observer_path(layout) -> Path | None:
    installed = layout.tool_root / "specforge-observe.py"
    if installed.is_file():
        return installed
    sibling = Path(__file__).resolve().parent / "specforge-observe.py"
    return sibling if sibling.is_file() else None


def observer_call(layout, *args) -> tuple[int, dict]:
    observer = observer_path(layout)
    if observer is None:
        return 2, {"ok": False, "error": "observer_missing"}
    result = subprocess.run(
        [sys.executable, "-B", str(observer), *map(str, args), "--root", str(layout.root), "--json"],
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except Exception:
        payload = {"ok": False, "error": "observer_output_invalid", "raw": (result.stdout + result.stderr).strip()}
    return result.returncode, payload


def interaction_started(layout, session: str | None) -> bool:
    if not session:
        return False
    code, payload = observer_call(layout, "summary", "--session", session)
    return code == 0 and (payload.get("phase_counts") or {}).get("request_received", 0) > 0


def begin_interaction(layout, session: str | None = None, request_text: str | None = None, change_id: str | None = None) -> dict:
    session = session or f"SESSION-{uuid.uuid4().hex[:12]}"
    if interaction_started(layout, session):
        _, existing = observer_call(layout, "summary", "--session", session)
        request_mark = next((mark for mark in existing.get("marks") or [] if mark.get("phase") == "request_received"), None)
        guard = _load_session_guard(layout, session)
        return {
            "started": True,
            "session": session,
            "existing": True,
            "request_received": request_mark,
            "completion_guard": {
                "enabled": bool(guard and guard.get("completion_guard_version") in SUPPORTED_COMPLETION_GUARD_VERSIONS),
                "version": (guard or {}).get("completion_guard_version"),
                "request_digest": ((guard or {}).get("request") or {}).get("digest"),
            },
        }
    if not request_text or not request_text.strip():
        return {"started": False, "session": session, "blockers": ["request_binding_missing"]}
    code, payload = observer_call(layout, "mark", "request_received", "--session", session)
    if code != 0 or not payload.get("ok"):
        return {"started": False, "session": session, "blockers": ["request_received_recording_failed"], "observer": payload}
    request_mark = payload.get("mark")
    guard = _write_session_guard(layout, session, request_mark, request_text.strip(), change_id)
    return {
        "started": True,
        "session": session,
        "existing": False,
        "request_received": request_mark,
        "completion_guard": {
            "enabled": True,
            "version": guard["completion_guard_version"],
            "request_digest": guard["request"]["digest"],
            "record": relative(layout, session_guard_path(layout, session)),
        },
    }

def project_definition_state(layout) -> dict:
    experience = layout.manifest.get("experience") or {}
    configured = experience.get("project_definition")
    if configured:
        target = (layout.root / configured).resolve()
        if target.is_file():
            return {"state": "defined", "path": relative(layout, target), "source": "manifest"}
        return {"state": "missing", "path": configured, "source": "manifest"}

    conventional = layout.root / PROJECT_DEFINITION_DEFAULT
    if conventional.is_file():
        return {"state": "defined", "path": PROJECT_DEFINITION_DEFAULT, "source": "convention"}

    return {"state": "undefined", "path": None, "source": None}


def lifecycle_bootstrap(layout) -> dict:
    tool = layout.tool_root / "specforge-lifecycle.py"
    if not tool.is_file():
        return {"ready": False, "blockers": ["lifecycle_tool_missing"]}
    result = subprocess.run(
        [sys.executable, "-B", str(tool), "bootstrap", "--root", str(layout.root), "--json"],
        capture_output=True,
        text=True,
    )
    try:
        out = json.loads(result.stdout or "{}")
    except Exception:
        return {"ready": False, "blockers": ["lifecycle_bootstrap_output_invalid"], "raw": (result.stdout + result.stderr).strip()}
    return out


def _alpha22_managed_tier_required(layout) -> bool:
    try:
        core = load_yaml(layout.core_root / "core.yaml")
    except Exception:
        return False
    if ((core or {}).get("managed_interaction_integrity") or {}).get("profile") != "controlled_v3":
        return False
    version = str((core or {}).get("core_version") or "")
    marker = "-alpha."
    if marker not in version:
        return True
    try:
        return int(version.rsplit(marker, 1)[1]) >= 22
    except (TypeError, ValueError):
        return False


def managed_bootstrap(layout) -> dict:
    governance = lifecycle_bootstrap(layout)
    definition = project_definition_state(layout)
    experience = layout.manifest.get("experience") or {}

    if _alpha22_managed_tier_required(layout):
        tier_state = read_project_governance_tier_state(layout)
        governance.setdefault("details", {})["managed_governance_tier"] = {
            "status": tier_state.get("status"),
            "enforcement_profile": tier_state.get("tier_enforcement_profile"),
        }
        if tier_state.get("status") == "not_activated":
            governance.setdefault("blockers", []).append("governance_tier_not_initialized")
            governance["ready"] = False
        elif tier_state.get("status") != "active":
            governance.setdefault("blockers", []).append("governance_tier_activation_state_corrupted")
            governance["ready"] = False
        elif tier_state.get("tier_enforcement_profile") != "deterministic_tier_v1":
            governance.setdefault("blockers", []).append("governance_tier_profile_mismatch")
            governance["ready"] = False

    if not governance.get("ready"):
        state = "blocked"
        user_message = "This project needs internal SpecForge attention before managed work can continue."
    elif definition.get("state") != "defined":
        state = "needs_project_definition"
        user_message = "Before I start managing this project, what are you trying to achieve?"
    else:
        state = "ready_for_work"
        user_message = "Project ready."

    return {
        "managed_state": state,
        "governance_ready": bool(governance.get("ready")),
        "project_definition": definition,
        "experience_profile": experience.get("profile") or PROFILE,
        "user_message": user_message,
        "manager": {
            "governance_blockers": governance.get("blockers") or [],
            "governance_details": governance.get("details") or {},
        },
    }


def render_project_definition(layout, purpose: str, deliverable: str | None, audience: str | None) -> str:
    project = layout.manifest.get("project") or {}
    name = project.get("name") or "Project"
    region = _render_managed_definition_region(
        purpose,
        "Project definition established. No governed implementation is currently bound.",
    )
    lines = [f"# {name}", "", region, ""]
    if deliverable:
        lines += ["## Intended deliverable", "", deliverable.strip(), ""]
    if audience:
        lines += ["## Audience", "", audience.strip(), ""]
    lines += [
        "## Project working agreement",
        "",
        "- Existing source and research files are reference material unless explicitly identified as instructions or authoritative specification.",
        "- Material ambiguity should be clarified before implementation rather than silently assumed.",
        "- SpecForge governance should remain invisible to the end user except when a meaningful decision, clarification or approval is required.",
        "- Project-manager detail remains available on request.",
        "",
    ]
    return "\n".join(lines)


def define_project(layout, purpose: str, deliverable: str | None, audience: str | None) -> dict:
    state = project_definition_state(layout)
    if state.get("state") == "defined":
        return {"created": False, "reason": "project_definition_already_exists", "project_definition": state}

    target = layout.root / PROJECT_DEFINITION_DEFAULT
    target.write_text(render_project_definition(layout, purpose, deliverable, audience), encoding="utf-8", newline="\n")

    manifest = load_yaml(layout.manifest_path)
    experience = manifest.get("experience") if isinstance(manifest.get("experience"), dict) else {}
    experience.update({
        "profile": PROFILE,
        "project_definition": f"./{PROJECT_DEFINITION_DEFAULT}",
        "progressive_disclosure": True,
        "informed_approval": "required",
    })
    manifest["experience"] = experience
    layout.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    mark(layout.root, "project_defined", note=f"Defined {PROJECT_DEFINITION_DEFAULT}")
    return {"created": True, "path": PROJECT_DEFINITION_DEFAULT, "experience": experience}


def prepare_project_definition(layout, session: str, change_id: str, summary: str, mode: str = RECONCILIATION_DURABLE_UPDATE) -> dict:
    guard = _load_session_guard(layout, session)
    guard_version = (guard or {}).get("completion_guard_version")
    if not guard or guard_version not in (2, COMPLETION_GUARD_VERSION):
        return {"prepared": False, "blockers": ["session_guard_v2_or_v3_required"]}
    if mode not in SUPPORTED_RECONCILIATION_MODES:
        return {"prepared": False, "blockers": ["project_definition_reconciliation_mode_unknown"]}
    request_digest = ((guard.get("request") or {}).get("digest"))
    if not request_digest:
        return {"prepared": False, "blockers": ["request_digest_missing"]}
    state = project_definition_state(layout)
    if state.get("state") != "defined" or not state.get("path"):
        return {"prepared": False, "blockers": ["project_definition_missing"]}
    target = (layout.root / state["path"]).resolve()

    if mode == RECONCILIATION_CONTEXT_ONLY:
        digest = _sha256_file(target)
        reconciliation = {
            "required": True,
            "mode": mode,
            "change": change_id,
            "path": state["path"],
            "authoritative_sha256": digest,
            "prepared_path": None,
            "prepared_sha256": None,
            "request_digest": request_digest,
        }
        if guard_version == COMPLETION_GUARD_VERSION:
            reconciliation["definition_format_version"] = PROJECT_DEFINITION_FORMAT_VERSION
        guard["project_definition_reconciliation"] = reconciliation
        session_guard_path(layout, session).write_text(json.dumps(guard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        mark(layout.root, "project_definition_context_bound", change=change_id, session=session, note=digest)
        binding = {
            "mode": mode,
            "path": state["path"],
            "sha256": digest,
            "request_digest": request_digest,
            "change": change_id,
        }
        if guard_version == COMPLETION_GUARD_VERSION:
            binding["definition_format_version"] = PROJECT_DEFINITION_FORMAT_VERSION
        return {
            "prepared": True,
            "mode": mode,
            "session": session,
            "change": change_id,
            "proposal_binding": binding,
            "prepared_path": None,
            "project_definition_changed": False,
        }

    original = target.read_text(encoding="utf-8")
    if guard_version == COMPLETION_GUARD_VERSION:
        region = _render_managed_definition_region(
            summary,
            f"Current governed work for {change_id}: {' '.join(summary.strip().split())}",
            request_digest,
            change_id,
        )
        prepared_text = _replace_managed_definition_region(original, region)
    else:
        block = _render_current_work_block(request_digest, change_id, summary)
        prepared_text = _replace_current_work_block(original, block)
    prepared_root = evidence_root(layout) / "prepared" / "project-definitions"
    prepared_root.mkdir(parents=True, exist_ok=True)
    prepared_path = prepared_root / f"{_safe_session_name(session)}.md"
    prepared_path.write_text(prepared_text, encoding="utf-8", newline="\n")
    digest = _sha256_file(prepared_path)
    reconciliation = {
        "required": True,
        "mode": mode,
        "change": change_id,
        "path": state["path"],
        "prepared_path": relative(layout, prepared_path),
        "prepared_sha256": digest,
        "request_digest": request_digest,
    }
    if guard_version == COMPLETION_GUARD_VERSION:
        reconciliation["definition_format_version"] = PROJECT_DEFINITION_FORMAT_VERSION
    guard["project_definition_reconciliation"] = reconciliation
    session_guard_path(layout, session).write_text(json.dumps(guard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    mark(layout.root, "project_definition_prepared", change=change_id, session=session, note=digest)
    binding = {
        "mode": mode,
        "path": state["path"],
        "sha256": digest,
        "request_digest": request_digest,
        "change": change_id,
    }
    if guard_version == COMPLETION_GUARD_VERSION:
        binding["definition_format_version"] = PROJECT_DEFINITION_FORMAT_VERSION
    return {
        "prepared": True,
        "mode": mode,
        "session": session,
        "change": change_id,
        "proposal_binding": binding,
        "prepared_path": relative(layout, prepared_path),
        "project_definition_changed": True,
    }


def implementation_authority(layout, change_id: str, proposal_id: str | None = None) -> dict:
    """Fail closed unless the exact current proposal has valid human implementation authority."""
    recs = records(layout)
    change_entry = recs.get(change_id)
    if not change_entry:
        return {"permitted": False, "change": change_id, "blockers": ["change_missing"]}
    change = change_entry[0]
    current = (change.get("proposal") or {}).get("current")
    if not current or current not in recs:
        return {"permitted": False, "change": change_id, "blockers": ["current_proposal_missing"]}
    if proposal_id and proposal_id != current:
        return {"permitted": False, "change": change_id, "proposal": current, "blockers": ["proposal_not_current"]}
    proposal, proposal_path = recs[current]
    blockers = list(approval_gate(layout, recs, change))
    if (change.get("governance") or {}).get("lifecycle_enforcement") == "controlled_v3":
        if change.get("status") not in ("approved", "in_progress", "implemented", "validated", "ready_for_checkpoint"):
            blockers.append("change_not_in_authorised_implementation")
        digest = canonical_artifact_digest(proposal_path)
        if not _informed_approval_proof(layout, current, digest):
            blockers.append("informed_approval_proof_missing")
    return {
        "permitted": not blockers,
        "change": change_id,
        "proposal": current,
        "proposal_digest": canonical_artifact_digest(proposal_path),
        "blockers": sorted(set(blockers)),
    }

def apply_project_definition(layout, session: str, change_id: str) -> dict:
    guard = _load_session_guard(layout, session)
    guard_version = (guard or {}).get("completion_guard_version")
    if not guard or guard_version not in (2, COMPLETION_GUARD_VERSION):
        return {"applied": False, "blockers": ["session_guard_v2_or_v3_required"]}
    rec = (guard.get("project_definition_reconciliation") or {})
    if rec.get("change") != change_id:
        return {"applied": False, "blockers": ["project_definition_preparation_missing"]}
    recs = records(layout)
    change_entry = recs.get(change_id)
    if not change_entry:
        return {"applied": False, "blockers": ["change_missing"]}
    change = change_entry[0]
    if change.get("status") not in ("in_progress", "implemented", "validated", "ready_for_checkpoint"):
        return {"applied": False, "blockers": ["change_not_in_authorised_implementation"]}
    authority = implementation_authority(layout, change_id)
    if not authority.get("permitted"):
        return {"applied": False, "blockers": authority.get("blockers") or ["valid_exact_human_approval_missing"]}
    proposal_id = (change.get("proposal") or {}).get("current")
    proposal_entry = recs.get(str(proposal_id))
    proposal = proposal_entry[0] if proposal_entry else None
    binding = (proposal or {}).get("project_definition_reconciliation") or {}
    mode, mode_blocker = _resolve_reconciliation_mode(binding, proposal)
    if mode_blocker:
        return {"applied": False, "blockers": [mode_blocker]}
    if rec.get("mode") not in (None, mode):
        return {"applied": False, "blockers": ["project_definition_reconciliation_mode_mismatch"]}
    if mode == RECONCILIATION_CONTEXT_ONLY:
        if (
            binding.get("path") != rec.get("path")
            or binding.get("sha256") != rec.get("authoritative_sha256")
            or binding.get("request_digest") != rec.get("request_digest")
            or binding.get("change") != change_id
            or (guard_version == COMPLETION_GUARD_VERSION and binding.get("definition_format_version") != PROJECT_DEFINITION_FORMAT_VERSION)
        ):
            return {"applied": False, "blockers": ["project_definition_not_bound_by_proposal"]}
        if _current_definition_digest(layout, rec.get("path")) != binding.get("sha256"):
            return {"applied": False, "blockers": ["project_definition_context_digest_changed"]}
        return {"applied": False, "mode": mode, "blockers": ["project_definition_apply_not_permitted_context_only"]}

    if not rec.get("prepared_path") or not rec.get("prepared_sha256"):
        return {"applied": False, "blockers": ["project_definition_preparation_missing"]}
    if (
        binding.get("path") != rec.get("path")
        or binding.get("sha256") != rec.get("prepared_sha256")
        or binding.get("request_digest") != rec.get("request_digest")
        or binding.get("change") != change_id
        or (guard_version == COMPLETION_GUARD_VERSION and binding.get("definition_format_version") != PROJECT_DEFINITION_FORMAT_VERSION)
    ):
        return {"applied": False, "blockers": ["project_definition_not_bound_by_proposal"]}
    prepared = (layout.root / rec["prepared_path"]).resolve()
    if not prepared.is_file() or _sha256_file(prepared) != rec["prepared_sha256"]:
        return {"applied": False, "blockers": ["prepared_project_definition_changed"]}
    target = (layout.root / rec["path"]).resolve()
    target.write_bytes(prepared.read_bytes())
    mark(layout.root, "project_definition_applied", change=change_id, proposal=proposal_id, session=session, note=rec["prepared_sha256"])
    return {"applied": True, "mode": mode, "path": rec["path"], "sha256": rec["prepared_sha256"]}

def _presentation_id() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"PRES-{stamp}"


def presentation_root(layout) -> Path:
    return evidence_root(layout) / "presentations"


def present_proposal(layout, proposal_id: str, summary: str, change_id: str | None = None, session: str | None = None) -> dict:
    if not session:
        return {"presented": False, "blockers": ["interaction_session_missing"]}
    if not interaction_started(layout, session):
        return {"presented": False, "blockers": ["interaction_session_not_started"], "session": session}
    open_items = _open_clarifications(layout, session)
    if open_items:
        return {"presented": False, "blockers": ["clarification_unresolved:" + item for item in open_items], "session": session}
    recs = records(layout)
    if proposal_id not in recs:
        return {"presented": False, "blockers": ["proposal_missing"]}
    proposal, proposal_path = recs[proposal_id]
    change_id = change_id or proposal.get("change")
    change = recs.get(str(change_id), ({}, None))[0]
    guard = _load_session_guard(layout, session)
    if (change.get("governance") or {}).get("lifecycle_enforcement") == "controlled_v3":
        if not guard or guard.get("completion_guard_version") not in (2, COMPLETION_GUARD_VERSION):
            return {"presented": False, "blockers": ["session_guard_v2_or_v3_required"], "session": session}
        rec = guard.get("project_definition_reconciliation") or {}
        if rec.get("required"):
            binding = proposal.get("project_definition_reconciliation") or {}
            mode, mode_blocker = _resolve_reconciliation_mode(binding, proposal)
            if mode_blocker:
                return {"presented": False, "blockers": [mode_blocker], "session": session}
            if rec.get("mode") not in (None, mode):
                return {"presented": False, "blockers": ["project_definition_reconciliation_mode_mismatch"], "session": session}
            expected_sha = rec.get("authoritative_sha256") if mode == RECONCILIATION_CONTEXT_ONLY else rec.get("prepared_sha256")
            if (
                binding.get("path") != rec.get("path")
                or binding.get("sha256") != expected_sha
                or binding.get("request_digest") != rec.get("request_digest")
                or binding.get("change") != change_id
                or (
                    guard.get("completion_guard_version") == COMPLETION_GUARD_VERSION
                    and binding.get("definition_format_version") != PROJECT_DEFINITION_FORMAT_VERSION
                )
            ):
                return {"presented": False, "blockers": ["project_definition_reconciliation_not_bound"], "session": session}
            definition_path = str(binding.get("path") or "").replace("\\", "/").lstrip("./")
            if mode == RECONCILIATION_CONTEXT_ONLY:
                if definition_path in _scope_paths(proposal):
                    return {"presented": False, "blockers": ["project_definition_context_only_in_scope"], "session": session}
                if _current_definition_digest(layout, binding.get("path")) != binding.get("sha256"):
                    return {"presented": False, "blockers": ["project_definition_context_digest_changed"], "session": session}
            elif definition_path not in _scope_paths(proposal):
                return {"presented": False, "blockers": ["project_definition_not_in_approved_scope"], "session": session}
    digest = canonical_artifact_digest(proposal_path)
    if (change.get("governance") or {}).get("lifecycle_enforcement") == "controlled_v3":
        if proposal.get("change") != change_id or (change.get("proposal") or {}).get("current") != proposal_id:
            return {"presented": False, "blockers": ["proposal_not_current"]}
        if any(item.get("proposal_digest") != digest for item in _presentations(layout, proposal_id)):
            return {"presented": False, "blockers": ["presented_proposal_revision_changed"]}
    presentation_id = _presentation_id()
    root = presentation_root(layout)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{presentation_id}.yaml"
    prospective = _exact_candidate_projection(layout, proposal)
    user_prompt = summary.strip()
    if prospective.get("eligible"):
        user_prompt += "\n\nThis exact prepared candidate can be finalised automatically if validation proves it unchanged. Say \"Approve and finalise\" to authorise that; ordinary approval keeps a separate final acceptance."
    user_prompt += "\n\nShall I make this change?"
    payload = {
        "id": presentation_id,
        "type": "proposal_presentation",
        "proposal": proposal_id,
        "proposal_digest": digest,
        "change": change_id,
        "session": session,
        "presented_at": utc_now(),
        "summary": summary.strip(),
        "user_prompt": user_prompt,
    }
    if prospective.get("eligible"):
        payload["prospective_finalisation"] = {
            "eligible": True,
            "baseline": prospective["baseline"],
            "projected_candidate": prospective["projected_candidate"],
            "acceptance_requirements": prospective["acceptance_requirements"],
        }
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    mark(layout.root, "proposal_presented", change=change_id, proposal=proposal_id, session=session, note=presentation_id)
    return {
        "presented": True,
        "presentation": presentation_id,
        "proposal": proposal_id,
        "proposal_digest": digest,
        "session": session,
        "user_prompt": user_prompt,
        "prospective_finalisation": payload.get("prospective_finalisation"),
        "manager_path": relative(layout, target),
    }

def _presentations(layout, proposal_id: str) -> list[dict]:
    root = presentation_root(layout)
    if not root.is_dir():
        return []
    found = []
    for path in root.glob("PRES-*.yaml"):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("proposal") == proposal_id:
            data["_path"] = path
            found.append(data)
    return sorted(found, key=lambda item: item.get("presented_at") or "")


def verify_informed_approval(layout, proposal_id: str, decision: str, approval_text: str, change_id: str | None = None, *, finalise: bool = False, actor_id: str = "product-owner", actor_name: str | None = None) -> dict:
    if decision not in ("approved", "rejected"):
        return {"permitted": False, "blockers": ["decision_invalid"]}
    if not approval_text.strip():
        return {"permitted": False, "blockers": ["approval_text_missing"]}
    recs = records(layout)
    if proposal_id not in recs:
        return {"permitted": False, "blockers": ["proposal_missing"]}
    proposal, proposal_path = recs[proposal_id]
    change_id = change_id or proposal.get("change")
    change_entry = recs.get(str(change_id))
    change = change_entry[0] if change_entry else {}
    current_digest = canonical_artifact_digest(proposal_path)
    candidates = [p for p in _presentations(layout, proposal_id) if p.get("proposal_digest") == current_digest]
    if not candidates:
        stale = bool(_presentations(layout, proposal_id))
        return {"permitted": False, "blockers": ["proposal_changed_since_presentation" if stale else "proposal_not_presented"], "proposal": proposal_id, "current_digest": current_digest}
    presentation = candidates[-1]
    prospective = presentation.get("prospective_finalisation") or {}
    reconciliation_binding = proposal.get("project_definition_reconciliation") or {}
    reconciliation_mode, reconciliation_blocker = _resolve_reconciliation_mode(reconciliation_binding, proposal)
    if reconciliation_blocker:
        return {"permitted": False, "blockers": [reconciliation_blocker], "proposal": proposal_id, "presentation": presentation.get("id")}
    if reconciliation_binding:
        definition_path = str(reconciliation_binding.get("path") or "").replace("\\", "/").lstrip("./")
        if reconciliation_mode == RECONCILIATION_CONTEXT_ONLY:
            if definition_path in _scope_paths(proposal):
                return {"permitted": False, "blockers": ["project_definition_context_only_in_scope"], "proposal": proposal_id, "presentation": presentation.get("id")}
            if _current_definition_digest(layout, reconciliation_binding.get("path")) != reconciliation_binding.get("sha256"):
                return {"permitted": False, "blockers": ["project_definition_context_digest_changed"], "proposal": proposal_id, "presentation": presentation.get("id")}
        elif definition_path not in _scope_paths(proposal):
            return {"permitted": False, "blockers": ["project_definition_not_in_approved_scope"], "proposal": proposal_id, "presentation": presentation.get("id")}
    if finalise:
        blockers = []
        if decision != "approved":
            blockers.append("prospective_finalisation_requires_approval")
        if not _explicit_finalisation_authority(approval_text):
            blockers.append("prospective_finalisation_not_explicit")
        if prospective.get("eligible") is not True:
            blockers.append("prospective_finalisation_not_eligible")
        try:
            current_material = material_snapshot(layout)
        except Exception as exc:
            blockers.append(f"material_snapshot_unavailable:{exc}")
            current_material = {}
        baseline = prospective.get("baseline") or {}
        if current_material.get("revision") != baseline.get("revision") or current_material.get("file_count") != baseline.get("file_count"):
            blockers.append("prospective_finalisation_baseline_changed")
        if blockers:
            return {"permitted": False, "blockers": sorted(set(blockers)), "proposal": proposal_id, "presentation": presentation.get("id")}
    received_at = utc_now()
    actor = {"type": "human", "id": actor_id}
    if actor_name:
        actor["display_name"] = actor_name
    proof = {
        "type": "informed_approval_proof",
        "proposal": proposal_id,
        "proposal_digest": current_digest,
        "change": change_id,
        "presentation": presentation.get("id"),
        "session": presentation.get("session"),
        "presented_at": presentation.get("presented_at"),
        "decision": decision,
        "approval_text": approval_text,
        "actor": actor,
        "received_at": received_at,
    }
    if finalise:
        proof["prospective_finalisation_requested"] = True
    proof_root = evidence_root(layout) / "informed-approvals"
    proof_root.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(presentation.get("id")))
    target = proof_root / f"{safe_id}.yaml"
    target.write_text(yaml.safe_dump(proof, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")

    canonical_approval = None
    if decision == "approved" and (change.get("governance") or {}).get("lifecycle_enforcement") == "controlled_v3":
        apr_id = _next_apr_id(layout)
        apr = {
            "id": apr_id,
            "change": change_id,
            "proposal": proposal_id,
            "decision": "approved",
            "actor": actor,
            "timestamp": received_at,
            "scope": {"proposal_sha256": current_digest},
            "mechanism": {"type": "conversation", "reference": approval_text.strip()},
            "evidence": {
                "proposal_digest_algorithm": "sha256",
                "proposal_digest": current_digest,
                "informed_approval_proof": relative(layout, target),
                "received_at": received_at,
            },
        }
        changed = dict(change)
        approvals = list(changed.get("approvals") or [])
        approvals.append(apr_id)
        changed["approvals"] = approvals
        apr_path = change_entry[1].parent / "approvals" / f"{apr_id}.yaml"
        _atomic_yaml_updates([(apr_path, apr), (change_entry[1], changed)])
        canonical_approval = {"id": apr_id, "record": relative(layout, apr_path)}
        recs = records(layout)
        change = recs[change_id][0]

    pfa = None
    pfa_path = None
    if finalise:
        pfa_id = _next_pfa_id(layout)
        pfa_root = _history_root(layout) / "authorities"
        pfa_root.mkdir(parents=True, exist_ok=True)
        pfa_path = pfa_root / f"{pfa_id}.yaml"
        pfa = {
            "id": pfa_id,
            "change": change_id,
            "proposal": proposal_id,
            "proposal_digest": current_digest,
            "actor": actor,
            "timestamp": received_at,
            "mechanism": {"type": "conversation", "reference": approval_text.strip()},
            "presentation": str(presentation.get("id")),
            "informed_approval_proof": relative(layout, target),
            "scope": {"mode": "prospective_exact_candidate_v1", "change_set": [change_id]},
            "baseline": prospective["baseline"],
            "projected_candidate": prospective["projected_candidate"],
            "acceptance_requirements": list(prospective.get("acceptance_requirements") or []),
        }
        pfa_path.write_text(yaml.safe_dump(pfa, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
        mark(layout.root, "prospective_finalisation_granted", change=change_id, proposal=proposal_id, session=proof.get("session"), note=pfa_id)

    mark(layout.root, "approval_received", change=change_id, proposal=proposal_id, session=proof.get("session"), note=decision)
    out = {
        "permitted": True,
        "decision": decision,
        "proposal": proposal_id,
        "proposal_digest": current_digest,
        "presentation": presentation.get("id"),
        "session": presentation.get("session"),
        "proof": relative(layout, target),
    }
    if canonical_approval:
        out["approval"] = canonical_approval
    if pfa:
        out["prospective_finalisation_authority"] = {
            "id": pfa["id"],
            "record": relative(layout, pfa_path),
            "projected_candidate": pfa["projected_candidate"],
        }
    return out

def _informed_approval_proof(layout, proposal_id: str, proposal_digest: str) -> dict | None:
    root = evidence_root(layout) / "informed-approvals"
    if not root.is_dir():
        return None
    matches = []
    for path in root.glob("*.yaml"):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("proposal") == proposal_id and data.get("proposal_digest") == proposal_digest and data.get("decision") == "approved" and data.get("presentation"):
            data["_path"] = path
            matches.append(data)
    return sorted(matches, key=lambda item: item.get("received_at") or "")[-1] if matches else None


def _checkpoint_authority(recs: dict, change: dict) -> tuple[dict | None, list[str]]:
    blockers = []
    meta = change.get("checkpoint") or {}
    checkpoint_id = meta.get("completed_in")
    acceptance_id = meta.get("acceptance")
    checkpoint = recs.get(str(checkpoint_id), (None, None))[0] if checkpoint_id else None
    acceptance = recs.get(str(acceptance_id), (None, None))[0] if acceptance_id else None
    if not checkpoint_id:
        blockers.append("checkpoint_completion_missing")
    elif not checkpoint:
        blockers.append("checkpoint_record_missing")
    elif checkpoint.get("status") != "accepted":
        blockers.append("checkpoint_not_accepted")
    if not acceptance_id:
        blockers.append("checkpoint_acceptance_missing")
    elif not acceptance:
        blockers.append("checkpoint_acceptance_record_missing")
    elif acceptance.get("decision") != "accepted":
        blockers.append("checkpoint_acceptance_not_accepted")
    if checkpoint and acceptance_id and (checkpoint.get("acceptance") or {}).get("current") != acceptance_id:
        blockers.append("checkpoint_acceptance_binding_mismatch")
    if acceptance and checkpoint_id and acceptance.get("checkpoint") != checkpoint_id:
        blockers.append("acceptance_checkpoint_binding_mismatch")
    return ({"checkpoint": checkpoint_id, "acceptance": acceptance_id} if not blockers else None, blockers)


def _scope_paths(proposal: dict) -> set[str]:
    out = set()
    for item in proposal.get("declared_scope") or []:
        if not isinstance(item, dict):
            continue
        for key in ("path", "to"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                out.add(value.strip().replace("\\", "/").lstrip("./"))
    return out


def finish_interaction(layout, session: str, change_id: str, deliverables: list[str], project_definition_action: str) -> dict:
    blockers = []
    guard = _load_session_guard(layout, session)
    guard_version = (guard or {}).get("completion_guard_version")
    if not guard or guard_version not in SUPPORTED_COMPLETION_GUARD_VERSIONS:
        blockers.append("session_not_completion_guarded")
    if not interaction_started(layout, session):
        blockers.append("interaction_session_not_started")

    recs = records(layout)
    change_entry = recs.get(change_id)
    change = change_entry[0] if change_entry else None
    if not change:
        blockers.append("change_missing")
    elif change.get("status") != "completed":
        blockers.append("change_not_completed")

    proposal_id = (change.get("proposal") or {}).get("current") if change else None
    proposal_entry = recs.get(str(proposal_id)) if proposal_id else None
    proposal = proposal_entry[0] if proposal_entry else None
    proposal_digest = canonical_artifact_digest(proposal_entry[1]) if proposal_entry else None
    if not proposal:
        blockers.append("current_proposal_missing")
    elif not _informed_approval_proof(layout, proposal_id, proposal_digest):
        blockers.append("informed_approval_proof_missing")

    authority = None
    if change:
        authority, extra = _checkpoint_authority(recs, change)
        blockers.extend(extra)

    if not deliverables:
        blockers.append("final_deliverables_missing")
    resolved = []
    seen = set()
    for raw in deliverables:
        candidate = (layout.root / raw).resolve()
        try:
            rel = relative(layout, candidate)
        except Exception:
            blockers.append(f"deliverable_outside_project:{raw}")
            continue
        if rel in seen:
            blockers.append(f"deliverable_duplicate:{rel}")
            continue
        seen.add(rel)
        if not candidate.is_file():
            blockers.append(f"deliverable_missing:{rel}")
            continue
        classification = classify_project_path(candidate, layout)
        if classification != "material":
            blockers.append(f"deliverable_not_project_material:{rel}:{classification}")
            continue
        resolved.append({"path": rel, "classification": classification, "sha256": _sha256_file(candidate), "size": candidate.stat().st_size})

    start_definition = (guard or {}).get("project_definition") or {}
    finish_definition = _project_definition_identity(layout)
    reconciliation = (guard or {}).get("project_definition_reconciliation") or {}
    binding = (proposal or {}).get("project_definition_reconciliation") or {}
    reconciliation_mode, reconciliation_blocker = _resolve_reconciliation_mode(binding, proposal)
    if reconciliation_blocker:
        blockers.append(reconciliation_blocker)
    if finish_definition.get("state") != "defined" or not finish_definition.get("path"):
        blockers.append("project_definition_missing")
    elif guard_version in (2, COMPLETION_GUARD_VERSION) and not reconciliation_blocker:
        request_digest = ((guard or {}).get("request") or {}).get("digest")
        if reconciliation.get("change") != change_id:
            blockers.append("project_definition_reconciliation_change_mismatch")
        if reconciliation.get("mode") not in (None, reconciliation_mode):
            blockers.append("project_definition_reconciliation_mode_mismatch")
        if reconciliation_mode == RECONCILIATION_CONTEXT_ONLY:
            definition_path = str(finish_definition.get("path") or "").replace("\\", "/").lstrip("./")
            if project_definition_action != "unchanged":
                blockers.append("project_definition_context_only_requires_unchanged")
            if definition_path in _scope_paths(proposal or {}):
                blockers.append("project_definition_context_only_in_scope")
            if (
                binding.get("path") != finish_definition.get("path")
                or binding.get("request_digest") != request_digest
                or binding.get("change") != change_id
                or (guard_version == COMPLETION_GUARD_VERSION and binding.get("definition_format_version") != PROJECT_DEFINITION_FORMAT_VERSION)
            ):
                blockers.append("project_definition_not_bound_by_approved_proposal")
            authoritative = reconciliation.get("authoritative_sha256") or binding.get("sha256")
            if not authoritative or binding.get("sha256") != authoritative:
                blockers.append("project_definition_context_binding_mismatch")
            if finish_definition.get("sha256") != authoritative:
                blockers.append("project_definition_context_digest_changed")
            if start_definition.get("sha256") != finish_definition.get("sha256"):
                blockers.append("project_definition_changed_but_declared_unchanged")
        else:
            finish_binding = finish_definition.get("current_work") or {}
            if finish_binding.get("request_digest") != request_digest or finish_binding.get("change") != change_id:
                blockers.append("project_definition_current_work_mismatch")
            if guard_version == COMPLETION_GUARD_VERSION:
                managed_definition = finish_definition.get("managed_definition") or {}
                if managed_definition.get("definition_format_version") != PROJECT_DEFINITION_FORMAT_VERSION:
                    blockers.append("project_definition_managed_region_missing_or_invalid")
                if (
                    managed_definition.get("request_digest") != request_digest
                    or managed_definition.get("change") != change_id
                    or managed_definition.get("status") != "current"
                ):
                    blockers.append("project_definition_managed_region_stale")
            if project_definition_action == "updated":
                if not reconciliation.get("required"):
                    blockers.append("project_definition_update_not_required")
                expected = reconciliation.get("prepared_sha256")
                if not expected or finish_definition.get("sha256") != expected:
                    blockers.append("project_definition_prepared_hash_mismatch")
                if (
                    binding.get("sha256") != expected
                    or binding.get("request_digest") != request_digest
                    or binding.get("change") != change_id
                    or binding.get("path") != finish_definition.get("path")
                    or (
                        guard_version == COMPLETION_GUARD_VERSION
                        and binding.get("definition_format_version") != PROJECT_DEFINITION_FORMAT_VERSION
                    )
                ):
                    blockers.append("project_definition_not_bound_by_approved_proposal")
                definition_path = str(finish_definition.get("path") or "").replace("\\", "/").lstrip("./")
                if proposal and definition_path not in _scope_paths(proposal):
                    blockers.append("project_definition_not_in_approved_scope")
            elif project_definition_action == "unchanged":
                start_binding = start_definition.get("current_work") or {}
                if start_definition.get("sha256") != finish_definition.get("sha256"):
                    blockers.append("project_definition_changed_but_declared_unchanged")
                if start_binding.get("request_digest") != request_digest or start_binding.get("change") != change_id:
                    blockers.append("project_definition_stale_but_declared_unchanged")
                if guard_version == COMPLETION_GUARD_VERSION:
                    start_managed = start_definition.get("managed_definition") or {}
                    if (
                        start_managed.get("definition_format_version") != PROJECT_DEFINITION_FORMAT_VERSION
                        or start_managed.get("request_digest") != request_digest
                        or start_managed.get("change") != change_id
                        or start_managed.get("status") != "current"
                    ):
                        blockers.append("project_definition_managed_region_stale_but_declared_unchanged")
            else:
                blockers.append("project_definition_action_invalid")
    elif project_definition_action == "updated":
        if start_definition.get("sha256") == finish_definition.get("sha256"):
            blockers.append("project_definition_not_updated")
        if start_definition.get("state") == "defined" and proposal:
            definition_path = str(finish_definition.get("path") or "").replace("\\", "/").lstrip("./")
            if definition_path not in _scope_paths(proposal):
                blockers.append("project_definition_not_in_approved_scope")
    elif project_definition_action == "unchanged":
        if start_definition.get("sha256") != finish_definition.get("sha256"):
            blockers.append("project_definition_changed_but_declared_unchanged")
    else:
        blockers.append("project_definition_action_invalid")

    if blockers:
        return {"permitted": False, "session": session, "change": change_id, "blockers": sorted(set(blockers))}

    target = completion_path(layout, session)
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        requested = [item["path"] for item in resolved]
        prior = [item.get("path") for item in (existing or {}).get("deliverables") or []]
        if isinstance(existing, dict) and existing.get("outcome") == "delivered" and existing.get("change") == change_id and prior == requested:
            return {"permitted": True, "existing": True, "session": session, "change": change_id, "receipt": relative(layout, target), "deliverables": existing.get("deliverables") or []}
        return {"permitted": False, "session": session, "change": change_id, "blockers": ["completion_receipt_already_exists"]}

    mark(layout.root, "managed_finish_started", change=change_id, proposal=proposal_id, session=session)
    receipt = {
        "type": "managed_completion_receipt",
        "receipt_version": guard_version,
        "outcome": "delivered",
        "session": session,
        "change": change_id,
        "proposal": proposal_id,
        "proposal_digest": proposal_digest,
        "checkpoint": authority["checkpoint"],
        "acceptance": authority["acceptance"],
        "project_definition": {
            "action": project_definition_action,
            "start": start_definition,
            "finish": finish_definition,
            "request_digest": ((guard or {}).get("request") or {}).get("digest"),
            "reconciliation": (guard or {}).get("project_definition_reconciliation"),
            "reconciliation_mode": reconciliation_mode,
        },
        "deliverables": resolved,
        "completed_at": utc_now(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    mark(layout.root, "managed_finish_completed", change=change_id, proposal=proposal_id, session=session, note=relative(layout, target))
    return {"permitted": True, "existing": False, "session": session, "change": change_id, "receipt": relative(layout, target), "checkpoint": authority["checkpoint"], "acceptance": authority["acceptance"], "deliverables": resolved}

def close_interaction(layout, session: str, reason: str) -> dict:
    guard = _load_session_guard(layout, session)
    guard_version = (guard or {}).get("completion_guard_version")
    blockers = []
    if not guard or guard_version not in SUPPORTED_COMPLETION_GUARD_VERSIONS:
        blockers.append("session_not_completion_guarded")
    if not interaction_started(layout, session):
        blockers.append("interaction_session_not_started")
    if not reason.strip():
        blockers.append("non_delivery_reason_missing")
    if blockers:
        return {"closed": False, "session": session, "blockers": blockers}
    target = completion_path(layout, session)
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        if isinstance(existing, dict) and existing.get("outcome") == "non_delivery":
            return {"closed": True, "existing": True, "session": session, "receipt": relative(layout, target)}
        return {"closed": False, "session": session, "blockers": ["completion_receipt_already_exists"]}
    receipt = {"type": "managed_completion_receipt", "receipt_version": guard_version, "outcome": "non_delivery", "session": session, "reason": reason.strip(), "closed_at": utc_now()}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    mark(layout.root, "managed_non_delivery_closed", session=session, note=reason.strip())
    return {"closed": True, "existing": False, "session": session, "receipt": relative(layout, target)}


def mark(root: Path, phase: str, *, change=None, proposal=None, session=None, note=None) -> None:
    try:
        layout = discover_layout(Path(root))
        observer = observer_path(layout)
        if observer is None:
            return
        cmd = [sys.executable, "-B", str(observer), "mark", phase, "--root", str(layout.root), "--json"]
        if change:
            cmd += ["--change", str(change)]
        if proposal:
            cmd += ["--proposal", str(proposal)]
        if session:
            cmd += ["--session", str(session)]
        if note:
            cmd += ["--note", str(note)]
        subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return


def _continuation_summary(layout, change_id: str) -> dict:
    tool = layout.tool_root / "specforge-status.py"
    if not tool.is_file():
        sibling = Path(__file__).resolve().parent / "specforge-status.py"
        tool = sibling if sibling.is_file() else tool
    if not tool.is_file():
        return {"found": False, "change": change_id, "blocked": True, "blockers": ["status_tool_missing"]}
    result = subprocess.run([sys.executable, "-B", str(tool), "--root", str(layout.root), "--continuation", change_id, "--json"], capture_output=True, text=True)
    try: return json.loads(result.stdout or "{}")
    except Exception: return {"found": False, "change": change_id, "blocked": True, "blockers": ["status_output_invalid"]}


def manager_summary(layout, change_id: str, detail: str) -> dict:
    recs = records(layout)
    if change_id not in recs:
        return {"found": False, "change": change_id}
    chg, chg_path = recs[change_id]
    request = chg.get("request") or {}
    current_proposal = (chg.get("proposal") or {}).get("current")
    approvals = []
    for approval_id in chg.get("approvals") or []:
        if approval_id not in recs:
            continue
        approval, path = recs[approval_id]
        approvals.append({
            "id": approval_id,
            "decision": approval.get("decision"),
            "actor": (approval.get("actor") or {}).get("display_name") or (approval.get("actor") or {}).get("id"),
            "path": relative(layout, path),
        })
    attempts = []
    for attempt_id in (chg.get("implementation") or {}).get("attempts") or []:
        if attempt_id not in recs:
            continue
        attempt, path = recs[attempt_id]
        attempts.append({"id": attempt_id, "outcome": attempt.get("outcome"), "path": relative(layout, path)})

    concise = {
        "found": True,
        "change": change_id,
        "what": request.get("summary") or chg.get("title"),
        "why": request.get("detail") or request.get("summary"),
        "status": chg.get("status"),
        "current_proposal": current_proposal,
        "approval": approvals[-1] if approvals else None,
        "implementation": attempts[-1] if attempts else None,
    }
    concise["continuation"] = _continuation_summary(layout, change_id)
    if detail == "minimal":
        return concise
    concise["paths"] = {"change": relative(layout, chg_path)}
    concise["all_approvals"] = approvals
    concise["all_implementation_attempts"] = attempts
    if detail == "full":
        concise["raw_change"] = chg
        if current_proposal in recs:
            concise["raw_proposal"] = recs[current_proposal][0]
    return concise



_PROGRESS_STAGE_LABELS = {
    "proposal_prepared": "proposal prepared",
    "proposal_approved": "proposal approved",
    "implementation": "implementation",
    "product_validation": "product validation",
    "specforge_validation": "SpecForge validation",
    "checkpoint_accepted": "checkpoint accepted",
    "completed": "completion",
}

_PROGRESS_ACTION_LABELS = {
    "approval": "your approval",
    "implementation_validation": "implementation and validation",
    "advance_to_ready_for_checkpoint": "checkpoint preparation",
    "checkpoint_presentation": "checkpoint presentation",
    "checkpoint_acceptance": "your checkpoint acceptance",
}


def _add_progress_stage(stages: list[str], value: str) -> None:
    if value not in stages:
        stages.append(value)


def _progress_observation(layout, change_id: str, session: str | None) -> dict:
    args = ["summary", "--change", change_id]
    if session:
        args += ["--session", session]
    code, payload = observer_call(layout, *args)
    if code != 0 or not payload.get("ok"):
        return {
            "ok": False,
            "current_activity": {
                "state": "unavailable",
                "category": None,
                "active": False,
                "started_at": None,
                "elapsed_seconds": None,
                "detail": None,
                "reason": payload.get("error") or "observer_summary_unavailable",
            },
            "phase_counts": {},
        }
    return payload


def _progress_boundary(continuation: dict) -> dict:
    if continuation.get("blocked"):
        return {"type": "blocked", "action": None, "label": "resolve the repository blocker"}
    action = continuation.get("next_action")
    if action is None:
        return {"type": "terminal", "action": None, "label": "no further governed action"}
    return {
        "type": "human" if continuation.get("human_boundary") else "lifecycle",
        "action": action,
        "label": _PROGRESS_ACTION_LABELS.get(action, str(action).replace("_", " ")),
    }


def _progress_message(state: str, detail: str | None, completed: list[str], boundary: dict) -> str:
    labels = [_PROGRESS_STAGE_LABELS.get(item, item.replace("_", " ")) for item in completed]
    prefix = "Completed: " + ", ".join(labels) + ". " if labels else ""
    if state == "completed":
        return prefix + "The change is complete. No further processing remains."
    if state == "blocked":
        return prefix + "Work is blocked by repository evidence that must be resolved before continuing."
    if state == "clarification_wait":
        return prefix + "I’m waiting for your clarification before I can continue."
    if state == "waiting_for_approval":
        return prefix + "The proposed change is ready and waiting for your approval."
    if state == "waiting_for_checkpoint_acceptance":
        return prefix + "The verified candidate is ready and waiting for your checkpoint acceptance."

    activity_text = {
        "specforge_validation": "SpecForge validation is running",
        "product_validation": "Product validation is running",
        "legacy_validation": "Validation is running",
        "implementation": "Implementation is in progress",
        "productive_work": "Product work is in progress",
        "preparing_checkpoint": "Checkpoint preparation is in progress",
        "implementation_validation": "Implementation or validation is the active lifecycle stage",
        "idle": "Work is between recorded stages",
        "unavailable": "Detailed observer progress is not available",
    }.get(state, str(state).replace("_", " ").capitalize())
    if detail:
        activity_text += ": " + detail.rstrip(".")
    message = prefix + activity_text + "."
    if boundary.get("type") not in ("terminal", "blocked") and boundary.get("label"):
        message += " Next: " + boundary["label"] + "."
    return message



def _integrity_live_progress(layout) -> dict | None:
    configured = os.environ.get("SPECFORGE_INTEGRITY_PROGRESS")
    path = Path(configured).resolve() if configured else (layout.root / "specforge/evidence/integrity/progress.jsonl").resolve()
    if not path.is_file():
        return None
    try:
        age = dt.datetime.now(dt.timezone.utc).timestamp() - path.stat().st_mtime
        if age > 300:
            return None
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        row = json.loads(lines[-1])
    except Exception:
        return None
    if row.get("phase") in ("complete", "failed"):
        return None
    return row


def _integrity_progress_detail(row: dict) -> str:
    phase = str(row.get("phase") or "integrity validation").replace("_", " ")
    substage = row.get("substage")
    processed = row.get("processed")
    total = row.get("total")
    detail = str(substage or phase)
    if isinstance(processed, int) and isinstance(total, int) and total >= 0:
        detail += f" ({processed}/{total})"
    return detail


def progress_summary(layout, change_id: str, session: str | None = None) -> dict:
    manager = manager_summary(layout, change_id, "minimal")
    if not manager.get("found"):
        return {"found": False, "change": change_id, "blockers": ["change_missing"]}
    continuation = manager.get("continuation") or {}
    observation = _progress_observation(layout, change_id, session)
    raw_activity = observation.get("current_activity") or {}
    phase_counts = observation.get("phase_counts") or {}
    status = manager.get("status")
    boundary = _progress_boundary(continuation)

    completed = []
    if manager.get("current_proposal"):
        _add_progress_stage(completed, "proposal_prepared")
    approval = manager.get("approval") or {}
    if approval.get("decision") == "approved" or status in ("approved", "in_progress", "implemented", "validated", "ready_for_checkpoint", "completed"):
        _add_progress_stage(completed, "proposal_approved")
    implementation = manager.get("implementation") or {}
    if implementation.get("outcome") == "passed" or phase_counts.get("implementation_completed", 0) or status in ("implemented", "validated", "ready_for_checkpoint", "completed"):
        _add_progress_stage(completed, "implementation")
    if phase_counts.get("product_validation_completed", 0):
        _add_progress_stage(completed, "product_validation")
    if phase_counts.get("specforge_validation_completed", 0) or phase_counts.get("validation_completed", 0):
        _add_progress_stage(completed, "specforge_validation")
    if status == "completed":
        _add_progress_stage(completed, "checkpoint_accepted")
        _add_progress_stage(completed, "completed")

    if status == "completed":
        state = "completed"
        effective_activity = {"state": state, "active": False, "source": "continuation"}
    elif continuation.get("blocked"):
        state = "blocked"
        effective_activity = {"state": state, "active": False, "source": "continuation"}
    elif raw_activity.get("state") == "clarification_wait" and raw_activity.get("active"):
        state = "clarification_wait"
        effective_activity = dict(raw_activity)
        effective_activity["source"] = "observer"
    elif continuation.get("human_boundary"):
        state = "waiting_for_approval" if continuation.get("next_action") == "approval" else "waiting_for_checkpoint_acceptance"
        effective_activity = {"state": state, "active": False, "source": "continuation"}
    elif raw_activity.get("active") and raw_activity.get("state") != "approval_wait":
        state = raw_activity.get("state")
        effective_activity = dict(raw_activity)
        effective_activity["source"] = "observer"
    else:
        action = continuation.get("next_action")
        if action in ("checkpoint_presentation", "advance_to_ready_for_checkpoint"):
            state = "preparing_checkpoint"
        elif action == "implementation_validation":
            state = "implementation_validation"
        else:
            state = raw_activity.get("state") or "unavailable"
        effective_activity = dict(raw_activity)
        effective_activity.update({"state": state, "active": False, "source": "continuation"})

    live_integrity = _integrity_live_progress(layout)
    if live_integrity and state not in ("completed", "blocked", "clarification_wait", "waiting_for_approval", "waiting_for_checkpoint_acceptance"):
        state = "specforge_validation"
        effective_activity = {
            "state": state,
            "active": True,
            "source": "integrity_validator",
            "detail": _integrity_progress_detail(live_integrity),
            "validator": live_integrity,
        }

    user_message = _progress_message(state, effective_activity.get("detail"), completed, boundary)
    return {
        "found": True,
        "change": change_id,
        "session": session,
        "status": status,
        "terminal": status == "completed",
        "completed_stages": completed,
        "current_activity": effective_activity,
        "observer_activity": raw_activity,
        "next_boundary": boundary,
        "blocked": bool(continuation.get("blocked")),
        "blockers": continuation.get("blockers") or [],
        "heartbeat": {"target_seconds": 60, "when_host_has_control": True, "invent_eta": False},
        "user_message": user_message,
    }



def _latest_matching_reconciliation_observation(layout, reconciliation: dict) -> dict | None:
    root = evidence_root(layout) / "reconciliations"
    if not root.is_dir(): return None
    kind = reconciliation.get("kind")
    paths = sorted(set(reconciliation.get("paths") or []))
    try: current = material_snapshot(layout)
    except Exception: current = None
    matches = []
    for path in root.glob("REC-*.yaml"):
        try: record = load_yaml(path)
        except Exception: continue
        if not isinstance(record, dict) or record.get("profile") != "material_reconciliation_v1": continue
        if record.get("kind") != kind or record.get("status") not in {"observed", "blocked"}: continue
        if sorted(set(((record.get("material") or {}).get("paths") or []))) != paths: continue
        snapshot = ((record.get("material") or {}).get("snapshot") or {})
        if snapshot.get("revision") and current and snapshot.get("revision") != current.get("revision"): continue
        item = dict(record); item["_path"] = relative(layout, path); matches.append(item)
    return sorted(matches, key=lambda item: (item.get("created_at") or "", item.get("id") or ""))[-1] if matches else None

def reconcile_observe(layout) -> dict:
    return capture_reconciliation_observation(layout)

def reconcile_decide(layout, reconciliation_id: str, decision: str, actor_id: str, actor_name: str | None) -> dict:
    return record_reconciliation_decision(layout, reconciliation_id, decision, actor_id=actor_id, actor_name=actor_name)

def reconcile_repair(layout, reconciliation_id: str | None) -> dict:
    return repair_authority_bookkeeping(layout, reconciliation_id)

def reconcile_apply(layout, reconciliation_id: str) -> dict:
    return apply_reconciliation_recovery(layout, reconciliation_id)

_GUIDE_TERMINAL_STATUSES = {"completed", "rejected", "cancelled", "superseded"}


def _guide_changes(layout) -> list[tuple[str, dict]]:
    found = []
    for rid, (record, _) in records(layout).items():
        if not str(rid).startswith("CHG-"):
            continue
        if record.get("status") in _GUIDE_TERMINAL_STATUSES:
            continue
        found.append((str(rid), record))
    return sorted(found, key=lambda item: item[0])


def _guide_approval_prompt(layout, change: dict) -> str:
    proposal_id = (change.get("proposal") or {}).get("current")
    if proposal_id:
        presentations = _presentations(layout, str(proposal_id))
        if presentations:
            prompt = str(presentations[-1].get("user_prompt") or "").strip()
            if prompt:
                return prompt
    summary = ((change.get("request") or {}).get("summary") or change.get("title") or "the proposed change").strip()
    return f"I'm ready to make the proposed change: {summary}. Shall I make this change?"


def _guide_checkpoint_prompt(layout, change_id: str) -> str:
    recs = records(layout)
    candidates = []
    for rid, (record, _) in recs.items():
        if not str(rid).startswith("CHK-"):
            continue
        if change_id not in (record.get("included_changes") or []):
            continue
        if record.get("status") not in ("candidate", "under_validation"):
            continue
        candidates.append((str(rid), record))
    if candidates:
        checkpoint_id, _ = sorted(candidates, key=lambda item: item[0])[-1]
        presentations = _checkpoint_presentations(layout, checkpoint_id)
        if presentations:
            prompt = str(presentations[-1][0].get("user_prompt") or "").strip()
            if prompt:
                return prompt
    return "The approved work has been implemented and verified. Accept the result?"


def guided_non_expert(layout, request_text: str | None = None, session: str | None = None, change_id: str | None = None) -> dict:
    """Read-only routing for an ordinary user or host. It never creates authority."""
    bootstrap = managed_bootstrap(layout)
    base = {
        "contract": GUIDE_PROFILE,
        "state": None,
        "internal_next_action": None,
        "human_decision_required": False,
        "blockers": [],
        "resolved": {"change": None, "session": session},
        "user_message": "",
    }


    governance_details = ((bootstrap.get("manager") or {}).get("governance_details") or {})
    reconciliation = governance_details.get("material_reconciliation") or {}
    if reconciliation:
        kind = reconciliation.get("kind")
        observation = _latest_matching_reconciliation_observation(layout, reconciliation)
        manager = {
            "reconciliation": reconciliation,
            "observation": ({k: v for k, v in observation.items() if k != "_path"} if observation else None),
            "observation_path": observation.get("_path") if observation else None,
        }
        if observation is None:
            base.update({
                "state": "reconciliation_observation_required",
                "internal_next_action": "reconcile_observe",
                "human_decision_required": False,
                "user_message": "I found project changes that need to be identified safely before work can continue. I’ll capture exactly what changed first; no project files will be altered.",
                "manager": manager,
            })
            return base
        observation_id = observation.get("id")
        if kind == "authority_bookkeeping":
            repairable = bool(reconciliation.get("repairable"))
            base.update({
                "state": "repairing_internal_bookkeeping" if repairable else "blocked",
                "internal_next_action": "reconcile_repair" if repairable else None,
                "human_decision_required": False,
                "blockers": [] if repairable else list((bootstrap.get("manager") or {}).get("governance_blockers") or ["authority_bookkeeping_reconciliation_not_safe"]),
                "reconciliation": observation_id,
                "user_message": "I found an internal SpecForge bookkeeping mismatch. The accepted project work itself is unchanged, so I can repair the internal pointer without changing project files." if repairable else "I found an internal SpecForge bookkeeping mismatch, but it is not safe to repair automatically. Project files will be left untouched for review.",
                "manager": manager,
            })
            return base
        if kind == "ambiguous_material":
            base.update({
                "state": "reconciliation_review_required",
                "internal_next_action": "reconcile_decision",
                "human_decision_required": True,
                "reconciliation": observation_id,
                "choices": [
                    {"decision": "leave_untouched", "label": "Leave everything untouched"},
                    {"decision": "unknown", "label": "I’m not sure; keep it blocked for review"},
                ],
                "user_message": "I found project changes, but their origin or boundaries are ambiguous. I won’t keep, undo or move them automatically. You can leave everything untouched or keep the project blocked for review.",
                "manager": manager,
            })
            return base
        base.update({
            "state": "waiting_for_material_reconciliation",
            "internal_next_action": "reconcile_decision",
            "human_decision_required": True,
            "reconciliation": observation_id,
            "choices": [
                {"decision": "keep", "label": "Keep these changes"},
                {"decision": "undo", "label": "Undo these changes"},
                {"decision": "set_aside", "label": "Set these changes aside"},
                {"decision": "leave_untouched", "label": "Leave everything untouched for now"},
            ],
            "user_message": "I found changes made outside the managed workflow. Would you like to keep them, undo them, set them aside, or leave everything untouched for now? Keeping them will still require a separate approval before they can become trusted project work.",
            "manager": manager,
        })
        return base

    if bootstrap.get("managed_state") == "blocked":
        base.update({
            "state": "blocked",
            "blockers": list((bootstrap.get("manager") or {}).get("governance_blockers") or ["managed_bootstrap_blocked"]),
            "user_message": "This project needs internal SpecForge attention before work can continue.",
            "manager": bootstrap.get("manager") or {},
        })
        return base

    if bootstrap.get("managed_state") == "needs_project_definition":
        base.update({
            "state": "needs_project_definition",
            "internal_next_action": "define_project",
            "human_decision_required": True,
            "user_message": "Before I start managing this project, what are you trying to achieve?",
        })
        return base

    recs = records(layout)
    selected = None
    selected_record = None

    if change_id:
        entry = recs.get(change_id)
        if not entry or not str(change_id).startswith("CHG-"):
            base.update({
                "state": "blocked",
                "blockers": ["current_workspace_missing_required_change"],
                "user_message": "The requested governed work is not available in this workspace, so I won't guess or switch lineages.",
            })
            return base
        selected, selected_record = change_id, entry[0]
    else:
        definition = _project_definition_identity(layout)
        current = (definition.get("current_work") or {}).get("change")
        if current and current in recs and recs[current][0].get("status") not in _GUIDE_TERMINAL_STATUSES:
            selected, selected_record = current, recs[current][0]
        else:
            open_changes = _guide_changes(layout)
            if len(open_changes) > 1:
                base.update({
                    "state": "blocked",
                    "blockers": ["ambiguous_continuation"],
                    "choices": [
                        {"change": cid, "summary": ((record.get("request") or {}).get("summary") or record.get("title"))}
                        for cid, record in open_changes
                    ],
                    "user_message": "More than one governed piece of work could be continued. I need the host to choose the correct one rather than guessing.",
                })
                return base
            if len(open_changes) == 1:
                selected, selected_record = open_changes[0]

    if selected is None:
        if request_text and request_text.strip():
            base.update({
                "state": "ready_for_new_work",
                "internal_next_action": "begin",
                "human_decision_required": False,
                "user_message": "I'm ready to start that work. No SpecForge identifiers are needed from you.",
            })
        else:
            base.update({
                "state": "ready_for_request",
                "internal_next_action": "await_request",
                "human_decision_required": True,
                "user_message": "What would you like me to change or create?",
            })
        return base

    base["resolved"]["change"] = selected
    status = selected_record.get("status")

    if status == "completed":
        base.update({
            "state": "completed",
            "internal_next_action": None,
            "human_decision_required": False,
            "user_message": "The governed work is complete. No further processing remains.",
        })
        return base

    continuation = _continuation_summary(layout, selected)
    if continuation.get("blocked"):
        base.update({
            "state": "blocked",
            "blockers": list(continuation.get("blockers") or ["continuation_blocked"]),
            "user_message": "The current governed work is blocked by repository evidence that must be resolved before continuing.",
            "manager": {"continuation": continuation},
        })
        return base

    action = continuation.get("next_action")
    human = bool(continuation.get("human_boundary"))
    state_by_action = {
        "approval": "waiting_for_approval",
        "implementation_validation": "implementation_validation",
        "advance_to_ready_for_checkpoint": "preparing_checkpoint",
        "checkpoint_presentation": "preparing_checkpoint",
        "checkpoint_acceptance": "waiting_for_checkpoint_acceptance",
    }
    state = state_by_action.get(action, "continuing" if action else "blocked")
    if action is None:
        base.update({
            "state": "blocked",
            "blockers": ["continuation_next_action_missing"],
            "user_message": "The repository does not expose a safe next action, so I won't guess.",
            "manager": {"continuation": continuation},
        })
        return base

    if action == "approval":
        message = _guide_approval_prompt(layout, selected_record)
    elif action == "checkpoint_acceptance":
        message = _guide_checkpoint_prompt(layout, selected)
    elif action == "implementation_validation":
        message = "The approved work can continue through implementation and validation. No response is needed."
    elif action in ("advance_to_ready_for_checkpoint", "checkpoint_presentation"):
        message = "The approved work is verified and can move to final review. No response is needed."
    else:
        message = "The current governed work can continue automatically. No response is needed."

    base.update({
        "state": state,
        "internal_next_action": action,
        "human_decision_required": human,
        "user_message": message,
        "manager": {"continuation": continuation},
    })
    return base

def main():
    parser = argparse.ArgumentParser(description="Experimental invisible SpecForge managed-workflow layer")
    sub = parser.add_subparsers(dest="command", required=True)

    bp = sub.add_parser("bootstrap")
    bp.add_argument("--root", default=".")
    bp.add_argument("--json", action="store_true")

    cap = sub.add_parser("capabilities")
    cap.add_argument("--root", default=".")
    cap.add_argument("--require", action="append", default=[])
    cap.add_argument("--available", action="append", default=[])
    cap.add_argument("--json", action="store_true")

    guide = sub.add_parser("guide")
    guide.add_argument("--root", default=".")
    guide.add_argument("--request")
    guide.add_argument("--session")
    guide.add_argument("--change")
    guide.add_argument("--json", action="store_true")

    begin = sub.add_parser("begin")
    begin.add_argument("--root", default=".")
    begin.add_argument("--session")
    begin.add_argument("--request")
    begin.add_argument("--change")
    begin.add_argument("--json", action="store_true")

    dp = sub.add_parser("define")
    dp.add_argument("--root", default=".")
    dp.add_argument("--purpose", required=True)
    dp.add_argument("--deliverable")
    dp.add_argument("--audience")
    dp.add_argument("--json", action="store_true")

    cr = sub.add_parser("clarify")
    cr.add_argument("--root", default=".")
    cr.add_argument("--session", required=True)
    cr.add_argument("--change")
    cr.add_argument("--question", required=True)
    cr.add_argument("--json", action="store_true")

    ro = sub.add_parser("reconcile-observe")
    ro.add_argument("--root", default=".")
    ro.add_argument("--json", action="store_true")

    rd = sub.add_parser("reconcile-decision")
    rd.add_argument("--root", default=".")
    rd.add_argument("--reconciliation", required=True)
    rd.add_argument("--decision", required=True, choices=("keep", "undo", "set_aside", "leave_untouched", "unknown"))
    rd.add_argument("--actor-id", default="product-owner")
    rd.add_argument("--actor-name")
    rd.add_argument("--json", action="store_true")

    ra = sub.add_parser("reconcile-apply")
    ra.add_argument("--root", default=".")
    ra.add_argument("--reconciliation", required=True)
    ra.add_argument("--json", action="store_true")

    rb = sub.add_parser("reconcile-repair")
    rb.add_argument("--root", default=".")
    rb.add_argument("--reconciliation")
    rb.add_argument("--json", action="store_true")

    rr = sub.add_parser("resolve-clarification")
    rr.add_argument("--root", default=".")
    rr.add_argument("--session", required=True)
    rr.add_argument("--change")
    rr.add_argument("--clarification", required=True)
    rr.add_argument("--response", required=True)
    rr.add_argument("--json", action="store_true")

    pd = sub.add_parser("prepare-definition")
    pd.add_argument("--root", default=".")
    pd.add_argument("--session", required=True)
    pd.add_argument("--change", required=True)
    pd.add_argument("--summary", required=True)
    pd.add_argument("--mode", choices=SUPPORTED_RECONCILIATION_MODES, default=RECONCILIATION_DURABLE_UPDATE)
    pd.add_argument("--json", action="store_true")

    ia = sub.add_parser("implementation-authority")
    ia.add_argument("--root", default=".")
    ia.add_argument("--change", required=True)
    ia.add_argument("--proposal")
    ia.add_argument("--json", action="store_true")

    ad = sub.add_parser("apply-definition")
    ad.add_argument("--root", default=".")
    ad.add_argument("--session", required=True)
    ad.add_argument("--change", required=True)
    ad.add_argument("--json", action="store_true")

    cpp = sub.add_parser("checkpoint-present")
    cpp.add_argument("--root", default=".")
    cpp.add_argument("--checkpoint", required=True)
    cpp.add_argument("--session", required=True)
    cpp.add_argument("--json", action="store_true")

    cpa = sub.add_parser("checkpoint-acceptance")
    cpa.add_argument("--root", default=".")
    cpa.add_argument("--checkpoint", required=True)
    cpa.add_argument("--session", required=True)
    cpa.add_argument("--text", required=True)
    cpa.add_argument("--actor-id", default="product-owner")
    cpa.add_argument("--actor-name")
    cpa.add_argument("--json", action="store_true")

    pp = sub.add_parser("present")
    pp.add_argument("--root", default=".")
    pp.add_argument("--proposal", required=True)
    pp.add_argument("--change")
    pp.add_argument("--session")
    pp.add_argument("--summary", required=True)
    pp.add_argument("--json", action="store_true")

    ap = sub.add_parser("approval")
    ap.add_argument("--root", default=".")
    ap.add_argument("--proposal", required=True)
    ap.add_argument("--change")
    ap.add_argument("--decision", required=True, choices=("approved", "rejected"))
    ap.add_argument("--text", required=True)
    ap.add_argument("--finalise", action="store_true")
    ap.add_argument("--actor-id", default="product-owner")
    ap.add_argument("--actor-name")
    ap.add_argument("--json", action="store_true")

    fp = sub.add_parser("finish")
    fp.add_argument("--root", default=".")
    fp.add_argument("--session", required=True)
    fp.add_argument("--change", required=True)
    fp.add_argument("--deliverable", action="append", default=[])
    fp.add_argument("--project-definition-action", required=True, choices=("updated", "unchanged"))
    fp.add_argument("--json", action="store_true")

    cp = sub.add_parser("close")
    cp.add_argument("--root", default=".")
    cp.add_argument("--session", required=True)
    cp.add_argument("--reason", required=True)
    cp.add_argument("--json", action="store_true")

    sp = sub.add_parser("summary")
    sp.add_argument("change")
    sp.add_argument("--root", default=".")
    sp.add_argument("--detail", choices=("minimal", "standard", "full"), default="minimal")
    sp.add_argument("--json", action="store_true")

    pg = sub.add_parser("progress")
    pg.add_argument("change")
    pg.add_argument("--root", default=".")
    pg.add_argument("--session")
    pg.add_argument("--json", action="store_true")

    args = parser.parse_args()
    try:
        layout = discover_layout(Path(args.root))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"project_discovery_failed:{exc}"}))
        sys.exit(2)

    if args.command == "bootstrap":
        out = managed_bootstrap(layout)
    elif args.command == "capabilities":
        out = execution_channel_capabilities(args.require, args.available)
    elif args.command == "guide":
        out = guided_non_expert(layout, args.request, args.session, args.change)
    elif args.command == "begin":
        out = begin_interaction(layout, args.session, args.request, args.change)
    elif args.command == "reconcile-observe":
        out = reconcile_observe(layout)
    elif args.command == "reconcile-decision":
        out = reconcile_decide(layout, args.reconciliation, args.decision, args.actor_id, args.actor_name)
    elif args.command == "reconcile-apply":
        out = reconcile_apply(layout, args.reconciliation)
    elif args.command == "reconcile-repair":
        out = reconcile_repair(layout, args.reconciliation)
    elif args.command == "clarify":
        out = request_clarification(layout, args.session, args.question, args.change)
    elif args.command == "resolve-clarification":
        out = resolve_clarification(layout, args.session, args.clarification, args.response, args.change)
    elif args.command == "prepare-definition":
        out = prepare_project_definition(layout, args.session, args.change, args.summary, args.mode)
    elif args.command == "implementation-authority":
        out = implementation_authority(layout, args.change, args.proposal)
    elif args.command == "apply-definition":
        out = apply_project_definition(layout, args.session, args.change)
    elif args.command == "checkpoint-present":
        out = present_checkpoint(layout, args.checkpoint, args.session)
    elif args.command == "checkpoint-acceptance":
        out = record_checkpoint_acceptance(layout, args.checkpoint, args.session, args.text, args.actor_id, args.actor_name)
    elif args.command == "define":
        out = define_project(layout, args.purpose, args.deliverable, args.audience)
    elif args.command == "present":
        out = present_proposal(layout, args.proposal, args.summary, args.change, args.session)
    elif args.command == "approval":
        out = verify_informed_approval(layout, args.proposal, args.decision, args.text, args.change, finalise=args.finalise, actor_id=args.actor_id, actor_name=args.actor_name)
    elif args.command == "finish":
        out = finish_interaction(layout, args.session, args.change, args.deliverable, args.project_definition_action)
    elif args.command == "close":
        out = close_interaction(layout, args.session, args.reason)
    elif args.command == "progress":
        out = progress_summary(layout, args.change, args.session)
    else:
        out = manager_summary(layout, args.change, args.detail)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    if args.command == "capabilities" and not out.get("permitted"):
        sys.exit(1)
    if args.command == "implementation-authority" and not out.get("permitted"):
        sys.exit(1)
    if args.command == "begin" and not out.get("started"):
        sys.exit(1)
    if args.command == "reconcile-observe" and not out.get("captured"):
        sys.exit(1)
    if args.command == "reconcile-decision" and not out.get("recorded"):
        sys.exit(1)
    if args.command == "reconcile-apply" and not out.get("applied"):
        sys.exit(1)
    if args.command == "reconcile-repair" and not out.get("repaired"):
        sys.exit(1)
    if args.command == "clarify" and not out.get("recorded"):
        sys.exit(1)
    if args.command == "resolve-clarification" and not out.get("resolved"):
        sys.exit(1)
    if args.command == "prepare-definition" and not out.get("prepared"):
        sys.exit(1)
    if args.command == "apply-definition" and not out.get("applied"):
        sys.exit(1)
    if args.command == "checkpoint-present" and not out.get("presented"):
        sys.exit(1)
    if args.command == "checkpoint-acceptance" and not out.get("permitted"):
        sys.exit(1)
    if args.command == "present" and not out.get("presented"):
        sys.exit(1)
    if args.command == "approval" and not out.get("permitted"):
        sys.exit(1)
    if args.command == "finish" and not out.get("permitted"):
        sys.exit(1)
    if args.command == "close" and not out.get("closed"):
        sys.exit(1)
    if args.command == "bootstrap" and out.get("managed_state") == "blocked":
        sys.exit(1)
    if args.command == "guide" and out.get("state") == "blocked":
        sys.exit(1)
    if args.command == "progress" and not out.get("found"):
        sys.exit(1)


if __name__ == "__main__":
    main()
