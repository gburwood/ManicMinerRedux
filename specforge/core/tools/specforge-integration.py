#!/usr/bin/env python3
"""Capture, build and verify SpecForge integration evidence."""
from pathlib import Path
import argparse
import json
import sys

from specforge_project import discover_layout, iter_record_files, load_yaml
from specforge_integration import (
    build_git_integration_evidence,
    build_snapshot_integration_evidence,
    capture_target,
    verify_integration_evidence,
)


def find_attempt(layout, attempt_id):
    for path in iter_record_files(layout):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id") == attempt_id:
            return data, path
    return None, None


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture-target")
    capture.add_argument("--root", default=".")
    capture.add_argument("--target-ref", required=True)
    capture.add_argument("--json", action="store_true")

    build = sub.add_parser("build")
    build.add_argument("--root", default=".")
    build.add_argument("--attempt", required=True)
    build.add_argument("--target-ref")
    build.add_argument("--target-before")
    build.add_argument("--integrated-revision")
    build.add_argument("--json", action="store_true")

    verify = sub.add_parser("verify")
    verify.add_argument("--root", default=".")
    verify.add_argument("--attempt", required=True)
    verify.add_argument("--mode", choices=("transition", "static"), default="transition")
    verify.add_argument("--json", action="store_true")

    args = parser.parse_args()
    try:
        layout = discover_layout(Path(args.root).resolve())
    except Exception as exc:
        out = {"valid": False, "captured": False, "blockers": [f"project_discovery_failed:{exc}"]}
        print(json.dumps(out, indent=2))
        sys.exit(1)

    if args.command == "capture-target":
        out = capture_target(layout, args.target_ref)
        ok = out.get("captured", False)
    else:
        attempt, _path = find_attempt(layout, args.attempt)
        if not attempt:
            out = {"valid": False, "blockers": ["implementation_attempt_missing"]}
            ok = False
        elif args.command == "build":
            source = attempt.get("source_revision") or {}
            provider = str(source.get("system") or source.get("provider") or "").lower().replace("-", "_")
            if provider == "specforge_snapshot":
                out = build_snapshot_integration_evidence(layout, source)
            elif args.target_ref and args.target_before:
                out = build_git_integration_evidence(
                    layout,
                    source,
                    args.target_ref,
                    args.target_before,
                    args.integrated_revision,
                )
            else:
                out = {"valid": False, "blockers": ["git_integration_target_capture_required"]}
            ok = out.get("valid", False)
        else:
            out = verify_integration_evidence(layout, attempt, mode=args.mode)
            ok = out.get("valid", False)

    if getattr(args, "json", False):
        print(json.dumps(out, indent=2))
    else:
        print("VALID" if ok else "REFUSED")
        for blocker in out.get("blockers") or []:
            print(" - " + blocker)
        if out.get("target_before"):
            print(" target_before: " + out["target_before"])
        integration = out.get("integration") or {}
        if integration.get("integrated_revision"):
            print(" integrated_revision: " + integration["integrated_revision"])
        material = integration.get("integrated_material") or {}
        if material.get("revision"):
            print(" material: " + material["revision"])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
