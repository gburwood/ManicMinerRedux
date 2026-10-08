#!/usr/bin/env python3
"""Bounded incremental and exhaustive integrity validation for SpecForge."""
from __future__ import annotations

from pathlib import Path
import argparse, copy, datetime as dt, hashlib, json, os, re, subprocess, sys, tempfile, time
import yaml, jsonschema

from specforge_project import canonical_artifact_digest, configured_path, discover_layout, iter_record_files, load_yaml, relative, verify_source_revision
from specforge_integration import PROFILE as INTEGRATION_PROFILE, verify_integration_evidence
from specforge_governance_tier import TIER_ORDER, GovernanceTierError, classify_entries, load_policy, validate_declared_scope, verify_policy_archive

INCREMENTAL_PROFILE="incremental_integrity_v1"
FULL_PROFILE="full_integrity_v1"
STATE_VERSION=1
PARTITION_COUNT=256
MASK_256=(1<<256)-1
TERMINAL={"completed","rejected","cancelled","superseded"}
PROGRESS_DEFAULT="specforge/evidence/integrity/progress.jsonl"
FULL_VALIDATOR_HEARTBEAT_SECONDS=10.0
TYPE_INFO=[
 ("acceptance-criterion",re.compile(r"^AC-\d{4,}-\d{2,}$")),
 ("implementation-attempt",re.compile(r"^IMP-\d{4,}-\d{2,}$")),
 ("impact-analysis",re.compile(r"^IA-\d{4,}-\d{2,}$")),
 ("proposal",re.compile(r"^PROP-\d{4,}-\d{2,}$")),
 ("requirement",re.compile(r"^REQ-\d{4,}$")),
 ("change",re.compile(r"^CHG-\d{4,}$")),
 ("approval",re.compile(r"^APR-\d{4,}$")),
 ("checkpoint",re.compile(r"^CHK-\d{4,}$")),
 ("checkpoint-acceptance-proof",re.compile(r"^CAP-\d{4,}$")),
 ("checkpoint-acceptance",re.compile(r"^ACC-\d{4,}$")),
 ("prospective-finalisation-authority",re.compile(r"^PFA-\d{4,}$")),
 ("decision",re.compile(r"^ADR-\d{4,}$")),
 ("forensic-event",re.compile(r"^EVT-\d{6,}$")),
 ("release",re.compile(r"^REL-\d{4,}$")),
 ("build",re.compile(r"^BLD-\d{4,}$")),
 ("environment",re.compile(r"^ENV-[A-Z0-9_-]+$")),
 ("deployment",re.compile(r"^DEP-\d{4,}$")),
]

def classify_id(value):
    for kind,pat in TYPE_INFO:
        if pat.match(str(value)): return kind
    return None

def git(root,*args):
    return subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True)

def git_text(root,*args):
    r=git(root,*args)
    return None if r.returncode else r.stdout.strip()

def sha(data): return hashlib.sha256(data).hexdigest()
def cjson(value): return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")

