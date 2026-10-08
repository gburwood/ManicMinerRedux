#!/usr/bin/env python3
"""Plan and execute deterministic SpecForge project-format migrations from a candidate distribution."""
from pathlib import Path
import argparse, copy, json, shutil, subprocess
import yaml

from specforge_project import load_yaml
from specforge_distribution import discover_distribution

TARGET_PROJECT_FORMAT = 1
PROJECT_DIRS = ("changes", "history")
STAGING_ROOTS = ("specforge-dist/",)
RECONCILIATION_COMPATIBILITY={"absent_mode":"historical_durable_update","supported_modes":["context_only","durable_update"],"new_proposals_require_mode_from":"0.1.0-alpha.26"}


def git_clean(root):
    try:
        r = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True)
        if r.returncode != 0: return False
        for line in r.stdout.splitlines():
            path = line[3:].strip().replace("\\", "/") if len(line) > 3 else ""
            if " -> " in path: path = path.split(" -> ", 1)[1]
            if any(path.startswith(prefix) for prefix in STAGING_ROOTS): continue
            return False
        return True
    except Exception: return False


def load_registry(distribution):
    data = load_yaml(distribution.migration_registry)
    if not isinstance(data, dict): raise ValueError("migration_registry_invalid")
    return data


def detect_source(root):
    format_manifest=root/"specforge"/"project.yaml"; legacy_manifest=root/"specforge.yaml"
    if format_manifest.is_file() and legacy_manifest.is_file(): return {"layout":"ambiguous","project_format":None,"core_version":None,"authorities":["specforge/project.yaml","specforge.yaml"]}
    if format_manifest.is_file():
        data=load_yaml(format_manifest); sf=(data.get("specforge") or {}) if isinstance(data,dict) else {}
        return {"layout":"project_format","project_format":sf.get("project_format"),"core_version":sf.get("core_version"),"authority":"specforge/project.yaml"}
    if legacy_manifest.is_file():
        data=load_yaml(legacy_manifest); sf=(data.get("specforge") or {}) if isinstance(data,dict) else {}
        return {"layout":"legacy_root","project_format":None,"core_version":sf.get("core_version"),"authority":"specforge.yaml"}
    return {"layout":"unknown","project_format":None,"core_version":None}


def source_key(source): return ("project_format",source.get("project_format")) if source.get("layout")=="project_format" else (source.get("layout"),source.get("core_version"))
def step_source_key(step):
    src=step.get("source") or {}; return ("project_format",src.get("project_format")) if "project_format" in src else (src.get("layout"),src.get("core_version"))
def step_target_key(step):
    target=step.get("target") or {}; return ("project_format",target.get("project_format")) if "project_format" in target else (target.get("layout"),target.get("core_version"))


def plan(root,target_format=TARGET_PROJECT_FORMAT,distribution_path=None):
    source=detect_source(root); target_key=("project_format",target_format); base={"source":source,"target_project_format":target_format,"path":[],"reconciliation_compatibility":RECONCILIATION_COMPATIBILITY,"blockers":[]}
    if source.get("layout")=="ambiguous": return {**base,"permitted":False,"blockers":["source_authority_ambiguous"]}
    if source.get("layout")=="unknown": return {**base,"permitted":False,"blockers":["source_format_unknown"]}
    try: distribution=discover_distribution(Path(distribution_path) if distribution_path else None,tool_file=Path(__file__))
    except Exception as exc: return {**base,"permitted":False,"blockers":[str(exc)]}
    base["candidate_distribution"]={"version":distribution.version,"package":str(distribution.package_path),"core":str(distribution.core_root)}
    if target_format not in distribution.project_formats: return {**base,"permitted":False,"blockers":["target_distribution_incompatible_with_project_format"]}
    if source_key(source)==target_key: return {**base,"permitted":True,"already_current":True}
    try: steps=load_registry(distribution).get("steps") or []
    except Exception as exc: return {**base,"permitted":False,"blockers":[str(exc)]}
    frontier=[(source_key(source),[])]; solutions=[]; best_depth=None
    while frontier:
        current,path=frontier.pop(0)
        if best_depth is not None and len(path)>best_depth: continue
        if current==target_key:
            best_depth=len(path) if best_depth is None else best_depth; solutions.append(path); continue
        used={step_source_key(s) for s in path}|{source_key(source)}
        for step in steps:
            if step_source_key(step)!=current: continue
            nxt=step_target_key(step)
            if nxt in used: continue
            frontier.append((nxt,path+[step]))
    if not solutions: return {**base,"permitted":False,"available_steps":[s.get("id") for s in steps],"blockers":["supported_migration_path_missing"]}
    shortest=min(len(x) for x in solutions); candidates=[x for x in solutions if len(x)==shortest]
    if len(candidates)!=1: return {**base,"permitted":False,"blockers":["migration_path_ambiguous"]}
    chosen=candidates[0]; return {**base,"permitted":True,"already_current":False,"path":[s.get("id") for s in chosen],"steps":chosen}


def _same_file(a,b):
    try: return Path(a).samefile(Path(b))
    except (OSError,ValueError): return Path(a).resolve()==Path(b).resolve()


