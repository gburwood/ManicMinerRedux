#!/usr/bin/env python3
"""Lightweight system-clock instrumentation for SpecForge managed interactions.

Observational only. It records real phase boundaries and never creates authority.
Repeated phases are distinguished by attempt id instead of becoming ambiguous duplicates.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import datetime as dt
import json
import subprocess
import sys
import uuid

from specforge_project import classify_project_path, discover_layout, is_governance_bookkeeping_path

RECOMMENDED_PHASES = (
    "request_received",
    "clarification_requested",
    "clarification_resolved",
    "productive_work_started",
    "productive_work_completed",
    "proposal_preparation_started",
    "proposal_presented",
    "approval_received",
    "checkpoint_presented",
    "checkpoint_acceptance_received",
    "project_definition_prepared",
    "project_definition_applied",
    "implementation_started",
    "implementation_completed",
    "validation_started",
    "validation_completed",
    "product_validation_started",
    "product_validation_completed",
    "specforge_validation_started",
    "specforge_validation_completed",
    "change_completed",
    "managed_finish_started",
    "managed_finish_completed",
    "managed_non_delivery_closed",
    "project_defined",
)

DURATION_PAIRS = (
    ("request_received", "proposal_presented", "request_to_proposal"),
    ("proposal_presented", "approval_received", "proposal_to_approval"),
    ("checkpoint_presented", "checkpoint_acceptance_received", "checkpoint_to_acceptance"),
    ("approval_received", "implementation_started", "approval_to_implementation_start"),
    ("implementation_started", "implementation_completed", "implementation"),
    ("implementation_completed", "validation_completed", "post_implementation_validation"),
    ("approval_received", "change_completed", "approval_to_completion"),
    ("request_received", "change_completed", "request_to_completion"),
    ("change_completed", "managed_finish_completed", "completion_to_delivery"),
)

INTERVAL_CLASSIFICATION = {
    ("request_received", "clarification_requested"): "specforge_management",
    ("request_received", "proposal_preparation_started"): "specforge_management",
    ("request_received", "productive_work_started"): "specforge_management",
    ("clarification_requested", "clarification_resolved"): "user_wait",
    ("clarification_resolved", "proposal_preparation_started"): "specforge_management",
    ("clarification_resolved", "productive_work_started"): "specforge_management",
    ("proposal_preparation_started", "productive_work_started"): "specforge_management",
    ("productive_work_started", "productive_work_completed"): "productive_work",
    ("productive_work_completed", "proposal_preparation_started"): "specforge_management",
    ("productive_work_completed", "proposal_presented"): "specforge_management",
    ("proposal_preparation_started", "proposal_presented"): "specforge_management",
    ("proposal_presented", "approval_received"): "user_wait",
    ("checkpoint_presented", "checkpoint_acceptance_received"): "user_wait",
    ("approval_received", "implementation_started"): "specforge_management",
    ("implementation_started", "implementation_completed"): "productive_work",
    ("implementation_completed", "validation_started"): "specforge_management",
    ("implementation_completed", "change_completed"): "specforge_management",
    ("validation_started", "validation_completed"): "specforge_management",
    ("validation_completed", "change_completed"): "specforge_management",
    ("change_completed", "managed_finish_started"): "specforge_management",
    ("managed_finish_started", "managed_finish_completed"): "specforge_management",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def evidence_root(layout) -> Path:
    paths = layout.manifest.get("paths") or {}
    return (layout.root / paths.get("evidence", "specforge/evidence")).resolve()


def metrics_path(layout) -> Path:
    return evidence_root(layout) / "interaction-metrics.jsonl"


def _git_head(layout) -> str | None:
    result = subprocess.run(["git", "-C", str(layout.root), "rev-parse", "HEAD"], capture_output=True, text=True)
    if result.returncode:
        return None
    value = result.stdout.strip()
    return value if value else None


def load_marks(layout) -> list[dict]:
    target = metrics_path(layout)
    if not target.is_file():
        return []
    out = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict) and item.get("timestamp") and item.get("phase"):
            out.append(item)
    return out


def next_occurrence(layout, phase: str, *, change=None, session=None) -> int:
    marks = load_marks(layout)
    matching = [m for m in marks if m.get("phase") == phase]
    if change:
        matching = [m for m in matching if m.get("change") == change]
    if session:
        matching = [m for m in matching if m.get("session") == session]
    return len(matching) + 1


def append_mark(layout, phase: str, *, change=None, proposal=None, session=None, attempt=None, note=None) -> dict:
    if phase not in RECOMMENDED_PHASES:
        raise ValueError(f"unsupported_phase:{phase}")
    target = metrics_path(layout)
    target.parent.mkdir(parents=True, exist_ok=True)
    occurrence = next_occurrence(layout, phase, change=change, session=session)
    event = {
        "event_id": f"OBS-{uuid.uuid4().hex[:12]}",
        "timestamp": utc_now(),
        "phase": phase,
        "occurrence": occurrence,
    }
    if change:
        event["change"] = change
    if proposal:
        event["proposal"] = proposal
    if session:
        event["session"] = session
    if attempt:
        event["attempt"] = attempt
    elif occurrence > 1:
        event["attempt"] = str(occurrence)
    if note:
        event["note"] = note
    head = _git_head(layout)
    if head:
        event["source_control"] = {"provider": "git", "head": head}
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return event


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def selected_marks(layout, *, change=None, session=None) -> list[dict]:
    marks = load_marks(layout)
    if change:
        linked_sessions = {
            mark.get("session")
            for mark in marks
            if mark.get("change") == change and mark.get("session")
        }
        marks = [
            mark
            for mark in marks
            if mark.get("change") == change
            or (
                not mark.get("change")
                and mark.get("session")
                and mark.get("session") in linked_sessions
            )
        ]
    if session:
        marks = [mark for mark in marks if mark.get("session") == session]
    marks.sort(key=lambda item: item["timestamp"])
    return marks


def apply_phase(state: dict, phase: str) -> None:
    if phase == "clarification_requested":
        state["clarification_wait"] = True
    elif phase == "clarification_resolved":
        state["clarification_wait"] = False
    elif phase == "proposal_presented":
        state["approval_wait"] = True
    elif phase == "approval_received":
        state["approval_wait"] = False
    elif phase == "productive_work_started":
        state["productive_work"] = True
    elif phase == "productive_work_completed":
        state["productive_work"] = False
    elif phase == "implementation_started":
        state["implementation"] = True
    elif phase == "implementation_completed":
        state["implementation"] = False
    elif phase == "product_validation_started":
        state["product_validation"] = True
    elif phase == "product_validation_completed":
        state["product_validation"] = False
    elif phase == "specforge_validation_started":
        state["specforge_validation"] = True
    elif phase == "specforge_validation_completed":
        state["specforge_validation"] = False
    elif phase == "validation_started":
        state["legacy_validation"] = True
    elif phase == "validation_completed":
        state["legacy_validation"] = False


def classify_interval(state: dict, left_phase: str, right_phase: str) -> tuple[str, str]:
    # Deterministic precedence means each atomic interval is counted exactly once.
    if state["clarification_wait"] or state["approval_wait"]:
        return "user_wait", "user_wait_span"
    if state["specforge_validation"]:
        return "specforge_management", "specforge_validation_span"
    if state["product_validation"]:
        return "productive_work", "product_validation_span"
    if state["productive_work"]:
        return "productive_work", "productive_work_span"
    if state["implementation"]:
        return "productive_work", "implementation_span"
    if state["legacy_validation"]:
        return "specforge_management", "legacy_validation_span"

    fallback = INTERVAL_CLASSIFICATION.get((left_phase, right_phase))
    if fallback:
        return fallback, "adjacent_pair_fallback"
    return "unclassified", "unclassified"



_ACTIVITY_KEYS = (
    "clarification_wait",
    "approval_wait",
    "specforge_validation",
    "product_validation",
    "productive_work",
    "implementation",
    "legacy_validation",
)

_ACTIVITY_CATEGORY = {
    "clarification_wait": "user_wait",
    "approval_wait": "user_wait",
    "specforge_validation": "specforge_management",
    "product_validation": "productive_work",
    "productive_work": "productive_work",
    "implementation": "productive_work",
    "legacy_validation": "specforge_management",
}

_ACTIVITY_START_PHASE = {
    "clarification_requested": "clarification_wait",
    "proposal_presented": "approval_wait",
    "productive_work_started": "productive_work",
    "implementation_started": "implementation",
    "product_validation_started": "product_validation",
    "specforge_validation_started": "specforge_validation",
    "validation_started": "legacy_validation",
}


def current_activity(marks: list[dict]) -> dict:
    if not marks:
        return {
            "state": "unavailable",
            "category": None,
            "active": False,
            "started_at": None,
            "elapsed_seconds": None,
            "detail": None,
            "reason": "no_observer_marks",
        }

    state = {
        "clarification_wait": False,
        "approval_wait": False,
        "productive_work": False,
        "implementation": False,
        "product_validation": False,
        "specforge_validation": False,
        "legacy_validation": False,
    }
    started_at = {key: None for key in _ACTIVITY_KEYS}
    detail = {key: None for key in _ACTIVITY_KEYS}

    for mark in marks:
        before = dict(state)
        apply_phase(state, mark["phase"])
        for key in _ACTIVITY_KEYS:
            if not before[key] and state[key]:
                started_at[key] = mark.get("timestamp")
            elif before[key] and not state[key]:
                started_at[key] = None
                detail[key] = None
        active_key = _ACTIVITY_START_PHASE.get(mark.get("phase"))
        if active_key and state.get(active_key) and mark.get("note"):
            detail[active_key] = str(mark["note"])

    for key in _ACTIVITY_KEYS:
        if not state[key]:
            continue
        stamp = started_at.get(key)
        elapsed = None
        if stamp:
            try:
                elapsed = round(max(0.0, (dt.datetime.now(dt.timezone.utc) - parse_time(stamp)).total_seconds()), 3)
            except Exception:
                elapsed = None
        return {
            "state": key,
            "category": _ACTIVITY_CATEGORY[key],
            "active": True,
            "started_at": stamp,
            "elapsed_seconds": elapsed,
            "detail": detail.get(key),
            "reason": None,
        }

    last = marks[-1]
    return {
        "state": "idle",
        "category": "unclassified",
        "active": False,
        "started_at": None,
        "elapsed_seconds": None,
        "detail": None,
        "reason": None,
        "last_observed_phase": last.get("phase"),
        "last_observed_at": last.get("timestamp"),
    }


def _repository_amplification(layout, marks: list[dict]) -> dict:
    if not marks:
        return {"available": False, "reason": "no_observer_marks"}
    first = (marks[0].get("source_control") or {}).get("head")
    last = (marks[-1].get("source_control") or {}).get("head") or _git_head(layout)
    if not first or not last:
        return {"available": False, "reason": "git_head_not_observed"}
    for revision in (first, last):
        exists = subprocess.run(["git", "-C", str(layout.root), "cat-file", "-e", f"{revision}^{{commit}}"], capture_output=True)
        if exists.returncode:
            return {"available": False, "reason": "observed_git_revision_unavailable"}
    revs = subprocess.run(["git", "-C", str(layout.root), "rev-list", "--reverse", f"{first}..{last}"], capture_output=True, text=True)
    if revs.returncode:
        return {"available": False, "reason": "git_revision_range_unavailable"}
    commits = [line.strip() for line in revs.stdout.splitlines() if line.strip()]
    totals = {"total_commits": len(commits), "material_changing_commits": 0, "governance_evidence_only_commits": 0, "other_non_material_commits": 0, "unclassified_commits": 0}
    detail = []
    for revision in commits:
        diff = subprocess.run(["git", "-C", str(layout.root), "diff-tree", "--no-commit-id", "--name-only", "-r", revision], capture_output=True, text=True)
        paths = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
        classes = [classify_project_path(layout.root / path, layout) for path in paths]
        if any(value == "material" for value in classes):
            bucket = "material_changing_commits"
        elif paths and all(is_governance_bookkeeping_path(layout.root / path, layout) for path in paths):
            bucket = "governance_evidence_only_commits"
        elif any(value == "unclassified" for value in classes):
            bucket = "unclassified_commits"
        else:
            bucket = "other_non_material_commits"
        totals[bucket] += 1
        detail.append({"revision": revision, "classification": bucket, "paths": paths})
    return {"available": True, "provider": "git", "from_revision": first, "to_revision": last, **totals, "commits": detail}


def _validation_attempts(phase_counts: dict) -> dict:
    attempts = {
        "product_validation": phase_counts.get("product_validation_started", 0),
        "specforge_validation": phase_counts.get("specforge_validation_started", 0),
        "legacy_validation": phase_counts.get("validation_started", 0),
    }
    repeated = {key: max(0, value - 1) for key, value in attempts.items()}
    return {"attempts": attempts, "repeated_attempts": repeated, "total_repeated_attempts": sum(repeated.values())}


def summarize(layout, *, change=None, session=None) -> dict:
    marks = selected_marks(layout, change=change, session=session)

    first_by_phase = {}
    last_by_phase = {}
    for mark in marks:
        first_by_phase.setdefault(mark["phase"], mark)
        last_by_phase[mark["phase"]] = mark

    durations = {}
    for start, end, name in DURATION_PAIRS:
        if start not in first_by_phase or end not in last_by_phase:
            continue
        seconds = (parse_time(last_by_phase[end]["timestamp"]) - parse_time(first_by_phase[start]["timestamp"])).total_seconds()
        if seconds >= 0:
            durations[name] = round(seconds, 3)

    phase_counts = {}
    for mark in marks:
        phase_counts[mark["phase"]] = phase_counts.get(mark["phase"], 0) + 1

    consecutive = []
    category_totals = {
        "productive_work": 0.0,
        "specforge_management": 0.0,
        "user_wait": 0.0,
        "unclassified": 0.0,
    }
    state = {
        "clarification_wait": False,
        "approval_wait": False,
        "productive_work": False,
        "implementation": False,
        "product_validation": False,
        "specforge_validation": False,
        "legacy_validation": False,
    }
    for left, right in zip(marks, marks[1:]):
        apply_phase(state, left["phase"])
        seconds = round(max(0.0, (parse_time(right["timestamp"]) - parse_time(left["timestamp"])).total_seconds()), 3)
        classification, source = classify_interval(state, left["phase"], right["phase"])
        category_totals[classification] += seconds
        consecutive.append({
            "from": left["phase"],
            "to": right["phase"],
            "seconds": seconds,
            "from_attempt": left.get("attempt"),
            "to_attempt": right.get("attempt"),
            "classification": classification,
            "classification_source": source,
        })

    observed_span = round(sum(item["seconds"] for item in consecutive), 3)
    category_totals = {key: round(value, 3) for key, value in category_totals.items()}
    classified_seconds = round(
        category_totals["productive_work"] + category_totals["specforge_management"] + category_totals["user_wait"],
        3,
    )
    active_work_seconds = round(category_totals["productive_work"] + category_totals["specforge_management"], 3)
    classified_coverage_percent = (
        round((classified_seconds / observed_span) * 100.0, 3) if observed_span > 0 else None
    )
    management_overhead_percent = (
        round((category_totals["specforge_management"] / active_work_seconds) * 100.0, 3)
        if active_work_seconds > 0 else None
    )

    linked_sessions = sorted({
        mark.get("session")
        for mark in marks
        if mark.get("session")
    })

    return {
        "events": len(marks),
        "filter": {"change": change, "session": session},
        "linked_sessions": linked_sessions,
        "durations_seconds": durations,
        "phase_counts": phase_counts,
        "consecutive": consecutive,
        "repository_amplification": _repository_amplification(layout, marks),
        "validation_attempts": _validation_attempts(phase_counts),
        "current_activity": current_activity(marks),
        "execution_breakdown": {
            "observed_span_seconds": observed_span,
            "category_totals_seconds": category_totals,
            "classified_seconds": classified_seconds,
            "active_work_seconds": active_work_seconds,
            "classified_coverage_percent": classified_coverage_percent,
            "specforge_management_overhead_percent": management_overhead_percent,
            "overhead_denominator": "productive_work_plus_specforge_management",
            "user_wait_excluded_from_overhead": True,
            "classification_model": "span_aware_v1",
        },
        "marks": marks,
    }


def main():
    parser = argparse.ArgumentParser(description="Record and summarize SpecForge interaction timings")
    sub = parser.add_subparsers(dest="command", required=True)

    mark = sub.add_parser("mark")
    mark.add_argument("phase", choices=RECOMMENDED_PHASES)
    mark.add_argument("--root", default=".")
    mark.add_argument("--change")
    mark.add_argument("--proposal")
    mark.add_argument("--session")
    mark.add_argument("--attempt")
    mark.add_argument("--note")
    mark.add_argument("--json", action="store_true")

    summary = sub.add_parser("summary")
    summary.add_argument("--root", default=".")
    summary.add_argument("--change")
    summary.add_argument("--session")
    summary.add_argument("--json", action="store_true")

    phases = sub.add_parser("phases")
    phases.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "phases":
        out = {"recommended_phases": list(RECOMMENDED_PHASES)}
    else:
        try:
            layout = discover_layout(Path(args.root))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"project_discovery_failed:{exc}"}))
            sys.exit(2)
        if args.command == "mark":
            out = {"ok": True, "mark": append_mark(layout, args.phase, change=args.change, proposal=args.proposal, session=args.session, attempt=args.attempt, note=args.note)}
        else:
            out = {"ok": True, **summarize(layout, change=args.change, session=args.session)}

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
