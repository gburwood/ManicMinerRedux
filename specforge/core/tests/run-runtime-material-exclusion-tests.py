#!/usr/bin/env python3
from pathlib import Path
import sys
import tempfile
import yaml

CORE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = CORE_ROOT / "tools"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TESTS))

from specforge_project import (
    MaterialBoundaryError,
    classify_project_path,
    discover_layout,
    material_boundary_blockers,
    material_snapshot,
    verify_source_revision,
)
from portable_fixture import create_project, git

RUNTIME_DIRS = (
    ".specforge-runtime",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
)

EXPLICIT_ROOTS = [
    "product.txt",
    "model.txt",
    "README.md",
    "src",
    "specforge/project.yaml",
    "specforge/SPECFORGE.md",
    "specforge/core",
    "specforge/packs",
]

GENESIS_AUTHORIZATION_ROOTS = [
    "authorization-policy.json",
    "gae-v1-ceremony.md",
    "gae",
    "specforge-authorization-policy.schema.json",
    "specforge-authorization-proof.schema.json",
    "specforge-transition-verify.py",
    "specforge-transition.schema.json",
    "specforge-webauthn-adapter.py",
    "specforge-webauthn-authority.schema.json",
    "specforge-webauthn-enrol.py",
    "tests",
    "transition-protocol.md",
]


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def add_runtime_noise(root: Path):
    for name in RUNTIME_DIRS:
        payload = root / name / "nested" / "runtime.bin"
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_bytes((name + " runtime noise").encode("utf-8"))


def set_explicit_material(root: Path, roots=None):
    manifest_path = root / "specforge/project.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["material"] = {"mode": "explicit_v1", "roots": list(EXPLICIT_ROOTS if roots is None else roots)}
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    if roots is None:
        (root / "src").mkdir(exist_ok=True)
        (root / "src/app.txt").write_text("one\n", encoding="utf-8", newline="\n")


def add_genesis_authorization_surface(root: Path):
    files = [
        "authorization-policy.json",
        "gae-v1-ceremony.md",
        "gae/README.md",
        "gae/gae.js",
        "specforge-authorization-policy.schema.json",
        "specforge-authorization-proof.schema.json",
        "specforge-transition-verify.py",
        "specforge-transition.schema.json",
        "specforge-webauthn-adapter.py",
        "specforge-webauthn-authority.schema.json",
        "specforge-webauthn-enrol.py",
        "tests/test_transition_contract.py",
        "transition-protocol.md",
    ]
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel + "\n", encoding="utf-8", newline="\n")


# Legacy projects keep the existing transient/runtime exclusions.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "snapshot-project"
    create_project(root, CORE_ROOT, git_backed=False)
    layout = discover_layout(root)
    baseline = material_snapshot(layout)
    add_runtime_noise(root)
    after = material_snapshot(layout)
    check("legacy-snapshot-runtime-directories-do-not-change-revision", after["revision"] == baseline["revision"])
    material_paths = {entry["path"] for entry in after["entries"]}
    check(
        "legacy-snapshot-runtime-directories-never-enter-material-manifest",
        all(not any(path == name or path.startswith(name + "/") for name in RUNTIME_DIRS) for path in material_paths),
    )


# Explicit mode positively declares material and blocks everything else.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "explicit-snapshot-project"
    create_project(root, CORE_ROOT, git_backed=False)
    set_explicit_material(root)
    layout = discover_layout(root)
    check("explicit-material-boundary-valid", not material_boundary_blockers(layout))

    baseline = material_snapshot(layout)
    add_runtime_noise(root)
    after_runtime = material_snapshot(layout)
    check("explicit-runtime-directories-do-not-change-revision", after_runtime["revision"] == baseline["revision"])

    (root / "src/new-module").mkdir(parents=True)
    (root / "src/new-module/file.py").write_text("print('material')\n", encoding="utf-8", newline="\n")
    after_material = material_snapshot(layout)
    check("explicit-new-descendant-is-material", after_material["revision"] != baseline["revision"])
    check(
        "explicit-new-descendant-enters-manifest",
        "src/new-module/file.py" in {entry["path"] for entry in after_material["entries"]},
    )

    unknown = root / "brand-new-tool-output"
    unknown.mkdir()
    (unknown / "noise.bin").write_bytes(b"unknown")
    try:
        material_snapshot(layout)
        raised = False
    except MaterialBoundaryError as exc:
        raised = True
        check("explicit-unclassified-path-evidence", "brand-new-tool-output" in exc.paths)
    check("explicit-unclassified-path-blocks-snapshot", raised)


# A structural parent is only a traversal container. An unknown sibling beneath it still blocks.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "structural-parent-project"
    create_project(root, CORE_ROOT, git_backed=False)
    set_explicit_material(root)
    mystery = root / "specforge/mystery"
    mystery.mkdir()
    (mystery / "file.txt").write_text("unknown sibling\n", encoding="utf-8", newline="\n")
    layout = discover_layout(root)
    try:
        material_snapshot(layout)
        raised = False
    except MaterialBoundaryError as exc:
        raised = True
        check("structural-parent-unknown-sibling-evidence", "specforge/mystery" in exc.paths)
    check("structural-parent-does-not-classify-unknown-sibling", raised)


