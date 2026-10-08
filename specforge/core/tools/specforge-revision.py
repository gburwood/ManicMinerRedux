#!/usr/bin/env python3
"""Capture and verify provider-neutral immutable material revisions."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

from specforge_project import (
    MaterialBoundaryError,
    discover_layout,
    git_worktree_root,
    material_snapshot,
    persist_material_manifest,
    verify_source_revision,
)
from specforge_integration import material_snapshot_for_git_revision


def capture(layout):
    if git_worktree_root(layout) is not None:
        result = subprocess.run(
            ["git", "-C", str(layout.root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            return {"captured": False, "provider": "git", "blockers": ["git_head_unavailable"]}
        revision = result.stdout.strip()
        check = verify_source_revision(
            layout,
            {
                "system": "git",
                "before": revision,
                "after": revision,
                "material_effects": False,
            },
            mode="transition",
            require_provider=True,
        )
        return {
            "captured": check.get("valid", False),
            "provider": "git",
            "revision": revision,
            "blockers": check.get("blockers") or [],
            "details": check.get("details") or {},
        }

    try:
        snapshot = material_snapshot(layout)
        persist_material_manifest(layout)
    except MaterialBoundaryError as exc:
        return {
            "captured": False,
            "provider": "specforge_snapshot",
            "blockers": ["unclassified_project_paths_present"],
            "details": {"unclassified_paths": list(exc.paths)},
        }
    except ValueError as exc:
        return {
            "captured": False,
            "provider": "specforge_snapshot",
            "blockers": [str(exc)],
        }
    return {
        "captured": True,
        "provider": "specforge_snapshot",
        "revision": snapshot["revision"],
        "file_count": snapshot["file_count"],
        "blockers": [],
    }


def material(layout, revision):
    if git_worktree_root(layout) is None:
        return {
            "valid": False,
            "provider": "git",
            "revision": revision,
            "blockers": ["source_revision_provider_unavailable:git"],
        }
    result = material_snapshot_for_git_revision(layout, revision)
    if not result.get("valid"):
        return {
            "valid": False,
            "provider": "git",
            "revision": revision,
            "blockers": result.get("blockers") or [],
        }
    snapshot = result["snapshot"]
    return {
        "valid": True,
        "provider": "git",
        "revision": result["revision"],
        "material_revision": snapshot["revision"],
        "file_count": snapshot["file_count"],
        "blockers": [],
    }


def verify(layout, args):
    check = verify_source_revision(
        layout,
        {
            "system": args.provider,
            "before": args.before,
            "after": args.after,
            "material_effects": not args.allow_same,
        },
        mode=args.mode,
        require_provider=args.mode == "transition",
    )
    return {
        "valid": check.get("valid", False),
        "provider": check.get("provider"),
        "blockers": check.get("blockers") or [],
        "details": check.get("details") or {},
    }


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--root", default=".")
    capture_parser.add_argument("--json", action="store_true")

    material_parser = sub.add_parser("material")
    material_parser.add_argument("--root", default=".")
    material_parser.add_argument("--revision", required=True)
    material_parser.add_argument("--json", action="store_true")

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--root", default=".")
    verify_parser.add_argument("--provider", required=True)
    verify_parser.add_argument("--before", required=True)
    verify_parser.add_argument("--after", required=True)
    verify_parser.add_argument("--mode", choices=("static", "transition"), default="transition")
    verify_parser.add_argument("--allow-same", action="store_true")
    verify_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    try:
        layout = discover_layout(Path(args.root).resolve())
    except Exception as exc:
        out = {"captured": False, "valid": False, "blockers": [f"project_discovery_failed:{exc}"]}
        print(json.dumps(out, indent=2) if getattr(args, "json", False) else "REFUSED\n - " + out["blockers"][0])
        sys.exit(1)

    if args.command == "capture":
        out = capture(layout)
        ok = out.get("captured", False)
    elif args.command == "material":
        out = material(layout, args.revision)
        ok = out.get("valid", False)
    else:
        out = verify(layout, args)
        ok = out.get("valid", False)

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        state = "CAPTURED" if args.command == "capture" else ("VALID" if ok else "REFUSED")
        print(state)
        for blocker in out.get("blockers") or []:
            print(" - " + blocker)
        if out.get("revision"):
            print(" revision: " + out["revision"])
        if out.get("material_revision"):
            print(" material: " + out["material_revision"])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
