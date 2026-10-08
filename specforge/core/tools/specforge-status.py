#!/usr/bin/env python3
"""Render current SpecForge project/bootstrap status from canonical repository evidence."""
from pathlib import Path
import argparse, hashlib, json, re, subprocess, sys, yaml
from specforge_project import SUPPORTED_LIFECYCLE_ENFORCEMENT_PROFILES, canonical_artifact_digest, discover_layout, iter_record_files, load_yaml, relative
from specforge_authority import evaluate as evaluate_material_authority

TERMINAL_CHANGE_STATUSES = {"completed", "rejected", "cancelled"}
RECONCILIATION_CONTEXT_ONLY = "context_only"
RECONCILIATION_DURABLE_UPDATE = "durable_update"
SUPPORTED_RECONCILIATION_MODES = {RECONCILIATION_CONTEXT_ONLY, RECONCILIATION_DURABLE_UPDATE}


def _alpha_revision(value):
    match=re.search(r"-alpha\.(\d+)$",str(value or ""))
    return int(match.group(1)) if match else None

def _scope_paths(proposal):
    out=set()
    for item in proposal.get("declared_scope") or []:
        if not isinstance(item,dict): continue
        for key in ("path","to"):
            value=item.get(key)
            if isinstance(value,str) and value.strip(): out.add(value.strip().replace("\\","/").lstrip("./"))
    return out

def _reconciliation_mode(proposal):
    binding=(proposal or {}).get("project_definition_reconciliation") or {}
    mode=binding.get("mode")
    if mode is None:
        revision=_alpha_revision((proposal or {}).get("proposed_specification_version"))
        if revision is not None and revision>=26: return None,"project_definition_reconciliation_mode_missing"
        return RECONCILIATION_DURABLE_UPDATE,None
    if mode not in SUPPORTED_RECONCILIATION_MODES: return None,"project_definition_reconciliation_mode_unknown"
    return mode,None

def _project_definition_path(layout,binding):
    value=binding.get("path")
    if value: return (layout.root/str(value)).resolve()
    configured=(layout.manifest.get("experience") or {}).get("project_definition")
    return (layout.root/str(configured)).resolve() if configured else (layout.root/"PROJECT.md").resolve()

def _reconciliation_blockers(layout,proposal):
    if not isinstance(proposal,dict): return []
    binding=proposal.get("project_definition_reconciliation") or {}
    if not binding: return []
    mode, blocker=_reconciliation_mode(proposal)
    if blocker: return [blocker]
    definition=_project_definition_path(layout,binding)
    rel=str(binding.get("path") or "").replace("\\","/").lstrip("./")
    scope=_scope_paths(proposal)
    if mode==RECONCILIATION_CONTEXT_ONLY:
        out=[]
        if rel in scope: out.append("project_definition_context_only_in_scope")
        if not definition.is_file(): out.append("project_definition_missing")
        else:
            digest=hashlib.sha256(definition.read_bytes()).hexdigest()
            if digest!=binding.get("sha256"): out.append("project_definition_context_digest_changed")
        return out
    return [] if rel in scope else ["project_definition_not_in_approved_scope"]


def _material_reconciliation_summary(layout):
    try:
        authority=evaluate_material_authority(layout)
    except Exception as exc:
        return {"required":True,"kind":"ambiguous_material","paths":[],"repairable":False,"blockers":["material_authority_evaluation_failed"],"error":str(exc)}
    details=authority.get("details") or {}
    reconciliation=details.get("reconciliation") or {}
    kind=reconciliation.get("kind")
    required=bool(kind) or "material_reconciliation_required" in (authority.get("blockers") or []) or "authority_bookkeeping_reconciliation_required" in (authority.get("blockers") or [])
    return {
        "required":required,
        "kind":kind,
        "paths":list(reconciliation.get("paths") or []),
        "repairable":bool(reconciliation.get("repairable")),
        "blockers":list(authority.get("blockers") or []),
        "trusted_revision":details.get("trusted_revision"),
        "current_identity":details.get("current_identity"),
        "authorized_by":details.get("authorized_by"),
        "authority_bookkeeping":details.get("authority_bookkeeping"),
    }


def discover_records(layout):
    records={}
    for path in iter_record_files(layout):
        try: data=load_yaml(path)
        except Exception: continue
        if isinstance(data,dict) and data.get("id"):
            records[str(data["id"])]= {"data":data,"path":relative(layout,path),"file":path}
    return records


def record_ref(records,record_id):
    if not record_id: return None
    record=records.get(str(record_id))
    if not record: return {"id":record_id,"status":"missing"}
    return {"id":record_id,"status":"present","path":record["path"],"record":record["data"]}


