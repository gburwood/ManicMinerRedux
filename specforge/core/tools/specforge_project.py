#!/usr/bin/env python3
"""Shared project-layout, canonical-artifact and material-revision helpers for SpecForge tooling."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import datetime
import hashlib
import re
import subprocess
from typing import Iterable

import yaml

DISTRIBUTION_ROOT_NAMES = frozenset({"specforge-dist"})
TRANSIENT_DIRECTORY_NAMES = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".specforge-runtime",
    ".venv",
    "venv",
    "node_modules",
})
TRANSIENT_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db"})
TRANSIENT_SUFFIXES = frozenset({".pyc"})
MATERIAL_MODE_EXPLICIT_V1 = "explicit_v1"
GIT_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
SNAPSHOT_REVISION_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


@dataclass(frozen=True)
class ProjectLayout:
    root: Path
    mode: str
    manifest_path: Path
    manifest: dict
    governance_root: Path
    core_root: Path
    record_roots: tuple[Path, ...]
    tool_root: Path


class MaterialBoundaryError(ValueError):
    """Raised when explicit material classification leaves project paths unclassified."""

    def __init__(self, paths: Iterable[str]):
        self.paths = tuple(sorted(dict.fromkeys(str(path).replace("\\", "/") for path in paths)))
        super().__init__("unclassified_project_paths_present:" + ",".join(self.paths))


def normalize_yaml_scalars(value):
    if isinstance(value, dict):
        return {k: normalize_yaml_scalars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_yaml_scalars(v) for v in value]
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return normalize_yaml_scalars(yaml.safe_load(handle))


def project_root(candidate: Path) -> Path:
    candidate = candidate.resolve()
    for current in (candidate, *candidate.parents):
        if current.name in DISTRIBUTION_ROOT_NAMES:
            continue
        if (current / "specforge" / "project.yaml").is_file() or (current / "specforge.yaml").is_file():
            return current
    raise FileNotFoundError(f"No SpecForge project manifest found from {candidate}")


def _resolve(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    return (root / value).resolve()


def configured_path(layout: ProjectLayout, key: str, default: str) -> Path:
    """Resolve a configured project path with a conventional-layout fallback."""
    paths = layout.manifest.get("paths") or {}
    value = paths.get(key, default)
    if not isinstance(value, str) or not value.strip():
        value = default
    return (layout.root / value).resolve()


def configured_relative_path(layout: ProjectLayout, key: str, default: str) -> str:
    return relative(layout, configured_path(layout, key, default))


def discover_layout(candidate: Path) -> ProjectLayout:
    root = project_root(candidate)
    new_manifest = root / "specforge" / "project.yaml"
    legacy_manifest = root / "specforge.yaml"
    if new_manifest.is_file() and legacy_manifest.is_file():
        raise ValueError("ambiguous_project_authority:specforge/project.yaml,specforge.yaml")
    if new_manifest.is_file():
        manifest = load_yaml(new_manifest)
        if not isinstance(manifest, dict):
            raise ValueError("specforge/project.yaml must contain a mapping")
        paths = manifest.get("paths") or {}
        governance_root = root / "specforge"
        core_root = _resolve(root, paths.get("core")) or (governance_root / "core")
        tool_root = _resolve(root, paths.get("tools")) or (core_root / "tools")
        record_roots = []
        for key, default in (
            ("changes", "specforge/changes"),
            ("decisions", "specforge/decisions"),
            ("history", "specforge/history"),
        ):
            record_roots.append(_resolve(root, paths.get(key, default)) or (root / default))
        # Git cannot preserve empty directories. Recreate declared record collections
        # deterministically so a fresh clone is bootstrap-equivalent to its source.
        # Evidence is deliberately excluded: it is mandatory authority state and a
        # missing evidence root must remain observable as a bootstrap blocker.
        for state_root in record_roots:
            state_root.mkdir(parents=True, exist_ok=True)
        return ProjectLayout(
            root=root,
            mode="project_format_1",
            manifest_path=new_manifest,
            manifest=manifest,
            governance_root=governance_root,
            core_root=core_root,
            record_roots=tuple(record_roots),
            tool_root=tool_root,
        )

    manifest = load_yaml(legacy_manifest)
    if not isinstance(manifest, dict):
        raise ValueError("specforge.yaml must contain a mapping")
    paths = manifest.get("paths") or {}
    record_roots = []
    for key in ("changes", "history"):
        value = paths.get(key)
        if value:
            record_roots.append(_resolve(root, value))
    return ProjectLayout(
        root=root,
        mode="legacy_root",
        manifest_path=legacy_manifest,
        manifest=manifest,
        governance_root=root,
        core_root=root,
        record_roots=tuple(p for p in record_roots if p is not None),
        tool_root=_resolve(root, paths.get("tools")) or (root / "tools"),
    )


def canonical_artifact_bytes(path: Path) -> bytes:
    """Canonical text bytes for governed-artifact integrity digests."""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8")


def canonical_artifact_digest(path: Path) -> str:
    return hashlib.sha256(canonical_artifact_bytes(path)).hexdigest()


def is_distribution_path(path: Path, root: Path) -> bool:
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    return bool(parts) and parts[0] in DISTRIBUTION_ROOT_NAMES


def is_nested_project(path: Path, layout: ProjectLayout) -> bool:
    if is_distribution_path(path, layout.root):
        return True
    current = path.parent
    while current != layout.root and layout.root in current.parents:
        if current.name in DISTRIBUTION_ROOT_NAMES:
            return True
        if (current / "specforge" / "project.yaml").is_file() or (current / "specforge.yaml").is_file():
            return True
        current = current.parent
    return False


def iter_record_files(layout: ProjectLayout) -> Iterable[Path]:
    if layout.mode == "project_format_1":
        for record_root in layout.record_roots:
            if not record_root.exists():
                continue
            for path in record_root.rglob("*.yaml"):
                if not is_nested_project(path, layout):
                    yield path
        return

    for path in layout.root.rglob("*.yaml"):
        if path == layout.manifest_path or is_distribution_path(path, layout.root) or is_nested_project(path, layout):
            continue
        yield path


def relative(layout: ProjectLayout, path: Path) -> str:
    return str(path.resolve().relative_to(layout.root)).replace("\\", "/")


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except (FileNotFoundError, OSError):
        return str(left.resolve()).casefold() == str(right.resolve()).casefold()


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def governance_bookkeeping_roots(layout: ProjectLayout) -> tuple[Path, ...]:
    if layout.mode == "project_format_1":
        paths = layout.manifest.get("paths") or {}
        defaults = {
            "changes": "specforge/changes",
            "decisions": "specforge/decisions",
            "history": "specforge/history",
            "evidence": "specforge/evidence",
        }
        return tuple((layout.root / paths.get(key, default)).resolve() for key, default in defaults.items())
    paths = layout.manifest.get("paths") or {}
    roots = []
    for key in ("changes", "history"):
        if paths.get(key):
            roots.append((layout.root / paths[key]).resolve())
    return tuple(roots)


def is_governance_bookkeeping_path(path: Path, layout: ProjectLayout) -> bool:
    candidate = path.resolve()
    return any(_is_within(candidate, root) for root in governance_bookkeeping_roots(layout))


def is_transient_material_path(path: Path, layout: ProjectLayout) -> bool:
    try:
        rel = path.resolve().relative_to(layout.root.resolve())
    except ValueError:
        return True
    if any(part in TRANSIENT_DIRECTORY_NAMES for part in rel.parts[:-1]):
        return True
    if path.is_dir() and rel.parts and rel.parts[-1] in TRANSIENT_DIRECTORY_NAMES:
        return True
    if rel.name in TRANSIENT_FILE_NAMES or rel.suffix in TRANSIENT_SUFFIXES:
        return True
    return False


def material_mode(layout: ProjectLayout) -> str:
    material = layout.manifest.get("material")
    if not isinstance(material, dict):
        return "legacy"
    return str(material.get("mode") or "legacy")


def declared_material_roots(layout: ProjectLayout) -> tuple[Path, ...]:
    if material_mode(layout) != MATERIAL_MODE_EXPLICIT_V1:
        return ()
    material = layout.manifest.get("material") or {}
    roots = material.get("roots") or []
    resolved = []
    for value in roots:
        if isinstance(value, str) and value.strip():
            resolved.append((layout.root / value).resolve())
    return tuple(resolved)


def deterministic_non_material_roots(layout: ProjectLayout) -> tuple[Path, ...]:
    roots = list(governance_bookkeeping_roots(layout))
    roots.append((layout.root / ".git").resolve())
    for name in DISTRIBUTION_ROOT_NAMES:
        roots.append((layout.root / name).resolve())
    return tuple(roots)


def is_core_non_material_path(path: Path, layout: ProjectLayout) -> bool:
    candidate = path.resolve()
    try:
        rel = candidate.relative_to(layout.root.resolve())
    except ValueError:
        return False
    if not rel.parts:
        return False
    if rel.parts[0] == ".git":
        return True
    if is_distribution_path(candidate, layout.root) or is_nested_project(candidate, layout):
        return True
    if is_governance_bookkeeping_path(candidate, layout):
        return True
    if is_transient_material_path(candidate, layout):
        return True
    return False


def classify_project_path(path: Path, layout: ProjectLayout) -> str:
    """Classify a path as material, non_material or unclassified.

    Legacy projects preserve the pre-explicit-boundary behaviour. In explicit_v1,
    Core-owned non-material classification has precedence over declared material roots.
    Structural parent directories are non-material containers only; this never grants
    material status to otherwise-unclassified children beneath them.
    """
    candidate = path.resolve()
    try:
        candidate.relative_to(layout.root.resolve())
    except ValueError:
        return "unclassified"

    if candidate == layout.root.resolve():
        return "non_material"

    if is_core_non_material_path(candidate, layout):
        return "non_material"

    if material_mode(layout) != MATERIAL_MODE_EXPLICIT_V1:
        return "material"

    material_roots = declared_material_roots(layout)
    for root in material_roots:
        if candidate == root or _is_within(candidate, root):
            return "material"

    if any(_is_within(root, candidate) for root in material_roots):
        return "non_material"
    if any(_is_within(root, candidate) for root in deterministic_non_material_roots(layout)):
        return "non_material"
    return "unclassified"


def material_boundary_blockers(layout: ProjectLayout) -> list[dict]:
    """Validate explicit_v1 configuration without inspecting working-tree contents."""
    if material_mode(layout) != MATERIAL_MODE_EXPLICIT_V1:
        return []

    material = layout.manifest.get("material")
    blockers = []
    roots = material.get("roots") if isinstance(material, dict) else None
    if not isinstance(roots, list) or not roots:
        return [{"code": "material_roots_missing_or_empty"}]

    normalized: list[tuple[str, Path]] = []
    seen = set()
    fixed_non_material_roots = deterministic_non_material_roots(layout)
    for value in roots:
        if not isinstance(value, str) or not value.strip():
            blockers.append({"code": "material_root_invalid", "path": value})
            continue
        raw = value.strip().replace("\\", "/")
        if raw in {".", "./"}:
            blockers.append({"code": "material_root_project_wide_forbidden", "path": value})
            continue
        resolved = (layout.root / value).resolve()
        if not _is_within(resolved, layout.root):
            blockers.append({"code": "material_root_outside_project", "path": value})
            continue
        key = str(resolved).casefold()
        if key in seen:
            blockers.append({"code": "material_root_duplicate", "path": value})
            continue
        seen.add(key)
        if is_core_non_material_path(resolved, layout) or any(
            _is_within(non_material_root, resolved) for non_material_root in fixed_non_material_roots
        ):
            blockers.append({"code": "material_root_non_material_overlap", "path": value})
            continue
        normalized.append((value, resolved))

    for index, (left_value, left) in enumerate(normalized):
        for right_value, right in normalized[index + 1:]:
            if _is_within(left, right) or _is_within(right, left):
                blockers.append({
                    "code": "material_root_redundant_overlap",
                    "path": left_value,
                    "other": right_value,
                })
    return blockers


def unclassified_project_paths(layout: ProjectLayout) -> list[str]:
    """Return top-most unclassified paths for explicit_v1 projects."""
    if material_mode(layout) != MATERIAL_MODE_EXPLICIT_V1:
        return []
    if material_boundary_blockers(layout):
        return []

    candidates = []
    for path in layout.root.rglob("*"):
        classification = classify_project_path(path, layout)
        if classification == "unclassified":
            rel = relative(layout, path)
            if any(rel == parent or rel.startswith(parent + "/") for parent in candidates):
                continue
            candidates.append(rel)
    return sorted(candidates)


def iter_material_files(layout: ProjectLayout) -> Iterable[Path]:
    """Yield files that constitute project material for immutable snapshot purposes."""
    for path in layout.root.rglob("*"):
        if not path.is_file():
            continue
        if classify_project_path(path, layout) == "material":
            yield path


def material_snapshot(layout: ProjectLayout) -> dict:
    """Return a deterministic content manifest digest for project material."""
    config_blockers = material_boundary_blockers(layout)
    if config_blockers:
        codes = [item["code"] + (":" + str(item.get("path")) if item.get("path") is not None else "") for item in config_blockers]
        raise ValueError("invalid_material_boundary:" + ",".join(codes))
    unclassified = unclassified_project_paths(layout)
    if unclassified:
        raise MaterialBoundaryError(unclassified)

    entries = []
    for path in sorted(iter_material_files(layout), key=lambda item: relative(layout, item)):
        rel = relative(layout, path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append((rel, digest))
    manifest_bytes = "".join(f"{rel}\0{digest}\n" for rel, digest in entries).encode("utf-8")
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return {
        "provider": "specforge_snapshot",
        "algorithm": "sha256",
        "revision": f"sha256:{digest}",
        "digest": digest,
        "file_count": len(entries),
        "entries": [{"path": rel, "sha256": sha} for rel, sha in entries],
    }


def _run_git(layout: ProjectLayout, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(layout.root), *args],
        capture_output=True,
        text=True,
    )


def git_worktree_root(layout: ProjectLayout) -> Path | None:
    try:
        result = _run_git(layout, "rev-parse", "--show-toplevel")
    except (FileNotFoundError, OSError):
        return None
    if result.returncode:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    candidate = Path(text)
    return candidate.resolve() if _same_path(candidate, layout.root) else None


def _looks_git_revision(value) -> bool:
    return isinstance(value, str) and bool(GIT_REVISION_RE.fullmatch(value.strip()))


def _snapshot_digest(value) -> str | None:
    if not isinstance(value, str):
        return None
    match = SNAPSHOT_REVISION_RE.fullmatch(value.strip())
    return match.group(1).lower() if match else None


def _provider_name(value) -> str | None:
    if not value:
        return None
    value = str(value).strip().lower().replace("-", "_")
    aliases = {
        "git": "git",
        "specforge_snapshot": "specforge_snapshot",
        "snapshot": "specforge_snapshot",
        "content_snapshot": "specforge_snapshot",
    }
    return aliases.get(value, value)


def _git_commit_exists(layout: ProjectLayout, revision: str) -> bool:
    result = _run_git(layout, "cat-file", "-e", f"{revision}^{{commit}}")
    return result.returncode == 0


def _git_is_ancestor(layout: ProjectLayout, ancestor: str, descendant: str) -> bool:
    result = _run_git(layout, "merge-base", "--is-ancestor", ancestor, descendant)
    return result.returncode == 0


def git_material_state(layout: ProjectLayout, after: str) -> dict:
    """Return current boundary validity plus changed material paths relative to a Git revision."""
    boundary_blockers = material_boundary_blockers(layout)
    if boundary_blockers:
        return {"material": [], "unclassified": [], "boundary_blockers": boundary_blockers}

    differences = set()
    tracked = _run_git(layout, "diff", "--name-only", after, "--")
    if tracked.returncode == 0:
        differences.update(line.strip() for line in tracked.stdout.splitlines() if line.strip())
    untracked = _run_git(layout, "ls-files", "--others", "--exclude-standard")
    if untracked.returncode == 0:
        differences.update(line.strip() for line in untracked.stdout.splitlines() if line.strip())

    material = []
    unclassified_paths = set(unclassified_project_paths(layout))
    for rel in sorted(differences):
        normalized = rel.replace("\\", "/")
        classification = classify_project_path(layout.root / rel, layout)
        if classification == "material":
            material.append(normalized)
        elif classification == "unclassified":
            unclassified_paths.add(normalized)
    return {
        "material": material,
        "unclassified": sorted(unclassified_paths),
        "boundary_blockers": [],
    }


def _git_material_differences(layout: ProjectLayout, after: str) -> list[str]:
    return git_material_state(layout, after)["material"]


def verify_source_revision(
    layout: ProjectLayout,
    source_revision: dict | None,
    *,
    mode: str = "static",
    require_provider: bool = False,
) -> dict:
    """Verify provider-neutral immutable material revision evidence.

    `mode='transition'` verifies current material capture and therefore requires the
    backing provider to be available. `mode='static'` validates historical evidence
    without requiring today's material tree to equal an old implementation state.
    """
    source_revision = source_revision or {}
    before = source_revision.get("before")
    after = source_revision.get("after")
    explicit = _provider_name(source_revision.get("system") or source_revision.get("provider"))
    material_effects = source_revision.get("material_effects", True) is not False
    blockers = []
    details = {}

    if not after:
        return {"valid": False, "provider": explicit, "blockers": ["source_revision_after_missing"], "details": details}

    if material_effects and before and str(before) == str(after):
        blockers.append("source_revision_not_advanced")

    git_root = git_worktree_root(layout)
    provider = explicit
    if provider is None:
        if require_provider:
            provider = "git" if git_root is not None else "specforge_snapshot"
        elif git_root is not None and _looks_git_revision(before) and _looks_git_revision(after):
            provider = "git"
        elif _snapshot_digest(before) and _snapshot_digest(after):
            provider = "specforge_snapshot"
        else:
            provider = "legacy"

    if provider == "legacy":
        return {"valid": not blockers, "provider": provider, "blockers": blockers, "details": details}

    if provider == "git":
        if git_root is None:
            details["provider_available"] = False
            if mode == "transition":
                blockers.append("source_revision_provider_unavailable:git")
            return {"valid": not blockers, "provider": provider, "blockers": blockers, "details": details}
        details["provider_available"] = True
        if not isinstance(before, str) or not _git_commit_exists(layout, before):
            blockers.append("source_revision_before_not_git_commit")
        if not isinstance(after, str) or not _git_commit_exists(layout, after):
            blockers.append("source_revision_after_not_git_commit")
        if not blockers:
            if before and not _git_is_ancestor(layout, before, after):
                blockers.append("source_revision_lineage_invalid:before_after")
            head = _run_git(layout, "rev-parse", "HEAD")
            current_head = head.stdout.strip() if head.returncode == 0 else None
            details["head"] = current_head
            if current_head and not _git_is_ancestor(layout, after, current_head):
                blockers.append("source_revision_lineage_invalid:after_head")
            if mode == "transition" and not blockers:
                state = git_material_state(layout, after)
                details["material_differences"] = state["material"]
                details["unclassified_paths"] = state["unclassified"]
                details["material_boundary_blockers"] = state["boundary_blockers"]
                if state["boundary_blockers"]:
                    blockers.append("invalid_material_boundary")
                if state["unclassified"]:
                    blockers.append("unclassified_project_paths_present")
                if state["material"]:
                    blockers.append("uncaptured_material_changes")
        return {"valid": not blockers, "provider": provider, "blockers": blockers, "details": details}

    if provider == "specforge_snapshot":
        before_digest = _snapshot_digest(before)
        after_digest = _snapshot_digest(after)
        if not before_digest:
            blockers.append("source_revision_before_snapshot_invalid")
        if not after_digest:
            blockers.append("source_revision_after_snapshot_invalid")
        if mode == "transition" and not blockers:
            try:
                current = material_snapshot(layout)
            except MaterialBoundaryError as exc:
                details["unclassified_paths"] = list(exc.paths)
                blockers.append("unclassified_project_paths_present")
                return {"valid": False, "provider": provider, "blockers": blockers, "details": details}
            except ValueError as exc:
                blockers.append("invalid_material_boundary")
                details["material_boundary_error"] = str(exc)
                return {"valid": False, "provider": provider, "blockers": blockers, "details": details}
            details["current_snapshot"] = current["revision"]
            details["file_count"] = current["file_count"]
            if current["digest"] != after_digest:
                blockers.append("uncaptured_material_changes")
        return {"valid": not blockers, "provider": provider, "blockers": blockers, "details": details}

    blockers.append(f"source_revision_provider_unsupported:{provider}")
    return {"valid": False, "provider": provider, "blockers": blockers, "details": details}


def _controlled_v3_approval_proof(layout, approval, proposal_id, proposal_digest):
    evidence = approval.get("evidence") or {}
    rel = evidence.get("informed_approval_proof")
    if not rel:
        return False
    target = (layout.root / str(rel)).resolve()
    try:
        target.relative_to(layout.root.resolve())
    except ValueError:
        return False
    if not target.is_file():
        return False
    try:
        proof = load_yaml(target)
    except Exception:
        return False
    if not isinstance(proof, dict):
        return False
    return bool(
        proof.get("type") == "informed_approval_proof"
        and proof.get("proposal") == proposal_id
        and proof.get("proposal_digest") == proposal_digest
        and proof.get("decision") == "approved"
        and proof.get("received_at") == approval.get("timestamp")
        and ((proof.get("actor") or {}).get("type") == "human")
        and (proof.get("actor") or {}).get("id") == (approval.get("actor") or {}).get("id")
    )


def approval_gate(layout, recs, chg):
    """Verify an exact, digest-bound, human approval of the change's current proposal."""
    blockers = []
    proposal_id = (chg.get("proposal") or {}).get("current")
    if not proposal_id or proposal_id not in recs:
        return ["current_proposal_missing"]
    _proposal, proposal_path = recs[proposal_id]
    actual = canonical_artifact_digest(proposal_path)
    profile = (chg.get("governance") or {}).get("lifecycle_enforcement")
    valid = False
    for approval_id in chg.get("approvals") or []:
        if approval_id not in recs:
            continue
        approval, _ = recs[approval_id]
        if approval.get("decision") != "approved" or approval.get("proposal") != proposal_id:
            continue
        if (approval.get("actor") or {}).get("type") != "human":
            continue
        evidence = approval.get("evidence") or {}
        expected = evidence.get("proposal_digest") or (approval.get("scope") or {}).get("proposal_sha256")
        if not expected or expected != actual:
            continue
        if profile == "controlled_v3" and not _controlled_v3_approval_proof(layout, approval, proposal_id, actual):
            continue
        valid = True
        break
    if not valid:
        blockers.append("valid_exact_human_approval_missing")
    return blockers


