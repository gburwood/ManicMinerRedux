#!/usr/bin/env python3
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile, yaml

CORE = Path(__file__).resolve().parents[1]
CORE_META = yaml.safe_load((CORE / "core.yaml").read_text(encoding="utf-8"))
TARGET_VERSION = CORE_META["core_version"]
TARGET_DATA_MODEL_VERSION = CORE_META["data_model_version"]
TARGET_DATA_MODEL_PATH = f"./specforge/core/docs/specforge-core-canonical-data-model-{TARGET_DATA_MODEL_VERSION}.md"


def run(args, cwd=None):
    env=os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"]="1"
    return subprocess.run(args,cwd=cwd,capture_output=True,text=True,env=env)
def expect(condition,message):
    if not condition: raise AssertionError(message)
def init_git(root):
    for command in (["git","init"],["git","config","user.email","specforge-tests@example.invalid"],["git","config","user.name","SpecForge Tests"],["git","add","."],["git","commit","-m","fixture"]):
        r=run(command,cwd=root); expect(r.returncode==0,f"git fixture setup failed: {command}: {r.stdout} {r.stderr}")
def write_legacy_fixture(root,core_version):
    root.joinpath("SPECFORGE.md").write_text("# Legacy entry\n",encoding="utf-8")
    root.joinpath("batty-joe-dev-spec.yaml").write_text("application:\n  name: Batty Joe Fixture\n  version: 1.5.0\n",encoding="utf-8")
    root.joinpath("specforge.yaml").write_text(f"""specforge:\n  core_version: {core_version}\n  data_model_version: 0.1.0-alpha.1\nproject:\n  id: PRJ-9000\n  name: External Migration Fixture\nspecification:\n  product_specification: ./batty-joe-dev-spec.yaml\n  canonical_data_model: ./docs/specforge-core-canonical-data-model-0.1.0-alpha.1.md\n  current_version: 1.5.0\npaths:\n  schemas: ./schemas\n  rules: ./rules\n  workflows: ./workflows\n  tools: ./tools\n  tests: ./tests\n  changes: ./changes\n  history: ./history\npolicy:\n  approval_mode: controlled\n  forensic_traceability: required\n  repository_completeness: required\n""",encoding="utf-8",newline="\n")
    (root/"changes").mkdir(); (root/"history").mkdir()
    (root/"changes"/"CHG-0007.yaml").write_text("id: CHG-0007\nstatus: blocked\n",encoding="utf-8")
    (root/"history"/"EVT-000701.yaml").write_text("id: EVT-000701\nevent_type: implementation_failed\n",encoding="utf-8")
    for key, rel in (("rules","source-of-truth.md"),("tools","specforge_project.py"),("tests","run-migration-tests.py")):
        d=root/key; d.mkdir(); (d/rel).write_text(f"legacy framework {key}\n",encoding="utf-8")
    (root/"tests"/"batty-project-test.txt").write_text("keep me\n",encoding="utf-8")
    (root/"tools"/"batty-project-helper.py").write_text("# keep me\n",encoding="utf-8")
    for key in ("schemas","workflows"):
        (root/key).mkdir()
        candidate_dir=CORE/key
        candidate_file=next((p for p in candidate_dir.rglob("*") if p.is_file()),None)
        if candidate_file:
            rel=candidate_file.relative_to(candidate_dir); dst=root/key/rel; dst.parent.mkdir(parents=True,exist_ok=True); dst.write_text("legacy framework\n",encoding="utf-8")
    (root/"docs").mkdir(); (root/"docs"/"specforge-core-canonical-data-model-0.1.0-alpha.1.md").write_text("legacy model\n",encoding="utf-8")
    init_git(root)
def stage_distribution(root):
    dist=root/"specforge-dist"/TARGET_VERSION/"core"
    shutil.copytree(CORE,dist,ignore=shutil.ignore_patterns("__pycache__","*.pyc","*.pyo"))
    return dist
