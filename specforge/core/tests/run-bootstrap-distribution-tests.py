#!/usr/bin/env python3
"""External-style regression for Candidate A distribution/bootstrap identity."""
from pathlib import Path
import json, shutil, subprocess, sys, tempfile, yaml

CORE = Path(__file__).resolve().parents[1]
REPO = CORE.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_fixture import create_project, install_controlled_change, install_pack_copy, git, write_yaml

EXPECTED_CORE = "0.1.0-beta.1"
EXPECTED_MODEL = "0.1.0-alpha.10"

def run_json(tool, *args, expect=0):
    result = subprocess.run([sys.executable, "-B", str(tool), *map(str,args)], capture_output=True, text=True)
    if result.returncode != expect:
        raise AssertionError(f"{tool.name} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout)

def assert_identity(root):
    manifest = yaml.safe_load((root/"specforge/project.yaml").read_text(encoding="utf-8"))
    core = yaml.safe_load((root/"specforge/core/core.yaml").read_text(encoding="utf-8"))
    package = yaml.safe_load((root/"specforge/core/package.yaml").read_text(encoding="utf-8"))
    assert core["core_version"] == EXPECTED_CORE
    assert core["data_model_version"] == EXPECTED_MODEL
    assert package["package"]["version"] == EXPECTED_CORE
    assert manifest["specforge"]["core_version"] == EXPECTED_CORE
    assert manifest["specforge"]["data_model_version"] == EXPECTED_MODEL
    assert (core.get("managed_progress") or {}).get("profile") == "managed_progress_v1"
    assert (core.get("integrity") or {}).get("routine_profile") == "incremental_integrity_v1"

with tempfile.TemporaryDirectory(prefix="specforge-bootstrap-dist-") as td:
    base = Path(td)

    # Managed bootstrap must fail closed before fresh alpha.25 tier initialization.
    missing = base/"missing-fresh-tier"
    create_project(missing, CORE, git_backed=True)
    missing_tools = missing/"specforge/core/tools"
    blocked = run_json(missing_tools/"specforge-managed.py", "bootstrap", "--root", missing, "--json", expect=1)
    assert blocked["managed_state"] == "blocked"
    assert "governance_tier_not_initialized" in blocked["manager"]["governance_blockers"]

    partial = base/"partial-fresh-tier"
    create_project(partial, CORE, git_backed=True)
    partial_manifest_path = partial/"specforge/project.yaml"
    partial_manifest = yaml.safe_load(partial_manifest_path.read_text(encoding="utf-8"))
    partial_manifest["governance_tier"] = {"enforcement_profile": "deterministic_tier_v1"}
    write_yaml(partial_manifest_path, partial_manifest)
    partial_tools = partial/"specforge/core/tools"
    corrupt = run_json(partial_tools/"specforge-managed.py", "bootstrap", "--root", partial, "--json", expect=1)
    assert corrupt["managed_state"] == "blocked"
    assert "governance_tier_activation_state_corrupted" in corrupt["manager"]["governance_blockers"]

    project = base/"school-project-shaped"
    create_project(project, CORE, git_backed=True, initialize_governance_tier=True)
    assert_identity(project)
    fresh_tier = yaml.safe_load((project/"specforge/evidence/governance-tier-grandfather.yaml").read_text(encoding="utf-8"))
    assert fresh_tier["provenance"] == "fresh_project_bootstrap_v1"
    assert fresh_tier["proposal_digests"] == []

    integrity_tool = project/"specforge/core/tools/specforge-integrity.py"
    missing_integrity = run_json(integrity_tool, "status", "--root", project, "--json", expect=1)
    assert missing_integrity["deep_audit_required"] is True
    integrity_state = project/"specforge/evidence/integrity/state.json"
    initial_integrity = run_json(
        integrity_tool, "full", "--root", project,
        "--state-output", integrity_state, "--progress-file", "-", "--json"
    )
    assert initial_integrity["ok"] and initial_integrity["mode"] == "full_integrity_v1"
    git(project, "add", "specforge/evidence/integrity/state.json")
    git(project, "commit", "-m", "Record initial integrity receipt")
    current_integrity = run_json(integrity_tool, "status", "--root", project, "--json")
    assert current_integrity["ok"] and current_integrity["deep_audit_required"] is False

    installed_tools = project/"specforge/core/tools"
    boot = run_json(installed_tools/"specforge-lifecycle.py", "bootstrap", "--root", project, "--json")
    assert boot["ready"], boot

    lite_research = REPO/"packs/lite-research"
    if lite_research.is_dir():
        install_pack_copy(project, lite_research, precedence=10)
        git(project, "add", "specforge/project.yaml", "specforge/packs/lite-research")
        git(project, "commit", "-m", "activate lite-research fixture")
        assert_identity(project)
        pack = run_json(installed_tools/"specforge-pack.py", "--root", project, "--json")
        assert pack["permitted"], pack
        assert any(item["id"] == "lite-research" and str(item["version"]) == "0.1.0" for item in pack["packs"])

    managed = run_json(
        installed_tools/"specforge-managed.py",
        "begin", "--root", project, "--session", "SESSION-ALPHA25", "--request", "Bootstrap distribution managed request", "--json"
    )
    assert managed["started"] is True
    assert managed["completion_guard"]["enabled"] is True
    assert managed["completion_guard"]["version"] == 3
    assert (project/managed["completion_guard"]["record"]).is_file()
    help_text = subprocess.run(
        [sys.executable, "-B", str(installed_tools/"specforge-managed.py"), "--help"],
        capture_output=True, text=True
    ).stdout
    assert "finish" in help_text and "close" in help_text
    assert "capabilities" in help_text

    missing_capability = subprocess.run(
        [sys.executable, "-B", str(installed_tools/"specforge-managed.py"),
         "capabilities", "--root", str(project), "--require", "workflow_dispatch", "--json"],
        capture_output=True, text=True
    )
    assert missing_capability.returncode == 1
    missing_capability_out = json.loads(missing_capability.stdout)
    assert missing_capability_out["permitted"] is False
    assert missing_capability_out["capabilities"]["workflow_dispatch"] is False
    assert "execution_channel_capability_unavailable:workflow_dispatch" in missing_capability_out["blockers"]

    available_capability = subprocess.run(
        [sys.executable, "-B", str(installed_tools/"specforge-managed.py"),
         "capabilities", "--root", str(project), "--require", "workflow_dispatch",
         "--available", "workflow_dispatch", "--json"],
        capture_output=True, text=True
    )
    assert available_capability.returncode == 0
    available_capability_out = json.loads(available_capability.stdout)
    assert available_capability_out["permitted"] is True
    assert available_capability_out["capabilities"]["workflow_dispatch"] is True

    # Fresh alpha.25 state can prepare and present controlled_v3 work immediately.
    run_json(
        installed_tools/"specforge-managed.py", "define", "--root", project,
        "--purpose", "Exercise fresh alpha.25 managed work.", "--json"
    )
    ids = install_controlled_change(
        project, "CHG-9009", status="awaiting_approval", skip_approval=True,
        lifecycle_enforcement="controlled_v3",
        declared_scope=[{"operation": "modify", "path": "PROJECT.md"}],
        governance_tier={"requested": "HIGH"},
    )
    prepared_tier = run_json(
        installed_tools/"specforge-governance-tier.py", "prepare", ids["proposal"],
        "--root", project, "--json"
    )
    assert prepared_tier["prepared"], prepared_tier
    prepared_definition = run_json(
        installed_tools/"specforge-managed.py", "prepare-definition", "--root", project,
        "--session", "SESSION-ALPHA25", "--change", ids["change"],
        "--summary", "Exercise fresh alpha.25 managed work.", "--json"
    )
    proposal = yaml.safe_load(ids["proposal_path"].read_text(encoding="utf-8"))
    proposal["project_definition_reconciliation"] = prepared_definition["proposal_binding"]
    write_yaml(ids["proposal_path"], proposal)
    presented = run_json(
        installed_tools/"specforge-managed.py", "present", "--root", project,
        "--proposal", ids["proposal"], "--change", ids["change"], "--session", "SESSION-ALPHA25",
        "--summary", "Exercise fresh alpha.25 managed work.", "--json"
    )
    assert presented["presented"], presented

    # CHG-1049: context_only binds durable definition without implementation scope or mutation.
    session2 = run_json(
        installed_tools/"specforge-managed.py", "begin", "--root", project,
        "--session", "SESSION-CONTEXT-ONLY", "--request", "Context-only reconciliation request", "--json"
    )
    assert session2["started"] is True
    before_definition = (project/"PROJECT.md").read_bytes()
    ids2 = install_controlled_change(
        project, "CHG-9010", status="awaiting_approval", skip_approval=True,
        lifecycle_enforcement="controlled_v3",
        declared_scope=[{"operation": "modify", "path": "README.md"}],
        governance_tier={"requested": "HIGH"},
    )
    prepared_tier2 = run_json(
        installed_tools/"specforge-governance-tier.py", "prepare", ids2["proposal"],
        "--root", project, "--json"
    )
    assert prepared_tier2["prepared"], prepared_tier2
    prepared_context = run_json(
        installed_tools/"specforge-managed.py", "prepare-definition", "--root", project,
        "--session", "SESSION-CONTEXT-ONLY", "--change", ids2["change"],
        "--summary", "Context-only reconciliation request", "--mode", "context_only", "--json"
    )
    assert prepared_context["mode"] == "context_only"
    assert prepared_context["project_definition_changed"] is False
    proposal2 = yaml.safe_load(ids2["proposal_path"].read_text(encoding="utf-8"))
    proposal2["proposed_specification_version"] = "0.1.0-alpha.26"
    proposal2["project_definition_reconciliation"] = prepared_context["proposal_binding"]
    write_yaml(ids2["proposal_path"], proposal2)
    presented2 = run_json(
        installed_tools/"specforge-managed.py", "present", "--root", project,
        "--proposal", ids2["proposal"], "--change", ids2["change"], "--session", "SESSION-CONTEXT-ONLY",
        "--summary", "Context-only reconciliation request", "--json"
    )
    assert presented2["presented"], presented2
    assert (project/"PROJECT.md").read_bytes() == before_definition

    stale = base/"stale-core"
    shutil.copytree(CORE, stale)
    stale_core = yaml.safe_load((stale/"core.yaml").read_text(encoding="utf-8"))
    stale_pkg = yaml.safe_load((stale/"package.yaml").read_text(encoding="utf-8"))
    stale_core["core_version"] = "0.1.0-alpha.17"
    stale_core["data_model_version"] = "0.1.0-alpha.6"
    stale_pkg["package"]["version"] = "0.1.0-alpha.17"
    write_yaml(stale/"core.yaml", stale_core)
    write_yaml(stale/"package.yaml", stale_pkg)
    assert stale_core["core_version"] != EXPECTED_CORE
    assert stale_core["data_model_version"] != EXPECTED_MODEL

print("Bootstrap distribution tests PASSED")

assert (CORE / 'schemas/prospective-finalisation-authority.schema.json').is_file()
assert (CORE / 'schemas/checkpoint-acceptance-proof.schema.json').is_file()
assert (CORE / 'docs/specforge-core-product-spec-0.1.0-alpha.25.md').is_file()
assert (CORE / 'docs/specforge-core-canonical-data-model-0.1.0-alpha.10.md').is_file()

with tempfile.TemporaryDirectory(prefix='specforge-fresh-clone-shape-') as td:
    root=Path(td)/'repo'
    create_project(root,CORE,git_backed=True,initialize_governance_tier=True)
    for rel in ('specforge/changes','specforge/decisions'):
        path=root/rel
        if path.exists(): shutil.rmtree(path)
    tools=root/'specforge/core/tools'
    boot=run_json(tools/'specforge-lifecycle.py','bootstrap','--root',root,'--json')
    assert boot['ready'],boot
    managed=run_json(tools/'specforge-managed.py','bootstrap','--root',root,'--json')
    assert managed['managed_state'] in ('ready_for_work','needs_project_definition'),managed
print('PASS fresh-clone-absent-optional-directories')