def proposal_ever_human_approved(recs, proposal_id):
    """True if any record anywhere is a human, decision=approved approval of this proposal id."""
    for _rid, item in recs.items():
        data = item[0] if isinstance(item, tuple) else item
        if not isinstance(data, dict):
            continue
        if data.get("proposal") != proposal_id:
            continue
        if data.get("decision") != "approved":
            continue
        if (data.get("actor") or {}).get("type") != "human":
            continue
        return True
    return False


def allocate_next_event_id(layout):
    """Return the next unused EVT-NNNNNN id, scanning specforge/history/events/ for the current max."""
    paths = layout.manifest.get("paths") or {}
    history_root = (layout.root / paths.get("history", "specforge/history")).resolve()
    events_root = history_root / "events"
    pattern = re.compile(r"^EVT-(\d{6,})\.yaml$")
    highest = 0
    if events_root.is_dir():
        for path in events_root.glob("EVT-*.yaml"):
            match = pattern.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"EVT-{(highest + 1) if highest else 100000:06d}"


def _evidence_root(layout) -> Path:
    paths = layout.manifest.get("paths") or {}
    return (layout.root / paths.get("evidence", "specforge/evidence")).resolve()


def persist_material_manifest(layout) -> dict:
    """Durably persist the current material snapshot's full path/digest manifest."""
    snapshot = material_snapshot(layout)
    digest = snapshot["digest"]
    manifest_root = _evidence_root(layout) / "material-manifests"
    manifest_root.mkdir(parents=True, exist_ok=True)
    target = manifest_root / f"{digest}.yaml"
    if not target.is_file():
        payload = {"revision": snapshot["revision"], "entries": snapshot["entries"]}
        target.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
            newline="\n",
        )
    return {"digest": digest, "path": target}


