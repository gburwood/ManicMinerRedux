#!/usr/bin/env python3
"""Domain-neutral checkpoint verification and completion for SpecForge."""
from pathlib import Path
import argparse, datetime as dt, hashlib, json, os, subprocess, sys, tempfile
import yaml
from specforge_project import approval_gate, canonical_artifact_digest, discover_layout, iter_record_files, load_yaml, material_snapshot, verify_source_revision
from specforge_integration import PROFILE as INTEGRATION_PROFILE, verify_integration_evidence
from specforge_authority import authority_path, current_identity, integrity_summary, load_authority

def records(layout):
    out={}
    for path in iter_record_files(layout):
        try: data=load_yaml(path)
        except Exception: continue
        if isinstance(data,dict) and data.get("id"): out[str(data["id"])]=(data,path)
    return out

def integrity_checkpoint_status(layout):
    """Expose integrity freshness alongside checkpoint readiness without changing checkpoint authority."""
    return integrity_summary(layout)

def change_set_digest(changes):
    body="\n".join(sorted(str(x) for x in changes))+"\n"
    return "sha256:"+hashlib.sha256(body.encode("utf-8")).hexdigest()

def passed_implementation(layout,recs,change):
    proposal=(change.get("proposal") or {}).get("current")
    for iid in (change.get("implementation") or {}).get("attempts") or []:
        item=recs.get(str(iid))
        if not item: continue
        imp=item[0]
        if imp.get("proposal")!=proposal or imp.get("outcome")!="passed": continue
        required=[x for x in (imp.get("validation_checks") or []) if x.get("required")]
        tests=imp.get("tests") or {}
        if not required or any(x.get("status")!="passed" for x in required): continue
        if not (tests.get("status")=="passed" or (tests.get("passed") and not tests.get("failed"))): continue
        integration=imp.get("integration") or {}
        verified=verify_integration_evidence(layout,imp,mode="static") if integration.get("profile")==INTEGRATION_PROFILE else verify_source_revision(layout,imp.get("source_revision") or {},mode="static",require_provider=False)
        if verified.get("valid"): return iid
    return None

def pack_assurance(layout):
    pack_tool=layout.tool_root/"specforge-pack.py"
    if not pack_tool.is_file(): return {"validation_required":[],"acceptance_required":[]},["pack_resolver_missing"]
    proc=subprocess.run([sys.executable,"-B",str(pack_tool),"--root",str(layout.root),"--json"],capture_output=True,text=True)
    try: result=json.loads(proc.stdout or "{}")
    except Exception: return {"validation_required":[],"acceptance_required":[]},["pack_resolver_output_invalid"]
    if proc.returncode or not result.get("permitted"):
        return {"validation_required":[],"acceptance_required":[]},["pack:"+x for x in result.get("blockers",["validation_failed"])]
    return result.get("assurance") or {"validation_required":[],"acceptance_required":[]},[]

def required_assurance(layout):
    policy=((layout.manifest.get("policy") or {}).get("checkpoint") or {})
    pack,blockers=pack_assurance(layout)
    validation=[]; acceptance=[]
    for x in (policy.get("validation_required") or [])+(pack.get("validation_required") or []):
        if x not in validation: validation.append(x)
    for x in (policy.get("acceptance_required") or [])+(pack.get("acceptance_required") or []):
        if x not in acceptance: acceptance.append(x)
    return {"validation_required":validation,"acceptance_required":acceptance},blockers

def _validation_passes(checkpoint,required):
    passed={x.get("requirement") for x in checkpoint.get("validation") or [] if x.get("status")=="passed"}
    return [f"checkpoint_validation_missing:{x}" for x in required if x not in passed]

