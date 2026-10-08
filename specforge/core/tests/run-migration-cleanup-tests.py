#!/usr/bin/env python3
from pathlib import Path
import importlib.util, shutil, sys, tempfile

CORE=Path(__file__).resolve().parents[1]


def expect(condition,message):
    if not condition: raise AssertionError(message)


def load_migrator(tool):
    sys.path.insert(0,str(tool.parent))
    spec=importlib.util.spec_from_file_location("specforge_migrate_cleanup_test",tool)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def write_fixture(root):
    (root/"SPECFORGE.md").write_text("# legacy\n",encoding="utf-8")
    (root/"specforge.yaml").write_text("""specforge:\n  core_version: 0.1.0-alpha.3\n  data_model_version: 0.1.0-alpha.1\nproject:\n  id: PRJ-ROLLBACK\n  name: Cleanup Rollback Fixture\nspecification:\n  product_specification: ./product.yaml\n  canonical_data_model: ./docs/specforge-core-canonical-data-model-0.1.0-alpha.1.md\npaths:\n  rules: ./rules\n  changes: ./changes\n  history: ./history\npolicy:\n  approval_mode: controlled\n""",encoding="utf-8",newline="\n")
    (root/"product.yaml").write_text("name: product\n",encoding="utf-8")
    (root/"rules").mkdir(); (root/"rules"/"source-of-truth.md").write_text("legacy framework rule\n",encoding="utf-8"); (root/"rules"/"project-note.md").write_text("project owned\n",encoding="utf-8")
    (root/"docs").mkdir(); (root/"docs"/"specforge-core-canonical-data-model-0.1.0-alpha.1.md").write_text("legacy model\n",encoding="utf-8")
    (root/"changes").mkdir(); (root/"changes"/"CHG-0001.yaml").write_text("id: CHG-0001\nstatus: completed\n",encoding="utf-8")
    (root/"history").mkdir(); (root/"history"/"EVT-000001.yaml").write_text("id: EVT-000001\nevent_type: change_completed\n",encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/"repo"; root.mkdir(); write_fixture(root)
        before={p.relative_to(root):p.read_bytes() for p in root.rglob("*") if p.is_file()}
        dist_core=root/"specforge-dist"/"0.1.0-alpha.8"/"core"; shutil.copytree(CORE,dist_core,ignore=shutil.ignore_patterns("__pycache__","*.pyc","*.pyo"))
        migrator=load_migrator(dist_core/"tools"/"specforge-migrate.py")
        distribution=migrator.discover_distribution(tool_file=dist_core/"tools"/"specforge-migrate.py")
        step=next(s for s in migrator.load_registry(distribution)["steps"] if s["id"]=="MIG-legacy-alpha3-to-format1")
        original=migrator.write_migration_evidence
        def fail_after_cleanup(*args,**kwargs): raise RuntimeError("forced_post_cleanup_failure")
        migrator.write_migration_evidence=fail_after_cleanup
        try:
            try: migrator.apply_legacy(root,distribution,step)
            except RuntimeError as exc: expect("forced_post_cleanup_failure" in str(exc),f"unexpected failure: {exc}")
            else: raise AssertionError("forced migration failure did not occur")
        finally: migrator.write_migration_evidence=original
        expect(not (root/"specforge").exists(),"incomplete target survived rollback")
        for rel,data in before.items(): expect((root/rel).is_file() and (root/rel).read_bytes()==data,f"rollback did not restore {rel}")
        expect((root/"rules"/"project-note.md").read_text(encoding="utf-8")=="project owned\n","project-owned mixed-directory file changed")
    print("Migration cleanup tests PASSED")
    return 0

if __name__=="__main__": raise SystemExit(main())