class Progress:
    def __init__(self,path,mode,append=False):
        self.path=path; self.mode=mode; self.started=time.monotonic()
        if path:
            path.parent.mkdir(parents=True,exist_ok=True)
            if not append: path.write_text("",encoding="utf-8")
    def emit(self,phase,processed=None,total=None,substage=None,**extra):
        row={"mode":self.mode,"phase":phase,"processed":processed,"total":total,
             "elapsed_seconds":round(time.monotonic()-self.started,3),"substage":substage,
             "timestamp":dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")}
        row.update(extra)
        if self.path:
            with self.path.open("a",encoding="utf-8",newline="\n") as h: h.write(json.dumps(row,sort_keys=True)+"\n")
        print("SPECFORGE_PROGRESS "+json.dumps(row,sort_keys=True),file=sys.stderr,flush=True)

def state_path(layout):
    ev=(layout.manifest.get("paths") or {}).get("evidence","specforge/evidence")
    return (layout.root/ev/"integrity/state.json").resolve()

def progress_path(layout,value):
    if value=="-": return None
    if value:
        p=Path(value); return p.resolve() if p.is_absolute() else (layout.root/p).resolve()
    return (configured_path(layout,"evidence","specforge/evidence")/"integrity/progress.jsonl").resolve()

def policy(layout): return ((layout.manifest.get("policy") or {}).get("integrity") or {})
def roots_rel(layout):
    out=[]
    for p in layout.record_roots:
        try: out.append(p.resolve().relative_to(layout.root.resolve()).as_posix())
        except ValueError: pass
    return out

def digest_named(root,paths):
    rows=[]
    for p in sorted(paths,key=lambda x:x.as_posix()):
        if p.is_file(): rows.append((p.resolve().relative_to(root.resolve()).as_posix(),canonical_artifact_digest(p)))
    return sha(cjson(rows))

def fingerprints(layout):
    tools=[layout.tool_root/"validate-specforge.py",layout.tool_root/"specforge-integrity.py"]
    schemas=list(configured_path(layout,"schemas","specforge/core/schemas").glob("*.schema.json"))
    policy_file=layout.core_root/"policy/governance-tier-policy.yaml"
    try: core=load_yaml(layout.core_root/"core.yaml").get("core_version")
    except Exception: core=None
    return {"core_version":core,"validator":digest_named(layout.root,tools),"schemas":digest_named(layout.root,schemas),
            "governance_policy":canonical_artifact_digest(policy_file) if policy_file.is_file() else None}

def head(layout): return git_text(layout.root,"rev-parse","HEAD")
def tree(layout,revision): return git_text(layout.root,"rev-parse",f"{revision}^{{tree}}")

def number(rid):
    m=re.search(r"-(\d{4,})(?:-\d{2,})?$",rid)
    return int(m.group(1)) if m else None

def change_number(rid):
    m=re.search(r"-(\d{4,})(?:-\d{2,})?$",rid)
    return m.group(1) if m else None

def path_candidates(layout,rid):
    paths=layout.manifest.get("paths") or {}
    changes=str(paths.get("changes","specforge/changes")).removeprefix("./").rstrip("/")
    decisions=str(paths.get("decisions","specforge/decisions")).removeprefix("./").rstrip("/")
    history=str(paths.get("history","specforge/history")).removeprefix("./").rstrip("/")
    n=change_number(rid)
    if rid.startswith("CHG-"): return [f"{changes}/{rid}.yaml"]
    if rid.startswith(("IA-","PROP-")): return [f"{changes}/CHG-{n}/{rid}.yaml"] if n else []
    if rid.startswith("IMP-"): return [f"{changes}/CHG-{n}/implementation/{rid}.yaml"] if n else []
    if rid.startswith("CHK-"): return [f"{history}/checkpoints/{rid}.yaml"]
    if rid.startswith("CAP-"): return [f"{history}/acceptance-proofs/{rid}.yaml"]
    if rid.startswith("ACC-"): return [f"{history}/acceptances/{rid}.yaml"]
    if rid.startswith("EVT-"): return [f"{history}/events/{rid}.yaml"]
    if rid.startswith("ADR-"): return [f"{decisions}/{rid}.yaml"]
    if rid.startswith("REL-"): return [f"{history}/releases/{rid}.yaml"]
    if rid.startswith("BLD-"): return [f"{history}/releases/builds/{rid}.yaml"]
    if rid.startswith("ENV-"): return [f"{history}/releases/environments/{rid}.yaml"]
    if rid.startswith("DEP-"): return [f"{history}/releases/deployments/{rid}.yaml"]
    if rid.startswith(("REQ-","AC-")): return [f"specforge/spec/requirements/{rid}.yaml",f"{decisions}/requirements/{rid}.yaml"]
    return []

def tree_paths_for_id(layout,revision,rid):
    out=[]
    for root in roots_rel(layout):
        pat=f":(glob){root}/**/{rid}.yaml"
        r=git(layout.root,"ls-tree","-r","--name-only",revision,"--",pat)
        if not r.returncode: out.extend(x.strip() for x in r.stdout.splitlines() if x.strip())
    return sorted(set(out))

def partition_key(rid): return hashlib.sha256(rid.encode()).hexdigest()[:2]
def entry_hash(rid,kind,path,digest): return int(hashlib.sha256(f"{rid}\0{kind}\0{path}\0{digest}".encode()).hexdigest(),16)

def partition_apply(parts,rid,kind,path,digest,direction):
    k=partition_key(rid); item=dict(parts.get(k) or {"count":0,"xor":"0"*64,"sum":"0"*64})
    value=entry_hash(rid,kind,path,digest)
    item["count"]=int(item["count"])+direction
    item["xor"]=f"{int(item['xor'],16)^value:064x}"
    item["sum"]=f"{(int(item['sum'],16)+(value if direction>0 else -value))&MASK_256:064x}"
    if item["count"]<0: raise ValueError("partition_count_underflow")
    if item["count"]: parts[k]=item
    else: parts.pop(k,None)

def registry_digest(parts): return sha(cjson(parts))

def schema_map(layout):
    out={}
    for p in configured_path(layout,"schemas","specforge/core/schemas").glob("*.schema.json"):
        try: out[p.name.replace(".schema.json","")]=json.loads(p.read_text(encoding="utf-8"))
        except Exception: pass
    return out

def record_entry(layout,path,data):
    rid=str(data["id"])
    return {"id":rid,"kind":classify_id(rid),"path":relative(layout,path),"digest":canonical_artifact_digest(path),"data":data}

def add_range(ranges,n):
    values=sorted([list(x) for x in ranges]+[[n,n]]); merged=[]
    for a,b in values:
        if not merged or a>merged[-1][1]+1: merged.append([a,b])
        else: merged[-1][1]=max(merged[-1][1],b)
    return merged

def in_ranges(ranges,n):
    return any(a<=n<=b for a,b in ranges)

def source_number(value,prefix):
    if not value or not str(value).startswith(prefix+"-"): return None
    tail=str(value).split("-",1)[1]
    return int(tail) if tail.isdigit() else None

def mutable_ids(records):
    out=set()
    for rid,rec in records.items():
        d=rec["data"]
        if rec["kind"]=="change" and d.get("status") not in TERMINAL:
            out.add(rid)
            if d.get("status") in {"draft","proposed","awaiting_approval"}:
                for x in ((d.get("impact_analysis") or {}).get("current"),(d.get("proposal") or {}).get("current")):
                    if x: out.add(str(x))
            out.update(str(x) for x in ((d.get("implementation") or {}).get("attempts") or []))
        elif rec["kind"]=="checkpoint" and d.get("status")!="accepted": out.add(rid)
    return sorted(out)

def build_state(layout,progress,last_full):
    paths=list(iter_record_files(layout)); records={}; parts={}; counts={}; maxima={}; exceptions={}; cap=[]; pfa=[]
    progress.emit("state_build",0,len(paths),"indexing canonical records")
    for i,path in enumerate(paths,1):
        d=load_yaml(path)
        if not isinstance(d,dict) or not d.get("id"): continue
        e=record_entry(layout,path,d); rid=e["id"]; kind=e["kind"]
        if not kind: continue
        records[rid]=e; counts[kind]=counts.get(kind,0)+1
        n=number(rid)
        if n is not None: maxima[kind]=max(maxima.get(kind,0),n)
        partition_apply(parts,rid,kind,e["path"],e["digest"],1)
        candidates=path_candidates(layout,rid)
        if Path(e["path"]).name!=f"{rid}.yaml" or (candidates and e["path"] not in candidates): exceptions[rid]=e["path"]
        if kind=="checkpoint-acceptance":
            src=(d.get("authority") or {}).get("source")
            a=source_number(src,"CAP"); b=source_number(src,"PFA")
            if a is not None: cap=add_range(cap,a)
            if b is not None: pfa=add_range(pfa,b)
        if i==len(paths) or i%100==0: progress.emit("state_build",i,len(paths),"indexing canonical records")
    rev=head(layout)
    state={"version":STATE_VERSION,"profile":INCREMENTAL_PROFILE,"status":"valid","validated_revision":rev,
           "validated_tree":tree(layout,rev) if rev else None,"fingerprints":fingerprints(layout),
           "inventory":{"total":sum(counts.values()),"by_kind":dict(sorted(counts.items())),"max_numeric":dict(sorted(maxima.items()))},
           "registry":{"algorithm":"git_anchored_partitioned_accumulator_v1","partition_count":PARTITION_COUNT,
                       "partitions":dict(sorted(parts.items())),"digest":registry_digest(parts),"path_exceptions":dict(sorted(exceptions.items()))},
           "consumed_authority":{"cap_ranges":cap,"pfa_ranges":pfa},"mutable_ids":mutable_ids(records),
           "last_full_audit":last_full,"last_validation":None}
    return state,records

def write_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",dir=str(path.parent)); os.close(fd); t=Path(tmp)
    try:
        t.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n"); os.replace(t,path)
    finally:
        if t.exists(): t.unlink()

def full_validate(layout,progress):
    validator=layout.tool_root/"validate-specforge.py"
    args=[sys.executable,"-B",str(validator),str(layout.root)]
    if progress.path: args+=["--progress-file",str(progress.path),"--progress-append"]
    progress.emit("full_validation",None,None,"running exhaustive validator")
    # Keep validator stdout isolated from the integrity command's JSON result, but
    # inherit stderr so nested SPECFORGE_PROGRESS events remain visible while the
    # exhaustive validator is still running. Emit a parent heartbeat independently
    # of child record progress so one expensive validator operation cannot appear dead.
    with tempfile.TemporaryFile(mode="w+",encoding="utf-8") as captured_stdout:
        process=subprocess.Popen(args,stdout=captured_stdout,stderr=None,text=True)
        try:
            while process.poll() is None:
                time.sleep(FULL_VALIDATOR_HEARTBEAT_SECONDS)
                if process.poll() is None:
                    progress.emit(
                        "full_validation",
                        None,
                        None,
                        "exhaustive validator still running",
                        child_pid=process.pid,
                    )
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            raise
        captured_stdout.seek(0)
        stdout=captured_stdout.read()
    if stdout: print(stdout,end="",file=sys.stderr)
    return process.returncode==0

def full_audit(layout,progress,output):
    if not full_validate(layout,progress):
        progress.emit("failed",None,None,"full integrity validation failed")
        return {"ok":False,"mode":FULL_PROFILE,"blockers":["full_validator_failed"]}
    now=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"); rev=head(layout)
    state,_=build_state(layout,progress,{"revision":rev,"tree":tree(layout,rev),"audited_at":now,"record_count":None})
    state["last_full_audit"]["record_count"]=state["inventory"]["total"]
    metrics={"changed_record_count":0,"closure_record_count":0,"historical_records_parsed":state["inventory"]["total"],
             "index_partitions_read":PARTITION_COUNT,"index_partitions_written":len(state["registry"]["partitions"])}
    state["last_validation"]={"mode":FULL_PROFILE,"validated_at":now,"metrics":metrics}
    if output: write_json(output,state)
    progress.emit("complete",state["inventory"]["total"],state["inventory"]["total"],"full integrity audit complete")
    return {"ok":True,"mode":FULL_PROFILE,"state":state,"metrics":metrics,"blockers":[]}

def load_state(path):
    try: d=json.loads(path.read_text(encoding="utf-8"))
    except Exception: return None
    return d if isinstance(d,dict) and d.get("version")==STATE_VERSION and d.get("profile")==INCREMENTAL_PROFILE else None

def state_receipt(layout,path,state):
    rel=relative(layout,path); receipt=git_text(layout.root,"log","-1","--format=%H","--",rel)
    if not receipt: return False,"integrity_receipt_missing"
    parent=git_text(layout.root,"rev-parse",f"{receipt}^")
    if parent!=state.get("validated_revision"): return False,"integrity_receipt_parent_mismatch"
    r=git(layout.root,"diff-tree","--no-commit-id","--name-only","-r",receipt)
    names=[x.strip() for x in r.stdout.splitlines() if x.strip()] if not r.returncode else []
    if names!=[rel]: return False,"integrity_receipt_not_state_only"
    if git(layout.root,"merge-base","--is-ancestor",receipt,head(layout) or "").returncode: return False,"integrity_receipt_not_ancestor"
    if tree(layout,state.get("validated_revision"))!=state.get("validated_tree"): return False,"integrity_validated_tree_mismatch"
    return True,receipt

def full_age(layout,state):
    audit=(state or {}).get("last_full_audit") or {}; stamp=audit.get("audited_at")
    if not stamp: return None
    try: return (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(str(stamp).replace("Z","+00:00"))).total_seconds()/86400
    except Exception: return None

def deep_reason(layout,state,path):
    if not state or state.get("status")!="valid": return "integrity_state_missing_or_invalid"
    ok,reason=state_receipt(layout,path,state)
    if not ok: return reason
    if state.get("fingerprints")!=fingerprints(layout): return "integrity_semantics_changed"
    age=full_age(layout,state)
    if age is None: return "full_audit_age_unknown"
    if age>int(policy(layout).get("maximum_full_audit_age_days") or 45): return "full_audit_age_exceeded"
    return None

def diff_records(layout,base):
    r=git(layout.root,"diff","--name-status","--find-renames",base,"HEAD","--",*roots_rel(layout))
    if r.returncode: raise RuntimeError("git_record_diff_failed:"+r.stderr.strip())
    out=[]
    for line in r.stdout.splitlines():
        p=line.split("\t"); status=p[0]
        if status.startswith("R") and len(p)>=3: out.append({"status":"R","old_path":p[1],"path":p[2]})
        elif len(p)>=2: out.append({"status":status[:1],"path":p[1]})
    return out

def yaml_at(layout,revision,path):
    r=git(layout.root,"show",f"{revision}:{path}")
    if r.returncode: return None,None
    try: d=yaml.safe_load(r.stdout)
    except Exception: return None,None
    return (d,sha(r.stdout.replace("\r\n","\n").replace("\r","\n").encode())) if isinstance(d,dict) else (None,None)

def current_record(layout,path):
    p=(layout.root/path).resolve()
    if not p.is_file(): return None,None
    try: d=load_yaml(p)
    except Exception: return None,None
    return (d,canonical_artifact_digest(p)) if isinstance(d,dict) else (None,None)

def contextual_paths(layout,rid,source):
    if not isinstance(source,dict):
        return []
    if str(rid).startswith("APR-") and source.get("kind") in {"change","proposal"}:
        change_id = source.get("id") if source.get("kind")=="change" else (source.get("data") or {}).get("change")
        if change_id:
            changes=str((layout.manifest.get("paths") or {}).get("changes","specforge/changes")).removeprefix("./").rstrip("/")
            return [f"{changes}/{change_id}/approvals/{rid}.yaml"]
    return []

def historical(layout,state,rid,cache,metrics,source=None):
    if rid in cache: return cache[rid]
    exc=((state.get("registry") or {}).get("path_exceptions") or {}).get(rid)
    candidates=([exc] if exc else []) + contextual_paths(layout,rid,source) + path_candidates(layout,rid)
    candidates=list(dict.fromkeys(x for x in candidates if x))
    if not candidates: candidates=tree_paths_for_id(layout,state["validated_revision"],rid)
    for path in candidates:
        d,digest=yaml_at(layout,state["validated_revision"],path)
        if isinstance(d,dict) and str(d.get("id"))==rid:
            metrics["historical_records_parsed"]+=1; cache[rid]={"data":d,"digest":digest,"path":path,"kind":classify_id(rid)}; return cache[rid]
    cache[rid]=None; return None

def refs(kind,d):
    out=[]; add=lambda f,v,k=None: out.append((f,str(v),k)) if v else None
    if kind=="requirement":
        add("introduced.by_change",(d.get("introduced") or {}).get("by_change"),"change")
        for x in d.get("acceptance_criteria") or []: add("acceptance_criteria",x,"acceptance-criterion")
    elif kind=="acceptance-criterion": add("requirement",d.get("requirement"),"requirement")
    elif kind=="impact-analysis": add("change",d.get("change"),"change")
    elif kind=="proposal":
        add("change",d.get("change"),"change")
        for x in d.get("based_on_impact_analysis") or []: add("based_on_impact_analysis",x,"impact-analysis")
        for x in d.get("approvals") or []: add("approvals",x,"approval")
    elif kind=="approval": add("change",d.get("change"),"change"); add("proposal",d.get("proposal"),"proposal")
    elif kind=="implementation-attempt": add("change",d.get("change"),"change"); add("proposal",d.get("proposal"),"proposal")
    elif kind=="change":
        add("impact_analysis.current",(d.get("impact_analysis") or {}).get("current"),"impact-analysis"); add("proposal.current",(d.get("proposal") or {}).get("current"),"proposal")
        for x in d.get("approvals") or []: add("approvals",x,"approval")
        for x in ((d.get("implementation") or {}).get("attempts") or []): add("implementation.attempts",x,"implementation-attempt")
        add("release.completed_in",(d.get("release") or {}).get("completed_in"),"release")
        for x in ((d.get("relationships") or {}).get("depends_on") or []): add("relationships.depends_on",x,"change")
    elif kind=="checkpoint":
        for x in d.get("included_changes") or []: add("included_changes",x,"change")
        add("acceptance.current",(d.get("acceptance") or {}).get("current"),"checkpoint-acceptance")
    elif kind=="checkpoint-acceptance-proof": add("checkpoint",d.get("checkpoint"),"checkpoint")
    elif kind=="checkpoint-acceptance": add("checkpoint",d.get("checkpoint"),"checkpoint"); add("authority.source",(d.get("authority") or {}).get("source"))
    elif kind=="release":
        for x in d.get("changes") or []: add("changes",x,"change")
        add("build.id",(d.get("build") or {}).get("id"),"build")
        for x in d.get("deployments") or []: add("deployments",x,"deployment")
    elif kind=="deployment": add("release",d.get("release"),"release"); add("environment",d.get("environment"),"environment"); add("build.id",(d.get("build") or {}).get("id"),"build")
    return out

def lookup(rid,changed,layout,state,cache,metrics,source=None): return changed.get(rid) or historical(layout,state,rid,cache,metrics,source)
def stamp(v):
    try: return dt.datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception: return None

def approval_errors(e,changed,layout,state,cache,metrics):
    d=e["data"]; errors=[]
    if d.get("decision")!="approved": return errors
    if (d.get("actor") or {}).get("type")!="human": errors.append(f"approval_human_actor_missing:{e['id']}")
    p=lookup(str(d.get("proposal") or ""),changed,layout,state,cache,metrics)
    if not p: return errors+[f"approval_proposal_missing:{e['id']}"]
    expected=(d.get("evidence") or {}).get("proposal_digest") or (d.get("scope") or {}).get("proposal_sha256")
    if expected!=p.get("digest"): errors.append(f"approval_proposal_digest_mismatch:{e['id']}")
    proof_rel=(d.get("evidence") or {}).get("informed_approval_proof")
    try: proof=load_yaml((layout.root/str(proof_rel)).resolve()) if proof_rel else None
    except Exception: proof=None
    if not isinstance(proof,dict): errors.append(f"approval_informed_proof_invalid:{e['id']}")
    elif proof.get("proposal")!=d.get("proposal") or proof.get("proposal_digest")!=p.get("digest") or proof.get("decision")!=d.get("decision") or proof.get("received_at")!=d.get("timestamp"):
        errors.append(f"approval_informed_proof_binding_mismatch:{e['id']}")
    return errors

def proposal_errors(e,layout):
    d=e["data"]; errors=[]; n=change_number(e["id"])
    if n and d.get("change") and str(d.get("change"))!=f"CHG-{n}":
        errors.append(f"proposal_change_id_mismatch:{e['id']}")
    tier=d.get("governance_tier") or {}
    requested=tier.get("requested")
    scope=d.get("declared_scope") or []
    if not requested and not scope:
        return errors
    if requested not in TIER_ORDER:
        return errors+[f"governance_tier_requested_invalid:{e['id']}"]
    try:
        entries=validate_declared_scope(scope)
        digest=tier.get("policy_digest")
        policy=verify_policy_archive(layout,digest) if digest else load_policy(layout.core_root/"policy/governance-tier-policy.yaml")
        if policy is None:
            raise GovernanceTierError("policy_archive_invalid_or_missing")
        classification=classify_entries(entries,policy,layout)
        minimum=classification.get("classification")
        if classification.get("blocker"):
            raise GovernanceTierError(classification["blocker"])
        if minimum in TIER_ORDER and TIER_ORDER[requested]<TIER_ORDER[minimum]:
            errors.append(f"governance_tier_below_minimum:{e['id']}")
    except GovernanceTierError as exc:
        errors.append(f"governance_tier_classification_failed:{e['id']}:{exc}")
    return errors

def change_errors(e,changed,layout,state,cache,metrics):
    d=e["data"]; errors=[]; approvals=[]
    for aid in d.get("approvals") or []:
        item=lookup(str(aid),changed,layout,state,cache,metrics,source=e)
        if item: approvals.append(item); errors.extend(approval_errors(item,changed,layout,state,cache,metrics))
    if d.get("status") in {"approved","in_progress","implemented","validated","ready_for_checkpoint","completed"}:
        prop=(d.get("proposal") or {}).get("current")
        valid=[x for x in approvals if x["data"].get("proposal")==prop and x["data"].get("decision")=="approved"]
        if not valid: errors.append(f"controlled_change_approval_missing:{e['id']}")
        ats=[stamp(x["data"].get("timestamp")) for x in valid]; ats=[x for x in ats if x]
        for iid in ((d.get("implementation") or {}).get("attempts") or []):
            imp=lookup(str(iid),changed,layout,state,cache,metrics); started=stamp(imp["data"].get("started_at")) if imp else None
            if ats and started and started<min(ats): errors.append(f"implementation_predates_approval:{iid}")
    if d.get("status")=="completed":
        ok=False
        for iid in ((d.get("implementation") or {}).get("attempts") or []):
            item=lookup(str(iid),changed,layout,state,cache,metrics)
            if not item: continue
            imp=item["data"]; required=[x for x in (imp.get("validation_checks") or []) if x.get("required")]; tests=imp.get("tests") or {}
            tests_ok=tests.get("status")=="passed" or (bool(tests.get("passed")) and not tests.get("failed"))
            if imp.get("outcome")!="passed" or not required or any(x.get("status")!="passed" for x in required) or not tests_ok: continue
            integ=imp.get("integration") or {}
            verdict=verify_integration_evidence(layout,imp,mode="static") if integ.get("profile")==INTEGRATION_PROFILE else verify_source_revision(layout,imp.get("source_revision") or {},mode="static",require_provider=False)
            if verdict.get("valid"): ok=True; break
        if not ok: errors.append(f"completion_evidence_invalid:{e['id']}")
    return errors

def binding_errors(e,changed,layout,state,cache,metrics):
    d=e["data"]; errors=[]; cp=lookup(str(d.get("checkpoint") or ""),changed,layout,state,cache,metrics)
    if e["kind"]=="checkpoint-acceptance-proof":
        if (d.get("actor") or {}).get("type")!="human": errors.append(f"cap_human_actor_missing:{e['id']}")
        if cp:
            if d.get("included_changes_digest")!=cp["data"].get("included_changes_digest"): errors.append(f"cap_change_set_mismatch:{e['id']}")
            a=((d.get("candidate") or {}).get("material") or {}); b=((cp["data"].get("candidate") or {}).get("material") or {})
            if a.get("revision")!=b.get("revision") or a.get("file_count")!=b.get("file_count"): errors.append(f"cap_candidate_mismatch:{e['id']}")
    elif e["kind"]=="checkpoint-acceptance" and cp:
        if d.get("included_changes_digest")!=cp["data"].get("included_changes_digest"): errors.append(f"acceptance_change_set_mismatch:{e['id']}")
        a=(((d.get("candidate") or {}).get("material") or {}).get("revision")); b=(((cp["data"].get("candidate") or {}).get("material") or {}).get("revision"))
        if a!=b: errors.append(f"acceptance_candidate_mismatch:{e['id']}")
    return errors

def schema_errors(e,schemas):
    s=schemas.get(e["kind"])
    if not s: return []
    try: jsonschema.Draft202012Validator(s,format_checker=jsonschema.FormatChecker()).validate(e["data"]); return []
    except jsonschema.ValidationError as x:
        loc=".".join(str(y) for y in x.absolute_path) or "<root>"; return [f"schema:{e['path']}:{loc}:{x.message}"]

def update_mutables(state,changed):
    vals=set(state.get("mutable_ids") or [])
    for rid,e in changed.items():
        d=e["data"]
        if e["kind"]=="change":
            ia=str((d.get("impact_analysis") or {}).get("current") or ""); prop=str((d.get("proposal") or {}).get("current") or ""); attempts={str(x) for x in ((d.get("implementation") or {}).get("attempts") or [])}
            vals.discard(rid); vals.discard(ia); vals.discard(prop); vals.difference_update(attempts)
            if d.get("status") not in TERMINAL:
                vals.add(rid)
                if d.get("status") in {"draft","proposed","awaiting_approval"}:
                    if ia: vals.add(ia)
                    if prop: vals.add(prop)
                vals.update(attempts)
        elif e["kind"]=="implementation-attempt":
            (vals.discard if d.get("outcome")=="passed" else vals.add)(rid)
        elif e["kind"]=="checkpoint":
            (vals.discard if d.get("status")=="accepted" else vals.add)(rid)
    state["mutable_ids"]=sorted(x for x in vals if x)

def next_state(layout,state,changed,old,metrics):
    new=copy.deepcopy(state); parts=copy.deepcopy((new.get("registry") or {}).get("partitions") or {}); exceptions=dict((new.get("registry") or {}).get("path_exceptions") or {})
    inv=copy.deepcopy(new.get("inventory") or {}); by=dict(inv.get("by_kind") or {}); maxima=dict(inv.get("max_numeric") or {}); total=int(inv.get("total") or 0)
    for rid,o in old.items():
        cur=changed.get(rid)
        if cur and o["path"]==cur["path"] and o["kind"]==cur["kind"]:
            partition_apply(parts,rid,o["kind"],o["path"],o["digest"],-1); partition_apply(parts,rid,cur["kind"],cur["path"],cur["digest"],1)
    for rid,e in changed.items():
        if rid in old: continue
        partition_apply(parts,rid,e["kind"],e["path"],e["digest"],1); total+=1; by[e["kind"]]=int(by.get(e["kind"]) or 0)+1
        n=number(rid)
        if n is not None: maxima[e["kind"]]=max(int(maxima.get(e["kind"]) or 0),n)
        candidates=path_candidates(layout,rid)
        if Path(e["path"]).name!=f"{rid}.yaml" or (candidates and e["path"] not in candidates): exceptions[rid]=e["path"]
    new["inventory"]={"total":total,"by_kind":dict(sorted(by.items())),"max_numeric":dict(sorted(maxima.items()))}
    new["registry"]={"algorithm":"git_anchored_partitioned_accumulator_v1","partition_count":PARTITION_COUNT,"partitions":dict(sorted(parts.items())),"digest":registry_digest(parts),"path_exceptions":dict(sorted(exceptions.items()))}
    update_mutables(new,changed)
    consumed=copy.deepcopy(new.get("consumed_authority") or {"cap_ranges":[],"pfa_ranges":[]})
    for e in changed.values():
        if e["kind"]!="checkpoint-acceptance": continue
        src=(e["data"].get("authority") or {}).get("source")
        a=source_number(src,"CAP"); b=source_number(src,"PFA")
        if a is not None: consumed["cap_ranges"]=add_range(consumed.get("cap_ranges") or [],a)
        if b is not None: consumed["pfa_ranges"]=add_range(consumed.get("pfa_ranges") or [],b)
    new["consumed_authority"]=consumed; rev=head(layout); new["validated_revision"]=rev; new["validated_tree"]=tree(layout,rev); new["fingerprints"]=fingerprints(layout)
    new["last_validation"]={"mode":INCREMENTAL_PROFILE,"validated_at":dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"),"metrics":metrics}
    return new

def incremental(layout,progress,output):
    source=state_path(layout); state=load_state(source); reason=deep_reason(layout,state,source) if state else "integrity_state_missing_or_invalid"
    if reason: return {"ok":False,"mode":INCREMENTAL_PROFILE,"requires_full":True,"blockers":[reason]}
    metrics={"changed_record_count":0,"closure_record_count":0,"historical_records_parsed":0,"index_partitions_read":0,"index_partitions_written":0}
    try: rows=diff_records(layout,state["validated_revision"])
    except Exception as x: return {"ok":False,"mode":INCREMENTAL_PROFILE,"requires_full":True,"blockers":[str(x)]}
    metrics["changed_record_count"]=len(rows); schemas=schema_map(layout); changed={}; old={}; errors=[]; deep=[]; mutable=set(state.get("mutable_ids") or []); touched=set()
    progress.emit("incremental_delta",0,len(rows),"validating changed canonical records")
    for i,row in enumerate(rows,1):
        st=row["status"]
        if st in {"D","R"}: deep.append(f"historical_record_{'deleted' if st=='D' else 'renamed'}:{row.get('old_path') or row.get('path')}"); continue
        path=row["path"]; d,digest=current_record(layout,path)
        if not isinstance(d,dict) or not d.get("id"): errors.append(f"changed_record_invalid:{path}"); continue
        rid=str(d["id"]); kind=classify_id(rid)
        if not kind: errors.append(f"changed_record_id_unrecognised:{rid}"); continue
        e={"id":rid,"kind":kind,"path":path,"digest":digest,"data":d}; changed[rid]=e; touched.add(partition_key(rid)); errors.extend(schema_errors(e,schemas))
        if st=="M":
            od,odigest=yaml_at(layout,state["validated_revision"],path)
            if not isinstance(od,dict) or not od.get("id"): deep.append(f"historical_record_baseline_unavailable:{path}")
            else:
                oid=str(od["id"]); okind=classify_id(oid); old[oid]={"id":oid,"kind":okind,"path":path,"digest":odigest,"data":od}
                if oid!=rid or okind!=kind: deep.append(f"historical_record_identity_changed:{path}")
                elif rid not in mutable: deep.append(f"immutable_historical_record_modified:{rid}")
        elif st=="A":
            if rid in ((state.get("registry") or {}).get("path_exceptions") or {}): errors.append(f"duplicate_canonical_id:{rid}")
            else:
                candidates=path_candidates(layout,rid); found=any(not git(layout.root,"cat-file","-e",f"{state['validated_revision']}:{p}").returncode for p in candidates)
                if not candidates: found=bool(tree_paths_for_id(layout,state["validated_revision"],rid))
                if found: errors.append(f"duplicate_canonical_id:{rid}")
        progress.emit("incremental_delta",i,len(rows),"validating changed canonical records")
    if deep: return {"ok":False,"mode":INCREMENTAL_PROFILE,"requires_full":True,"blockers":sorted(set(deep)),"metrics":metrics}
    cache={}; local={"CAP":set(),"PFA":set()}; progress.emit("incremental_closure",0,len(changed),"validating references and authority closure")
    for i,e in enumerate(changed.values(),1):
        for field,ref,expected in refs(e["kind"],e["data"]):
            target=lookup(ref,changed,layout,state,cache,metrics,source=e)
            if not target: errors.append(f"broken_reference:{e['id']}:{field}:{ref}")
            elif expected and target.get("kind")!=expected: errors.append(f"reference_kind_mismatch:{e['id']}:{field}:{ref}")
        if e["kind"]=="proposal": errors.extend(proposal_errors(e,layout))
        elif e["kind"]=="approval": errors.extend(approval_errors(e,changed,layout,state,cache,metrics))
        elif e["kind"]=="change": errors.extend(change_errors(e,changed,layout,state,cache,metrics))
        elif e["kind"] in {"checkpoint-acceptance-proof","checkpoint-acceptance"}: errors.extend(binding_errors(e,changed,layout,state,cache,metrics))
        if e["kind"]=="impact-analysis":
            n=change_number(e["id"])
            if n and e["data"].get("change")!=f"CHG-{n}": errors.append(f"impact_analysis_change_id_mismatch:{e['id']}")
        if e["kind"]=="checkpoint-acceptance":
            src=str((e["data"].get("authority") or {}).get("source") or "")
            for pref,key in (("CAP","cap_ranges"),("PFA","pfa_ranges")):
                n=source_number(src,pref)
                if n is not None:
                    if in_ranges((state.get("consumed_authority") or {}).get(key) or [],n) or n in local[pref]: errors.append(f"{pref.lower()}_authority_replay:{src}")
                    local[pref].add(n)
        progress.emit("incremental_closure",i,len(changed),"validating references and authority closure")
    metrics["closure_record_count"]=len(cache); metrics["index_partitions_read"]=len(touched); metrics["index_partitions_written"]=len(touched)
    if errors:
        progress.emit("failed",None,None,"incremental integrity validation failed",errors=len(errors))
        return {"ok":False,"mode":INCREMENTAL_PROFILE,"requires_full":False,"blockers":sorted(set(errors)),"metrics":metrics}
    new=next_state(layout,state,changed,old,metrics)
    if output: write_json(output,new)
    progress.emit("complete",len(rows),len(rows),"incremental integrity validation complete")
    return {"ok":True,"mode":INCREMENTAL_PROFILE,"state":new,"metrics":metrics,"blockers":[]}

def audit_age_status(layout,state):
    age=full_age(layout,state)
    if age is None: return {"age_days":None,"status":"unknown"}
    warn=int(policy(layout).get("full_audit_warning_age_days") or 35); maximum=int(policy(layout).get("maximum_full_audit_age_days") or 45)
    return {"age_days":round(age,2),"status":"overdue" if age>maximum else ("warning" if age>warn else "current"),"warning_age_days":warn,"maximum_age_days":maximum}

def status(layout):
    p=state_path(layout); s=load_state(p); reason=deep_reason(layout,s,p) if s else "integrity_state_missing_or_invalid"
    return {"ok":reason is None,"profile":INCREMENTAL_PROFILE,"state_path":relative(layout,p),"deep_audit_required":reason is not None,"reason":reason,
            "validated_revision":s.get("validated_revision") if s else None,"last_full_audit":s.get("last_full_audit") if s else None,
            "audit_age":audit_age_status(layout,s) if s else {"age_days":None,"status":"unknown"},"inventory":s.get("inventory") if s else None}

def scale_probe(total,changed):
    touched=sorted({partition_key(x) for x in changed})
    return {"ok":True,"mode":"scale_probe","represented_historical_records":int(total),"changed_record_count":len(changed),
            "index_partitions_read":len(touched),"historical_records_parsed":0,"bounded_by_delta":len(touched)<=len(changed)}

def main():
    p=argparse.ArgumentParser(description="SpecForge incremental/full integrity validator")
    p.add_argument("command",choices=("auto","incremental","full","status","scale-probe")); p.add_argument("--root",default=".")
    p.add_argument("--state-output"); p.add_argument("--progress-file"); p.add_argument("--records",type=int,default=1000000); p.add_argument("--changed-id",action="append",default=[]); p.add_argument("--json",action="store_true")
    a=p.parse_args(); layout=discover_layout(Path(a.root).resolve())
    if a.command=="status": result=status(layout)
    elif a.command=="scale-probe": result=scale_probe(a.records,a.changed_id or ["CHG-999999"])
    else:
        pp=progress_path(layout,a.progress_file); output=Path(a.state_output).resolve() if a.state_output else None
        if a.command=="full": result=full_audit(layout,Progress(pp,FULL_PROFILE),output)
        elif a.command=="incremental": result=incremental(layout,Progress(pp,INCREMENTAL_PROFILE),output)
        else:
            prog=Progress(pp,INCREMENTAL_PROFILE); result=incremental(layout,prog,output)
            if result.get("requires_full"):
                reasons=list(result.get("blockers") or [])
                prog.emit("escalating",None,None,"incremental trust preconditions require full audit",reason=(reasons or [None])[0])
                result=full_audit(layout,Progress(pp,FULL_PROFILE),output); result["escalated_from"]=reasons
    if a.json: print(json.dumps(result,indent=2,sort_keys=True))
    else:
        print("SpecForge integrity "+("PASSED" if result.get("ok") else "FAILED")); print(" Mode: "+str(result.get("mode") or result.get("profile")))
        for b in result.get("blockers") or []: print(" - "+str(b))
    return 0 if result.get("ok") else (2 if result.get("requires_full") else 1)

if __name__=="__main__": raise SystemExit(main())
