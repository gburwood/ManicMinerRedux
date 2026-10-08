#!/usr/bin/env python3
"""Integration-aware immutable material evidence for SpecForge Core."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath
import hashlib
import subprocess
import tarfile
import tempfile

import yaml

from specforge_project import (
    _git_material_differences,
    discover_layout,
    git_worktree_root,
    iter_record_files,
    load_yaml,
    material_snapshot,
)

PROFILE = "immutable_material_v3"

# CHG-1058: process-local, repository-bound historical material caches.
_HISTORICAL_SNAPSHOT_CACHE = {}
_HISTORICAL_BLOB_SHA256_CACHE = {}


def _run_git(layout, *args, text=True):
    return subprocess.run(
        ["git", "-C", str(layout.root), *args],
        capture_output=True,
        text=text,
    )


def _snapshot_revision(value):
    if isinstance(value, dict):
        value = value.get("revision")
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.startswith("sha256:") and len(text) == 71:
        body = text[7:]
    elif len(text) == 64:
        body = text
        text = "sha256:" + text
    else:
        return None
    if all(ch in "0123456789abcdef" for ch in body):
        return text
    return None


def _git_commit(layout, value):
    if git_worktree_root(layout) is None or not isinstance(value, str) or not value.strip():
        return None
    result = _run_git(layout, "rev-parse", "--verify", f"{value.strip()}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _git_is_ancestor(layout, ancestor, descendant):
    if not ancestor or not descendant:
        return False
    return _run_git(layout, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def _integration_evidence_corrections(layout, implementation_id):
    if not implementation_id:
        return []
    matches = []
    for path in iter_record_files(layout):
        try:
            record = load_yaml(path)
        except Exception:
            continue
        if not isinstance(record, dict) or record.get("event_type") != "integration_evidence_correction":
            continue
        entity = record.get("entity") or {}
        if entity.get("type") == "implementation" and entity.get("id") == implementation_id:
            matches.append({"record": record, "path": str(path)})
    return matches


def _verify_static_integration_correction(
    layout,
    implementation,
    *,
    source_after,
    integrated_revision,
    recorded_implementation_material,
    recorded_integrated_material,
    source_snapshot,
    integrated_snapshot,
):
    implementation_id = implementation.get("id")
    matches = _integration_evidence_corrections(layout, implementation_id)
    if not matches:
        return {
            "valid": False,
            "blockers": ["integration_evidence_correction_missing"],
            "implementation": implementation_id,
        }
    if len(matches) != 1:
        return {
            "valid": False,
            "blockers": ["integration_evidence_correction_ambiguous"],
            "implementation": implementation_id,
            "events": [item["record"].get("id") for item in matches],
        }

    event = matches[0]["record"]
    evidence = event.get("evidence") or {}
    original = evidence.get("original") or {}
    corrected = evidence.get("corrected") or {}
    blockers = []

    event_original_implementation = _snapshot_revision(original.get("implementation_material"))
    event_original_integrated = _snapshot_revision(original.get("integrated_material"))
    if event_original_implementation != recorded_implementation_material:
        blockers.append("integration_evidence_correction_original_implementation_mismatch")
    if event_original_integrated != recorded_integrated_material:
        blockers.append("integration_evidence_correction_original_integrated_mismatch")

    event_source_after = _git_commit(layout, evidence.get("source_revision_after"))
    if not event_source_after or event_source_after != source_after:
        blockers.append("integration_evidence_correction_source_revision_mismatch")

    event_integrated_revision = _git_commit(layout, evidence.get("integrated_revision"))
    if not event_integrated_revision or event_integrated_revision != integrated_revision:
        blockers.append("integration_evidence_correction_integrated_revision_mismatch")

    corrected_material = _snapshot_revision(corrected.get("material"))
    corrected_count = corrected.get("file_count")
    if not corrected_material:
        blockers.append("integration_evidence_correction_corrected_material_invalid")
    if not isinstance(corrected_count, int) or isinstance(corrected_count, bool) or corrected_count < 0:
        blockers.append("integration_evidence_correction_file_count_invalid")

    source_material = source_snapshot.get("revision") if source_snapshot else None
    integrated_material = integrated_snapshot.get("revision") if integrated_snapshot else None
    source_count = source_snapshot.get("file_count") if source_snapshot else None
    integrated_count = integrated_snapshot.get("file_count") if integrated_snapshot else None

    if source_material != integrated_material:
        blockers.append("integration_evidence_correction_source_integrated_material_mismatch")
    if source_count != integrated_count:
        blockers.append("integration_evidence_correction_source_integrated_file_count_mismatch")
    if corrected_material and (corrected_material != source_material or corrected_material != integrated_material):
        blockers.append("integration_evidence_correction_corrected_material_mismatch")
    if isinstance(corrected_count, int) and (corrected_count != source_count or corrected_count != integrated_count):
        blockers.append("integration_evidence_correction_file_count_mismatch")

    return {
        "valid": not blockers,
        "blockers": sorted(set(blockers)),
        "implementation": implementation_id,
        "event": event.get("id"),
        "path": matches[0]["path"],
        "corrected_material": corrected_material,
        "file_count": corrected_count,
    }


def _safe_extract_tar(raw, destination):
    destination = destination.resolve()
    with tarfile.open(fileobj=BytesIO(raw), mode="r:") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError("git_archive_path_escape")
        archive.extractall(destination)


def _repository_identity(layout):
    result = _run_git(layout, "rev-parse", "--absolute-git-dir")
    if result.returncode or not result.stdout.strip():
        return None
    return str(Path(result.stdout.strip()).resolve()).casefold()


def _canonical_material_snapshot_for_git_revision(layout, commit):
    """Slow canonical oracle used whenever optimized equivalence is uncertain."""
    result = _run_git(layout, "archive", "--format=tar", commit, text=False)
    if result.returncode:
        return {
            "valid": False,
            "revision": commit,
            "blockers": ["integration_revision_archive_failed"],
            "snapshot": None,
        }
    try:
        with tempfile.TemporaryDirectory(prefix="specforge-material-") as td:
            root = Path(td)
            _safe_extract_tar(result.stdout, root)
            historical_layout = discover_layout(root)
            snapshot = material_snapshot(historical_layout)
    except Exception as exc:
        return {
            "valid": False,
            "revision": commit,
            "blockers": [f"integration_revision_materialisation_failed:{exc}"],
            "snapshot": None,
        }
    return {"valid": True, "revision": commit, "blockers": [], "snapshot": snapshot}


def _git_tree_entries(layout, commit):
    result = _run_git(layout, "ls-tree", "-r", "-z", "--full-tree", commit, text=False)
    if result.returncode:
        return None
    entries = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            meta, path_raw = raw.split(b"\t", 1)
            mode, kind, object_id = meta.decode("ascii").split(" ", 2)
            path = path_raw.decode("utf-8")
        except Exception:
            return None
        entries.append((mode, kind, object_id, path))
    return entries


def _git_blob_bytes(layout, object_id):
    result = _run_git(layout, "cat-file", "blob", object_id, text=False)
    if result.returncode:
        return None
    return result.stdout


def _historical_manifest(layout, commit, tree_entries):
    paths = {path: (mode, kind, object_id) for mode, kind, object_id, path in tree_entries}
    manifest_path = None
    if "specforge/project.yaml" in paths:
        manifest_path = "specforge/project.yaml"
    elif "specforge.yaml" in paths:
        manifest_path = "specforge.yaml"
    if manifest_path != "specforge/project.yaml":
        return None
    blob = _git_blob_bytes(layout, paths[manifest_path][2])
    if blob is None:
        return None
    try:
        manifest = yaml.safe_load(blob.decode("utf-8-sig"))
    except Exception:
        return None
    if not isinstance(manifest, dict):
        return None
    material = manifest.get("material")
    if not isinstance(material, dict) or str(material.get("mode") or "legacy") != "explicit_v1":
        return None
    roots = material.get("roots")
    if not isinstance(roots, list) or not roots:
        return None
    return manifest


def _normalise_repo_rel(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text or text == "." or text.startswith("/"):
        return None
    parts = PurePosixPath(text).parts
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _under(path, root):
    return path == root or path.startswith(root + "/")


def _contains(parent, child):
    return child == parent or child.startswith(parent + "/")


def _nested_project_roots(tree_entries):
    roots = set()
    for _mode, _kind, _oid, path in tree_entries:
        if path == "specforge/project.yaml" or path == "specforge.yaml":
            continue
        if path.endswith("/specforge/project.yaml"):
            roots.add(path[: -len("/specforge/project.yaml")])
        elif path.endswith("/specforge.yaml"):
            roots.add(path[: -len("/specforge.yaml")])
    return tuple(sorted(roots))


def _archive_attributes_are_plain(layout, tree_entries, repository_id):
    """Return False when git archive could transform or exclude tree content."""
    for _mode, kind, object_id, path in tree_entries:
        if kind != "blob" or PurePosixPath(path).name != ".gitattributes":
            continue
        key = (repository_id, object_id, "attribute-scan")
        cached = _HISTORICAL_BLOB_SHA256_CACHE.get(key)
        if cached is not None:
            if cached is False:
                return False
            continue
        raw = _git_blob_bytes(layout, object_id)
        if raw is None:
            return False
        text = raw.decode("utf-8", errors="replace")
        plain = "export-ignore" not in text and "export-subst" not in text
        _HISTORICAL_BLOB_SHA256_CACHE[key] = plain
        if not plain:
            return False
    return True


def _archive_file_map(layout, commit):
    """Return exact git-archive file bytes without extracting to the filesystem."""
    result = _run_git(layout, "archive", "--format=tar", commit, text=False)
    if result.returncode:
        return None
    files = {}
    try:
        with tarfile.open(fileobj=BytesIO(result.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                path = member.name.rstrip("/")
                if not path:
                    continue
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream is None:
                        return None
                    files[path] = ("file", stream.read())
                elif member.isdir():
                    continue
                else:
                    files[path] = ("special", None)
    except Exception:
        return None
    return files


def _fast_historical_material_snapshot(layout, commit, repository_id):
    """Compute explicit_v1 material identity from exact git-archive bytes.

    This uses Git's archive byte stream rather than raw object blobs, preserving
    the canonical archive/extract byte semantics while avoiding filesystem
    extraction, Path.resolve/rglob classification and disk re-reads.
    """
    archive_files = _archive_file_map(layout, commit)
    if archive_files is None:
        return None

    manifest_item = archive_files.get("specforge/project.yaml")
    if manifest_item is None or manifest_item[0] != "file":
        return None
    try:
        manifest = yaml.safe_load(manifest_item[1].decode("utf-8-sig"))
    except Exception:
        return None
    if not isinstance(manifest, dict):
        return None
    material = manifest.get("material")
    if not isinstance(material, dict) or str(material.get("mode") or "legacy") != "explicit_v1":
        return None

    roots = []
    for value in material.get("roots") or []:
        normalised = _normalise_repo_rel(value)
        if normalised is None:
            return None
        roots.append(normalised)
    if not roots or len(set(path.casefold() for path in roots)) != len(roots):
        return None
    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            if _under(left, right) or _under(right, left):
                return None

    paths = manifest.get("paths") or {}
    governance_roots = []
    for key, default in (
        ("changes", "specforge/changes"),
        ("decisions", "specforge/decisions"),
        ("history", "specforge/history"),
        ("evidence", "specforge/evidence"),
    ):
        value = _normalise_repo_rel(paths.get(key, default))
        if value is None:
            return None
        governance_roots.append(value)

    nested_roots = set()
    for path_value in archive_files:
        if path_value == "specforge/project.yaml" or path_value == "specforge.yaml":
            continue
        if path_value.endswith("/specforge/project.yaml"):
            nested_roots.add(path_value[: -len("/specforge/project.yaml")])
        elif path_value.endswith("/specforge.yaml"):
            nested_roots.add(path_value[: -len("/specforge.yaml")])
    nested_roots = tuple(sorted(nested_roots))

    transient_dirs = {
        "__pycache__", ".pytest_cache", ".specforge-runtime", ".venv",
        "venv", "node_modules",
    }
    transient_files = {".DS_Store", "Thumbs.db"}

    material_entries = []
    unclassified = []
    for path_value, (kind, raw) in archive_files.items():
        posix = PurePosixPath(path_value)
        parts = posix.parts

        if kind != "file":
            if any(_under(path_value, root) for root in roots):
                return None
            continue

        if (
            any(part in transient_dirs for part in parts[:-1])
            or posix.name in transient_files
            or posix.suffix == ".pyc"
            or any(_under(path_value, root) for root in governance_roots)
            or any(_under(path_value, root) for root in nested_roots)
            or (parts and parts[0] == "specforge-dist")
        ):
            classification = "non_material"
        elif any(_under(path_value, root) for root in roots):
            classification = "material"
        elif any(_contains(path_value, root) for root in roots):
            classification = "non_material"
        elif any(_contains(path_value, root) for root in governance_roots):
            classification = "non_material"
        else:
            classification = "unclassified"

        if classification == "unclassified":
            unclassified.append(path_value)
            continue
        if classification != "material":
            continue

        digest_key = (repository_id, commit, path_value, "archive-sha256")
        digest = _HISTORICAL_BLOB_SHA256_CACHE.get(digest_key)
        if not isinstance(digest, str):
            digest = hashlib.sha256(raw).hexdigest()
            _HISTORICAL_BLOB_SHA256_CACHE[digest_key] = digest
        material_entries.append((path_value, digest))

    if unclassified:
        return None

    material_entries.sort(key=lambda item: item[0])
    manifest_bytes = "".join(
        f"{path_value}\0{digest}\n" for path_value, digest in material_entries
    ).encode("utf-8")
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return {
        "provider": "specforge_snapshot",
        "algorithm": "sha256",
        "revision": f"sha256:{digest}",
        "digest": digest,
        "file_count": len(material_entries),
        "entries": [
            {"path": path_value, "sha256": sha256}
            for path_value, sha256 in material_entries
        ],
    }


def material_snapshot_for_git_revision(layout, revision):
    """Calculate the canonical material snapshot for an arbitrary Git commit.

    CHG-1058 first attempts a repository/revision-bound Git-tree calculation for
    explicit_v1 histories. Any uncertain case falls back to the unchanged
    canonical archive/extract/project-discovery/material_snapshot path.
    """
    commit = _git_commit(layout, revision)
    if not commit:
        return {
            "valid": False,
            "revision": revision,
            "blockers": ["integration_revision_not_git_commit"],
            "snapshot": None,
        }

    repository_id = _repository_identity(layout)
    cache_key = (repository_id, commit) if repository_id else None
    if cache_key and cache_key in _HISTORICAL_SNAPSHOT_CACHE:
        cached = _HISTORICAL_SNAPSHOT_CACHE[cache_key]
        return {
            "valid": cached["valid"],
            "revision": commit,
            "blockers": list(cached.get("blockers") or []),
            "snapshot": cached.get("snapshot"),
        }

    snapshot = None
    if repository_id:
        try:
            snapshot = _fast_historical_material_snapshot(layout, commit, repository_id)
        except Exception:
            snapshot = None

    if snapshot is not None:
        result = {"valid": True, "revision": commit, "blockers": [], "snapshot": snapshot}
    else:
        result = _canonical_material_snapshot_for_git_revision(layout, commit)

    if cache_key:
        _HISTORICAL_SNAPSHOT_CACHE[cache_key] = {
            "valid": bool(result.get("valid")),
            "blockers": list(result.get("blockers") or []),
            "snapshot": result.get("snapshot"),
        }
    return result


def capture_target(layout, target_ref):
    """Capture the accepted target state before a Git integration begins."""
    if git_worktree_root(layout) is None:
        return {
            "captured": False,
            "provider": "git",
            "target_ref": target_ref,
            "blockers": ["integration_provider_unavailable:git"],
        }
    target_before = _git_commit(layout, target_ref)
    if not target_before:
        return {
            "captured": False,
            "provider": "git",
            "target_ref": target_ref,
            "blockers": ["integration_target_ref_unresolvable"],
        }
    return {
        "captured": True,
        "provider": "git",
        "profile": PROFILE,
        "target_ref": target_ref,
        "target_before": target_before,
        "blockers": [],
    }


def _first_parent_commits(layout, start, end):
    result = _run_git(layout, "rev-list", "--first-parent", "--reverse", f"{start}..{end}")
    if result.returncode:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def discover_integrated_revision(layout, target_before, target_ref, implementation_material):
    """Find the actual target-line commit that first carries implementation material."""
    implementation_material = _snapshot_revision(implementation_material)
    before = _git_commit(layout, target_before)
    target = _git_commit(layout, target_ref)
    if not implementation_material:
        return {"valid": False, "blockers": ["implementation_material_identity_invalid"]}
    if not before:
        return {"valid": False, "blockers": ["integration_target_before_not_git_commit"]}
    if not target:
        return {"valid": False, "blockers": ["integration_target_ref_unresolvable"]}
    if not _git_is_ancestor(layout, before, target):
        return {"valid": False, "blockers": ["integration_target_lineage_invalid:target_before_target_ref"]}
    commits = _first_parent_commits(layout, before, target)
    if commits is None:
        return {"valid": False, "blockers": ["integration_target_first_parent_path_unavailable"]}
    checked = []
    for commit in commits:
        material = material_snapshot_for_git_revision(layout, commit)
        if not material.get("valid"):
            return {"valid": False, "blockers": material.get("blockers") or ["integration_materialisation_failed"]}
        revision = material["snapshot"]["revision"]
        checked.append({"revision": commit, "material": revision})
        if revision == implementation_material:
            return {
                "valid": True,
                "target_before": before,
                "target_revision": target,
                "integrated_revision": commit,
                "implementation_material": implementation_material,
                "checked": checked,
                "blockers": [],
            }
    return {
        "valid": False,
        "target_before": before,
        "target_revision": target,
        "checked": checked,
        "blockers": ["integration_material_not_found_on_target_first_parent_path"],
    }


def build_git_integration_evidence(layout, source_revision, target_ref, target_before, integrated_revision=None):
    """Build authoritative Git integration evidence from observed repository state."""
    source_revision = source_revision or {}
    source_after = source_revision.get("after")
    source_material = material_snapshot_for_git_revision(layout, source_after)
    if not source_material.get("valid"):
        return {"valid": False, "blockers": source_material.get("blockers") or []}
    implementation_material = source_material["snapshot"]["revision"]
    discovery = discover_integrated_revision(layout, target_before, target_ref, implementation_material)
    if not discovery.get("valid"):
        return {"valid": False, "blockers": discovery.get("blockers") or [], "details": discovery}
    discovered = discovery["integrated_revision"]
    if integrated_revision:
        supplied = _git_commit(layout, integrated_revision)
        if not supplied or supplied != discovered:
            return {
                "valid": False,
                "blockers": ["integration_revision_not_mechanically_discovered_target_transition"],
                "details": {"supplied": supplied or integrated_revision, "discovered": discovered},
            }
    integrated_material = material_snapshot_for_git_revision(layout, discovered)
    if not integrated_material.get("valid"):
        return {"valid": False, "blockers": integrated_material.get("blockers") or []}
    return {
        "valid": True,
        "blockers": [],
        "integration": {
            "profile": PROFILE,
            "provider": "git",
            "target_ref": target_ref,
            "target_before": discovery["target_before"],
            "integrated_revision": discovered,
            "implementation_material": {
                "provider": "specforge_snapshot",
                "revision": implementation_material,
                "file_count": source_material["snapshot"]["file_count"],
            },
            "integrated_material": {
                "provider": "specforge_snapshot",
                "revision": integrated_material["snapshot"]["revision"],
                "file_count": integrated_material["snapshot"]["file_count"],
            },
            "verification": {
                "status": "passed",
                "method": "target_first_parent_transition_plus_canonical_material_equivalence",
            },
        },
        "details": {"discovery": discovery},
    }


def build_snapshot_integration_evidence(layout, source_revision):
    """Build direct integration evidence for a provider-neutral snapshot project."""
    source_revision = source_revision or {}
    before = _snapshot_revision(source_revision.get("before"))
    after = _snapshot_revision(source_revision.get("after"))
    blockers = []
    if not before:
        blockers.append("source_revision_before_snapshot_invalid")
    if not after:
        blockers.append("source_revision_after_snapshot_invalid")
    if before and after and source_revision.get("material_effects", True) is not False and before == after:
        blockers.append("source_revision_not_advanced")
    current = material_snapshot(layout)
    if after and current["revision"] != after:
        blockers.append("uncaptured_material_changes")
    if blockers:
        return {"valid": False, "blockers": sorted(set(blockers))}
    material = {
        "provider": "specforge_snapshot",
        "revision": after,
        "file_count": current["file_count"],
    }
    return {
        "valid": True,
        "blockers": [],
        "integration": {
            "profile": PROFILE,
            "provider": "specforge_snapshot",
            "integrated_revision": after,
            "implementation_material": material,
            "integrated_material": dict(material),
            "verification": {
                "status": "passed",
                "method": "direct_canonical_material_identity",
            },
        },
    }


def _verify_source_git_lineage(layout, source_revision, *, required):
    source_revision = source_revision or {}
    before = _git_commit(layout, source_revision.get("before"))
    after = _git_commit(layout, source_revision.get("after"))
    blockers = []
    if not before:
        blockers.append("source_revision_before_not_git_commit")
    if not after:
        blockers.append("source_revision_after_not_git_commit")
    if before and after:
        if source_revision.get("material_effects", True) is not False and before == after:
            blockers.append("source_revision_not_advanced")
        if not _git_is_ancestor(layout, before, after):
            blockers.append("source_revision_lineage_invalid:before_after")
    if required and blockers:
        return None, blockers
    return after, blockers


def verify_integration_evidence(layout, implementation, *, mode="transition"):
    """Verify immutable_material_v3 integration evidence.

    Transition mode recomputes source and integrated material, mechanically derives
    the accepted target-line integration commit and verifies current material capture.
    Static mode preserves historical verification after squash/rebase source commits
    may no longer be reachable, using persisted implementation-material identity plus
    the durable integrated commit on the accepted line.
    """
    implementation = implementation or {}
    source_revision = implementation.get("source_revision") or {}
    integration = implementation.get("integration") or {}
    blockers = []
    details = {"profile": integration.get("profile")}

    if integration.get("profile") != PROFILE:
        blockers.append("integration_profile_missing_or_unsupported")
        return {"valid": False, "profile": integration.get("profile"), "blockers": blockers, "details": details}

    source_provider = str(source_revision.get("system") or source_revision.get("provider") or "").lower().replace("-", "_")
    provider = str(integration.get("provider") or source_provider or "").lower().replace("-", "_")
    implementation_material = _snapshot_revision(integration.get("implementation_material"))
    integrated_material = _snapshot_revision(integration.get("integrated_material"))
    details.update({
        "provider": provider,
        "implementation_material": implementation_material,
        "integrated_material": integrated_material,
    })
    if not implementation_material:
        blockers.append("implementation_material_identity_invalid")
    if not integrated_material:
        blockers.append("integrated_material_identity_invalid")
    if implementation_material and integrated_material and implementation_material != integrated_material:
        blockers.append("integration_material_identity_mismatch")

    if provider == "specforge_snapshot":
        before = _snapshot_revision(source_revision.get("before"))
        source_after = _snapshot_revision(source_revision.get("after"))
        integrated_revision = _snapshot_revision(integration.get("integrated_revision"))
        if not before:
            blockers.append("source_revision_before_snapshot_invalid")
        if not source_after:
            blockers.append("source_revision_after_snapshot_invalid")
        if (
            before
            and source_after
            and source_revision.get("material_effects", True) is not False
            and before == source_after
        ):
            blockers.append("source_revision_not_advanced")
        if not integrated_revision:
            blockers.append("integrated_revision_snapshot_invalid")
        if source_after and implementation_material and source_after != implementation_material:
            blockers.append("source_material_identity_mismatch")
        if integrated_revision and integrated_material and integrated_revision != integrated_material:
            blockers.append("integrated_revision_material_identity_mismatch")
        if mode == "transition" and not blockers:
            current = material_snapshot(layout)
            details["current_material"] = current["revision"]
            if current["revision"] != integrated_material:
                blockers.append("integrated_material_not_current")
        return {
            "valid": not blockers,
            "profile": PROFILE,
            "provider": provider,
            "blockers": sorted(set(blockers)),
            "details": details,
        }

    if provider != "git":
        blockers.append(f"integration_provider_unsupported:{provider or 'missing'}")
        return {"valid": False, "profile": PROFILE, "provider": provider or None, "blockers": blockers, "details": details}

    if git_worktree_root(layout) is None:
        details["provider_available"] = False
        if mode == "transition":
            blockers.append("integration_provider_unavailable:git")
        return {"valid": not blockers, "profile": PROFILE, "provider": provider, "blockers": blockers, "details": details}
    details["provider_available"] = True

    target_ref = integration.get("target_ref")
    target_commit = _git_commit(layout, target_ref) if target_ref else None
    target_before = _git_commit(layout, integration.get("target_before"))
    integrated_revision = _git_commit(layout, integration.get("integrated_revision"))
    if not target_ref:
        blockers.append("integration_target_ref_missing")
    elif mode == "transition" and not target_commit:
        blockers.append("integration_target_ref_unresolvable")
    if not target_before:
        blockers.append("integration_target_before_not_git_commit")
    if not integrated_revision:
        blockers.append("integrated_revision_not_git_commit")
    if target_before and integrated_revision and not _git_is_ancestor(layout, target_before, integrated_revision):
        blockers.append("integration_target_lineage_invalid:target_before_integrated")

    head = _git_commit(layout, "HEAD")
    details["head"] = head
    if integrated_revision and head and not _git_is_ancestor(layout, integrated_revision, head):
        blockers.append("integrated_revision_not_on_current_project_lineage")

    computed_integrated_snapshot = None
    computed_integrated_material = None
    if integrated_revision and integrated_material:
        snapshot = material_snapshot_for_git_revision(layout, integrated_revision)
        if not snapshot.get("valid"):
            blockers += snapshot.get("blockers") or []
        else:
            computed_integrated_snapshot = snapshot["snapshot"]
            computed_integrated_material = computed_integrated_snapshot["revision"]
            details["computed_integrated_material"] = computed_integrated_material

    source_after, source_blockers = _verify_source_git_lineage(
        layout,
        source_revision,
        required=mode == "transition",
    )
    if mode == "transition":
        blockers += source_blockers
    else:
        details["source_revision_static_blockers"] = source_blockers

    computed_source_snapshot = None
    computed_implementation_material = None
    if source_after and implementation_material:
        source_snapshot_result = material_snapshot_for_git_revision(layout, source_after)
        if not source_snapshot_result.get("valid"):
            if mode == "transition":
                blockers += source_snapshot_result.get("blockers") or []
        else:
            computed_source_snapshot = source_snapshot_result["snapshot"]
            computed_implementation_material = computed_source_snapshot["revision"]
            details["computed_implementation_material"] = computed_implementation_material

    recomputation_mismatch = (
        (computed_integrated_material is not None and computed_integrated_material != integrated_material)
        or (
            computed_implementation_material is not None
            and computed_implementation_material != implementation_material
        )
    )
    effective_material = implementation_material
    correction = None
    if (
        mode == "static"
        and recomputation_mismatch
        and computed_source_snapshot is not None
        and computed_integrated_snapshot is not None
        and source_after
        and integrated_revision
        and implementation_material
        and integrated_material
        and implementation_material == integrated_material
    ):
        correction = _verify_static_integration_correction(
            layout,
            implementation,
            source_after=source_after,
            integrated_revision=integrated_revision,
            recorded_implementation_material=implementation_material,
            recorded_integrated_material=integrated_material,
            source_snapshot=computed_source_snapshot,
            integrated_snapshot=computed_integrated_snapshot,
        )
        details["forensic_integration_correction"] = correction
        if correction.get("valid"):
            effective_material = correction.get("corrected_material")
        else:
            blockers += correction.get("blockers") or []

    if not (correction and correction.get("valid")):
        if computed_integrated_material is not None and computed_integrated_material != integrated_material:
            blockers.append("integrated_material_recomputation_mismatch")
        if (
            computed_implementation_material is not None
            and computed_implementation_material != implementation_material
        ):
            blockers.append("implementation_material_recomputation_mismatch")

    if target_ref and target_before and effective_material:
        endpoint = target_commit or ("HEAD" if mode == "static" else None)
        if endpoint:
            discovery = discover_integrated_revision(layout, target_before, endpoint, effective_material)
            details["discovery"] = discovery
            if not discovery.get("valid"):
                blockers += discovery.get("blockers") or []
            elif integrated_revision and discovery.get("integrated_revision") != integrated_revision:
                blockers.append("integration_revision_not_mechanically_discovered_target_transition")

    if mode == "transition" and integrated_revision:
        material_differences = _git_material_differences(layout, integrated_revision)
        details["material_differences"] = material_differences
        if material_differences:
            blockers.append("uncaptured_material_changes")

    verification = integration.get("verification") or {}
    if verification.get("status") not in {None, "passed"}:
        blockers.append("integration_record_verification_not_passed")

    return {
        "valid": not blockers,
        "profile": PROFILE,
        "provider": provider,
        "blockers": sorted(set(blockers)),
        "details": details,
    }

def verified_material_bridge(layout, implementation):
    """Return independently verified canonical material identities for one implementation bridge.

    The bridge is historical/static evidence: it proves where a completed implementation starts
    and ends in canonical material space without requiring today's project material to equal that
    historical endpoint. Git commits are re-materialised and hashed; snapshot providers use their
    canonical snapshot revisions directly. Integration evidence must verify before a bridge is
    returned.
    """
    implementation = implementation or {}
    verification = verify_integration_evidence(layout, implementation, mode="static")
    if not verification.get("valid"):
        return {
            "valid": False,
            "blockers": ["successor_integration_evidence_invalid"] + (verification.get("blockers") or []),
            "details": {"verification": verification},
        }

    source_revision = implementation.get("source_revision") or {}
    integration = implementation.get("integration") or {}
    source_provider = str(source_revision.get("system") or source_revision.get("provider") or "").lower().replace("-", "_")
    provider = str(integration.get("provider") or source_provider or "").lower().replace("-", "_")
    blockers = []
    details = {"provider": provider, "verification": verification}

    if provider == "git":
        before_commit = _git_commit(layout, source_revision.get("before"))
        integrated_commit = _git_commit(layout, integration.get("integrated_revision"))
        if not before_commit:
            blockers.append("successor_source_before_not_git_commit")
        if not integrated_commit:
            blockers.append("successor_integrated_revision_not_git_commit")

        before_snapshot = None
        integrated_snapshot = None
        if before_commit:
            result = material_snapshot_for_git_revision(layout, before_commit)
            if not result.get("valid"):
                blockers += ["successor_source_before_material_unavailable"] + (result.get("blockers") or [])
            else:
                before_snapshot = result["snapshot"]
        if integrated_commit:
            result = material_snapshot_for_git_revision(layout, integrated_commit)
            if not result.get("valid"):
                blockers += ["successor_integrated_material_unavailable"] + (result.get("blockers") or [])
            else:
                integrated_snapshot = result["snapshot"]

        if blockers:
            return {"valid": False, "blockers": sorted(set(blockers)), "details": details}

        details.update({
            "start_revision": before_commit,
            "end_revision": integrated_commit,
            "start_material": before_snapshot["revision"],
            "end_material": integrated_snapshot["revision"],
        })
        return {
            "valid": True,
            "provider": "git",
            "start_material": before_snapshot["revision"],
            "end_material": integrated_snapshot["revision"],
            "start_revision": before_commit,
            "end_revision": integrated_commit,
            "blockers": [],
            "details": details,
        }

    if provider == "specforge_snapshot":
        start_material = _snapshot_revision(source_revision.get("before"))
        end_material = _snapshot_revision(integration.get("integrated_revision"))
        if not start_material:
            blockers.append("successor_source_before_snapshot_invalid")
        if not end_material:
            blockers.append("successor_integrated_snapshot_invalid")
        if blockers:
            return {"valid": False, "blockers": sorted(set(blockers)), "details": details}
        details.update({"start_material": start_material, "end_material": end_material})
        return {
            "valid": True,
            "provider": "specforge_snapshot",
            "start_material": start_material,
            "end_material": end_material,
            "start_revision": start_material,
            "end_revision": end_material,
            "blockers": [],
            "details": details,
        }

    return {
        "valid": False,
        "blockers": [f"successor_integration_provider_unsupported:{provider or 'missing'}"],
        "details": details,
    }