def public_ref(item,extra_fields=()):
    if item is None: return None
    result={key:value for key,value in item.items() if key!="record"}
    if item.get("status")=="present":
        for field in extra_fields: result[field]=item["record"].get(field)
    return result


def manifest_artifact(layout,declared_path,label,gaps):
    if not declared_path:
        gaps.append(f"Manifest does not declare {label}"); return {"declared_path":declared_path,"status":"missing"}
    path=(layout.root/str(declared_path)).resolve()
    try: display_path=relative(layout,path)
    except Exception: display_path=str(path)
    status="present" if path.is_file() else "missing"
    if status=="missing": gaps.append(f"Missing {label} {declared_path}")
    return {"declared_path":declared_path,"path":display_path,"status":status}


def effective_approval(records,change_id,proposal_id,approval_ids,controlled):
    proposal=records.get(str(proposal_id))
    if not proposal: return {"status":"invalid" if controlled else "historical_unverified","reason":"current_proposal_missing"}
    actual=canonical_artifact_digest(proposal["file"]) if controlled else None
    saw_approval=False
    for approval_id in approval_ids or []:
        rec=records.get(str(approval_id))
        if not rec: continue
        a=rec["data"]
        if a.get("proposal")!=proposal_id or a.get("change")!=change_id: continue
        if a.get("decision")!="approved" or (a.get("actor") or {}).get("type")!="human": continue
        saw_approval=True
        if not controlled:
            return {"status":"historical_approved","approval":approval_id,"verification":"pre_controlled_v1"}
        expected=(a.get("evidence") or {}).get("proposal_digest") or (a.get("scope") or {}).get("proposal_sha256")
        if expected and expected==actual:
            return {"status":"approved","approval":approval_id,"proposal_digest":actual}
    if not controlled:
        return {"status":"historical_unverified","reason":"historical_human_approval_missing" if not saw_approval else "historical_approval_not_verifiable_under_current_contract"}
    return {"status":"invalid" if saw_approval else "unapproved","reason":"valid_exact_human_approval_missing" if saw_approval else "approval_missing"}


def authority_state(change_status,approval,controlled):
    if change_status in TERMINAL_CHANGE_STATUSES: return "completed" if change_status=="completed" else change_status
    if not controlled:
        return change_status or "historical"
    approved=approval.get("status")=="approved"
    if change_status in {"approved","in_progress","implemented","validated"}: return change_status if approved else "invalid"
    if approved: return "authorised"
    if approval.get("status")=="invalid": return "invalid"
    return "proposed"


def build_change_summary(records,change_id,change_record,gaps):
    data=change_record["data"]
    profile=(data.get("governance") or {}).get("lifecycle_enforcement")
    controlled=profile in SUPPORTED_LIFECYCLE_ENFORCEMENT_PROFILES
    item={"id":change_id,"path":change_record["path"],"title":data.get("title"),"classification":data.get("classification"),"status":data.get("status"),"lifecycle_category":"terminal" if data.get("status") in TERMINAL_CHANGE_STATUSES else "open","governance_mode":profile if controlled else "historical","authority_state":None,"effective_approval":None,"current_links":{"impact_analysis":None,"proposal":None,"approvals":[],"implementation_attempts":[],"release":None}}
    impact_id=(data.get("impact_analysis") or {}).get("current")
    if impact_id:
        ref=record_ref(records,impact_id); item["current_links"]["impact_analysis"]=public_ref(ref,("change","revision"))
        if ref["status"]=="missing": gaps.append(f"{change_id}: Missing impact analysis {impact_id}")
        elif ref["record"].get("change")!=change_id: gaps.append(f"{change_id}: Impact analysis {impact_id} links to change {ref['record'].get('change')}")
    proposal_id=(data.get("proposal") or {}).get("current")
    if proposal_id:
        ref=record_ref(records,proposal_id); item["current_links"]["proposal"]=public_ref(ref,("change","revision","status"))
        if item["current_links"]["proposal"] and item["current_links"]["proposal"].get("status")!="missing": item["current_links"]["proposal"]["document_status"]=ref["record"].get("status")
        if ref["status"]=="missing": gaps.append(f"{change_id}: Missing proposal {proposal_id}")
        elif ref["record"].get("change")!=change_id: gaps.append(f"{change_id}: Proposal {proposal_id} links to change {ref['record'].get('change')}")
    for approval_id in data.get("approvals") or []:
        ref=record_ref(records,approval_id); item["current_links"]["approvals"].append(public_ref(ref,("change","proposal","decision","timestamp")))
        if ref["status"]=="missing": gaps.append(f"{change_id}: Missing approval {approval_id}")
        elif ref["record"].get("change")!=change_id: gaps.append(f"{change_id}: Approval {approval_id} links to change {ref['record'].get('change')}")
    approval=effective_approval(records,change_id,proposal_id,data.get("approvals") or [],controlled) if proposal_id else {"status":"unapproved" if controlled else "historical_unverified","reason":"current_proposal_missing"}
    item["effective_approval"]=approval; item["authority_state"]=authority_state(data.get("status"),approval,controlled)
    if item["current_links"]["proposal"]: item["current_links"]["proposal"]["effective_approval"]=approval.get("status")
    for attempt_id in ((data.get("implementation") or {}).get("attempts") or []):
        ref=record_ref(records,attempt_id); item["current_links"]["implementation_attempts"].append(public_ref(ref,("change","proposal","attempt","outcome","source_revision","tests")))
        if ref["status"]=="missing": gaps.append(f"{change_id}: Missing implementation attempt {attempt_id}")
        elif ref["record"].get("change")!=change_id: gaps.append(f"{change_id}: Implementation attempt {attempt_id} links to change {ref['record'].get('change')}")
    release_id=(data.get("release") or {}).get("completed_in")
    if release_id:
        ref=record_ref(records,release_id); item["current_links"]["release"]=public_ref(ref,("version","status"))
        if ref["status"]=="missing": gaps.append(f"{change_id}: Missing release {release_id}")
    return item