def read_material_manifest(layout, digest: str) -> dict | None:
    """Read and digest-verify a manifest persisted by persist_material_manifest."""
    target = _evidence_root(layout) / "material-manifests" / f"{digest}.yaml"
    if not target.is_file():
        return None
    try:
        data = load_yaml(target)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    entries = data.get("entries")
    if not isinstance(entries, list) or not all(isinstance(e, dict) and "path" in e and "sha256" in e for e in entries):
        return None
    manifest_bytes = "".join(f"{e['path']}\0{e['sha256']}\n" for e in sorted(entries, key=lambda e: e["path"])).encode("utf-8")
    if hashlib.sha256(manifest_bytes).hexdigest() != digest:
        return None
    return {"revision": data.get("revision"), "entries": entries}


GOVERNANCE_TIER_PROFILE_TO_LIFECYCLE = {"deterministic_tier_v1": "controlled_v2"}
SUPPORTED_LIFECYCLE_ENFORCEMENT_PROFILES = frozenset({"controlled_v1", "controlled_v2", "controlled_v3"})


def read_project_governance_tier_state(layout) -> dict:
    """Read and integrity-verify this project's governance-tier activation state."""
    manifest_tier = layout.manifest.get("governance_tier")
    manifest_tier = manifest_tier if isinstance(manifest_tier, dict) else {}
    tier_enforcement_profile = manifest_tier.get("enforcement_profile")
    anchor = manifest_tier.get("grandfather_digest")

    corrupted = {
        "status": "corrupted",
        "tier_enforcement_profile": tier_enforcement_profile,
        "effective_lifecycle_profile": None,
        "grandfather_digests": frozenset(),
    }

    if tier_enforcement_profile is None and anchor is None:
        return {
            "status": "not_activated",
            "tier_enforcement_profile": None,
            "effective_lifecycle_profile": "controlled_v1",
            "grandfather_digests": frozenset(),
        }
    if tier_enforcement_profile is None or anchor is None:
        return corrupted

    effective_lifecycle_profile = GOVERNANCE_TIER_PROFILE_TO_LIFECYCLE.get(tier_enforcement_profile)
    if effective_lifecycle_profile is None:
        return corrupted

    evidence_path = _evidence_root(layout) / "governance-tier-grandfather.yaml"
    if not evidence_path.is_file():
        return corrupted
    try:
        actual_digest = canonical_artifact_digest(evidence_path)
        evidence = load_yaml(evidence_path)
    except Exception:
        return corrupted
    if actual_digest != anchor or not isinstance(evidence, dict):
        return corrupted

    digests = evidence.get("proposal_digests")
    if not isinstance(digests, list):
        return corrupted

    return {
        "status": "active",
        "tier_enforcement_profile": tier_enforcement_profile,
        "effective_lifecycle_profile": effective_lifecycle_profile,
        "grandfather_digests": frozenset(str(d) for d in digests),
        "activation_provenance": evidence.get("provenance") or "governed_activation_v1",
    }