def _relative_to_root(path,root):
    """Return a root-relative path even when Windows presents equivalent long/8.3 aliases."""
    path=Path(path).resolve(); root=Path(root).resolve()
    try: return path.relative_to(root)
    except ValueError:
        current=path; parts=[]
        while True:
            if _same_file(current,root): return Path(*reversed(parts))
            parent=current.parent
            if parent==current: break
            parts.append(current.name); current=parent
        raise RuntimeError(f"legacy_framework_path_outside_project:{path}")


def _safe_root_path(root,value):
    p=(root/value).resolve(); _relative_to_root(p,root); return p


def _canonical_model_replacement(legacy_spec,distribution,config):
    authority=legacy_spec.get("canonical_data_model")
    if not config.get("rebind_canonical_data_model") or not authority: return None
    name=Path(authority).name
    if not (name.startswith("specforge-core-canonical-data-model-") and name.endswith(".md")): return None
    version=distribution.core.get("data_model_version")
    if not version: return None
    rel=Path("docs")/f"specforge-core-canonical-data-model-{version}.md"
    if not (distribution.core_root/rel).is_file(): return None
    return "./specforge/core/"+str(rel).replace("\\","/")


def new_manifest(legacy,distribution,step=None):
    project=legacy.get("project") or {}; policy=legacy.get("policy") or {}; legacy_spec=copy.deepcopy(legacy.get("specification") or {}); core=distribution.core; cleanup=(step or {}).get("legacy_framework") or {}
    replacement=_canonical_model_replacement(legacy_spec,distribution,cleanup)
    if replacement: legacy_spec["canonical_data_model"]=replacement
    data={"specforge":{"project_format":1,"core_version":distribution.version,"data_model_version":core.get("data_model_version")},"project":{"id":project.get("id"),"name":project.get("name")},"specification":legacy_spec,"paths":{"core":"./specforge/core","packs":"./specforge/packs","schemas":"./specforge/core/schemas","rules":"./specforge/core/rules","workflows":"./specforge/core/workflows","tools":"./specforge/core/tools","tests":"./specforge/core/tests","examples":"./specforge/core/examples","changes":"./specforge/changes","decisions":"./specforge/decisions","history":"./specforge/history","evidence":"./specforge/evidence"},"packs":[],"ownership":{"framework_owned":["./specforge/core","./specforge/packs"],"project_owned":["./specforge/project.yaml","./specforge/changes","./specforge/decisions","./specforge/history","./specforge/evidence"]},"policy":policy}
    return yaml.safe_dump(data,sort_keys=False,allow_unicode=True)


def entry_point():
    return """# SpecForge Project Entry Point\n\nThis repository uses SpecForge project format 1.\n\nA fresh human or AI session MUST:\n1. Read `specforge/project.yaml`.\n2. Resolve project-format and Core versions.\n3. Load Core rules, schemas, workflows and tooling through manifest paths.\n4. Resolve installed packs and precedence.\n5. Locate authoritative product specification and canonical data model.\n6. Inspect every non-terminal change and current proposal, approvals and implementation evidence.\n7. Inspect relevant decisions and forensic history.\n8. Run bootstrap/status before governed mutation.\n9. Treat repository state, never prior chat or AI memory, as continuation authority.\n10. Request lifecycle transitions through SpecForge tooling.\n\nFramework-owned material is beneath `specforge/core/` and `specforge/packs/`. Project-owned governance state is beneath `specforge/changes/`, `specforge/decisions/`, `specforge/history/` and `specforge/evidence/`. Candidate distributions such as `specforge-dist/` are upgrade inputs, never installed project authority.\n"""


def target_entries(target):
    if not target.exists(): return []
    return sorted(str(p.relative_to(target)).replace("\\","/") for p in target.rglob("*") if p.is_file() or p.is_symlink())


def _prune_empty(path,root):
    current=Path(path); root=Path(root)
    while current.exists() and current.is_dir() and not _same_file(current,root):
        try: current.rmdir()
        except OSError: break
        current=current.parent


def retire_legacy_framework(root,legacy,distribution,step,evidence_root):
    """Retire only framework files whose ownership can be positively established."""
    config=(step or {}).get("legacy_framework") or {}; paths=legacy.get("paths") or {}; retired=[]; preserved=[]; backup=evidence_root/"retired-framework"; backup.mkdir(parents=True,exist_ok=True)
    for key in config.get("manifest_path_keys") or []:
        value=paths.get(key)
        if not value: continue
        source_dir=_safe_root_path(root,value)
        if not source_dir.exists() or not source_dir.is_dir(): continue
        target_dir=distribution.core_root/key
        for src in sorted(p for p in source_dir.rglob("*") if p.is_file()):
            rel=src.relative_to(source_dir); counterpart=target_dir/rel
            relroot=_relative_to_root(src,root)
            if counterpart.is_file():
                dst=backup/relroot; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst); src.unlink(); retired.append(str(relroot).replace("\\","/")); _prune_empty(src.parent,root)
            else: preserved.append(str(relroot).replace("\\","/"))
    legacy_spec=legacy.get("specification") or {}; replacement=_canonical_model_replacement(legacy_spec,distribution,config)
    authority=legacy_spec.get("canonical_data_model")
    if replacement and authority:
        src=_safe_root_path(root,authority)
        if src.is_file():
            relroot=_relative_to_root(src,root); dst=backup/relroot; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst); src.unlink(); retired.append(str(relroot).replace("\\","/")); _prune_empty(src.parent,root)
    return retired,preserved


