#!/usr/bin/env python3
"""Plan or apply ownership-aware Core upgrades from a candidate SpecForge distribution."""
from pathlib import Path
import argparse, json, shutil, subprocess, tempfile
import yaml

from specforge_project import (
    CANONICAL_DATA_MODEL_DOC_RE,
    CANONICAL_DATA_MODEL_DOC_TEMPLATE,
    PRODUCT_SPEC_DOC_RE,
    PRODUCT_SPEC_DOC_TEMPLATE,
    configured_path,
    discover_layout,
    manifest_core_consistency_blockers,
    relative,
    self_referencing_core_doc_version,
)
from specforge_distribution import discover_distribution
from specforge_upgrade_authority import establish_upgrade_authority
from specforge_authority import authority_path

STAGING_ROOTS=("specforge-dist/",)
RECONCILIATION_COMPATIBILITY={"absent_mode":"historical_durable_update","supported_modes":["context_only","durable_update"],"new_proposals_require_mode_from":"0.1.0-alpha.26"}


def clean(root):
    try:
        r=subprocess.run(["git","-C",str(root),"status","--porcelain","--untracked-files=all"],capture_output=True,text=True)
    except FileNotFoundError:
        return True
    if r.returncode!=0:
        return True
    for line in r.stdout.splitlines():
        path=line[3:].strip().replace("\\","/") if len(line)>3 else ""
        if " -> " in path: path=path.split(" -> ",1)[1]
        if any(path.startswith(prefix) for prefix in STAGING_ROOTS): continue
        return False
    return True


def _format_consistency_blocker(blocker):
    code=blocker["code"]
    if code=="core_version_inconsistent":
        return f"source_core_version_inconsistent:declared={blocker['declared_core_version']}:installed={blocker['installed_core_version']}"
    if code=="data_model_version_inconsistent":
        return f"source_data_model_version_inconsistent:declared={blocker['declared_data_model_version']}:installed={blocker['installed_data_model_version']}"
    if code=="package_core_version_inconsistent":
        return f"source_package_version_inconsistent:package={blocker['package_version']}:core={blocker['installed_core_version']}"
    if code=="self_referencing_product_specification_inconsistent":
        return (f"source_self_referencing_product_specification_inconsistent:embedded={blocker['embedded_version']}:"
                f"core_version={blocker['declared_core_version']}:current_version={blocker['declared_current_version']}")
    if code=="self_referencing_canonical_data_model_inconsistent":
        return (f"source_self_referencing_canonical_data_model_inconsistent:embedded={blocker['embedded_version']}:"
                f"data_model_version={blocker['declared_data_model_version']}")
    return code


def _self_referencing_rebind_plan(layout, distribution, target_core_version, target_data_model_version):
    """Determine, per field and independently, whether an already-consistent self-referencing
    specification field should be rebound to the candidate's equivalently-versioned doc.

    Only called once manifest_core_consistency_blockers(layout) has already returned no
    self-referencing blockers, so a field matching here is known to already be internally
    consistent and therefore eligible for deterministic rebinding.
    """
    spec=layout.manifest.get("specification") or {}
    blockers=[]; rebind={}

    if self_referencing_core_doc_version(layout, spec.get("product_specification"), PRODUCT_SPEC_DOC_RE) is not None:
        target_name=PRODUCT_SPEC_DOC_TEMPLATE.format(version=target_core_version)
        if not (distribution.core_root/"docs"/target_name).is_file():
            blockers.append(f"self_referencing_product_specification_target_doc_missing:{target_name}")
        else:
            rebind["product_specification"]="./"+relative(layout, layout.core_root/"docs"/target_name)
            rebind["current_version"]=target_core_version

    if self_referencing_core_doc_version(layout, spec.get("canonical_data_model"), CANONICAL_DATA_MODEL_DOC_RE) is not None:
        target_name=CANONICAL_DATA_MODEL_DOC_TEMPLATE.format(version=target_data_model_version)
        if not (distribution.core_root/"docs"/target_name).is_file():
            blockers.append(f"self_referencing_canonical_data_model_target_doc_missing:{target_name}")
        else:
            rebind["canonical_data_model"]="./"+relative(layout, layout.core_root/"docs"/target_name)

    return blockers, rebind


def plan(root, distribution_path=None):
    try: layout=discover_layout(root)
    except Exception as e: return {"permitted":False,"blockers":[f"project_discovery_failed:{e}"]}
    if layout.mode!="project_format_1": return {"permitted":False,"blockers":["project_format_upgrade_required"]}
    try: distribution=discover_distribution(Path(distribution_path) if distribution_path else None,tool_file=Path(__file__))
    except Exception as e: return {"permitted":False,"blockers":[str(e)]}
    sf=layout.manifest.get("specforge") or {}; fmt=sf.get("project_format"); blockers=[]
    if fmt not in distribution.project_formats: blockers.append("target_core_incompatible_with_project_format")
    current=sf.get("core_version"); target=distribution.version
    current_data_model=sf.get("data_model_version"); target_data_model=distribution.core.get("data_model_version")

    # Source-state preflight: verify the source project's own installed-state coherence
    # before authority establishment or any mutation, reusing validate-specforge.py's own
    # predicate logic rather than duplicating it. Runs strictly before any write.
    blockers += [_format_consistency_blocker(b) for b in manifest_core_consistency_blockers(layout)]

    rebind={}
    if not blockers:
        rebind_blockers, rebind = _self_referencing_rebind_plan(layout, distribution, target, target_data_model)
        blockers += rebind_blockers

    preserve=[relative(layout,layout.manifest_path)]
    for key,default in (("changes","specforge/changes"),("decisions","specforge/decisions"),("history","specforge/history"),("evidence","specforge/evidence")):
        value=relative(layout,configured_path(layout,key,default))
        if value not in preserve: preserve.append(value)

    return {
        "permitted":not blockers,
        "already_current":current==target,
        "current_core_version":current,
        "target_core_version":target,
        "current_data_model_version":current_data_model,
        "target_data_model_version":target_data_model,
        "project_format":fmt,
        "candidate_distribution":{"version":target,"package":str(distribution.package_path),"core":str(distribution.core_root)},
        "replace":[str(layout.core_root.relative_to(layout.root)).replace('\\','/')],
        "preserve":preserve,
        "specification_rebind":rebind,
        "reconciliation_compatibility":RECONCILIATION_COMPATIBILITY,
        "blockers":blockers,
    }