def build_status(root,event_limit=10):
    layout=discover_layout(root); manifest=layout.manifest; gaps=[]; records=discover_records(layout)
    sf=manifest.get("specforge") or {}; project=manifest.get("project") or {}; specification=manifest.get("specification") or {}; policy=manifest.get("policy") or {}
    changes=[build_change_summary(records,rid,rec,gaps) for rid,rec in records.items() if rid.startswith("CHG-")]; changes.sort(key=lambda x:x["id"])
    events=[]
    for rid,rec in records.items():
        if not rid.startswith("EVT-"): continue
        e=rec["data"]; events.append({"id":rid,"timestamp":e.get("timestamp"),"event_type":e.get("event_type"),"actor":e.get("actor"),"entity":e.get("entity"),"related":e.get("related"),"path":rec["path"]})
    events.sort(key=lambda x:(str(x.get("timestamp") or ""),x["id"]),reverse=True)
    if event_limit>=0: events=events[:event_limit]
    return {"project_root":str(layout.root),"project_format_mode":layout.mode,"manifest":relative(layout,layout.manifest_path),"project":{"id":project.get("id"),"name":project.get("name")},"specforge":{"project_format":sf.get("project_format"),"core_version":sf.get("core_version"),"data_model_version":sf.get("data_model_version"),"approval_mode":policy.get("approval_mode"),"forensic_traceability":policy.get("forensic_traceability"),"repository_completeness":policy.get("repository_completeness")},"specification":{"authoritative_version":specification.get("current_version"),"product_specification":manifest_artifact(layout,specification.get("product_specification"),"product specification",gaps),"canonical_data_model":manifest_artifact(layout,specification.get("canonical_data_model"),"canonical data model",gaps)},"packs":manifest.get("packs") or [],"changes":{"open":[x for x in changes if x["lifecycle_category"]=="open"],"terminal":[x for x in changes if x["lifecycle_category"]=="terminal"]},"material_reconciliation":_material_reconciliation_summary(layout),"recent_events":events,"gaps":gaps}


def _checkpoint_candidates(records, change_id):
    found=[]
    for rid, rec in records.items():
        if str(rid).startswith("CHK-") and change_id in (rec["data"].get("included_changes") or []):
            data=rec["data"]
            found.append({"id":rid,"status":data.get("status"),"acceptance":(data.get("acceptance") or {}).get("current"),"path":rec["path"]})
    return sorted(found,key=lambda item:item["id"])


