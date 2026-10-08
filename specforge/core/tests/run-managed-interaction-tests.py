#!/usr/bin/env python3
"""Regression tests for Candidate A managed interaction and instrumentation behaviour."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "specforge" / "core" / "tools"
MANAGED = TOOLS / "specforge-managed.py"
OBSERVE = TOOLS / "specforge-observe.py"
CHECKPOINT = TOOLS / "specforge-checkpoint.py"


def run(*args, cwd=None, expect=0):
    result = subprocess.run([sys.executable, "-B", *map(str, args)], cwd=cwd, capture_output=True, text=True)
    if result.returncode != expect:
        raise AssertionError(f"command failed ({result.returncode}, expected {expect}): {' '.join(map(str,args))}\nstdout={result.stdout}\nstderr={result.stderr}")
    try:
        return json.loads(result.stdout)
    except Exception as exc:
        raise AssertionError(f"invalid JSON output: {result.stdout}\n{result.stderr}") from exc


def fixture(root: Path):
    sf = root / "specforge"
    for name in ("changes", "decisions", "history", "evidence"):
        (sf / name).mkdir(parents=True, exist_ok=True)
    manifest = {
        "specforge": {"project_format": 1, "core_version": "candidate-a-test", "data_model_version": "test"},
        "project": {"id": "PRJ-TEST", "name": "Candidate A Test Project"},
        "specification": {"product_specification": "./spec.md", "canonical_data_model": "./model.md", "current_version": "0.1"},
        "paths": {
            "core": "./specforge/core",
            "tools": "./specforge/core/tools",
            "changes": "./specforge/changes",
            "decisions": "./specforge/decisions",
            "history": "./specforge/history",
            "evidence": "./specforge/evidence",
        },
        "packs": [],
        "policy": {"approval_mode": "controlled"},
    }
    (sf / "project.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    (root / "spec.md").write_text("# generated product specification\n", encoding="utf-8")
    (root / "model.md").write_text("# generated model\n", encoding="utf-8")

    change_dir = sf / "changes" / "CHG-T001"
    change_dir.mkdir(parents=True)
    (sf / "changes" / "CHG-T001.yaml").write_text(
        yaml.safe_dump({
            "id": "CHG-T001",
            "title": "Add a small useful thing",
            "status": "proposed",
            "request": {"summary": "Add a small useful thing", "detail": "The user asked for a small useful thing."},
            "proposal": {"current": "PROP-T001-01"},
            "approvals": [],
            "implementation": {"attempts": []},
        }, sort_keys=False),
        encoding="utf-8",
    )
    (change_dir / "PROP-T001-01.yaml").write_text(
        yaml.safe_dump({
            "id": "PROP-T001-01",
            "change": "CHG-T001",
            "revision": 1,
            "summary": "Add one small useful thing and preserve everything else.",
        }, sort_keys=False),
        encoding="utf-8",
    )


def test_project_definition(root: Path):
    # A generated product spec does not substitute for an explicit human intent anchor.
    out = run(MANAGED, "define", "--root", root, "--purpose", "Learn acids and bases", "--deliverable", "A GCSE report", "--audience", "GCSE student", "--json")
    assert out["created"] is True
    assert (root / "PROJECT.md").is_file()
    manifest = yaml.safe_load((root / "specforge" / "project.yaml").read_text(encoding="utf-8"))
    assert manifest["experience"]["profile"] == "invisible_managed_v1"
    assert manifest["experience"]["project_definition"] == "./PROJECT.md"
    assert manifest["experience"]["informed_approval"] == "required"


def test_presentation_and_approval(root: Path):
    missing = run(
        MANAGED,
        "present",
        "--root", root,
        "--proposal", "PROP-T001-01",
        "--change", "CHG-T001",
        "--summary", "Not started.",
        "--json",
        expect=1,
    )
    assert missing["blockers"] == ["interaction_session_missing"]

    not_started = run(
        MANAGED,
        "present",
        "--root", root,
        "--proposal", "PROP-T001-01",
        "--change", "CHG-T001",
        "--session", "SESSION-NOT-STARTED",
        "--summary", "Not started.",
        "--json",
        expect=1,
    )
    assert not_started["blockers"] == ["interaction_session_not_started"]

    begun = run(MANAGED, "begin", "--root", root, "--session", "SESSION-T001", "--request", "Add a small useful thing", "--json")
    assert begun["started"] is True
    assert begun["existing"] is False
    assert begun["request_received"]["phase"] == "request_received"
    first_event = begun["request_received"]["event_id"]

    repeated = run(MANAGED, "begin", "--root", root, "--session", "SESSION-T001", "--json")
    assert repeated["started"] is True
    assert repeated["existing"] is True
    assert repeated["request_received"]["event_id"] == first_event

    generated = run(MANAGED, "begin", "--root", root, "--request", "Generated-session request", "--json")
    assert generated["started"] is True
    assert generated["session"].startswith("SESSION-")

    presented = run(
        MANAGED,
        "present",
        "--root", root,
        "--proposal", "PROP-T001-01",
        "--change", "CHG-T001",
        "--session", "SESSION-T001",
        "--summary", "I’ll add one small useful thing and leave everything else unchanged.",
        "--json",
    )
    assert presented["presented"] is True
    assert presented["session"] == "SESSION-T001"
    assert "PROP-" not in presented["user_prompt"]
    assert "sha-256" not in presented["user_prompt"].lower()
    assert presented["proposal_digest"].lower() not in presented["user_prompt"].lower()
    assert presented["user_prompt"].endswith("Shall I make this change?")

    presentation_data = yaml.safe_load((root / presented["manager_path"]).read_text(encoding="utf-8"))
    assert presentation_data["session"] == "SESSION-T001"

    proposal_path = root / "specforge" / "changes" / "CHG-T001" / "PROP-T001-01.yaml"
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    proposal["summary"] = "Changed after presentation"
    proposal_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    stale = run(
        MANAGED,
        "approval",
        "--root", root,
        "--proposal", "PROP-T001-01",
        "--change", "CHG-T001",
        "--decision", "approved",
        "--text", "Yes please",
        "--json",
        expect=1,
    )
    assert stale["permitted"] is False
    assert "proposal_changed_since_presentation" in stale["blockers"]

    represented = run(
        MANAGED,
        "present",
        "--root", root,
        "--proposal", "PROP-T001-01",
        "--change", "CHG-T001",
        "--session", "SESSION-T001",
        "--summary", "I’ll use the revised wording and leave everything else unchanged.",
        "--json",
    )
    approved = run(
        MANAGED,
        "approval",
        "--root", root,
        "--proposal", "PROP-T001-01",
        "--change", "CHG-T001",
        "--decision", "approved",
        "--text", "Yes please",
        "--json",
    )
    assert approved["permitted"] is True
    assert approved["presentation"] == represented["presentation"]
    assert approved["session"] == "SESSION-T001"
    assert (root / approved["proof"]).is_file()

    timing = run(OBSERVE, "summary", "--root", root, "--change", "CHG-T001", "--json")
    assert timing["phase_counts"]["request_received"] == 1
    assert timing["marks"][0]["phase"] == "request_received"
    assert timing["marks"][0]["session"] == "SESSION-T001"


def test_unseen_proposal_fails(root: Path):
    proposal2 = root / "specforge" / "changes" / "CHG-T001" / "PROP-T001-02.yaml"
    proposal2.write_text(yaml.safe_dump({"id": "PROP-T001-02", "change": "CHG-T001", "revision": 2, "summary": "Never shown"}, sort_keys=False), encoding="utf-8")
    out = run(
        MANAGED,
        "approval",
        "--root", root,
        "--proposal", "PROP-T001-02",
        "--change", "CHG-T001",
        "--decision", "approved",
        "--text", "Please",
        "--json",
        expect=1,
    )
    assert out["permitted"] is False
    assert "proposal_not_presented" in out["blockers"]


def test_instrumentation(root: Path):
    run(OBSERVE, "mark", "request_received", "--root", root, "--change", "CHG-T001", "--json")
    run(OBSERVE, "mark", "proposal_preparation_started", "--root", root, "--change", "CHG-T001", "--json")
    run(OBSERVE, "mark", "change_completed", "--root", root, "--change", "CHG-T001", "--json")
    out = run(OBSERVE, "summary", "--root", root, "--change", "CHG-T001", "--json")
    assert out["ok"] is True
    assert out["events"] >= 3
    assert "request_to_completion" in out["durations_seconds"]
    metrics = root / "specforge" / "evidence" / "interaction-metrics.jsonl"
    assert metrics.is_file()
    for line in metrics.read_text(encoding="utf-8").splitlines():
        if line.strip():
            stamp = json.loads(line)["timestamp"]
            assert stamp.endswith("Z")

    fixed = [
        ("request_received", "2026-09-18T09:00:00.000Z"),
        ("clarification_requested", "2026-09-18T09:00:10.000Z"),
        ("clarification_resolved", "2026-09-18T09:00:30.000Z"),
        ("proposal_preparation_started", "2026-09-18T09:00:35.000Z"),
        ("proposal_presented", "2026-09-18T09:00:50.000Z"),
        ("approval_received", "2026-09-18T09:01:20.000Z"),
        ("implementation_started", "2026-09-18T09:01:25.000Z"),
        ("implementation_completed", "2026-09-18T09:02:25.000Z"),
        ("validation_started", "2026-09-18T09:02:30.000Z"),
        ("validation_completed", "2026-09-18T09:02:50.000Z"),
        ("change_completed", "2026-09-18T09:02:55.000Z"),
    ]
    metrics.write_text(
        "".join(
            json.dumps({"event_id": f"FIXED-{index}", "timestamp": timestamp, "phase": phase, "change": "CHG-T001"})
            + "\n"
            for index, (phase, timestamp) in enumerate(fixed, start=1)
        ),
        encoding="utf-8",
    )
    measured = run(OBSERVE, "summary", "--root", root, "--change", "CHG-T001", "--json")
    breakdown = measured["execution_breakdown"]
    assert breakdown["observed_span_seconds"] == 175.0
    assert breakdown["category_totals_seconds"] == {
        "productive_work": 60.0,
        "specforge_management": 65.0,
        "user_wait": 50.0,
        "unclassified": 0.0,
    }
    assert breakdown["classified_coverage_percent"] == 100.0
    assert breakdown["specforge_management_overhead_percent"] == 52.0
    assert breakdown["user_wait_excluded_from_overhead"] is True

    metrics.write_text(
        "\n".join([
            json.dumps({"event_id": "UNKNOWN-1", "timestamp": "2026-09-18T10:00:00.000Z", "phase": "request_received", "change": "CHG-T001"}),
            json.dumps({"event_id": "UNKNOWN-2", "timestamp": "2026-09-18T10:00:12.000Z", "phase": "implementation_started", "change": "CHG-T001"}),
            json.dumps({"event_id": "UNKNOWN-3", "timestamp": "2026-09-18T10:00:32.000Z", "phase": "implementation_completed", "change": "CHG-T001"}),
        ]) + "\n",
        encoding="utf-8",
    )
    conservative = run(OBSERVE, "summary", "--root", root, "--change", "CHG-T001", "--json")
    assert conservative["execution_breakdown"]["category_totals_seconds"]["unclassified"] == 12.0
    assert conservative["execution_breakdown"]["category_totals_seconds"]["productive_work"] == 20.0
    assert conservative["execution_breakdown"]["classified_coverage_percent"] == 62.5

    school_project_5 = [
        ("request_received", "2026-09-18T10:00:00.000Z"),
        ("clarification_requested", "2026-09-18T10:00:10.000Z"),
        ("clarification_resolved", "2026-09-18T10:02:10.000Z"),
        ("productive_work_started", "2026-09-18T10:02:15.000Z"),
        ("productive_work_completed", "2026-09-18T10:03:15.000Z"),
        ("proposal_preparation_started", "2026-09-18T10:03:20.000Z"),
        ("proposal_presented", "2026-09-18T10:03:40.000Z"),
        ("approval_received", "2026-09-18T10:04:30.000Z"),
        ("implementation_started", "2026-09-18T10:04:40.000Z"),
        ("implementation_completed", "2026-09-18T10:14:20.000Z"),
        ("validation_started", "2026-09-18T10:14:30.000Z"),
        ("validation_completed", "2026-09-18T10:16:48.000Z"),
        ("change_completed", "2026-09-18T10:16:55.000Z"),
    ]
    metrics.write_text(
        "".join(
            json.dumps({"event_id": f"SP5-{index}", "timestamp": timestamp, "phase": phase, "change": "CHG-T001"})
            + "\n"
            for index, (phase, timestamp) in enumerate(school_project_5, start=1)
        ),
        encoding="utf-8",
    )
    refined = run(OBSERVE, "summary", "--root", root, "--change", "CHG-T001", "--json")
    refined_breakdown = refined["execution_breakdown"]
    assert refined_breakdown["observed_span_seconds"] == 1015.0
    assert refined_breakdown["category_totals_seconds"] == {
        "productive_work": 640.0,
        "specforge_management": 205.0,
        "user_wait": 170.0,
        "unclassified": 0.0,
    }
    assert refined_breakdown["classified_coverage_percent"] == 100.0
    assert refined_breakdown["specforge_management_overhead_percent"] == 24.26

    school_project_6 = [
        {"event_id": "SP6-01", "timestamp": "2026-09-18T11:00:00.000Z", "phase": "request_received", "session": "SESSION-SP6"},
        {"event_id": "SP6-X", "timestamp": "2026-09-18T11:00:00.500Z", "phase": "request_received", "session": "OTHER-SESSION"},
        {"event_id": "SP6-02", "timestamp": "2026-09-18T11:00:01.000Z", "phase": "productive_work_started", "session": "SESSION-SP6"},
        {"event_id": "SP6-03", "timestamp": "2026-09-18T11:01:00.000Z", "phase": "proposal_preparation_started", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-04", "timestamp": "2026-09-18T11:01:10.000Z", "phase": "proposal_presented", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-05", "timestamp": "2026-09-18T11:01:40.000Z", "phase": "approval_received", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-06", "timestamp": "2026-09-18T11:01:50.000Z", "phase": "implementation_started", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-07", "timestamp": "2026-09-18T11:05:00.000Z", "phase": "product_validation_started", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-08", "timestamp": "2026-09-18T11:05:30.000Z", "phase": "specforge_validation_started", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-09", "timestamp": "2026-09-18T11:05:35.000Z", "phase": "specforge_validation_completed", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-10", "timestamp": "2026-09-18T11:06:00.000Z", "phase": "implementation_completed", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-11", "timestamp": "2026-09-18T11:06:10.000Z", "phase": "product_validation_completed", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-12", "timestamp": "2026-09-18T11:06:20.000Z", "phase": "change_completed", "change": "CHG-T001", "session": "SESSION-SP6"},
        {"event_id": "SP6-13", "timestamp": "2026-09-18T11:06:30.000Z", "phase": "productive_work_completed", "session": "SESSION-SP6"},
    ]
    metrics.write_text(
        "".join(json.dumps(item) + "\n" for item in school_project_6),
        encoding="utf-8",
    )
    sp6 = run(OBSERVE, "summary", "--root", root, "--change", "CHG-T001", "--json")
    sp6_breakdown = sp6["execution_breakdown"]
    assert sp6["linked_sessions"] == ["SESSION-SP6"]
    assert sp6["events"] == 13
    assert sp6_breakdown["observed_span_seconds"] == 390.0
    assert sp6_breakdown["category_totals_seconds"] == {
        "productive_work": 354.0,
        "specforge_management": 6.0,
        "user_wait": 30.0,
        "unclassified": 0.0,
    }
    assert sp6_breakdown["classified_coverage_percent"] == 100.0
    assert sp6_breakdown["specforge_management_overhead_percent"] == 1.667
    assert sp6_breakdown["classification_model"] == "span_aware_v1"
    assert any(
        item["classification_source"] == "specforge_validation_span" and item["seconds"] == 5.0
        for item in sp6["consecutive"]
    )
    assert not any(mark.get("session") == "OTHER-SESSION" for mark in sp6["marks"])



def test_completion_guard(root: Path):
    session = "SESSION-T001"
    guard = root / "specforge" / "evidence" / "managed-sessions" / f"{session}.json"
    assert guard.is_file()
    guard_data = json.loads(guard.read_text(encoding="utf-8"))
    assert guard_data["completion_guard_version"] == 3
    # Preserve the alpha.19 completion-guard regression as an explicit legacy-v1 compatibility case.
    guard_data["completion_guard_version"] = 1
    guard.write_text(json.dumps(guard_data, indent=2) + "\n", encoding="utf-8", newline="\n")

    change_path = root / "specforge" / "changes" / "CHG-T001.yaml"
    change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
    change["status"] = "completed"
    change["checkpoint"] = {"completed_in": "CHK-T001", "acceptance": "ACC-T001"}
    change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")

    history = root / "specforge" / "history"
    history.mkdir(parents=True, exist_ok=True)
    (history / "CHK-T001.yaml").write_text(
        yaml.safe_dump({"id": "CHK-T001", "status": "accepted", "acceptance": {"current": "ACC-T001"}}, sort_keys=False),
        encoding="utf-8", newline="\n"
    )
    (history / "ACC-T001.yaml").write_text(
        yaml.safe_dump({"id": "ACC-T001", "checkpoint": "CHK-T001", "decision": "accepted"}, sort_keys=False),
        encoding="utf-8", newline="\n"
    )

    deliverable = root / "final.txt"
    deliverable.write_text("final governed deliverable\n", encoding="utf-8", newline="\n")
    outside = root.parent / "external-final.txt"
    outside.write_text("external staging\n", encoding="utf-8", newline="\n")

    rejected = run(
        MANAGED, "finish",
        "--root", root,
        "--session", session,
        "--change", "CHG-T001",
        "--deliverable", str(outside),
        "--project-definition-action", "unchanged",
        "--json",
        expect=1,
    )
    assert any(item.startswith("deliverable_outside_project:") for item in rejected["blockers"])

    accepted = run(
        MANAGED, "finish",
        "--root", root,
        "--session", session,
        "--change", "CHG-T001",
        "--deliverable", "final.txt",
        "--project-definition-action", "unchanged",
        "--json",
    )
    assert accepted["permitted"] is True
    receipt = root / accepted["receipt"]
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["outcome"] == "delivered"
    assert data["checkpoint"] == "CHK-T001"
    assert data["acceptance"] == "ACC-T001"
    assert data["deliverables"][0]["path"] == "final.txt"
    assert len(data["deliverables"][0]["sha256"]) == 64

    run(MANAGED, "begin", "--root", root, "--session", "SESSION-NON-DELIVERY", "--request", "Stop before delivery", "--json")
    closed = run(
        MANAGED, "close",
        "--root", root,
        "--session", "SESSION-NON-DELIVERY",
        "--reason", "User stopped before a deliverable was requested.",
        "--json",
    )
    assert closed["closed"] is True
    close_data = json.loads((root / closed["receipt"]).read_text(encoding="utf-8"))
    assert close_data["outcome"] == "non_delivery"
    assert close_data["receipt_version"] == 3

    # Historical guard-v2 sessions close using receipt version 2, not v1.
    run(MANAGED, "begin", "--root", root, "--session", "SESSION-NON-DELIVERY-V2", "--request", "Stop legacy guard-v2 session", "--json")
    legacy_guard = root / "specforge/evidence/managed-sessions/SESSION-NON-DELIVERY-V2.json"
    legacy_data = json.loads(legacy_guard.read_text(encoding="utf-8"))
    legacy_data["completion_guard_version"] = 2
    legacy_guard.write_text(json.dumps(legacy_data, indent=2) + "\n", encoding="utf-8", newline="\n")
    closed_v2 = run(
        MANAGED, "close", "--root", root, "--session", "SESSION-NON-DELIVERY-V2",
        "--reason", "Historical guard-v2 compatibility.", "--json",
    )
    close_v2_data = json.loads((root / closed_v2["receipt"]).read_text(encoding="utf-8"))
    assert close_v2_data["receipt_version"] == 2



def test_controlled_v3_interaction_integrity(root: Path):
    # Reproduce an unmarked alpha.21 definition and retain arbitrary user prose during v2 migration.
    (root / "PROJECT.md").write_text(
        "# Candidate A Test Project\n\n"
        "## Purpose\n\nInitial bootstrap purpose.\n\n"
        "## Current status\n\nFurther work remains to be requested.\n\n"
        "## User notes\n\nKeep this user-authored note exactly.\n",
        encoding="utf-8", newline="\n",
    )
    change_id = "CHG-9300"
    proposal_id = "PROP-9300-01"
    change_dir = root / "specforge" / "changes" / change_id
    change_dir.mkdir(parents=True, exist_ok=True)
    change_path = root / "specforge" / "changes" / f"{change_id}.yaml"
    change = {
        "id": change_id,
        "title": "Write the current report",
        "status": "awaiting_approval",
        "request": {"summary": "Write the current report"},
        "clarification": {"required": True},
        "proposal": {"current": proposal_id},
        "approvals": [],
        "implementation": {"attempts": []},
        "governance": {"lifecycle_enforcement": "controlled_v3"},
    }
    change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")

    begun = run(
        MANAGED, "begin", "--root", root, "--session", "SESSION-V3",
        "--request", "Write the current report", "--json",
    )
    assert begun["completion_guard"]["version"] == 3
    assert begun["completion_guard"]["request_digest"].startswith("sha256:")

    asked = run(
        MANAGED, "clarify", "--root", root, "--session", "SESSION-V3",
        "--change", change_id, "--question", "What word count should I use?", "--json",
    )
    assert asked["recorded"] is True
    assert asked["clarification"].startswith("CLR-")

    prepared = run(
        MANAGED, "prepare-definition", "--root", root, "--session", "SESSION-V3",
        "--change", change_id, "--summary", "Prepare the requested report.", "--json",
    )
    proposal = {
        "id": proposal_id,
        "change": change_id,
        "revision": 1,
        "status": "awaiting_approval",
        "declared_scope": [{"operation": "modify", "path": "PROJECT.md"}],
        "project_definition_reconciliation": prepared["proposal_binding"],
    }
    proposal_path = change_dir / f"{proposal_id}.yaml"
    proposal_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8", newline="\n")

    # Helpdesk S09: validate the actual emitted reconciliation, including its format version.
    schema = json.loads((TOOLS.parent / "schemas/proposal.schema.json").read_text(encoding="utf-8"))
    reconciliation_schema = schema["properties"]["project_definition_reconciliation"]
    binding = prepared["proposal_binding"]
    assert set(reconciliation_schema["required"]) <= set(binding) <= set(reconciliation_schema["properties"])
    assert binding["definition_format_version"] == 2
    assert reconciliation_schema["properties"]["definition_format_version"] == {"type": "integer", "const": 2}
    original_material = (root / "PROJECT.md").read_bytes()
    denied = run(MANAGED, "implementation-authority", "--root", root,
                 "--change", change_id, "--proposal", proposal_id, "--json", expect=1)
    assert denied["permitted"] is False
    assert (root / "PROJECT.md").read_bytes() == original_material

    blocked = run(
        MANAGED, "present", "--root", root, "--proposal", proposal_id, "--change", change_id,
        "--session", "SESSION-V3", "--summary", "I’ll prepare the report.", "--json", expect=1,
    )
    assert any(item.startswith("clarification_unresolved:") for item in blocked["blockers"])

    resolved = run(
        MANAGED, "resolve-clarification", "--root", root, "--session", "SESSION-V3",
        "--change", change_id, "--clarification", asked["clarification"],
        "--response", "About 1,500 words", "--json",
    )
    assert resolved["resolved"] is True

    shown = run(
        MANAGED, "present", "--root", root, "--proposal", proposal_id, "--change", change_id,
        "--session", "SESSION-V3", "--summary", "I’ll prepare the report.", "--json",
    )
    # Helpdesk S03/S04: presentation alone cannot authorise material implementation.
    denied = run(MANAGED, "implementation-authority", "--root", root,
                 "--change", change_id, "--proposal", proposal_id, "--json", expect=1)
    assert denied["permitted"] is False
    change["status"] = "in_progress"
    change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
    denied_apply = run(MANAGED, "apply-definition", "--root", root,
                       "--session", "SESSION-V3", "--change", change_id, "--json", expect=1)
    assert denied_apply["applied"] is False
    assert (root / "PROJECT.md").read_bytes() == original_material
    presented_bytes = proposal_path.read_bytes()
    approved = run(
        MANAGED, "approval", "--root", root, "--proposal", proposal_id, "--change", change_id,
        "--decision", "approved", "--text", "Yes", "--actor-id", "fixture-owner",
        "--actor-name", "Fixture Owner", "--json",
    )
    assert approved["permitted"] is True
    assert approved["approval"]["id"].startswith("APR-")
    proof = yaml.safe_load((root / approved["proof"]).read_text(encoding="utf-8"))
    approval_record = yaml.safe_load((root / approved["approval"]["record"]).read_text(encoding="utf-8"))
    assert approval_record["timestamp"] == proof["received_at"]
    assert approval_record["evidence"]["informed_approval_proof"] == approved["proof"]
    assert proposal_path.read_bytes() == presented_bytes
    allowed = run(MANAGED, "implementation-authority", "--root", root,
                  "--change", change_id, "--proposal", proposal_id, "--json")
    assert allowed["permitted"] is True
    assert allowed["proposal_digest"] == shown["proposal_digest"]
    wrong = run(MANAGED, "implementation-authority", "--root", root,
                "--change", change_id, "--proposal", "PROP-9300-02", "--json", expect=1)
    assert wrong["blockers"] == ["proposal_not_current"]

    change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
    assert approved["approval"]["id"] in change["approvals"]
    change["status"] = "in_progress"
    change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
    manager = run(MANAGED, "summary", change_id, "--root", root, "--detail", "minimal", "--json")
    assert manager["continuation"]["blocked"] is False
    assert manager["continuation"]["next_action"] == "implementation_validation"
    applied = run(
        MANAGED, "apply-definition", "--root", root, "--session", "SESSION-V3",
        "--change", change_id, "--json",
    )
    assert applied["applied"] is True
    assert proposal_path.read_bytes() == presented_bytes
    project_text = (root / "PROJECT.md").read_text(encoding="utf-8")
    assert "SPECFORGE-MANAGED-DEFINITION:START" in project_text
    assert "definition_format_version: 2" in project_text
    assert "SPECFORGE-CURRENT-WORK:START" in project_text
    assert begun["completion_guard"]["request_digest"] in project_text
    assert change_id in project_text
    assert "Keep this user-authored note exactly." in project_text
    managed_region = project_text.split("SPECFORGE-MANAGED-DEFINITION:START", 1)[1].split("SPECFORGE-MANAGED-DEFINITION:END", 1)[0]
    assert "Further work remains to be requested." not in managed_region
    assert "Prepare the requested report." in managed_region

    timing = run(OBSERVE, "summary", "--root", root, "--session", "SESSION-V3", "--json")
    assert timing["phase_counts"]["clarification_requested"] == 1
    assert timing["phase_counts"]["clarification_resolved"] == 1
    assert timing["phase_counts"]["project_definition_prepared"] == 1
    assert timing["phase_counts"]["project_definition_applied"] == 1

    # A changed controlled-v3 proposal must use a new revision, even if re-presented.
    proposal["behaviour_summary"] = "A materially revised report"
    proposal_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8", newline="\n")
    denied = run(MANAGED, "implementation-authority", "--root", root,
                 "--change", change_id, "--json", expect=1)
    assert denied["permitted"] is False
    represented = run(MANAGED, "present", "--root", root,
                      "--proposal", proposal_id, "--change", change_id, "--session", "SESSION-V3",
                      "--summary", "A revised report", "--json", expect=1)
    assert represented["blockers"] == ["presented_proposal_revision_changed"]
    proposal["id"] = "PROP-9300-02"
    proposal["revision"] = 2
    revised_path = change_dir / "PROP-9300-02.yaml"
    revised_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8", newline="\n")
    proposal_path.write_bytes(presented_bytes)
    change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
    change["proposal"]["current"] = proposal["id"]
    change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
    run(MANAGED, "implementation-authority", "--root", root, "--change", change_id, "--json", expect=1)
    run(MANAGED, "present", "--root", root, "--proposal", proposal["id"], "--change", change_id,
        "--session", "SESSION-V3", "--summary", "A revised report", "--json")
    run(MANAGED, "implementation-authority", "--root", root, "--change", change_id, "--json", expect=1)
    run(MANAGED, "approval", "--root", root, "--proposal", proposal["id"], "--change", change_id,
        "--decision", "approved", "--text", "Approve revised report", "--json")
    run(MANAGED, "implementation-authority", "--root", root, "--change", change_id, "--json")



def test_project_definition_reconciliation_modes(root: Path):
    project = root / "PROJECT.md"
    assert project.is_file()
    original = project.read_bytes()
    original_digest = hashlib.sha256(original).hexdigest()
    change_id = "CHG-MODE1"
    proposal_id = "PROP-MODE1-01"
    change_dir = root / "specforge/changes" / change_id
    change_dir.mkdir(parents=True, exist_ok=True)
    change_path = root / "specforge/changes" / f"{change_id}.yaml"
    change = {
        "id": change_id,
        "title": "Context-only reconciliation fixture",
        "status": "awaiting_approval",
        "request": {"summary": "Use project definition as immutable context"},
        "clarification": {"required": False},
        "proposal": {"current": proposal_id},
        "approvals": [],
        "implementation": {"attempts": []},
        "governance": {"lifecycle_enforcement": "controlled_v3"},
    }
    change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
    run(
        MANAGED, "begin", "--root", root, "--session", "SESSION-MODE1",
        "--request", "Use project definition as immutable context", "--change", change_id, "--json",
    )
    prepared = run(
        MANAGED, "prepare-definition", "--root", root, "--session", "SESSION-MODE1",
        "--change", change_id, "--summary", "Use the existing durable project definition.",
        "--mode", "context_only", "--json",
    )
    assert prepared["prepared"] is True
    assert prepared["mode"] == "context_only"
    assert prepared["prepared_path"] is None
    assert prepared["project_definition_changed"] is False
    assert prepared["proposal_binding"]["sha256"] == original_digest
    assert project.read_bytes() == original

    proposal = {
        "id": proposal_id,
        "change": change_id,
        "revision": 1,
        "status": "awaiting_approval",
        "proposed_specification_version": "0.1.0-alpha.26",
        "declared_scope": [{"operation": "modify", "path": "specforge/core/tools/specforge-status.py"}],
        "project_definition_reconciliation": prepared["proposal_binding"],
    }
    proposal_path = change_dir / f"{proposal_id}.yaml"
    proposal_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8", newline="\n")
    shown = run(
        MANAGED, "present", "--root", root, "--proposal", proposal_id, "--change", change_id,
        "--session", "SESSION-MODE1", "--summary", "Use the current project definition as context only.", "--json",
    )
    assert shown["presented"] is True

    missing_mode = dict(proposal)
    missing_mode["project_definition_reconciliation"] = dict(prepared["proposal_binding"])
    missing_mode["project_definition_reconciliation"].pop("mode")
    proposal_path.write_text(yaml.safe_dump(missing_mode, sort_keys=False), encoding="utf-8", newline="\n")
    blocked = run(
        MANAGED, "present", "--root", root, "--proposal", proposal_id, "--change", change_id,
        "--session", "SESSION-MODE1", "--summary", "Missing mode should fail closed.", "--json", expect=1,
    )
    assert blocked["blockers"] == ["project_definition_reconciliation_mode_missing"]
    proposal_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8", newline="\n")

    scoped = dict(proposal)
    scoped["declared_scope"] = list(proposal["declared_scope"]) + [{"operation": "modify", "path": "PROJECT.md"}]
    proposal_path.write_text(yaml.safe_dump(scoped, sort_keys=False), encoding="utf-8", newline="\n")
    blocked_scope = run(
        MANAGED, "present", "--root", root, "--proposal", proposal_id, "--change", change_id,
        "--session", "SESSION-MODE1", "--summary", "Context-only cannot scope PROJECT.md.", "--json", expect=1,
    )
    assert blocked_scope["blockers"] == ["project_definition_context_only_in_scope"]
    proposal_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8", newline="\n")
    assert project.read_bytes() == original

    # Approval must recheck the exact durable identity.
    project.write_bytes(original + b"drift\n")
    drifted = run(
        MANAGED, "approval", "--root", root, "--proposal", proposal_id, "--change", change_id,
        "--decision", "approved", "--text", "Yes", "--json", expect=1,
    )
    assert "project_definition_context_digest_changed" in drifted["blockers"]
    project.write_bytes(original)

    approved = run(
        MANAGED, "approval", "--root", root, "--proposal", proposal_id, "--change", change_id,
        "--decision", "approved", "--text", "Yes", "--json",
    )
    assert approved["permitted"] is True


def test_prospective_finalisation(root: Path):
    proposal_path = root / "specforge" / "changes" / "CHG-T001" / "PROP-T001-03.yaml"
    prepared_bytes = b"prepared exact candidate\n"
    proposal = {
        "id": "PROP-T001-03",
        "change": "CHG-T001",
        "revision": 3,
        "status": "awaiting_approval",
        "behaviour_summary": "Add one exact prepared result.",
        "declared_scope": [{"operation": "add", "path": "prospective-result.txt"}],
        "exact_candidate_finalisation": {
            "eligible": True,
            "prepared_artifacts": [{
                "path": "prospective-result.txt",
                "sha256": hashlib.sha256(prepared_bytes).hexdigest(),
            }],
            "deletions": [],
        },
    }
    proposal_path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8", newline="\n")
    run(MANAGED, "begin", "--root", root, "--session", "SESSION-PFA", "--request", "Add prepared exact result", "--json")
    presented = run(
        MANAGED, "present", "--root", root,
        "--proposal", "PROP-T001-03", "--change", "CHG-T001",
        "--session", "SESSION-PFA",
        "--summary", "I’ll add the prepared exact result.",
        "--json",
    )
    assert presented["prospective_finalisation"]["eligible"] is True
    assert "Approve and finalise" in presented["user_prompt"]
    approved = run(
        MANAGED, "approval", "--root", root,
        "--proposal", "PROP-T001-03", "--change", "CHG-T001",
        "--decision", "approved", "--text", "Approve and finalise",
        "--finalise", "--actor-id", "fixture-owner", "--actor-name", "Fixture Owner",
        "--json",
    )
    pfa = approved["prospective_finalisation_authority"]
    assert pfa["id"] == "PFA-0001"
    authority = yaml.safe_load((root / pfa["record"]).read_text(encoding="utf-8"))
    assert authority["actor"]["type"] == "human"
    assert authority["proposal"] == "PROP-T001-03"
    assert authority["scope"]["change_set"] == ["CHG-T001"]
    assert authority["projected_candidate"]["revision"].startswith("sha256:")

    run(MANAGED, "begin", "--root", root, "--session", "SESSION-PFA-DRIFT", "--request", "Add prepared exact result drift test", "--json")
    represented = run(
        MANAGED, "present", "--root", root,
        "--proposal", "PROP-T001-03", "--change", "CHG-T001",
        "--session", "SESSION-PFA-DRIFT",
        "--summary", "I’ll add the same prepared exact result.",
        "--json",
    )
    assert represented["prospective_finalisation"]["eligible"] is True
    (root / "unrelated-material.txt").write_text("drift\n", encoding="utf-8", newline="\n")
    drift = run(
        MANAGED, "approval", "--root", root,
        "--proposal", "PROP-T001-03", "--change", "CHG-T001",
        "--decision", "approved", "--text", "Approve and finalise",
        "--finalise", "--json", expect=1,
    )
    assert "prospective_finalisation_baseline_changed" in drift["blockers"]
    (root / "unrelated-material.txt").unlink()



def test_progress_reporting(root: Path):
    change_path = root / "specforge" / "changes" / "CHG-T001.yaml"
    metrics = root / "specforge" / "evidence" / "interaction-metrics.jsonl"
    original_change = change_path.read_text(encoding="utf-8")
    original_metrics = metrics.read_text(encoding="utf-8") if metrics.exists() else None
    checkpoint = root / "specforge" / "history" / "CHK-PROGRESS.yaml"

    def tree_state():
        state = {}
        for path in root.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            state[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return state

    try:
        change = yaml.safe_load(original_change)
        change["status"] = "in_progress"
        change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
        metrics.parent.mkdir(parents=True, exist_ok=True)
        metrics.write_text(
            "\n".join([
                json.dumps({"event_id": "PROG-1", "timestamp": "2026-09-24T09:00:00.000Z", "phase": "request_received", "change": "CHG-T001", "session": "SESSION-T001"}),
                json.dumps({"event_id": "PROG-2", "timestamp": "2026-09-24T09:01:00.000Z", "phase": "implementation_started", "change": "CHG-T001", "session": "SESSION-T001"}),
                json.dumps({"event_id": "PROG-3", "timestamp": "2026-09-24T09:02:00.000Z", "phase": "implementation_completed", "change": "CHG-T001", "session": "SESSION-T001"}),
                json.dumps({"event_id": "PROG-4", "timestamp": "2026-09-24T09:03:00.000Z", "phase": "specforge_validation_started", "change": "CHG-T001", "session": "SESSION-T001", "note": "Immutable lineage passed; repository integrity is running"}),
            ]) + "\n",
            encoding="utf-8",
        )
        before = tree_state()
        progress = run(MANAGED, "progress", "CHG-T001", "--root", root, "--session", "SESSION-T001", "--json")
        after = tree_state()
        assert before == after, "progress query mutated the project"
        assert progress["current_activity"]["state"] == "specforge_validation"
        assert "repository integrity is running" in progress["user_message"]
        assert progress["heartbeat"]["target_seconds"] == 60
        assert progress["heartbeat"]["invent_eta"] is False
        assert "CHG-" not in progress["user_message"] and "PROP-" not in progress["user_message"]

        metrics.write_text("", encoding="utf-8")
        resumed = run(MANAGED, "progress", "CHG-T001", "--root", root, "--json")
        assert resumed["current_activity"]["source"] == "continuation"
        assert resumed["current_activity"]["state"] == "implementation_validation"

        change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
        change["status"] = "awaiting_approval"
        change["approvals"] = []
        change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
        awaiting = run(MANAGED, "progress", "CHG-T001", "--root", root, "--json")
        assert awaiting["current_activity"]["state"] == "waiting_for_approval"
        assert awaiting["next_boundary"]["type"] == "human"

        change["status"] = "ready_for_checkpoint"
        change["approvals"] = yaml.safe_load(original_change).get("approvals") or []
        change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(
            yaml.safe_dump({
                "id": "CHK-PROGRESS",
                "status": "candidate",
                "included_changes": ["CHG-T001"],
                "candidate": {"material": {"provider": "specforge_snapshot", "revision": "sha256:" + "0" * 64}},
                "validation": [],
                "acceptance": {"current": None},
            }, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )
        waiting_checkpoint = run(MANAGED, "progress", "CHG-T001", "--root", root, "--json")
        assert waiting_checkpoint["current_activity"]["state"] == "waiting_for_checkpoint_acceptance"
        assert waiting_checkpoint["next_boundary"]["type"] == "human"

        checkpoint.unlink()
        change["status"] = "completed"
        change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
        terminal = run(MANAGED, "progress", "CHG-T001", "--root", root, "--json")
        assert terminal["terminal"] is True
        assert terminal["current_activity"]["state"] == "completed"
        assert "No further processing remains" in terminal["user_message"]
        assert terminal["next_boundary"]["type"] == "terminal"
    finally:
        change_path.write_text(original_change, encoding="utf-8", newline="\n")
        if checkpoint.exists():
            checkpoint.unlink()
        if original_metrics is None:
            if metrics.exists():
                metrics.unlink()
        else:
            metrics.write_text(original_metrics, encoding="utf-8", newline="\n")



def test_integrity_live_progress(root: Path):
    change_path = root / "specforge/changes/CHG-T001.yaml"
    progress_path = root / "specforge/evidence/integrity/progress.jsonl"
    original_change = change_path.read_text(encoding="utf-8")
    original_progress = progress_path.read_text(encoding="utf-8") if progress_path.exists() else None
    try:
        change = yaml.safe_load(original_change)
        change["status"] = "in_progress"
        change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding="utf-8", newline="\n")
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps({
            "mode": "incremental_integrity_v1",
            "phase": "incremental_closure",
            "processed": 42,
            "total": 100,
            "elapsed_seconds": 12.5,
            "substage": "checking reference and authority closure",
        }) + "\n", encoding="utf-8", newline="\n")
        result = run(MANAGED, "progress", "CHG-T001", "--root", root, "--json")
        assert result["current_activity"]["source"] == "integrity_validator"
        assert result["current_activity"]["validator"]["processed"] == 42
        assert "42/100" in result["current_activity"]["detail"]
        assert "42/100" in result["user_message"]
    finally:
        change_path.write_text(original_change, encoding="utf-8", newline="\n")
        if original_progress is None:
            if progress_path.exists():
                progress_path.unlink()
        else:
            progress_path.write_text(original_progress, encoding="utf-8", newline="\n")


def test_ci_contract():
    smoke = ROOT / ".github/workflows/candidate-a-smoke.yml"
    evidence = ROOT / ".github/workflows/candidate-a-evidence.yml"
    receipts = ROOT / ".github/workflows/specforge-monthly-integrity.yml"
    if not smoke.is_file():
        return
    smoke_text = smoke.read_text(encoding="utf-8")
    evidence_text = evidence.read_text(encoding="utf-8")
    receipt_text = receipts.read_text(encoding="utf-8")
    assert "paths:" in smoke_text
    assert "specforge/core/**" in smoke_text and "specforge/packs/**" in smoke_text
    assert "specforge/changes/**" not in smoke_text
    assert "specforge/history/**" not in smoke_text
    assert "specforge/evidence/**" not in smoke_text
    assert "uses: ./.github/workflows/candidate-a-evidence.yml" in smoke_text
    assert "workflow_call:" in evidence_text
    assert "fetch-depth: 0" in evidence_text
    assert "specforge-revision.py verify" in evidence_text
    assert "specforge-integrity.py auto" in evidence_text
    assert "Publish integrity state" in evidence_text
    assert "Record integrity receipt" in evidence_text
    assert 'specforge/evidence/integrity/state.json' in evidence_text
    assert "schedule:" in receipt_text
    assert "workflow_dispatch:" in receipt_text
    assert "Full history audit" in receipt_text
    assert "workflow_run:" not in receipt_text


def test_checkpoint_capability_present():
    assert CHECKPOINT.is_file()
    assert 'ready_for_checkpoint' in (TOOLS / 'specforge-lifecycle.py').read_text(encoding='utf-8')
    checkpoint_text = CHECKPOINT.read_text(encoding='utf-8')
    assert 'def complete(' in checkpoint_text
    assert 'def finalise_prospective(' in checkpoint_text
    assert 'def finalise_direct(' in checkpoint_text
    assert 'def _cap_preflight(' in checkpoint_text


def test_guided_non_expert_contract():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from portable_fixture import canonical_digest, create_project, git, install_controlled_change, write_yaml

    def trust_current_definition(root):
        git(root, "add", "PROJECT.md", "specforge/project.yaml")
        git(root, "commit", "-m", "fixture project definition")
        trusted = git(root, "rev-parse", "HEAD").stdout.strip()
        write_yaml(
            root / "specforge/evidence/material-authority.yaml",
            {"version": 1, "trusted": {"provider": "git", "revision": trusted}},
        )
        git(root, "add", "specforge/evidence/material-authority.yaml")
        git(root, "commit", "-m", "trust fixture project definition")

    def install_valid_controlled_v2_change(root, change_id, status):
        installed = install_controlled_change(
            root,
            change_id,
            status="awaiting_approval",
            skip_approval=True,
            lifecycle_enforcement="controlled_v2",
            declared_scope=[{"operation": "modify", "path": "README.md"}],
            governance_tier={"requested": "LOW"},
        )

        prepared = run(
            TOOLS / "specforge-governance-tier.py",
            "prepare",
            installed["proposal"],
            "--root",
            root,
            "--json",
        )
        assert prepared["prepared"] is True

        proposal_path = root / "specforge" / "changes" / change_id / f'{installed["proposal"]}.yaml'
        proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
        tier = proposal.get("governance_tier") or {}
        assert tier.get("requested") == "LOW"
        assert tier.get("calculated_minimum") == "LOW"
        assert isinstance(tier.get("policy_digest"), str) and len(tier["policy_digest"]) == 64

        if status == "awaiting_approval":
            return installed
        if status != "approved":
            raise AssertionError(f"unsupported guided fixture status: {status}")

        digest = canonical_digest(proposal_path)
        approval_id = installed["approval"]

        write_yaml(
            root / "specforge" / "changes" / change_id / "approvals" / f"{approval_id}.yaml",
            {
                "id": approval_id,
                "change": change_id,
                "proposal": installed["proposal"],
                "decision": "approved",
                "actor": {"type": "human", "id": "fixture-product-owner"},
                "timestamp": "2026-01-01T00:00:00+00:00",
                "evidence": {
                    "proposal_digest_algorithm": "sha256",
                    "proposal_digest": digest,
                    "proposal_identity": installed["proposal"],
                },
                "mechanism": {"type": "test_fixture", "reference": "guided-non-expert-contract"},
            },
        )

        change_path = root / "specforge" / "changes" / f"{change_id}.yaml"
        change = yaml.safe_load(change_path.read_text(encoding="utf-8"))
        change["approvals"] = [approval_id]
        change["status"] = "approved"
        write_yaml(change_path, change)
        return installed


    with tempfile.TemporaryDirectory(prefix="specforge-guide-new-") as td:
        root = Path(td) / "repo"
        create_project(root, ROOT / "specforge" / "core", git_backed=True, initialize_governance_tier=True)
        undefined = run(MANAGED, "guide", "--root", root, "--request", "Add a useful report", "--json")
        assert undefined["contract"] == "guided_non_expert_v1"
        assert undefined["state"] == "needs_project_definition"
        assert undefined["internal_next_action"] == "define_project"
        assert undefined["human_decision_required"] is True
        assert undefined["resolved"]["change"] is None
        assert "CHG-" not in undefined["user_message"] and "PROP-" not in undefined["user_message"]

        defined = run(
            MANAGED, "define", "--root", root,
            "--purpose", "Maintain a useful portable test project",
            "--deliverable", "A governed software project",
            "--audience", "Project users",
            "--json",
        )
        trust_current_definition(root)

        assert defined["created"] is True

        fresh = run(MANAGED, "guide", "--root", root, "--request", "Add a useful report", "--json")
        assert fresh["contract"] == "guided_non_expert_v1"
        assert fresh["state"] == "ready_for_new_work"
        assert fresh["internal_next_action"] == "begin"
        assert fresh["human_decision_required"] is False
        assert fresh["resolved"]["change"] is None
        assert "CHG-" not in fresh["user_message"] and "PROP-" not in fresh["user_message"]

    with tempfile.TemporaryDirectory(prefix="specforge-guide-resume-") as td:
        root = Path(td) / "repo"
        create_project(root, ROOT / "specforge" / "core", git_backed=True, initialize_governance_tier=True)
        run(
            MANAGED, "define", "--root", root,
            "--purpose", "Maintain a useful portable test project",
            "--deliverable", "A governed software project",
            "--audience", "Project users",
            "--json",
        )
        trust_current_definition(root)

        install_valid_controlled_v2_change(root, "CHG-9101", status="approved")
        resumed = run(MANAGED, "guide", "--root", root, "--json")
        assert resumed["resolved"]["change"] == "CHG-9101"
        assert resumed["state"] == "implementation_validation"
        assert resumed["internal_next_action"] == "implementation_validation"
        assert resumed["human_decision_required"] is False

        install_valid_controlled_v2_change(root, "CHG-9102", status="approved")
        ambiguous = run(MANAGED, "guide", "--root", root, "--json", expect=1)
        assert ambiguous["state"] == "blocked"
        assert "ambiguous_continuation" in ambiguous["blockers"]
        assert len(ambiguous["choices"]) == 2

        selected = run(MANAGED, "guide", "--root", root, "--change", "CHG-9101", "--json")
        assert selected["resolved"]["change"] == "CHG-9101"

        missing = run(MANAGED, "guide", "--root", root, "--change", "CHG-NOT-HERE", "--json", expect=1)
        assert "current_workspace_missing_required_change" in missing["blockers"]

    with tempfile.TemporaryDirectory(prefix="specforge-guide-approval-") as td:
        root = Path(td) / "repo"
        create_project(root, ROOT / "specforge" / "core", git_backed=True, initialize_governance_tier=True)
        run(
            MANAGED, "define", "--root", root,
            "--purpose", "Maintain a useful portable test project",
            "--deliverable", "A governed software project",
            "--audience", "Project users",
            "--json",
        )
        trust_current_definition(root)

        install_valid_controlled_v2_change(root, "CHG-9201", status="awaiting_approval")
        waiting = run(MANAGED, "guide", "--root", root, "--change", "CHG-9201", "--json")
        assert waiting["state"] == "waiting_for_approval"
        assert waiting["human_decision_required"] is True
        assert waiting["internal_next_action"] == "approval"
        assert "CHG-" not in waiting["user_message"] and "PROP-" not in waiting["user_message"]

def main():
    with tempfile.TemporaryDirectory(prefix="specforge-candidate-a-") as td:
        root = Path(td)
        fixture(root)
        test_project_definition(root)
        test_unseen_proposal_fails(root)
        test_presentation_and_approval(root)
        test_progress_reporting(root)
        test_guided_non_expert_contract()
        test_integrity_live_progress(root)
        test_completion_guard(root)
        test_instrumentation(root)
        test_controlled_v3_interaction_integrity(root)
        test_project_definition_reconciliation_modes(root)
        test_prospective_finalisation(root)
        test_ci_contract()
        test_checkpoint_capability_present()
    print("Candidate A managed interaction tests: PASSED")


if __name__ == "__main__":
    main()


# CHG-1043 regression: managed pre-edit authority gate is exposed and fail-closed.
_managed_1043 = MANAGED.read_text(encoding="utf-8")
assert "def implementation_authority(" in _managed_1043
assert '"implementation-authority"' in _managed_1043
assert "valid_exact_human_approval_missing" in _managed_1043
assert "informed_approval_proof_missing" in _managed_1043
