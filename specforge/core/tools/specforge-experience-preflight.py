#!/usr/bin/env python3
"""Candidate A experience preflight.

Keeps execution/runtime infrastructure out of ordinary managed projects and prevents
an ordinary project change from silently becoming a framework repair.
"""
from pathlib import Path
import argparse
import json
import sys

FORBIDDEN_RUNTIME_DIRS = (
    ".specforge-runtime",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
)


def scan(root: Path) -> dict:
    root = root.resolve()
    local_runtimes = []
    for name in FORBIDDEN_RUNTIME_DIRS:
        candidate = root / name
        if candidate.exists():
            local_runtimes.append(name)
    return {
        "ok": not local_runtimes,
        "project_root": str(root),
        "local_runtime_paths": local_runtimes,
        "blockers": ["project_local_runtime_present"] if local_runtimes else [],
        "guidance": (
            "Use an existing/shared execution environment outside the managed project. "
            "Project-local runtimes are execution infrastructure, not project material."
            if local_runtimes else "experience_preflight_passed"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Candidate A experience preflight")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    out = scan(Path(args.root))
    print(json.dumps(out, indent=2))
    if not out["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