def _external_continuation_candidates(layout, change_id):
    paths=layout.manifest.get("paths") or {}
    changes=str(paths.get("changes","specforge/changes")).replace("\\","/").removeprefix("./").rstrip("/")
    rel=f"{changes}/{change_id}.yaml"
    refs=subprocess.run(
        ["git","-C",str(layout.root),"for-each-ref","--format=%(refname:short)\t%(objectname)","refs/heads","refs/remotes"],
        capture_output=True,text=True
    )
    if refs.returncode:
        return []
    current=subprocess.run(["git","-C",str(layout.root),"rev-parse","--abbrev-ref","HEAD"],capture_output=True,text=True)
    current_ref=current.stdout.strip() if current.returncode==0 else None
    grouped={}
    for line in refs.stdout.splitlines():
        if not line.strip() or "\t" not in line: continue
        ref,revision=line.split("\t",1)
        if ref==current_ref or ref.endswith("/HEAD"): continue
        shown=subprocess.run(["git","-C",str(layout.root),"show",f"{ref}:{rel}"],capture_output=True,text=True)
        if shown.returncode: continue
        try: data=yaml.safe_load(shown.stdout)
        except Exception: continue
        if not isinstance(data,dict) or data.get("id")!=change_id: continue
        if data.get("status") in TERMINAL_CHANGE_STATUSES: continue
        key=(revision,data.get("status"))
        item=grouped.setdefault(key,{"revision":revision,"status":data.get("status"),"path":rel,"refs":[]})
        item["refs"].append(ref)
    out=[]
    for item in grouped.values():
        item["refs"]=sorted(set(item["refs"])); out.append(item)
    return sorted(out,key=lambda item:(item["revision"],item["refs"]))


def build_continuation(root, change_id):
    layout=discover_layout(root); records=discover_records(layout); gaps=[]
    material=_material_reconciliation_summary(layout)
    rec=records.get(str(change_id))
    if not rec:
        candidates=_external_continuation_candidates(layout,change_id)
        if not candidates:
            return {"found":False,"change":change_id,"discoverable":False,"blocked":True,"blockers":["change_missing"],"candidates":[],"next_action":None,"material_reconciliation":material}
        blockers=["change_not_in_current_workspace","explicit_workspace_switch_required"]
        if len(candidates)>1: blockers.append("continuation_candidate_ambiguous")
        return {"found":False,"change":change_id,"discoverable":True,"blocked":True,"blockers":blockers,"candidates":candidates,"next_action":None,"material_reconciliation":material}
    item=build_change_summary(records,change_id,rec,gaps)
    current_status=item.get("status"); approval=item.get("effective_approval") or {}
    attempts=item["current_links"].get("implementation_attempts") or []; latest=attempts[-1] if attempts else None
    checkpoints=_checkpoint_candidates(records,change_id); blockers=[]
    proposal=item["current_links"].get("proposal")
    if proposal is None or proposal.get("status")=="missing": blockers.append("current_proposal_missing")
    else:
        proposal_record=records.get(str(proposal.get("id")))
        if proposal_record: blockers += _reconciliation_blockers(layout, proposal_record["data"])
    if material.get("required"):
        blockers.append("material_reconciliation_required")
        blockers.extend(material.get("blockers") or [])
    if current_status not in TERMINAL_CHANGE_STATUSES and approval.get("status")=="invalid": blockers.append("effective_approval_invalid")
    if len([x for x in checkpoints if x.get("status") not in ("rejected","superseded")])>1: blockers.append("checkpoint_state_ambiguous")
    action=None; human=False
    if not blockers:
        if current_status in TERMINAL_CHANGE_STATUSES:
            action=None
        elif current_status in ("proposed","awaiting_approval"):
            if approval.get("status")=="approved": blockers.append("approval_recorded_but_change_status_not_advanced")
            else: action="approval"; human=True
        elif current_status in ("approved","in_progress"):
            action="implementation_validation" if not latest or latest.get("outcome")!="passed" else "advance_to_ready_for_checkpoint"
        elif current_status in ("implemented","validated"):
            action="advance_to_ready_for_checkpoint" if latest and latest.get("outcome")=="passed" else "implementation_validation"
        elif current_status=="ready_for_checkpoint":
            active=[x for x in checkpoints if x.get("status") not in ("rejected","superseded")]
            if not active: action="checkpoint_presentation"
            elif active[-1].get("status")=="accepted" or active[-1].get("acceptance"): blockers.append("checkpoint_accepted_but_change_not_completed")
            else: action="checkpoint_acceptance"; human=True
        else:
            blockers.append("unsupported_change_status:"+str(current_status))
    return {"found":True,"change":change_id,"status":current_status,"authority_state":item.get("authority_state"),"proposal":proposal,"effective_approval":approval,"latest_implementation":latest,"checkpoints":checkpoints,"material_reconciliation":material,"blocked":bool(blockers),"blockers":sorted(set(blockers)),"next_action":None if blockers else action,"human_boundary":False if blockers else human}