def migrate_fixture(core_version):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); write_legacy_fixture(root,core_version)
        change_before=(root/"changes"/"CHG-0007.yaml").read_bytes(); product_before=(root/"batty-joe-dev-spec.yaml").read_bytes()
        project_test=(root/"tests"/"batty-project-test.txt").read_bytes(); project_helper=(root/"tools"/"batty-project-helper.py").read_bytes()
        dist=stage_distribution(root); tool=dist/"tools"/"specforge-migrate.py"
        r=run([sys.executable,"-B",str(tool),"plan","--root",str(root),"--json"])
        expect(r.returncode==0,f"plan failed for {core_version}: {r.stdout} {r.stderr}")
        plan=json.loads(r.stdout)
        expect(plan["source"]["layout"]=="legacy_root",f"staged distribution impersonated project: {plan}")
        expect(plan["source"]["core_version"]==core_version,f"wrong legacy version detected: {plan}")
        expect(plan["candidate_distribution"]["version"]==TARGET_VERSION,f"wrong candidate version: {plan}")
        expect(plan["path"],f"migration path missing: {plan}")
        r=run([sys.executable,"-B",str(tool),"migrate","--root",str(root),"--apply","--json"])
        expect(r.returncode==0,f"migration failed for {core_version}: {r.stdout} {r.stderr}")
        result=json.loads(r.stdout); expect(result.get("migrated") is True,f"migration did not reach target: {result}")
        expect((root/"specforge"/"project.yaml").is_file(),"new project manifest missing")
        expect((root/"specforge"/"core"/"core.yaml").is_file(),"candidate Core not installed")
        expect((root/"specforge"/"changes"/"CHG-0007.yaml").read_bytes()==change_before,"CHG-0007 changed")
        expect((root/"batty-joe-dev-spec.yaml").read_bytes()==product_before,"governed product spec changed")
        manifest=(root/"specforge"/"project.yaml").read_text(encoding="utf-8")
        expect("./batty-joe-dev-spec.yaml" in manifest,"product specification authority not preserved")
        expect(TARGET_VERSION in manifest,"target Core version not installed")
        expect(TARGET_DATA_MODEL_PATH in manifest,"canonical data model was not rebound to installed Core")
        expect(not (root/"specforge.yaml").exists(),"legacy manifest still authoritative")
        expect(not (root/"rules"/"source-of-truth.md").exists(),"known legacy framework rule survived")
        expect(not (root/"tools"/"specforge_project.py").exists(),"known legacy framework tool survived")
        expect(not (root/"tests"/"run-migration-tests.py").exists(),"known legacy framework test survived")
        expect(not (root/"docs").exists(),"legacy canonical-model docs directory survived")
        expect((root/"tests"/"batty-project-test.txt").read_bytes()==project_test,"project-owned test was removed")
        expect((root/"tools"/"batty-project-helper.py").read_bytes()==project_helper,"project-owned tool was removed")
        evidence=(root/"specforge"/"evidence"/"migrations"/"legacy-root-v1"/"migration-result.yaml").read_text(encoding="utf-8")
        expect("retired_framework_artifacts" in evidence,"framework retirement evidence missing")
        shutil.rmtree(root/"specforge-dist")
        installed_tool=root/"specforge"/"core"/"tools"/"specforge-migrate.py"
        r=run([sys.executable,"-B",str(installed_tool),"plan","--root",str(root),"--json"])
        expect(r.returncode==0,f"post-migration plan failed without staging dir: {r.stdout} {r.stderr}")
        expect(json.loads(r.stdout).get("already_current") is True,"post-migration project not current")
def ambiguous_source_fixture():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); write_legacy_fixture(root,"0.1.0-alpha.3"); dist=stage_distribution(root)
        (root/"specforge").mkdir(); (root/"specforge"/"project.yaml").write_text("specforge:\n  project_format: 1\n  core_version: bogus\n",encoding="utf-8")
        tool=dist/"tools"/"specforge-migrate.py"; r=run([sys.executable,"-B",str(tool),"plan","--root",str(root),"--json"])
        expect(r.returncode!=0,"ambiguous project authority unexpectedly permitted")
        expect("source_authority_ambiguous" in json.loads(r.stdout).get("blockers",[]),f"wrong ambiguous blocker: {r.stdout}")
def unsupported_fixture():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); write_legacy_fixture(root,"0.0.0-unknown"); before=(root/"specforge.yaml").read_bytes(); dist=stage_distribution(root); tool=dist/"tools"/"specforge-migrate.py"
        r=run([sys.executable,"-B",str(tool),"plan","--root",str(root),"--json"])
        expect(r.returncode!=0,"unsupported source unexpectedly permitted")
        expect("supported_migration_path_missing" in json.loads(r.stdout).get("blockers",[]),f"wrong blocker: {r.stdout}")
        expect((root/"specforge.yaml").read_bytes()==before,"planning mutated source")
def main():
    migrate_fixture("0.1.0-alpha.4")
    migrate_fixture("0.1.0-alpha.3")
    ambiguous_source_fixture()
    unsupported_fixture()
    print("Migration tests PASSED")
    return 0

if __name__=="__main__": raise SystemExit(main())

# CHG-1049 reconciliation compatibility contract
_contract_core=Path(__file__).resolve().parents[1]
_source=(_contract_core/"tools"/"specforge-migrate.py").read_text(encoding="utf-8")
assert 'context_only' in _source
assert 'durable_update' in _source