def verify(root,checkpoint_id,acceptance_id=None,require_current=True):
    layout=discover_layout(Path(root).resolve()); recs=records(layout); blockers=[]; details={'integrity':integrity_summary(layout)}
    item=recs.get(checkpoint_id)
    if not item: return {"valid":False,"blockers":["checkpoint_missing"],"checkpoint":checkpoint_id}
    checkpoint=item[0]; changes=checkpoint.get("included_changes") or []
    if not changes or len(changes)!=len(set(changes)): blockers.append("checkpoint_change_set_invalid")
    digest=change_set_digest(changes); details["included_changes_digest"]=digest
    if checkpoint.get("included_changes_digest")!=digest: blockers.append("checkpoint_change_set_digest_mismatch")
    candidate=(checkpoint.get("candidate") or {}).get("material") or {}
    if not candidate.get("revision"): blockers.append("checkpoint_candidate_material_missing")
    if require_current:
        try: current=material_snapshot(layout)
        except Exception as exc: blockers.append("checkpoint_current_material_unavailable"); current={"error":str(exc)}
        details["current_material"]=current
        if current.get("revision")!=candidate.get("revision"): blockers.append("checkpoint_candidate_not_current")
    for cid in changes:
        item=recs.get(str(cid))
        if not item: blockers.append(f"checkpoint_change_missing:{cid}"); continue
        change=item[0]
        if change.get("status") not in ("ready_for_checkpoint","completed"): blockers.append(f"checkpoint_change_not_ready:{cid}")
        if approval_gate(layout,recs,change): blockers.append(f"checkpoint_change_approval_invalid:{cid}")
        if not passed_implementation(layout,recs,change): blockers.append(f"checkpoint_change_implementation_invalid:{cid}")
    assurance,ab=required_assurance(layout); blockers+=ab; details["assurance"]=assurance
    blockers+=_validation_passes(checkpoint,assurance["validation_required"])
    if acceptance_id:
        item=recs.get(acceptance_id)
        if not item: blockers.append("checkpoint_acceptance_missing")
        else:
            acc=item[0]
            if acc.get("checkpoint")!=checkpoint_id: blockers.append("checkpoint_acceptance_checkpoint_mismatch")
            if acc.get("decision")!="accepted": blockers.append("checkpoint_acceptance_not_accepted")
            if acc.get("included_changes_digest")!=digest: blockers.append("checkpoint_acceptance_change_set_mismatch")
            acc_material=((acc.get("candidate") or {}).get("material") or {}).get("revision")
            if acc_material!=candidate.get("revision"): blockers.append("checkpoint_acceptance_candidate_mismatch")
            actor=acc.get("actor") or {}; mechanism=acc.get("mechanism") or {}
            if actor.get("type") in ("human","external_system") and (not mechanism.get("type") or not mechanism.get("reference")): blockers.append("checkpoint_acceptance_provenance_missing")
            evidence=acc.get("evidence") or {}
            if evidence.get("candidate_revision")!=candidate.get("revision"): blockers.append("checkpoint_acceptance_evidence_not_bound")
            satisfied=set(evidence.get("requirements") or [])
            for requirement in assurance["acceptance_required"]:
                if requirement not in satisfied: blockers.append(f"checkpoint_acceptance_requirement_missing:{requirement}")
    return {"valid":not blockers,"checkpoint":checkpoint_id,"acceptance":acceptance_id,"blockers":sorted(set(blockers)),"details":details}

def _atomic_yaml_updates(updates):
    backups={}; temps={}
    try:
        for path,data in updates:
            path.parent.mkdir(parents=True,exist_ok=True)
            backups[path]=path.read_text(encoding="utf-8") if path.exists() else None
            fd,tmp=tempfile.mkstemp(prefix=path.name+".",dir=str(path.parent)); os.close(fd)
            temp=Path(tmp); temp.write_text(yaml.safe_dump(data,sort_keys=False),encoding="utf-8",newline="\n"); temps[path]=temp
        replaced=[]
        try:
            for path,_ in updates: os.replace(temps[path],path); replaced.append(path)
        except Exception:
            for path in replaced:
                if backups[path] is None:
                    if path.exists(): path.unlink()
                else:
                    path.write_text(backups[path],encoding="utf-8",newline="\n")
            raise
    finally:
        for temp in temps.values():
            if temp.exists(): temp.unlink()