# Invalid explicit contracts fail deterministically.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "invalid-empty-roots"
    create_project(root, CORE_ROOT, git_backed=False)
    set_explicit_material(root, [])
    blockers = material_boundary_blockers(discover_layout(root))
    check("explicit-empty-roots-rejected", any(item["code"] == "material_roots_missing_or_empty" for item in blockers))

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "invalid-project-wide-root"
    create_project(root, CORE_ROOT, git_backed=False)
    set_explicit_material(root, ["."])
    blockers = material_boundary_blockers(discover_layout(root))
    check("explicit-project-wide-root-rejected", any(item["code"] == "material_root_project_wide_forbidden" for item in blockers))

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "invalid-non-material-overlap"
    create_project(root, CORE_ROOT, git_backed=False)
    set_explicit_material(root, ["specforge/history"])
    blockers = material_boundary_blockers(discover_layout(root))
    check("explicit-non-material-overlap-rejected", any(item["code"] == "material_root_non_material_overlap" for item in blockers))


# Git verification checks untracked and already-tracked unknown paths across the whole current boundary.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "git-project"
    create_project(root, CORE_ROOT, git_backed=True)
    set_explicit_material(root)
    git(root, "add", "specforge/project.yaml", "src")
    git(root, "commit", "-m", "enable explicit material boundary")
    baseline = git(root, "rev-parse", "HEAD").stdout.strip()
    layout = discover_layout(root)
    add_runtime_noise(root)

    result = verify_source_revision(
        layout,
        {"system": "git", "before": baseline, "after": baseline, "material_effects": False},
        mode="transition",
        require_provider=True,
    )
    check("explicit-git-runtime-directories-do-not-create-material-drift", result["valid"])
    check("explicit-git-runtime-directories-absent-from-material-differences", not result["details"].get("material_differences"))

    (root / "unknown-output.txt").write_text("unknown\n", encoding="utf-8", newline="\n")
    result = verify_source_revision(
        layout,
        {"system": "git", "before": baseline, "after": baseline, "material_effects": False},
        mode="transition",
        require_provider=True,
    )
    check(
        "explicit-git-untracked-unclassified-path-blocked",
        not result["valid"]
        and "unclassified_project_paths_present" in result["blockers"]
        and "unknown-output.txt" in result["details"].get("unclassified_paths", []),
    )

    git(root, "add", "unknown-output.txt")
    git(root, "commit", "-m", "commit unclassified path")
    committed_unknown = git(root, "rev-parse", "HEAD").stdout.strip()
    layout = discover_layout(root)
    result = verify_source_revision(
        layout,
        {"system": "git", "before": baseline, "after": committed_unknown, "material_effects": True},
        mode="transition",
        require_provider=True,
    )
    check(
        "explicit-git-already-tracked-unclassified-path-blocked",
        not result["valid"]
        and "unclassified_project_paths_present" in result["blockers"]
        and "unknown-output.txt" in result["details"].get("unclassified_paths", []),
    )


# CHG-1050: Genesis/WebAuthn authorization assets are explicit material, not bookkeeping.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "genesis-authorization-material"
    create_project(root, CORE_ROOT, git_backed=False)
    add_genesis_authorization_surface(root)
    set_explicit_material(root, EXPLICIT_ROOTS + GENESIS_AUTHORIZATION_ROOTS)
    layout = discover_layout(root)
    check("chg1050-material-boundary-valid", not material_boundary_blockers(layout))

    for rel in GENESIS_AUTHORIZATION_ROOTS:
        check(
            "chg1050-root-material-" + rel.replace("/", "-").replace(".", "_"),
            classify_project_path(root / rel, layout) == "material",
        )

    baseline = material_snapshot(layout)
    for rel in (
        "authorization-policy.json",
        "specforge-transition-verify.py",
        "gae/gae.js",
        "tests/test_transition_contract.py",
    ):
        path = root / rel
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "changed\n", encoding="utf-8", newline="\n")
        changed = material_snapshot(layout)
        check("chg1050-material-change-affects-snapshot-" + rel.replace("/", "-").replace(".", "_"), changed["revision"] != baseline["revision"])
        path.write_text(original, encoding="utf-8", newline="\n")

    unknown = root / "unrelated-local-scratch"
    unknown.mkdir()
    (unknown / "note.txt").write_text("local only\n", encoding="utf-8", newline="\n")
    try:
        material_snapshot(layout)
        raised = False
    except MaterialBoundaryError as exc:
        raised = True
        check("chg1050-unrelated-root-remains-unclassified", "unrelated-local-scratch" in exc.paths)
    check("chg1050-unknown-root-still-fails-closed", raised)

print("Runtime material exclusion tests PASSED")


# CHG-1034: prepared project-definition evidence remains governance bookkeeping, never material.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "prepared-definition-evidence"
    create_project(root, CORE_ROOT, git_backed=False)
    prepared = root / "specforge/evidence/prepared/project-definitions/SESSION-1.md"
    prepared.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_text("prepared only\n", encoding="utf-8", newline="\n")
    snapshot = material_snapshot(discover_layout(root))
    check("prepared-project-definition-evidence-excluded-from-material", "specforge/evidence/prepared/project-definitions/SESSION-1.md" not in {e["path"] for e in snapshot["entries"]})