def evidence_path(layout,current,target):
    safe=lambda v:str(v).replace("/","_").replace("\\","_")
    return configured_path(layout,"evidence","specforge/evidence")/"upgrades"/f"core-{safe(current)}-to-{safe(target)}.yaml"


def write_evidence(layout,p):
    path=evidence_path(layout,p["current_core_version"],p["target_core_version"])
    path.parent.mkdir(parents=True,exist_ok=True)
    payload={
        "operation":"core_upgrade",
        "from_core_version":p["current_core_version"],
        "to_core_version":p["target_core_version"],
        "from_data_model_version":p.get("current_data_model_version"),
        "to_data_model_version":p.get("target_data_model_version"),
        "project_format":p["project_format"],
        "candidate_distribution":p["candidate_distribution"],
        "replaced":p["replace"],
        "preserved":p["preserve"],
        "specification_rebind":p.get("specification_rebind") or {},
        "reconciliation_compatibility":p.get("reconciliation_compatibility") or RECONCILIATION_COMPATIBILITY,
        "authority":p.get("authority"),
        "result":"upgraded",
    }
    path.write_text(yaml.safe_dump(payload,sort_keys=False,allow_unicode=True),encoding="utf-8",newline="\n")
    return str(path.relative_to(layout.root)).replace("\\","/")


def restore_file(path, existed, content):
    if existed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    elif path.exists():
        path.unlink()


def apply(root,distribution_path=None):
    p=plan(root,distribution_path)
    if not p.get("permitted") or p.get("already_current"): return p
    if not clean(root): p["permitted"]=False; p["blockers"]=["working_tree_not_clean"]; return p
    layout=discover_layout(root)
    distribution=discover_distribution(Path(distribution_path) if distribution_path else None,tool_file=Path(__file__))
    target=layout.core_root
    if target.resolve()==distribution.core_root.resolve():
        p["permitted"]=False; p["blockers"]=["candidate_distribution_is_installed_core"]; return p
    authority_file=authority_path(layout)
    authority_existed=authority_file.is_file()
    authority_before=authority_file.read_bytes() if authority_existed else None
    manifest_before=layout.manifest_path.read_bytes()
    upgrade_evidence=evidence_path(layout,p["current_core_version"],p["target_core_version"])
    evidence_existed=upgrade_evidence.is_file()
    evidence_before=upgrade_evidence.read_bytes() if evidence_existed else None
    try:
        p["authority"]=establish_upgrade_authority(layout,p["current_core_version"],p["target_core_version"])
    except Exception as exc:
        p["permitted"]=False; p["blockers"]=[f"upgrade_authority_failed:{exc}"]; return p
    try:
        with tempfile.TemporaryDirectory(prefix="specforge-upgrade-") as tmp:
            backup=Path(tmp)/"core-backup"
            shutil.copytree(target,backup)
            try:
                shutil.rmtree(target)
                shutil.copytree(distribution.core_root,target,ignore=shutil.ignore_patterns("__pycache__","*.pyc","*.pyo"))
                manifest=layout.manifest
                sf=manifest.setdefault("specforge",{})
                sf["core_version"]=p["target_core_version"]
                sf["data_model_version"]=p["target_data_model_version"]
                rebind=p.get("specification_rebind") or {}
                if rebind:
                    manifest.setdefault("specification",{}).update(rebind)
                layout.manifest_path.write_text(yaml.safe_dump(manifest,sort_keys=False,allow_unicode=True),encoding="utf-8",newline="\n")
                p["evidence"]=write_evidence(layout,p)
            except Exception:
                if target.exists(): shutil.rmtree(target)
                shutil.copytree(backup,target)
                layout.manifest_path.write_bytes(manifest_before)
                restore_file(upgrade_evidence,evidence_existed,evidence_before)
                raise
    except Exception:
        restore_file(authority_file,authority_existed,authority_before)
        raise
    p["applied"]=True
    return p


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=("plan","upgrade")); ap.add_argument("--root",default=".")
    ap.add_argument("--distribution"); ap.add_argument("--package",dest="legacy_package")
    ap.add_argument("--apply",action="store_true"); ap.add_argument("--json",action="store_true")
    a=ap.parse_args(); root=Path(a.root).resolve(); distribution=a.distribution or a.legacy_package
    out=plan(root,distribution) if a.command=="plan" or not a.apply else apply(root,distribution)
    print(json.dumps(out,indent=2) if a.json else out); return 0 if out.get("permitted") else 1
if __name__=="__main__": raise SystemExit(main())
