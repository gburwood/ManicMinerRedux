#!/usr/bin/env python3
"""CLI for the deterministic governance-tier floor: initialize, prepare and activate."""
from pathlib import Path
import argparse
import json
import sys

from specforge_project import discover_layout, iter_record_files, load_yaml
from specforge_governance_tier import activate, initialize_fresh_project, prepare


def _records(layout):
    out = {}
    for path in iter_record_files(layout):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id"):
            out[str(data["id"])] = (data, path)
    return out


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    initialize_parser = sub.add_parser("initialize")
    initialize_parser.add_argument("--root", default=".")
    initialize_parser.add_argument("--json", action="store_true")

    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("proposal")
    prepare_parser.add_argument("--root", default=".")
    prepare_parser.add_argument("--json", action="store_true")

    activate_parser = sub.add_parser("activate")
    activate_parser.add_argument("--change", required=True)
    activate_parser.add_argument("--root", default=".")
    activate_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        layout = discover_layout(root)
    except Exception as exc:
        out = {"permitted": False, "blockers": [f"project_discovery_failed:{exc}"]}
        print(json.dumps(out, indent=2) if args.json else "REFUSED\n - " + out["blockers"][0])
        sys.exit(1)

    recs = _records(layout)
    if args.cmd == "initialize":
        result = initialize_fresh_project(layout, recs)
        ok = result.get("initialized", False)
    elif args.cmd == "prepare":
        result = prepare(layout, recs, args.proposal)
        ok = result.get("prepared", False)
    else:
        result = activate(layout, recs, args.change)
        ok = result.get("activated", False)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("PERMITTED" if ok else "REFUSED")
        for blocker in result.get("blockers", []):
            print(" - " + blocker)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