def _accepted_authority_update(layout,checkpoint_id,acceptance_id,checkpoint,acceptance):
    authority=load_authority(layout)
    if not authority:
        return None,None,"trusted_material_baseline_missing"
    candidate=dict((checkpoint.get("candidate") or {}).get("material") or {})
    if not candidate.get("provider") or not candidate.get("revision"):
        return None,None,"checkpoint_candidate_material_missing"
    updated=dict(authority)
    updated["trusted"]=current_identity(layout)
    updated["accepted_checkpoint"]={
        "id":checkpoint_id,
        "acceptance":acceptance_id,
        "candidate_material":candidate,
        "accepted_at":acceptance.get("timestamp"),
    }
    updated.pop("active_operation",None)
    return authority_path(layout),updated,None

def complete(root,checkpoint_id,acceptance_id):
    result=verify(root,checkpoint_id,acceptance_id,True)
    if not result["valid"]: return result
    layout=discover_layout(Path(root).resolve()); recs=records(layout)
    checkpoint,path=recs[checkpoint_id]; checkpoint=dict(checkpoint); checkpoint["status"]="accepted"; checkpoint["acceptance"]={"current":acceptance_id}
    acceptance=recs[acceptance_id][0]
    authority_file,authority,error=_accepted_authority_update(layout,checkpoint_id,acceptance_id,checkpoint,acceptance)
    if error:
        result["valid"]=False
        result["blockers"]=sorted(set((result.get("blockers") or [])+[error]))
        return result
    updates=[(path,checkpoint),(authority_file,authority)]; completed=[]
    for cid in checkpoint.get("included_changes") or []:
        change,cpath=recs[cid]
        if change.get("status")=="completed": continue
        changed=dict(change); changed["status"]="completed"; changed["checkpoint"]={"completed_in":checkpoint_id,"acceptance":acceptance_id}
        updates.append((cpath,changed)); completed.append(cid)
    _atomic_yaml_updates(updates); result["completed_changes"]=completed
    result["trusted_material"]=authority["trusted"]
    return result

def _utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")


def _next_acceptance_id(recs):
    highest=0
    for rid in recs:
        if str(rid).startswith("ACC-") and str(rid)[4:].isdigit(): highest=max(highest,int(str(rid)[4:]))
    return f"ACC-{highest+1:04d}"


def _acceptance_path(layout,acceptance_id):
    value=(layout.manifest.get("paths") or {}).get("history","specforge/history")
    return (layout.root/value/"acceptances"/f"{acceptance_id}.yaml").resolve()


def _pfa_preflight(layout,recs,checkpoint,pfa):
    blockers=[]; changes=checkpoint.get("included_changes") or []; pfa_change=pfa.get("change")
    if changes != [pfa_change]: blockers.append("prospective_authority_requires_single_matching_change")
    if ((pfa.get("scope") or {}).get("mode"))!="prospective_exact_candidate_v1": blockers.append("prospective_authority_mode_invalid")
    if ((pfa.get("scope") or {}).get("change_set") or []) != [pfa_change]: blockers.append("prospective_authority_change_set_invalid")
    if (pfa.get("actor") or {}).get("type")!="human": blockers.append("prospective_authority_human_principal_missing")
    change=recs.get(str(pfa_change),(None,None))[0]
    if not change: blockers.append("prospective_authority_change_missing")
    else:
        proposal_id=(change.get("proposal") or {}).get("current")
        if proposal_id!=pfa.get("proposal"): blockers.append("prospective_authority_proposal_not_current")
        proposal_item=recs.get(str(proposal_id))
        if not proposal_item: blockers.append("prospective_authority_proposal_missing")
        elif canonical_artifact_digest(proposal_item[1])!=pfa.get("proposal_digest"): blockers.append("prospective_authority_proposal_digest_mismatch")
    candidate=(checkpoint.get("candidate") or {}).get("material") or {}; projected=pfa.get("projected_candidate") or {}
    if candidate.get("revision")!=projected.get("revision") or candidate.get("file_count")!=projected.get("file_count"): blockers.append("prospective_authority_candidate_mismatch")
    assurance,assurance_blockers=required_assurance(layout); blockers.extend(assurance_blockers)
    if sorted(pfa.get("acceptance_requirements") or []) != sorted(assurance.get("acceptance_required") or []): blockers.append("prospective_authority_acceptance_requirements_changed")
    for rid,(data,_) in recs.items():
        if not str(rid).startswith("ACC-"): continue
        authority=data.get("authority") or {}; mechanism=data.get("mechanism") or {}
        if authority.get("source")==pfa.get("id") or (mechanism.get("type")=="prospective_finalisation_authority" and mechanism.get("reference")==pfa.get("id")):
            blockers.append("prospective_authority_already_consumed")
    return sorted(set(blockers)),assurance


