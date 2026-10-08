#!/usr/bin/env python3
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile, yaml

ROOT=Path(__file__).resolve().parents[1]
CORE_ROOT=ROOT if (ROOT/"tools"/"specforge-pack.py").is_file() else ROOT/"specforge"/"core"
TOOL=CORE_ROOT/"tools"/"specforge-pack.py"

def run(args):
    env=os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"]="1"
    return subprocess.run([sys.executable,"-B",str(TOOL),*args],capture_output=True,text=True,env=env)

def write_project(root,packs):
    sf=root/"specforge"; (sf/"core").mkdir(parents=True); (sf/"packs").mkdir();
    for d in ("changes","decisions","history","evidence"): (sf/d).mkdir()
    (sf/"SPECFORGE.md").write_text("# entry\n",encoding="utf-8")
    manifest={"specforge":{"project_format":1,"core_version":"0.1.0-alpha.5","data_model_version":"0.1.0-alpha.2"},"project":{"id":"PRJ-9999","name":"Pack Fixture"},"specification":{"product_specification":"./product.md","canonical_data_model":"./model.md","current_version":"1"},"paths":{"core":"./specforge/core","packs":"./specforge/packs","schemas":"./specforge/core/schemas","rules":"./specforge/core/rules","workflows":"./specforge/core/workflows","tools":"./specforge/core/tools","tests":"./specforge/core/tests","changes":"./specforge/changes","decisions":"./specforge/decisions","history":"./specforge/history","evidence":"./specforge/evidence"},"ownership":{"framework_owned":["./specforge/core","./specforge/packs"],"project_owned":["./specforge/project.yaml","./specforge/changes","./specforge/decisions","./specforge/history","./specforge/evidence"]},"packs":packs,"policy":{}}
    (sf/"project.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf-8")
    (root/"product.md").write_text("product\n",encoding="utf-8"); (root/"model.md").write_text("model\n",encoding="utf-8")

def pack(root,pid,version,precedence,overrides=None,compatibility=None):
    p=root/"specforge"/"packs"/pid; p.mkdir(parents=True)
    meta={"id":pid,"version":version,"compatibility":compatibility or {"project_formats":[1],"core_versions":["0.1.0-alpha.5"]}}
    if overrides is not None: meta["overrides"]=overrides
    (p/"pack.yaml").write_text(yaml.safe_dump(meta,sort_keys=False),encoding="utf-8")

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    packs=[{"id":"game","version":"1.0","path":"./specforge/packs/game","precedence":20,"extensions":["rules","vocabulary"]},{"id":"coding","version":"1.0","path":"./specforge/packs/coding","precedence":10,"extensions":["schemas","rules"]}]
    write_project(root,packs); pack(root,"game","1.0",20); pack(root,"coding","1.0",10)
    r=run(["--root",str(root),"--json"]); assert r.returncode==0,r.stdout+r.stderr
    data=json.loads(r.stdout); assert [x["id"] for x in data["packs"]]==["coding","game"]

with tempfile.TemporaryDirectory() as td:
    root=Path(td); packs=[{"id":"bad","version":"1.0","path":"./specforge/packs/bad","precedence":1,"extensions":["rules"]}]
    write_project(root,packs); pack(root,"bad","1.0",1,{"approval_mode":"none"})
    r=run(["--root",str(root),"--json"]); assert r.returncode!=0
    assert "pack_core_invariant_override_forbidden:bad:approval_mode" in json.loads(r.stdout)["blockers"]

with tempfile.TemporaryDirectory() as td:
    root=Path(td); packs=[{"id":"a","version":"1","path":"./specforge/packs/a","precedence":1,"extensions":[]},{"id":"b","version":"1","path":"./specforge/packs/b","precedence":1,"extensions":[]}]
    write_project(root,packs); pack(root,"a","1",1); pack(root,"b","1",1)
    r=run(["--root",str(root),"--json"]); assert r.returncode!=0
    assert "pack_precedence_duplicate:1" in json.loads(r.stdout)["blockers"]

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    packs=[{"id":"lite-research","version":"0.1.0","path":"./specforge/packs/lite-research","precedence":10,"extensions":["rules","workflows"]}]
    write_project(root,packs)
    pack(root,"lite-research","0.1.0",10,compatibility={"project_formats":[1]})
    p=root/"specforge"/"packs"/"lite-research"
    (p/"rules").mkdir(); (p/"workflows").mkdir()
    (p/"rules"/"research-material.md").write_text("# Lite Research rules\n",encoding="utf-8")
    (p/"workflows"/"research-intake.md").write_text("# Lite Research workflow\n",encoding="utf-8")
    r=run(["--root",str(root),"--json"]); assert r.returncode==0,r.stdout+r.stderr
    data=json.loads(r.stdout)
    assert data["packs"]==[{"id":"lite-research","version":"0.1.0","path":"./specforge/packs/lite-research","precedence":10,"extensions":["rules","workflows"]}]

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    packs=[{"id":"dogfood-development","version":"0.1.0","path":"./specforge/packs/dogfood-development","precedence":10,"extensions":["rules","workflows"]}]
    write_project(root,packs)
    p=root/"specforge"/"packs"/"dogfood-development"
    p.mkdir(parents=True)
    (p/"pack.yaml").write_text(yaml.safe_dump({
        "id":"dogfood-development",
        "version":"0.1.0",
        "compatibility":{"project_formats":[1]},
        "extensions":["rules","workflows"],
        "overrides":{},
        "entrypoints":{
            "rules":["rules/dogfood-development.md"],
            "workflows":["workflows/fastest-valid-path.md"],
        },
    },sort_keys=False),encoding="utf-8")
    (p/"rules").mkdir(); (p/"workflows").mkdir()
    (p/"rules"/"dogfood-development.md").write_text("# Dogfood Development rules\n",encoding="utf-8")
    (p/"workflows"/"fastest-valid-path.md").write_text("# Fastest Valid Path\n",encoding="utf-8")
    r=run(["--root",str(root),"--json"]); assert r.returncode==0,r.stdout+r.stderr
    data=json.loads(r.stdout)
    assert data["packs"]==[{"id":"dogfood-development","version":"0.1.0","path":"./specforge/packs/dogfood-development","precedence":10,"extensions":["rules","workflows"]}]

print("Pack tests PASSED")


# CHG-1030 regression: assurance profiles are an explicit additive pack extension.
_pack_text = (CORE_ROOT / 'tools/specforge-pack.py').read_text(encoding='utf-8')
assert 'assurance_profiles' in _pack_text
assert 'pack_assurance_profile_non_additive' in _pack_text