def human_continuation(data):
    if not data.get("found"):
        if data.get("discoverable"):
            refs=[ref for item in data.get("candidates") or [] for ref in item.get("refs") or []]
            return f"Continuation requires an explicit workspace/ref choice for {data.get('change')}: "+", ".join(refs)
        return f"Continuation unavailable: {data.get('change')} was not found."
    lines=[f"Continuation: {data.get('change')}",f"Status: {data.get('status')}  Authority: {data.get('authority_state')}"]
    reconciliation=data.get("material_reconciliation") or {}
    if reconciliation.get("required"):
        lines.append(f"Material reconciliation: {reconciliation.get('kind') or 'required'}")
        if reconciliation.get("paths"): lines.append("Reconciliation paths: "+", ".join(reconciliation.get("paths") or []))
    if data.get("blocked"): lines.append("Blocked: "+", ".join(data.get("blockers") or []))
    elif data.get("next_action"): lines.append("Next governed action: "+data["next_action"])
    else: lines.append("Next governed action: none")
    return "\n".join(lines)


def link_label(link):
    if not link: return "<none>"
    suffix=""
    if link.get("status")=="missing": suffix=" [missing]"
    elif link.get("decision"): suffix=f" [{link['decision']}]"
    elif link.get("outcome"): suffix=f" [{link['outcome']}]"
    elif link.get("effective_approval"): suffix=f" [{link['effective_approval']}; document={link.get('document_status',link.get('status'))}]"
    return f"{link.get('id')}{suffix}"


def human(status):
    project=status["project"]; sf=status["specforge"]; specification=status["specification"]
    lines=["SpecForge project status",f"Project: {project.get('id')}  {project.get('name')}",f"Layout: {status.get('project_format_mode')}  Project format: {sf.get('project_format')}",f"Core: {sf.get('core_version')}  Data model: {sf.get('data_model_version')}",f"Approval mode: {sf.get('approval_mode')}",f"Authoritative specification: {specification.get('authoritative_version')}","","Open changes:"]
    if not status["changes"]["open"]: lines.append("  <none>")
    for change in status["changes"]["open"]:
        links=change["current_links"]; lines.append(f"  {change['id']} [{change.get('status')}; authority={change.get('authority_state')}] {change.get('title')}")
        lines.append(f"    impact: {link_label(links['impact_analysis'])}"); lines.append(f"    proposal: {link_label(links['proposal'])}"); lines.append(f"    approvals: {', '.join(link_label(x) for x in links['approvals']) or '<none>'}"); lines.append(f"    implementation: {', '.join(link_label(x) for x in links['implementation_attempts']) or '<none>'}"); lines.append(f"    release: {link_label(links['release'])}")
    reconciliation=status.get("material_reconciliation") or {}
    lines.extend(["","Material reconciliation:"])
    if reconciliation.get("required"):
        lines.append(f"  required: {reconciliation.get('kind') or 'yes'}")
        if reconciliation.get("paths"): lines.append("  paths: "+", ".join(reconciliation.get("paths") or []))
        if reconciliation.get("blockers"): lines.append("  blockers: "+", ".join(reconciliation.get("blockers") or []))
    else:
        lines.append("  none")
    lines.extend(["","Terminal changes:"])
    if not status["changes"]["terminal"]: lines.append("  <none>")
    for change in status["changes"]["terminal"]: lines.append(f"  {change['id']} [{change.get('status')}; authority={change.get('authority_state')}] {change.get('title')}")
    lines.extend(["","Recent forensic events:"])
    if not status["recent_events"]: lines.append("  <none>")
    for event in status["recent_events"]:
        entity=event.get("entity") or {}; lines.append(f"  {event.get('timestamp','?')}  {event['id']}  {event.get('event_type','?')}  {entity.get('id','?')}")
    lines.append("")
    if status["gaps"]: lines.append("Evidence gaps:"); lines.extend(f"  ! {gap}" for gap in status["gaps"])
    else: lines.append("Evidence gaps: none detected in explicit project/current links")
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description="Render current SpecForge project/bootstrap status from canonical evidence."); parser.add_argument("--root",default="."); parser.add_argument("--json",action="store_true",dest="as_json"); parser.add_argument("--events",type=int,default=10); parser.add_argument("--continuation"); args=parser.parse_args()
    try:
        if args.continuation:
            result=build_continuation(Path(args.root).resolve(),args.continuation)
            print(json.dumps(result,indent=2) if args.as_json else human_continuation(result))
            return 0 if result.get("found") else 1
        status=build_status(Path(args.root).resolve(),args.events)
    except Exception as exc: print(f"ERROR: Unable to read SpecForge project: {exc}",file=sys.stderr); return 1
    print(json.dumps(status,indent=2) if args.as_json else human(status)); return 0

if __name__=="__main__": sys.exit(main())