def _parse_time(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _cap_preflight(layout, recs, checkpoint, cap):
    blockers = []
    checkpoint_id = checkpoint.get("id")
    if cap.get("checkpoint") != checkpoint_id:
        blockers.append("checkpoint_acceptance_proof_checkpoint_mismatch")
    if (cap.get("actor") or {}).get("type") != "human":
        blockers.append("checkpoint_acceptance_proof_human_actor_missing")
    candidate = (checkpoint.get("candidate") or {}).get("material") or {}
    accepted = (cap.get("candidate") or {}).get("material") or {}
    if candidate.get("revision") != accepted.get("revision") or candidate.get("file_count") != accepted.get("file_count"):
        blockers.append("checkpoint_acceptance_proof_candidate_mismatch")
    if checkpoint.get("included_changes_digest") != cap.get("included_changes_digest"):
        blockers.append("checkpoint_acceptance_proof_change_set_mismatch")
    presented_at = _parse_time(cap.get("presented_at"))
    received_at = _parse_time(cap.get("received_at"))
    created_at = _parse_time((checkpoint.get("metadata") or {}).get("created_at"))
    if presented_at is None or received_at is None or created_at is None:
        blockers.append("checkpoint_acceptance_proof_chronology_invalid")
    else:
        if presented_at < created_at:
            blockers.append("checkpoint_acceptance_proof_presentation_predates_checkpoint")
        if received_at < presented_at:
            blockers.append("checkpoint_acceptance_proof_predates_presentation")
    presentation_rel = cap.get("presentation")
    if not presentation_rel:
        blockers.append("checkpoint_acceptance_presentation_missing")
    else:
        presentation_path = (layout.root / str(presentation_rel)).resolve()
        try:
            presentation_path.relative_to(layout.root.resolve())
        except ValueError:
            blockers.append("checkpoint_acceptance_presentation_outside_project")
        else:
            if not presentation_path.is_file():
                blockers.append("checkpoint_acceptance_presentation_missing")
            else:
                try:
                    presentation = load_yaml(presentation_path)
                except Exception:
                    presentation = {}
                shown = ((presentation.get("candidate") or {}).get("material") or {})
                if presentation.get("checkpoint") != checkpoint_id:
                    blockers.append("checkpoint_acceptance_presentation_checkpoint_mismatch")
                if presentation.get("session") != cap.get("session"):
                    blockers.append("checkpoint_acceptance_presentation_session_mismatch")
                if presentation.get("presented_at") != cap.get("presented_at"):
                    blockers.append("checkpoint_acceptance_presentation_time_mismatch")
                if shown.get("revision") != candidate.get("revision") or shown.get("file_count") != candidate.get("file_count"):
                    blockers.append("checkpoint_acceptance_presentation_candidate_mismatch")
                if presentation.get("included_changes_digest") != checkpoint.get("included_changes_digest"):
                    blockers.append("checkpoint_acceptance_presentation_change_set_mismatch")
    for rid, (data, _) in recs.items():
        if not str(rid).startswith("ACC-"):
            continue
        authority = data.get("authority") or {}
        mechanism = data.get("mechanism") or {}
        if authority.get("source") == cap.get("id") or (
            mechanism.get("type") == "checkpoint_acceptance_proof"
            and mechanism.get("reference") == cap.get("id")
        ):
            blockers.append("checkpoint_acceptance_proof_already_consumed")
    return sorted(set(blockers))


def finalise_direct(root, checkpoint_id, proof_id):
    layout = discover_layout(Path(root).resolve())
    recs = records(layout)
    pre = verify(root, checkpoint_id, None, True)
    if not pre.get("valid"):
        return pre
    checkpoint_item = recs.get(checkpoint_id)
    cap_item = recs.get(proof_id)
    if not checkpoint_item:
        return {"valid": False, "checkpoint": checkpoint_id, "proof": proof_id, "blockers": ["checkpoint_missing"]}
    if not cap_item:
        return {"valid": False, "checkpoint": checkpoint_id, "proof": proof_id, "blockers": ["checkpoint_acceptance_proof_missing"]}
    checkpoint, checkpoint_path = checkpoint_item
    cap, _ = cap_item
    blockers = _cap_preflight(layout, recs, checkpoint, cap)
    if blockers:
        return {"valid": False, "checkpoint": checkpoint_id, "proof": proof_id, "blockers": blockers}
    assurance, assurance_blockers = required_assurance(layout)
    if assurance_blockers:
        return {"valid": False, "checkpoint": checkpoint_id, "proof": proof_id, "blockers": assurance_blockers}
    acceptance_id = _next_acceptance_id(recs)
    candidate = dict((checkpoint.get("candidate") or {}).get("material") or {})
    acceptance = {
        "id": acceptance_id,
        "checkpoint": checkpoint_id,
        "decision": "accepted",
        "candidate": {"material": candidate},
        "included_changes_digest": checkpoint.get("included_changes_digest"),
        "actor": cap.get("actor"),
        "timestamp": cap.get("received_at"),
        "mechanism": {"type": "checkpoint_acceptance_proof", "reference": proof_id},
        "authority": {
            "mode": "direct_checkpoint_acceptance_v1",
            "source": proof_id,
            "principal": cap.get("actor"),
            "granted_at": cap.get("received_at"),
            "presentation": cap.get("presentation"),
            "session": cap.get("session"),
        },
        "evidence": {
            "candidate_revision": candidate.get("revision"),
            "included_changes_digest": checkpoint.get("included_changes_digest"),
            "requirements": list(assurance.get("acceptance_required") or []),
            "checkpoint_acceptance_proof": proof_id,
            "presentation": cap.get("presentation"),
            "session": cap.get("session"),
        },
        "comment": "Direct human checkpoint acceptance derived from a distinct post-checkpoint acceptance proof.",
    }
    accepted_checkpoint = dict(checkpoint)
    accepted_checkpoint["status"] = "accepted"
    accepted_checkpoint["acceptance"] = {"current": acceptance_id}
    authority_file, material_authority, error = _accepted_authority_update(layout,checkpoint_id,acceptance_id,accepted_checkpoint,acceptance)
    if error:
        return {"valid": False, "checkpoint": checkpoint_id, "proof": proof_id, "blockers": [error]}
    updates = [
        (_acceptance_path(layout, acceptance_id), acceptance),
        (checkpoint_path, accepted_checkpoint),
        (authority_file, material_authority),
    ]
    completed = []
    for cid in checkpoint.get("included_changes") or []:
        change, cpath = recs[cid]
        if change.get("status") == "completed":
            continue
        changed = dict(change)
        changed["status"] = "completed"
        changed["checkpoint"] = {"completed_in": checkpoint_id, "acceptance": acceptance_id}
        updates.append((cpath, changed))
        completed.append(cid)
    _atomic_yaml_updates(updates)
    return {
        "valid": True,
        "checkpoint": checkpoint_id,
        "proof": proof_id,
        "acceptance": acceptance_id,
        "completed_changes": completed,
        "trusted_material": material_authority["trusted"],
    }


def finalise_prospective(root,checkpoint_id,authority_id):
    layout=discover_layout(Path(root).resolve()); recs=records(layout); pre=verify(root,checkpoint_id,None,True)
    if not pre.get("valid"): return pre
    checkpoint_item=recs.get(checkpoint_id); pfa_item=recs.get(authority_id)
    if not checkpoint_item: return {"valid":False,"checkpoint":checkpoint_id,"authority":authority_id,"blockers":["checkpoint_missing"]}
    if not pfa_item: return {"valid":False,"checkpoint":checkpoint_id,"authority":authority_id,"blockers":["prospective_authority_missing"]}
    checkpoint,checkpoint_path=checkpoint_item; pfa,_=pfa_item
    blockers,assurance=_pfa_preflight(layout,recs,checkpoint,pfa)
    if blockers: return {"valid":False,"checkpoint":checkpoint_id,"authority":authority_id,"blockers":blockers}
    acceptance_id=_next_acceptance_id(recs); timestamp=_utc_now(); candidate=dict((checkpoint.get("candidate") or {}).get("material") or {})
    acceptance={"id":acceptance_id,"checkpoint":checkpoint_id,"decision":"accepted","candidate":{"material":candidate},"included_changes_digest":checkpoint.get("included_changes_digest"),"actor":{"type":"automated_system","id":"specforge-pfa-finaliser","display_name":"SpecForge prospective finaliser"},"timestamp":timestamp,"mechanism":{"type":"prospective_finalisation_authority","reference":authority_id},"authority":{"mode":"prospective_exact_candidate_v1","source":authority_id,"principal":pfa.get("actor"),"granted_at":pfa.get("timestamp")},"evidence":{"candidate_revision":candidate.get("revision"),"included_changes_digest":checkpoint.get("included_changes_digest"),"requirements":list(assurance.get("acceptance_required") or []),"prospective_authority":authority_id,"human_principal":pfa.get("actor"),"human_authority_timestamp":pfa.get("timestamp"),"proposal_digest":pfa.get("proposal_digest"),"projected_candidate_revision":(pfa.get("projected_candidate") or {}).get("revision"),"checkpoint_verification":"specforge-checkpoint.py finalise preflight"},"comment":"Checkpoint acceptance derived at finalisation time from earlier exact-candidate human authority."}
    accepted_checkpoint=dict(checkpoint); accepted_checkpoint["status"]="accepted"; accepted_checkpoint["acceptance"]={"current":acceptance_id}
    authority_file,material_authority,error=_accepted_authority_update(layout,checkpoint_id,acceptance_id,accepted_checkpoint,acceptance)
    if error: return {"valid":False,"checkpoint":checkpoint_id,"authority":authority_id,"blockers":[error]}
    updates=[(_acceptance_path(layout,acceptance_id),acceptance),(checkpoint_path,accepted_checkpoint),(authority_file,material_authority)]; completed=[]
    for cid in checkpoint.get("included_changes") or []:
        change,cpath=recs[cid]
        if change.get("status")=="completed": continue
        changed=dict(change); changed["status"]="completed"; changed["checkpoint"]={"completed_in":checkpoint_id,"acceptance":acceptance_id}; updates.append((cpath,changed)); completed.append(cid)
    _atomic_yaml_updates(updates)
    return {"valid":True,"checkpoint":checkpoint_id,"authority":authority_id,"acceptance":acceptance_id,"completed_changes":completed,"trusted_material":material_authority["trusted"]}


def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    vp=sub.add_parser("verify"); vp.add_argument("checkpoint"); vp.add_argument("--acceptance"); vp.add_argument("--root",default="."); vp.add_argument("--allow-historical",action="store_true"); vp.add_argument("--json",action="store_true")
    cp=sub.add_parser("complete"); cp.add_argument("checkpoint"); cp.add_argument("--acceptance",required=True); cp.add_argument("--root",default="."); cp.add_argument("--json",action="store_true")
    fp=sub.add_parser("finalise"); fp.add_argument("checkpoint"); fp.add_argument("--authority",required=True); fp.add_argument("--root",default="."); fp.add_argument("--json",action="store_true")
    fd=sub.add_parser("finalise-direct"); fd.add_argument("checkpoint"); fd.add_argument("--proof",required=True); fd.add_argument("--root",default="."); fd.add_argument("--json",action="store_true")
    dp=sub.add_parser("digest"); dp.add_argument("changes",nargs="+"); dp.add_argument("--json",action="store_true")
    a=ap.parse_args()
    if a.cmd=="digest": out={"valid":True,"digest":change_set_digest(a.changes),"changes":sorted(a.changes)}
    elif a.cmd=="verify": out=verify(a.root,a.checkpoint,a.acceptance,not a.allow_historical)
    elif a.cmd=="finalise": out=finalise_prospective(a.root,a.checkpoint,a.authority)
    elif a.cmd=="finalise-direct": out=finalise_direct(a.root,a.checkpoint,a.proof)
    else: out=complete(a.root,a.checkpoint,a.acceptance)
    print(json.dumps(out,indent=2) if a.json else out); return 0 if out.get("valid") else 1
if __name__=="__main__": raise SystemExit(main())