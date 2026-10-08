#!/usr/bin/env python3
"""Candidate SpecForge distribution discovery and validation helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from specforge_project import load_yaml


@dataclass(frozen=True)
class Distribution:
    root: Path
    core_root: Path
    package_path: Path
    package: dict
    core: dict

    @property
    def version(self):
        return (self.package.get("package") or {}).get("version")

    @property
    def project_formats(self):
        return (self.package.get("compatibility") or {}).get("project_formats") or []

    @property
    def migration_registry(self):
        declared = (self.package.get("migrations") or {}).get("registry")
        base = self.package_path.parent
        return (base / declared).resolve() if declared else self.core_root / "migrations" / "registry.yaml"


def _candidate_paths(path: Path):
    path = path.resolve()
    yield path
    if path.name == "core":
        yield path.parent


def discover_distribution(path: Path | None = None, *, tool_file: Path | None = None) -> Distribution:
    """Resolve a candidate distribution without consulting installed project state.

    Preferred package layout:
      <distribution>/package.yaml
      <distribution>/core/core.yaml

    For source-tree/development use, package.yaml may also live directly in the
    Core directory. This convenience does not make that directory project state.
    """
    candidates = []
    if path is not None:
        candidates.extend(_candidate_paths(path))
    elif tool_file is not None:
        tool_file = tool_file.resolve()
        candidates.extend([tool_file.parents[2], tool_file.parents[1]])

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        root_package = candidate / "package.yaml"
        core_package = candidate / "core" / "package.yaml"
        if root_package.is_file():
            package_path = root_package
            core_root = candidate / "core"
            root = candidate
        elif core_package.is_file():
            package_path = core_package
            core_root = candidate / "core"
            root = candidate
        elif candidate.name == "core" and (candidate / "package.yaml").is_file():
            package_path = candidate / "package.yaml"
            core_root = candidate
            root = candidate
        else:
            continue

        if not core_root.is_dir() and candidate.name == "core":
            core_root = candidate
            root = candidate
        core_meta_path = core_root / "core.yaml"
        if not core_meta_path.is_file():
            raise FileNotFoundError(f"distribution_core_metadata_missing:{core_meta_path}")
        package = load_yaml(package_path)
        core = load_yaml(core_meta_path)
        if not isinstance(package, dict):
            raise ValueError("distribution_package_metadata_invalid")
        if not isinstance(core, dict):
            raise ValueError("distribution_core_metadata_invalid")
        p = package.get("package") or {}
        blockers = []
        if p.get("type") != "specforge_core": blockers.append("distribution_package_type_invalid")
        if not p.get("version"): blockers.append("distribution_package_version_missing")
        if p.get("version") != core.get("core_version"): blockers.append("distribution_core_version_mismatch")
        compat = (package.get("compatibility") or {}).get("project_formats")
        if not isinstance(compat, list) or not compat: blockers.append("distribution_project_format_compatibility_missing")
        if blockers:
            raise ValueError(",".join(blockers))
        dist = Distribution(root=root, core_root=core_root, package_path=package_path, package=package, core=core)
        if not dist.migration_registry.is_file():
            raise FileNotFoundError(f"distribution_migration_registry_missing:{dist.migration_registry}")
        return dist

    raise FileNotFoundError("specforge_distribution_not_found")