def restore_retired_framework(root,evidence_root,retired):
    backup=evidence_root/"retired-framework"
    for rel in retired:
        src=backup/rel; dst=root/rel
        if src.is_file(): dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)


def write_migration_evidence(target,source,executed,distribution,retired=None,preserved=None):
    evidence=target/"evidence"/"migrations"/"legacy-root-v1"/"migration-result.yaml"
    payload={"operation":"project_format_migration","source":source,"candidate_distribution":{"version":distribution.version,"package":str(distribution.package_path)},"target":{"project_format":1,"core_version":distribution.version},"executed_steps":executed,"result":"migrated","preserved_identity_contract":True,"reconciliation_compatibility":RECONCILIATION_COMPATIBILITY,"retired_framework_artifacts":retired or [],"preserved_legacy_files":preserved or []}
    evidence.write_text(yaml.safe_dump(payload,sort_keys=False,allow_unicode=True),encoding="utf-8",newline="\n")


def apply_legacy(root,distribution,step=None):
    old_manifest=root/"specforge.yaml"; old_entry=root/"SPECFORGE.md"; legacy=load_yaml(old_manifest); sf=legacy.get("specforge") or {}; source={"layout":"legacy_root","project_format":None,"core_version":sf.get("core_version"),"authority":"specforge.yaml"}; target=root/"specforge"; occupied=target_entries(target)
    if occupied: raise RuntimeError("target_specforge_directory_not_empty:"+",".join(occupied[:20]))
    moved=[]; retired=[]; evidence_root=target/"evidence"/"migrations"/"legacy-root-v1"
    try:
        core=target/"core"; target.mkdir(parents=True,exist_ok=True)
        for name in PROJECT_DIRS:
            src=root/name; dst=target/name
            if src.exists(): shutil.move(str(src),str(dst)); moved.append((dst,src))
            else: dst.mkdir(parents=True)
        for name in ("decisions","evidence","packs"): (target/name).mkdir(parents=True,exist_ok=True)
        evidence_root.mkdir(parents=True); shutil.copy2(old_manifest,evidence_root/"specforge.yaml.before.yaml")
        if old_entry.is_file(): shutil.copy2(old_entry,evidence_root/"SPECFORGE.before.md")
        shutil.copytree(distribution.core_root,core,ignore=shutil.ignore_patterns("__pycache__","*.pyc","*.pyo"))
        retired,preserved=retire_legacy_framework(root,legacy,distribution,step or {},evidence_root)
        (target/"project.yaml").write_text(new_manifest(legacy,distribution,step),encoding="utf-8",newline="\n"); (target/"SPECFORGE.md").write_text(entry_point(),encoding="utf-8",newline="\n")
        write_migration_evidence(target,source,[(step or {}).get("id")] if (step or {}).get("id") else [],distribution,retired,preserved); old_manifest.unlink()
        if old_entry.exists(): old_entry.unlink()
    except Exception:
        restore_retired_framework(root,evidence_root,retired)
        for dst,src in reversed(moved):
            if dst.exists() and not src.exists(): shutil.move(str(dst),str(src))
        if target.exists(): shutil.rmtree(target)
        raise


def migrate(root,target_format,apply,distribution_path=None):
    p=plan(root,target_format,distribution_path)
    if not p.get("permitted") or p.get("already_current"): return p
    if not apply: p["apply_required"]=True; return p
    if not git_clean(root): p["permitted"]=False; p["blockers"]=["working_tree_not_clean"]; return p
    distribution=discover_distribution(Path(distribution_path) if distribution_path else None,tool_file=Path(__file__)); executed=[]
    try:
        for step in p.get("steps") or []:
            if step.get("handler")!="legacy_root_to_format1": return {"permitted":False,"blockers":[f"migration_handler_missing:{step.get('handler')}"]}
            apply_legacy(root,distribution,step); executed.append(step.get("id"))
    except Exception as exc: p["permitted"]=False; p["blockers"]=[str(exc)]; p["executed"]=executed; return p
    result=plan(root,target_format,distribution_path); result["executed"]=executed; result["migrated"]=bool(result.get("already_current")); return result


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=("plan","migrate")); ap.add_argument("--root",default="."); ap.add_argument("--to",type=int,default=1,dest="target_format"); ap.add_argument("--distribution"); ap.add_argument("--apply",action="store_true"); ap.add_argument("--json",action="store_true")
    a=ap.parse_args(); root=Path(a.root).resolve(); out=plan(root,a.target_format,a.distribution) if a.command=="plan" else migrate(root,a.target_format,a.apply,a.distribution); print(json.dumps(out,indent=2) if a.json else out); return 0 if out.get("permitted") else 1

if __name__=="__main__": raise SystemExit(main())
