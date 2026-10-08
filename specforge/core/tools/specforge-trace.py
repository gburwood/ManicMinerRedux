#!/usr/bin/env python3
from pathlib import Path
import argparse
import json
import sys

from specforge_project import discover_layout, iter_record_files, load_yaml, relative


def discover(layout):
    records = {}
    for path in iter_record_files(layout):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id"):
            records[str(data["id"])] = {"data": data, "path": relative(layout, path)}
    return records


def ref(records, rid):
    if not rid:
        return {"id": rid, "status": "missing"}
    record = records.get(str(rid))
    if not record:
        return {"id": rid, "status": "missing"}
    return {"id": rid, "status": "present", "path": record["path"], "record": record["data"]}


def build_trace(root, change_id):
    layout = discover_layout(root)
    records = discover(layout)
    change = records.get(change_id)
    if not change:
        raise KeyError(change_id)
    data = change["data"]
    out = {
        "project_root": str(layout.root),
        "project_format_mode": layout.mode,
        "manifest": relative(layout, layout.manifest_path),
        "change": {
            "id": change_id,
            "path": change["path"],
            "status": data.get("status"),
            "title": data.get("title"),
            "classification": data.get("classification"),
        },
        "sources": data.get("sources") or [],
        "request": data.get("request"),
        "impact_analysis": [],
        "proposals": [],
        "approvals": [],
        "implementation_attempts": [],
        "events": [],
        "release": None,
        "gaps": [],
    }

    impact_id = (data.get("impact_analysis") or {}).get("current")
    if impact_id:
        item = ref(records, impact_id)
        out["impact_analysis"].append({k: v for k, v in item.items() if k != "record"})
        if item["status"] == "missing":
            out["gaps"].append(f"Missing impact analysis {impact_id}")

    proposal_id = (data.get("proposal") or {}).get("current")
    if proposal_id:
        item = ref(records, proposal_id)
        out["proposals"].append({k: v for k, v in item.items() if k != "record"})
        if item["status"] == "missing":
            out["gaps"].append(f"Missing proposal {proposal_id}")

    for approval_id in data.get("approvals") or []:
        item = ref(records, approval_id)
        public = {k: v for k, v in item.items() if k != "record"}
        if item["status"] == "present":
            public["decision"] = item["record"].get("decision")
            public["proposal"] = item["record"].get("proposal")
            public["evidence"] = item["record"].get("evidence")
        out["approvals"].append(public)
        if item["status"] == "missing":
            out["gaps"].append(f"Missing approval {approval_id}")

    for attempt_id in ((data.get("implementation") or {}).get("attempts") or []):
        item = ref(records, attempt_id)
        public = {k: v for k, v in item.items() if k != "record"}
        if item["status"] == "present":
            record = item["record"]
            public["outcome"] = record.get("outcome")
            public["source_revision"] = record.get("source_revision")
            public["tests"] = record.get("tests")
            public["validation_checks"] = record.get("validation_checks")
        out["implementation_attempts"].append(public)
        if item["status"] == "missing":
            out["gaps"].append(f"Missing implementation attempt {attempt_id}")

    events = []
    for rid, record in records.items():
        if not rid.startswith("EVT-"):
            continue
        event = record["data"]
        entity = event.get("entity") or {}
        related = event.get("related") or {}
        if entity.get("id") == change_id or related.get("change") == change_id:
            events.append({
                "id": rid,
                "timestamp": event.get("timestamp"),
                "event_type": event.get("event_type"),
                "entity": entity,
                "related": related,
                "evidence": event.get("evidence"),
                "path": record["path"],
            })
    out["events"] = sorted(events, key=lambda item: (str(item.get("timestamp") or ""), item["id"]))

    release_id = (data.get("release") or {}).get("completed_in")
    if release_id:
        item = ref(records, release_id)
        out["release"] = {k: v for k, v in item.items() if k != "record"}
        if item["status"] == "missing":
            out["gaps"].append(f"Missing release {release_id}")
    return out


def human(trace):
    lines = [
        f"SpecForge forensic trace: {trace['change']['id']}",
        f"Title: {trace['change'].get('title')}",
        f"Status: {trace['change'].get('status')}",
        f"Project format mode: {trace.get('project_format_mode')}",
        "",
        "Evidence chain:",
    ]
    for source in trace["sources"]:
        lines.append(f"  SOURCE  {source.get('type', '?')}  {source.get('reference', '?')}")
    if trace.get("request"):
        lines.append(f"  REQUEST {trace['request'].get('summary', '')}")
    for item in trace["impact_analysis"]:
        lines.append(f"  IMPACT  {item['id']} [{item['status']}]")
    for item in trace["proposals"]:
        lines.append(f"  PROPOSAL {item['id']} [{item['status']}]")
    for item in trace["approvals"]:
        lines.append(f"  APPROVAL {item['id']} [{item['status']}] decision={item.get('decision')}")
    for item in trace["implementation_attempts"]:
        lines.append(f"  IMPLEMENT {item['id']} [{item['status']}] outcome={item.get('outcome')}")
        source_revision = item.get("source_revision") or {}
        if source_revision.get("after"):
            lines.append(f"    SOURCE REVISION {source_revision['after']}")
    if trace["release"]:
        lines.append(f"  RELEASE {trace['release']['id']} [{trace['release']['status']}]")
    else:
        lines.append("  RELEASE <none recorded>")
    lines.extend(["", "Forensic events:"])
    for event in trace["events"]:
        lines.append(f"  {event.get('timestamp', '?')}  {event['id']}  {event.get('event_type', '?')}")
    lines.append("")
    if trace["gaps"]:
        lines.append("Evidence gaps:")
        lines.extend("  ! " + gap for gap in trace["gaps"])
    else:
        lines.append("Evidence gaps: none detected in explicit change links")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Reconstruct explicit SpecForge forensic evidence for a change.")
    parser.add_argument("change_id")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        trace = build_trace(root, args.change_id)
    except KeyError:
        print(f"ERROR: Unknown change {args.change_id}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Unable to read SpecForge project: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(trace, indent=2) if args.as_json else human(trace))
    return 0


if __name__ == "__main__":
    sys.exit(main())