PRODUCT_SPEC_DOC_RE = re.compile(r"^specforge-core-product-spec-(.+)\.md$")
PRODUCT_SPEC_DOC_TEMPLATE = "specforge-core-product-spec-{version}.md"
CANONICAL_DATA_MODEL_DOC_RE = re.compile(r"^specforge-core-canonical-data-model-(.+)\.md$")
CANONICAL_DATA_MODEL_DOC_TEMPLATE = "specforge-core-canonical-data-model-{version}.md"


def read_installed_core_metadata(layout) -> dict:
    core_path = layout.core_root / "core.yaml"
    package_path = layout.core_root / "package.yaml"
    core = load_yaml(core_path) if core_path.is_file() else None
    package = load_yaml(package_path) if package_path.is_file() else None
    return {
        "core": core if isinstance(core, dict) else None,
        "package": package if isinstance(package, dict) else None,
    }


def self_referencing_core_doc_version(layout, value, pattern) -> str | None:
    if not value:
        return None
    match = pattern.match(Path(str(value)).name)
    if not match:
        return None
    try:
        resolved = (layout.root / str(value)).resolve()
    except Exception:
        return None
    try:
        resolved.relative_to((layout.core_root / "docs").resolve())
    except ValueError:
        return None
    return match.group(1)


def manifest_core_consistency_blockers(layout, manifest: dict | None = None) -> list[dict]:
    manifest = manifest if manifest is not None else layout.manifest
    installed = read_installed_core_metadata(layout)
    core_meta = installed["core"] or {}
    package_meta = installed["package"]

    sf = manifest.get("specforge") or {}
    spec = manifest.get("specification") or {}
    declared_core_version = sf.get("core_version")
    declared_data_model_version = sf.get("data_model_version")
    installed_core_version = core_meta.get("core_version")
    installed_data_model_version = core_meta.get("data_model_version")

    blockers = []

    if installed_core_version and declared_core_version != installed_core_version:
        blockers.append({
            "code": "core_version_inconsistent",
            "declared_core_version": declared_core_version,
            "installed_core_version": installed_core_version,
        })

    if installed_data_model_version and declared_data_model_version != installed_data_model_version:
        blockers.append({
            "code": "data_model_version_inconsistent",
            "declared_data_model_version": declared_data_model_version,
            "installed_data_model_version": installed_data_model_version,
        })

    if package_meta is not None and installed_core_version:
        package_version = (package_meta.get("package") or {}).get("version")
        if package_version != installed_core_version:
            blockers.append({
                "code": "package_core_version_inconsistent",
                "package_version": package_version,
                "installed_core_version": installed_core_version,
            })

    product_spec_embedded = self_referencing_core_doc_version(layout, spec.get("product_specification"), PRODUCT_SPEC_DOC_RE)
    if product_spec_embedded is not None:
        declared_current_version = spec.get("current_version")
        if product_spec_embedded != declared_core_version or declared_current_version != declared_core_version:
            blockers.append({
                "code": "self_referencing_product_specification_inconsistent",
                "embedded_version": product_spec_embedded,
                "declared_core_version": declared_core_version,
                "declared_current_version": declared_current_version,
            })

    data_model_embedded = self_referencing_core_doc_version(layout, spec.get("canonical_data_model"), CANONICAL_DATA_MODEL_DOC_RE)
    if data_model_embedded is not None and data_model_embedded != declared_data_model_version:
        blockers.append({
            "code": "self_referencing_canonical_data_model_inconsistent",
            "embedded_version": data_model_embedded,
            "declared_data_model_version": declared_data_model_version,
        })

    return blockers

