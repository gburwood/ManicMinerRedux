#!/usr/bin/env python3
from pathlib import Path
import importlib.util, json, shutil, subprocess, sys, tempfile, yaml

CORE=Path(__file__).resolve().parents[1]
TESTS=CORE/"tests"
sys.path.insert(0,str(TESTS))
from portable_fixture import canonical_digest, create_project, git, install_controlled_change, write_yaml

def load_integrity(root):
    tool=root/"specforge/core/tools/specforge-integrity.py"
    spec=importlib.util.spec_from_file_location("specforge_integrity_under_test",tool)
    module=importlib.util.module_from_spec(spec); sys.path.insert(0,str(tool.parent)); spec.loader.exec_module(module)
    return module

def run(tool,*args,expect=0):
    r=subprocess.run([sys.executable,"-B",str(tool),*map(str,args)],capture_output=True,text=True)
    if r.returncode!=expect:
        raise AssertionError(f"{tool.name} returned {r.returncode}, expected {expect}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    return json.loads(r.stdout[r.stdout.rfind("\n{")+1:] if "\n{" in r.stdout else r.stdout)

def baseline():
    td=tempfile.TemporaryDirectory(prefix="specforge-integrity-")
    root=Path(td.name)/"repo"
    create_project(root,CORE,git_backed=True,initialize_governance_tier=True)
    tool=root/"specforge/core/tools/specforge-integrity.py"
    state=root/"specforge/evidence/integrity/state.json"
    result=run(tool,"full","--root",root,"--state-output",state,"--progress-file","-","--json")
    assert result["ok"] and result["mode"]=="full_integrity_v1"
    validated=result["state"]["validated_revision"]
    git(root,"add","specforge/evidence/integrity/state.json")
    git(root,"commit","-m","Record SpecForge integrity receipt [skip ci]")
    receipt=git(root,"rev-parse","HEAD").stdout.strip()
    assert git(root,"rev-parse",f"{receipt}^").stdout.strip()==validated
    return td,root,tool

# Million-scale algorithmic fixture: state size/work is partition based, not one entry per historical record.
with tempfile.TemporaryDirectory(prefix="specforge-scale-") as td:
    root=Path(td)/"repo"
    create_project(root,CORE,git_backed=True,initialize_governance_tier=True)
    module=load_integrity(root)
    probe=module.scale_probe(1_000_000,["CHG-999998","EVT-999999"])
    assert probe["represented_historical_records"]==1_000_000
    assert probe["historical_records_parsed"]==0
    assert probe["index_partitions_read"]<=2
    assert probe["bounded_by_delta"] is True

# Routine append-only change validates incrementally and reads only its closure.
td,root,tool=baseline()
try:
    install_controlled_change(
        root,"CHG-9008",status="awaiting_approval",skip_approval=True,
        lifecycle_enforcement="controlled_v3",
        declared_scope=[{"operation":"modify","path":"specforge/core/tools/specforge-managed.py"}],
        governance_tier={"requested":"HIGH"},
    )
    git(root,"add","specforge/changes")
    git(root,"commit","-m","Add routine governed change")
    out=Path(td.name)/"next-state.json"
    result=run(tool,"incremental","--root",root,"--state-output",out,"--progress-file","-","--json")
    assert result["ok"],result
    assert result["mode"]=="incremental_integrity_v1"
    assert result["metrics"]["changed_record_count"]>=3
    assert result["metrics"]["historical_records_parsed"]<20
    assert result["metrics"]["index_partitions_read"]<=result["metrics"]["changed_record_count"]
finally:
    td.cleanup()

# Historical approval lookup must be bounded even when APR numbering is unrelated to the CHG id.
td,root,tool=baseline()
try:
    ids=install_controlled_change(
        root,"CHG-9020",status="awaiting_approval",skip_approval=False,
        lifecycle_enforcement="controlled_v3",
    )
    old_apr=root/"specforge/changes/CHG-9020/approvals"/f"{ids['approval']}.yaml"
    approval=yaml.safe_load(old_apr.read_text(encoding="utf-8"))
    approval["id"]="APR-9901"
    new_apr=old_apr.with_name("APR-9901.yaml")
    write_yaml(new_apr,approval); old_apr.unlink()
    chg_path=root/"specforge/changes/CHG-9020.yaml"
    chg=yaml.safe_load(chg_path.read_text(encoding="utf-8")); chg["approvals"]=["APR-9901"]; write_yaml(chg_path,chg)
    git(root,"add","."); git(root,"commit","-m","Add historical mismatched approval id fixture")
    state=root/"specforge/evidence/integrity/state.json"
    refreshed=run(tool,"full","--root",root,"--state-output",state,"--progress-file","-","--json")
    assert refreshed["ok"],refreshed
    git(root,"add",state.relative_to(root)); git(root,"commit","-m","Record refreshed integrity receipt [skip ci]")
    chg=yaml.safe_load(chg_path.read_text(encoding="utf-8")); chg["priority"]="high"; write_yaml(chg_path,chg)
    git(root,"add",chg_path.relative_to(root)); git(root,"commit","-m","Change only the governed change record")
    result=run(tool,"incremental","--root",root,"--progress-file","-","--json")
    assert result["ok"],result
    assert result["mode"]=="incremental_integrity_v1"
    assert result["metrics"]["changed_record_count"]==1
    assert result["metrics"]["historical_records_parsed"]<10
finally:
    td.cleanup()

# Validator/schema/policy semantic changes must escalate rather than silently using prior integrity.
td,root,tool=baseline()
try:
    validator=root/"specforge/core/tools/validate-specforge.py"
    validator.write_text(validator.read_text(encoding="utf-8")+"\n# semantic-change-fixture\n",encoding="utf-8",newline="\n")
    git(root,"add",str(validator.relative_to(root))); git(root,"commit","-m","Change validator semantics")
    result=run(tool,"incremental","--root",root,"--progress-file","-","--json",expect=2)
    assert result["requires_full"] and "integrity_semantics_changed" in result["blockers"]
finally:
    td.cleanup()

def parity_case(name,mutator):
    td,root,tool=baseline()
    try:
        mutator(root)
        git(root,"add","."); git(root,"commit","-m",name)
        inc=run(tool,"incremental","--root",root,"--progress-file","-","--json",expect=1)
        full=subprocess.run([sys.executable,"-B",str(root/"specforge/core/tools/validate-specforge.py"),str(root)],capture_output=True,text=True)
        assert not inc["ok"] and full.returncode!=0,(name,inc,full.stdout,full.stderr)
    finally:
        td.cleanup()

def broken_reference(root):
    ids=install_controlled_change(
        root,"CHG-9010",status="awaiting_approval",skip_approval=True,
        lifecycle_enforcement="controlled_v3",
        declared_scope=[{"operation":"modify","path":"specforge/core/tools/specforge-managed.py"}],
        governance_tier={"requested":"HIGH"},
    )
    ia=root/"specforge/changes/CHG-9010"/f"{ids['impact']}.yaml"
    data=yaml.safe_load(ia.read_text(encoding="utf-8")); data["change"]="CHG-9999"; write_yaml(ia,data)

def tier_violation(root):
    ids=install_controlled_change(
        root,"CHG-9011",status="approved",skip_approval=False,
        lifecycle_enforcement="controlled_v2",
        declared_scope=[{"operation":"modify","path":"specforge/core/tools/specforge-managed.py"}],
        governance_tier={"requested":"LOW"},
    )
    proposal_path=root/"specforge/changes/CHG-9011"/f"{ids['proposal']}.yaml"
    proposal=yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    policy_path=root/"specforge/core/policy/governance-tier-policy.yaml"
    proposal["governance_tier"]["policy_digest"]=canonical_digest(policy_path)
    write_yaml(proposal_path,proposal)

def completion_without_evidence(root):
    install_controlled_change(
        root,"CHG-9012",status="completed",attempt=False,
        lifecycle_enforcement="controlled_v3",
        declared_scope=[{"operation":"modify","path":"specforge/core/tools/specforge-managed.py"}],
        governance_tier={"requested":"HIGH"},
    )

parity_case("broken reference parity",broken_reference)
parity_case("governance tier parity",tier_violation)
parity_case("completion evidence parity",completion_without_evidence)

# Duplicate identity parity needs a validated historical identity first.
td,root,tool=baseline()
try:
    install_controlled_change(
        root,"CHG-9013",status="awaiting_approval",skip_approval=True,
        lifecycle_enforcement="controlled_v3",
        declared_scope=[{"operation":"modify","path":"specforge/core/tools/specforge-managed.py"}],
        governance_tier={"requested":"HIGH"},
    )
    git(root,"add","specforge/changes"); git(root,"commit","-m","Add historical identity")
    # Full audit resets the baseline to include CHG-9013.
    state=root/"specforge/evidence/integrity/state.json"
    run(tool,"full","--root",root,"--state-output",state,"--progress-file","-","--json")
    git(root,"add",state.relative_to(root)); git(root,"commit","-m","Record refreshed integrity receipt [skip ci]")
    original=root/"specforge/changes/CHG-9013.yaml"
    duplicate=root/"specforge/changes/duplicate-identity.yaml"
    duplicate.write_text(original.read_text(encoding="utf-8"),encoding="utf-8",newline="\n")
    git(root,"add",duplicate.relative_to(root)); git(root,"commit","-m","Introduce duplicate identity")
    inc=run(tool,"incremental","--root",root,"--progress-file","-","--json",expect=1)
    full=subprocess.run([sys.executable,"-B",str(root/"specforge/core/tools/validate-specforge.py"),str(root)],capture_output=True,text=True)
    assert any("duplicate_canonical_id" in x for x in inc["blockers"]),inc
    assert full.returncode!=0
finally:
    td.cleanup()

print("Incremental integrity tests PASSED")

# CHG-1044: configured schema roots must drive incremental integrity semantics.
with tempfile.TemporaryDirectory(prefix="specforge-relocated-schemas-") as td:
    root=Path(td)/"repo"
    create_project(root,CORE,git_backed=True,initialize_governance_tier=True)
    relocated=root/"project-config/schemas"
    shutil.copytree(root/"specforge/core/schemas",relocated)
    manifest_path=root/"specforge/project.yaml"
    manifest=yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("paths",{})["schemas"]="./project-config/schemas"
    write_yaml(manifest_path,manifest)
    module=load_integrity(root); layout=module.discover_layout(root)
    schemas=module.schema_map(layout)
    assert "change" in schemas and "proposal" in schemas,schemas.keys()
    expected=module.digest_named(root,list(relocated.glob("*.schema.json")))
    assert module.fingerprints(layout)["schemas"]==expected
print("PASS configured-schema-root-integrity")


# CHG-1057: the integrity wrapper must preserve validator failure semantics while
# allowing child stderr (including SPECFORGE_PROGRESS) to flow live.
with tempfile.TemporaryDirectory(prefix="specforge-live-progress-") as td:
    root=Path(td)/"repo"
    tools=root/"tools"
    tools.mkdir(parents=True)
    fake=tools/"validate-specforge.py"
    fake.write_text(
        "import sys\n"
        "print('SPECFORGE_PROGRESS {\"phase\":\"fixture\"}', file=sys.stderr, flush=True)\n"
        "print('fixture validator failed')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
        newline="\n",
    )
    module=load_integrity(CORE.parent.parent)
    class _Layout:
        tool_root=tools
        root=root
    progress=module.Progress(None,module.FULL_PROFILE)
    assert module.full_validate(_Layout(),progress) is False
print("PASS live-progress-preserves-validator-failure")


# CHG-1057: parent heartbeat remains visible even when the child emits no progress.
with tempfile.TemporaryDirectory(prefix="specforge-parent-heartbeat-") as td:
    root=Path(td)/"repo"
    tools=root/"tools"
    tools.mkdir(parents=True)
    fake=tools/"validate-specforge.py"
    fake.write_text(
        "import time\n"
        "time.sleep(0.16)\n"
        "print('fixture validator passed')\n",
        encoding="utf-8",
        newline="\n",
    )
    module=load_integrity(CORE.parent.parent)
    module.FULL_VALIDATOR_HEARTBEAT_SECONDS=0.05
    class _Layout:
        tool_root=tools
        root=root
    class _Progress:
        path=None
        def __init__(self): self.rows=[]
        def emit(self,phase,processed=None,total=None,substage=None,**extra):
            self.rows.append({
                "phase":phase,
                "processed":processed,
                "total":total,
                "substage":substage,
                **extra,
            })
    progress=_Progress()
    assert module.full_validate(_Layout(),progress) is True
    heartbeats=[
        row for row in progress.rows
        if row.get("phase")=="full_validation"
        and row.get("substage")=="exhaustive validator still running"
    ]
    assert heartbeats, progress.rows
print("PASS parent-heartbeat-visible-during-silent-child")