def record_root_relpaths(layout: ProjectLayout) -> tuple[str, ...]:
    """Return canonical record roots relative to the project root."""
    values = []
    for root in layout.record_roots:
        try:
            values.append(root.resolve().relative_to(layout.root.resolve()).as_posix())
        except ValueError:
            continue
    return tuple(values)


def git_diff_name_status(layout: ProjectLayout, before: str, after: str = "HEAD", paths: Iterable[str] | None = None) -> list[dict]:
    """Return a parsed Git name-status delta without opening unchanged files."""
    args = ["git", "-C", str(layout.root), "diff", "--name-status", "--find-renames", before, after]
    selected = list(paths or [])
    if selected:
        args.extend(["--", *selected])
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("git_diff_failed:" + result.stderr.strip())
    rows = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            rows.append({"status": "R", "old_path": parts[1], "path": parts[2]})
        elif len(parts) >= 2:
            rows.append({"status": status[:1], "path": parts[1]})
    return rows


def git_show_yaml_at_revision(layout: ProjectLayout, revision: str, relpath: str):
    """Read one YAML artifact from a trusted Git revision without scanning its siblings."""
    result = subprocess.run(
        ["git", "-C", str(layout.root), "show", f"{revision}:{relpath}"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None
    try:
        value = yaml.safe_load(result.stdout)
    except Exception:
        return None
    return normalize_yaml_scalars(value)

