from pathlib import Path
import datetime as dt, hashlib, json, shutil, subprocess, tempfile, yaml
from specforge_project import (
    MaterialBoundaryError,
    SUPPORTED_LIFECYCLE_ENFORCEMENT_PROFILES,
    canonical_artifact_digest,
    classify_project_path,
    git_material_state,
    git_worktree_root,
    iter_record_files,
    load_yaml,
    material_boundary_blockers,
    material_snapshot,
    unclassified_project_paths,
)

def run_git(layout,*args):
    return subprocess.run(['git','-C',str(layout.root),*args],capture_output=True,text=True)

def authority_path(layout):
    evidence=(layout.manifest.get('paths') or {}).get('evidence','./specforge/evidence')
    return (layout.root/evidence/'material-authority.yaml').resolve()

def reconciliation_root(layout):
    evidence=(layout.manifest.get('paths') or {}).get('evidence','./specforge/evidence')
    return (layout.root/evidence/'reconciliations').resolve()

def load_authority(layout):
    p=authority_path(layout)
    if not p.is_file(): return None
    d=load_yaml(p); return d if isinstance(d,dict) else None

def save_authority(layout,data):
    p=authority_path(layout); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(yaml.safe_dump(data,sort_keys=False,allow_unicode=True),encoding='utf-8',newline='\n'); return p

def current_identity(layout):
    if git_worktree_root(layout) is not None:
        r=run_git(layout,'rev-parse','HEAD')
        if r.returncode==0: return {'provider':'git','revision':r.stdout.strip()}
    s=material_snapshot(layout); return {'provider':'specforge_snapshot','revision':s['revision'],'file_count':s.get('file_count')}

def material_difference_state(layout,provider,reference):
    boundary=material_boundary_blockers(layout)
    if boundary:
        return {'material':[],'unclassified':[],'boundary_blockers':boundary}
    if provider=='specforge_snapshot':
        try:
            current=material_snapshot(layout)
        except MaterialBoundaryError as exc:
            return {'material':[],'unclassified':list(exc.paths),'boundary_blockers':[]}
        return {
            'material':[] if current['revision']==reference else ['<snapshot-material-drift>'],
            'unclassified':[],
            'boundary_blockers':[],
        }
    return git_material_state(layout,reference)

def material_differences(layout,provider,reference):
    return material_difference_state(layout,provider,reference)['material']

def records(layout):
    out={}
    for p in iter_record_files(layout):
        try: d=load_yaml(p)
        except Exception: continue
        if isinstance(d,dict) and d.get('id'): out[str(d['id'])]=(d,p)
    return out

def _parse_time(value):
    try: return dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except Exception: return None

def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def latest_accepted_checkpoint(layout,recs=None):
    recs=recs or records(layout); candidates=[]
    for rid,(acc,_) in recs.items():
        if not str(rid).startswith('ACC-') or acc.get('decision')!='accepted': continue
        checkpoint_id=acc.get('checkpoint'); item=recs.get(str(checkpoint_id))
        if not item: continue
        checkpoint=item[0]
        if checkpoint.get('status')!='accepted': continue
        if ((checkpoint.get('acceptance') or {}).get('current'))!=rid: continue
        material=(checkpoint.get('candidate') or {}).get('material') or {}
        acc_material=(acc.get('candidate') or {}).get('material') or {}
        if not material.get('revision') or acc_material.get('revision')!=material.get('revision'): continue
        if checkpoint.get('included_changes_digest')!=acc.get('included_changes_digest'): continue
        when=_parse_time(acc.get('timestamp'))
        candidates.append((when or dt.datetime.min.replace(tzinfo=dt.timezone.utc),str(rid),checkpoint_id,checkpoint,acc))
    if not candidates: return None
    _,acceptance_id,checkpoint_id,checkpoint,acc=sorted(candidates,key=lambda item:(item[0],item[1]))[-1]
    material=(checkpoint.get('candidate') or {}).get('material') or {}
    source=(checkpoint.get('candidate') or {}).get('source_revision') or {}
    return {
        'checkpoint':checkpoint_id,
        'acceptance':acceptance_id,
        'accepted_at':acc.get('timestamp'),
        'material':material,
        'source_revision':source,
    }

def authority_bookkeeping_state(layout,authority=None,recs=None):
    authority=authority or load_authority(layout); recs=recs or records(layout)
    if not authority: return {'state':'unavailable','repairable':False,'blockers':['trusted_material_baseline_missing']}
    latest=latest_accepted_checkpoint(layout,recs)
    if not latest: return {'state':'no_accepted_checkpoint','repairable':False,'latest':None,'blockers':[]}
    stored=authority.get('accepted_checkpoint') or {}
    stored_material=stored.get('candidate_material') or {}
    latest_material=latest.get('material') or {}
    consistent=(
        stored.get('id')==latest.get('checkpoint')
        and stored.get('acceptance')==latest.get('acceptance')
        and stored_material.get('revision')==latest_material.get('revision')
    )
    if consistent:
        return {'state':'consistent','repairable':False,'latest':latest,'blockers':[]}
    try: current=material_snapshot(layout)
    except Exception as exc:
        return {
            'state':'pointer_drift','repairable':False,'latest':latest,'current_material':None,
            'blockers':['authority_bookkeeping_current_material_unavailable'], 'error':str(exc),
        }
    repairable=(
        current.get('revision')==latest_material.get('revision')
        and (latest_material.get('file_count') is None or current.get('file_count')==latest_material.get('file_count'))
    )
    blockers=[] if repairable else ['authority_bookkeeping_candidate_not_current']
    return {
        'state':'pointer_drift',
        'repairable':repairable,
        'latest':latest,
        'stored':stored or None,
        'current_material':{'provider':current.get('provider'),'revision':current.get('revision'),'file_count':current.get('file_count')},
        'blockers':blockers,
    }

def exact_approval(layout,recs,change):
    pid=(change.get('proposal') or {}).get('current'); pr=recs.get(str(pid))
    if not pr: return None
    digest=canonical_artifact_digest(pr[1])
    for aid in change.get('approvals') or []:
        item=recs.get(str(aid))
        if not item: continue
        a=item[0]
        if a.get('change')!=change.get('id') or a.get('proposal')!=pid or a.get('decision')!='approved': continue
        if (a.get('actor') or {}).get('type')!='human': continue
        expected=(a.get('evidence') or {}).get('proposal_digest') or (a.get('scope') or {}).get('proposal_sha256')
        if expected==digest: return {'approval':aid,'proposal':pid}
    return None

def _proposal_material_scope_paths(layout,proposal):
    declared=proposal.get('declared_scope')
    if not isinstance(declared,list) or not declared:
        return None
    out=set()
    for item in declared:
        if not isinstance(item,dict): continue
        for key in ('path','from','to'):
            value=item.get(key)
            if not isinstance(value,str) or not value.strip(): continue
            normalized=value.replace('\\','/')
            while normalized.startswith('./'):
                normalized=normalized[2:]
            try: classification=classify_project_path(layout.root/normalized,layout)
            except Exception: classification='unclassified'
            if classification=='material': out.add(normalized)
    return sorted(out)

def active_implementations(layout,recs):
    items=[]
    for rid,(chg,_) in recs.items():
        if not rid.startswith('CHG-') or (chg.get('governance') or {}).get('lifecycle_enforcement') not in SUPPORTED_LIFECYCLE_ENFORCEMENT_PROFILES: continue
        if chg.get('status') not in {'in_progress','implemented','validated','ready_for_checkpoint'}: continue
        ap=exact_approval(layout,recs,chg)
        if not ap: continue
        proposal_item=recs.get(str(ap['proposal'])); proposal=proposal_item[0] if proposal_item else {}
        attempts = list((chg.get('implementation') or {}).get('attempts') or [])
        material_candidates = {}
        candidate_order = []
        for iid in attempts:
            rec = recs.get(str(iid))
            if not rec:
                continue
            imp = rec[0]
            if imp.get('change') != rid or imp.get('proposal') != ap['proposal']:
                continue
            if imp.get('outcome') not in {'in_progress', 'passed', 'blocked'}:
                continue
            src = imp.get('source_revision') or {}
            before = src.get('before')
            if not before:
                continue
            after = src.get('after')
            candidate = ('after', after) if after else ('before_attempt', before, str(iid))
            if candidate in material_candidates:
                continue
            material_candidates[candidate] = (iid, imp, src)
            candidate_order.append(candidate)
        for candidate in candidate_order:
            iid, imp, src = material_candidates[candidate]
            before = src.get('before')
            provider = str(src.get('system') or src.get('provider') or '').lower().replace('-', '_')
            if provider == 'github':
                provider = 'git'
            items.append({'type':'implementation','change':rid,'attempt':iid,'before':before,'provider':provider or None,'approval':ap['approval'],'proposal':ap['proposal'],'outcome':imp.get('outcome'),'scope_paths':_proposal_material_scope_paths(layout,proposal)})
    return items

def _git_commit_exists(layout,revision):
    return bool(revision) and run_git(layout,'cat-file','-e',f'{revision}^{{commit}}').returncode==0

def _git_is_ancestor(layout,ancestor,descendant):
    return bool(ancestor and descendant) and run_git(layout,'merge-base','--is-ancestor',ancestor,descendant).returncode==0

def _git_lineage_distance(layout,ancestor,descendant):
    r=run_git(layout,'rev-list','--count',f'{ancestor}..{descendant}')
    if r.returncode: return None
    try: return int(r.stdout.strip())
    except Exception: return None

def _git_material_paths_between(layout,base,head):
    r=run_git(layout,'diff','--name-only',f'{base}..{head}','--')
    if r.returncode: return None,['stacked_material_lineage_diff_unavailable']
    material=[]; unclassified=[]
    for raw in r.stdout.splitlines():
        path=raw.strip().replace('\\','/')
        while path.startswith('./'):
            path=path[2:]
        if not path: continue
        try: classification=classify_project_path(layout.root/path,layout)
        except Exception: classification='unclassified'
        if classification=='material': material.append(path)
        elif classification=='unclassified': unclassified.append(path)
    return sorted(set(material)),['stacked_material_lineage_unclassified_path:'+x for x in sorted(set(unclassified))]

def implementation_authority_chain(layout,impls,trusted_revision,provider,current_revision):
    compatible=[x for x in impls if x.get('provider') in {None,provider}]
    if not compatible: return {'layers':[],'covered_paths':[],'blockers':[],'rejected':[],'mode':'none'}
    if len(compatible)==1 and compatible[0].get('before')==trusted_revision:
        layer=dict(compatible[0]); scope=layer.get('scope_paths')
        return {'layers':[layer],'covered_paths':None if scope is None else sorted(set(scope)),'blockers':[],'rejected':[],'mode':'single_trusted_root'}
    if provider!='git': return {'layers':[],'covered_paths':[],'blockers':['stacked_material_continuity_unsupported:'+str(provider)],'rejected':compatible,'mode':'unsupported_provider'}
    if not _git_commit_exists(layout,trusted_revision) or not _git_commit_exists(layout,current_revision): return {'layers':[],'covered_paths':[],'blockers':['stacked_material_lineage_endpoint_unavailable'],'rejected':compatible,'mode':'git'}
    candidates=[]; rejected=[]; blockers=[]
    for item in compatible:
        before=item.get('before')
        if not _git_commit_exists(layout,before): rejected.append(dict(item,reason='source_revision_unavailable')); continue
        if not _git_is_ancestor(layout,trusted_revision,before): rejected.append(dict(item,reason='source_not_descendant_of_trusted')); continue
        if not _git_is_ancestor(layout,before,current_revision): rejected.append(dict(item,reason='source_not_ancestor_of_current')); continue
        distance=_git_lineage_distance(layout,trusted_revision,before)
        if distance is None: blockers.append('stacked_material_lineage_distance_unavailable:'+str(item.get('attempt'))); continue
        layer=dict(item); layer['lineage_distance']=distance; candidates.append(layer)
    if not candidates: return {'layers':[],'covered_paths':[],'blockers':sorted(set(blockers)),'rejected':rejected,'mode':'git'}
    candidates.sort(key=lambda x:(x['lineage_distance'],str(x.get('before')),str(x.get('change')),str(x.get('attempt'))))
    for previous,current in zip(candidates,candidates[1:]):
        if previous.get('before')==current.get('before') or not _git_is_ancestor(layout,previous.get('before'),current.get('before')): blockers.append('stacked_material_lineage_incomparable:'+str(previous.get('attempt'))+':'+str(current.get('attempt')))
    if len(candidates)>1:
        for item in candidates:
            if item.get('scope_paths') is None: blockers.append('stacked_material_scope_unbounded:'+str(item.get('attempt')))
    covered=set()
    if not blockers:
        for item in candidates:
            scope=set(item.get('scope_paths') or [])
            present,path_blockers=_git_material_paths_between(layout,trusted_revision,item.get('before'))
            blockers.extend(path_blockers)
            if present is None: continue
            unexplained=[x for x in present if x not in covered and x not in scope]
            if unexplained:
                blockers.append('stacked_material_preexisting_unexplained:'+str(item.get('attempt')))
                blockers.extend('stacked_material_preexisting_path:'+x for x in unexplained)
            covered.update(scope)
    return {'layers':candidates,'covered_paths':sorted(covered),'blockers':sorted(set(blockers)),'rejected':rejected,'mode':'git'}

def upgrade_scope_ok(layout,diffs):
    core=str(layout.core_root.relative_to(layout.root)).replace('\\','/').rstrip('/')+'/'; manifest=str(layout.manifest_path.relative_to(layout.root)).replace('\\','/')
    return all(p.startswith(core) or p==manifest for p in diffs)

def integrity_state_path(layout):
    evidence=(layout.manifest.get('paths') or {}).get('evidence','./specforge/evidence')
    return (layout.root/evidence/'integrity'/'state.json').resolve()

def load_integrity_state(layout):
    p=integrity_state_path(layout)
    if not p.is_file(): return None
    try: data=json.loads(p.read_text(encoding='utf-8'))
    except Exception: return None
    return data if isinstance(data,dict) else None

def integrity_summary(layout):
    state=load_integrity_state(layout)
    config=((layout.manifest.get('policy') or {}).get('integrity') or {})
    if not state:
        return {'available':False,'profile':'incremental_integrity_v1','status':'requires_full_audit','reason':'integrity_state_missing'}
    audit=state.get('last_full_audit') or {}; stamp=audit.get('audited_at'); age=None
    if stamp:
        try: age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(str(stamp).replace('Z','+00:00'))).total_seconds()/86400
        except Exception: age=None
    warning=int(config.get('full_audit_warning_age_days') or 35); maximum=int(config.get('maximum_full_audit_age_days') or 45)
    age_status='unknown' if age is None else ('overdue' if age>maximum else ('warning' if age>warning else 'current'))
    return {
        'available':True,
        'profile':state.get('profile'),
        'status':state.get('status'),
        'validated_revision':state.get('validated_revision'),
        'record_count':((state.get('inventory') or {}).get('total')),
        'last_full_audit':audit or None,
        'full_audit_age_days':round(age,2) if age is not None else None,
        'full_audit_age_status':age_status,
        'maximum_full_audit_age_days':maximum,
    }

def _path_digest(layout,path):
    target=(layout.root/path).resolve()
    try: target.relative_to(layout.root.resolve())
    except ValueError: return None
    if not target.is_file(): return None
    try: return 'sha256:'+hashlib.sha256(target.read_bytes()).hexdigest()
    except Exception: return None

def _next_reconciliation_id(layout):
    highest=0
    root=reconciliation_root(layout)
    if root.is_dir():
        for path in root.glob('REC-*.yaml'):
            stem=path.stem
            if stem[4:].isdigit(): highest=max(highest,int(stem[4:]))
    return f'REC-{highest+1:04d}'

def reconciliation_record(layout,reconciliation_id):
    target=reconciliation_root(layout)/f'{reconciliation_id}.yaml'
    if not target.is_file(): return None,None
    try: data=load_yaml(target)
    except Exception: return None,target
    return (data if isinstance(data,dict) else None),target

def _reconciliation_candidate_current(layout,record):
    expected=((record.get('material') or {}).get('snapshot') or {})
    if not expected.get('revision'):
        return False,{'reason':'reconciliation_snapshot_missing'}
    try: current=material_snapshot(layout)
    except Exception as exc:
        return False,{'reason':'reconciliation_current_material_unavailable','error':str(exc)}
    same=(
        current.get('revision')==expected.get('revision')
        and (expected.get('file_count') is None or current.get('file_count')==expected.get('file_count'))
    )
    return same,{'expected':expected,'current':{'provider':current.get('provider'),'revision':current.get('revision'),'file_count':current.get('file_count')}}

def _write_reconciliation_successor(layout,source,status,extra=None):
    rec_id=_next_reconciliation_id(layout)
    payload={
        'id':rec_id,
        'profile':'material_reconciliation_v1',
        'kind':source.get('kind'),
        'status':status,
        'created_at':_now(),
        'trusted':source.get('trusted') or {},
        'observed':source.get('observed') or {},
        'material':source.get('material') or {'paths':[]},
        'provenance':source.get('provenance') or {'claim':None,'source':None,'verified':False},
        'blockers':[],
        'supersedes':source.get('id'),
    }
    if source.get('authority_bookkeeping'):
        payload['authority_bookkeeping']=source.get('authority_bookkeeping')
    if extra:
        payload.update(extra)
    root=reconciliation_root(layout); root.mkdir(parents=True,exist_ok=True)
    target=root/f'{rec_id}.yaml'
    target.write_text(yaml.safe_dump(payload,sort_keys=False,allow_unicode=True),encoding='utf-8',newline='\n')
    return rec_id,target,payload

def capture_reconciliation_observation(layout,check=None):
    check=check or evaluate(layout)
    rec_info=(check.get('details') or {}).get('reconciliation') or {}
    kind=rec_info.get('kind')
    if kind not in {'unexplained_material','authority_bookkeeping','mixed_material','ambiguous_material'}:
        return {'captured':False,'blockers':['material_reconciliation_not_required']}
    rec_id=_next_reconciliation_id(layout); root=reconciliation_root(layout); root.mkdir(parents=True,exist_ok=True)
    authority=load_authority(layout) or {}; trusted=authority.get('trusted') or {}
    paths=sorted(set(rec_info.get('paths') or []))
    try: snapshot=material_snapshot(layout)
    except Exception: snapshot=None
    payload={
        'id':rec_id,
        'profile':'material_reconciliation_v1',
        'kind':kind,
        'status':'observed' if kind!='ambiguous_material' else 'blocked',
        'created_at':_now(),
        'trusted':trusted,
        'observed':current_identity(layout),
        'material':{
            'paths':paths,
            'snapshot':({'provider':snapshot.get('provider'),'revision':snapshot.get('revision'),'file_count':snapshot.get('file_count')} if snapshot else None),
            'path_digests':{path:_path_digest(layout,path) for path in paths},
        },
        'provenance':{'claim':None,'source':None,'verified':False},
        'blockers':sorted(set(check.get('blockers') or [])),
    }
    if kind=='authority_bookkeeping':
        bookkeeping=(check.get('details') or {}).get('authority_bookkeeping') or {}
        latest=bookkeeping.get('latest') or {}
        payload['authority_bookkeeping']={
            'checkpoint':latest.get('checkpoint'),
            'acceptance':latest.get('acceptance'),
            'repairable':bool(bookkeeping.get('repairable')),
        }
    target=root/f'{rec_id}.yaml'
    target.write_text(yaml.safe_dump(payload,sort_keys=False,allow_unicode=True),encoding='utf-8',newline='\n')
    return {'captured':True,'reconciliation':rec_id,'path':str(target.relative_to(layout.root)).replace('\\','/'),'record':payload,'blockers':[]}

def record_reconciliation_decision(layout,reconciliation_id,decision,actor_id='product-owner',actor_name=None,provenance_claim=None,provenance_source=None,provenance_verified=False):
    if decision not in {'keep','undo','set_aside','leave_untouched','unknown'}:
        return {'recorded':False,'blockers':['reconciliation_decision_invalid']}
    source,_=reconciliation_record(layout,reconciliation_id)
    if not source:
        return {'recorded':False,'blockers':['reconciliation_record_missing']}
    if source.get('profile')!='material_reconciliation_v1':
        return {'recorded':False,'blockers':['reconciliation_profile_invalid']}
    if source.get('kind')=='authority_bookkeeping':
        return {'recorded':False,'blockers':['authority_bookkeeping_requires_canonical_repair']}
    if source.get('kind')=='ambiguous_material' and decision not in {'leave_untouched','unknown'}:
        return {'recorded':False,'blockers':['ambiguous_material_requires_manager_review']}
    current,continuity=_reconciliation_candidate_current(layout,source)
    if not current:
        return {'recorded':False,'blockers':['reconciliation_candidate_stale'],'details':continuity}
    actor={'type':'human','id':actor_id}
    if actor_name: actor['display_name']=actor_name
    provenance={
        'claim':provenance_claim,
        'source':provenance_source,
        'verified':bool(provenance_verified),
    }
    next_action={
        'keep':'prospective_adoption_proposal',
        'undo':'restore_exact_trusted_state',
        'set_aside':'quarantine_then_restore_trusted_state',
        'leave_untouched':'remain_blocked',
        'unknown':'remain_blocked',
    }[decision]
    status='acknowledged' if decision in {'keep','undo','set_aside'} else 'blocked'
    rec_id,target,payload=_write_reconciliation_successor(layout,source,status,{
        'provenance':provenance,
        'acknowledgement':{'decision':decision,'actor':actor,'received_at':_now()},
        'blockers':([] if status=='acknowledged' else ['material_reconciliation_unresolved']),
    })
    return {
        'recorded':True,
        'reconciliation':rec_id,
        'path':str(target.relative_to(layout.root)).replace('\\','/'),
        'decision':decision,
        'next_action':next_action,
        'record':payload,
        'blockers':payload.get('blockers') or [],
    }


def _trusted_git_restore_plan(layout, record):
    trusted = record.get('trusted') or {}
    provider = str(trusted.get('provider') or '').lower().replace('-', '_')
    if provider != 'git': return None, ['trusted_material_restore_provider_unsupported:' + str(provider or 'missing')]
    revision = trusted.get('revision')
    if not revision or run_git(layout, 'cat-file', '-e', f'{revision}^{{commit}}').returncode != 0: return None, ['trusted_material_restore_revision_unavailable']
    plan, blockers = [], []
    for rel in sorted(set(((record.get('material') or {}).get('paths') or []))):
        target = (layout.root / rel).resolve()
        try: target.relative_to(layout.root.resolve())
        except ValueError: blockers.append('reconciliation_path_outside_project:' + rel); continue
        if classify_project_path(target, layout) != 'material': blockers.append('reconciliation_path_not_material:' + rel); continue
        plan.append({'path': rel, 'exists_in_trusted': run_git(layout, 'cat-file', '-e', f'{revision}:{rel}').returncode == 0})
    return plan, sorted(set(blockers))

def _backup_current_paths(layout, record, root):
    manifest = []
    for rel in sorted(set(((record.get('material') or {}).get('paths') or []))):
        source = (layout.root / rel).resolve(); item = {'path': rel, 'exists': source.exists()}
        if source.is_file():
            target = root / 'files' / rel; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
            item['sha256'] = 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()
        elif source.exists(): raise RuntimeError('reconciliation_directory_path_unsupported:' + rel)
        manifest.append(item)
    return manifest

def _restore_backup(layout, manifest, root):
    for item in manifest:
        target = (layout.root / item['path']).resolve(); backup = root / 'files' / item['path']
        if item.get('exists'): target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(backup, target)
        elif target.is_file(): target.unlink()

def _restore_trusted_git_material(layout, record):
    plan, blockers = _trusted_git_restore_plan(layout, record)
    if blockers: return {'restored': False, 'blockers': blockers}
    trusted = (record.get('trusted') or {}).get('revision')
    with tempfile.TemporaryDirectory(prefix='specforge-reconcile-') as tmp:
        backup_root = Path(tmp); manifest = _backup_current_paths(layout, record, backup_root)
        try:
            for item in plan:
                rel = item['path']; target = (layout.root / rel).resolve()
                if item['exists_in_trusted']:
                    result = run_git(layout, 'restore', '--source', trusted, '--worktree', '--staged', '--', rel)
                    if result.returncode: raise RuntimeError('trusted_material_restore_failed:' + rel + ':' + (result.stderr or '').strip())
                else:
                    if target.is_file(): target.unlink()
                    elif target.exists(): raise RuntimeError('reconciliation_directory_path_unsupported:' + rel)
            state = material_difference_state(layout, 'git', trusted)
            if state.get('boundary_blockers') or state.get('unclassified') or state.get('material'): raise RuntimeError('trusted_material_restore_verification_failed')
        except Exception as exc:
            _restore_backup(layout, manifest, backup_root); return {'restored': False, 'blockers': [str(exc)]}
    return {'restored': True, 'trusted_revision': trusted, 'paths': [item['path'] for item in plan], 'blockers': []}

def _quarantine_material(layout, record):
    root = reconciliation_root(layout) / 'quarantine' / str(record.get('id'))
    if root.exists(): return None, ['reconciliation_quarantine_already_exists']
    root.mkdir(parents=True, exist_ok=False)
    try:
        manifest = _backup_current_paths(layout, record, root)
        payload = {'profile': 'material_quarantine_v1', 'source_reconciliation': record.get('id'), 'created_at': _now(), 'trusted': record.get('trusted') or {}, 'observed': record.get('observed') or {}, 'material_snapshot': ((record.get('material') or {}).get('snapshot')), 'files': manifest}
        manifest_path = root / 'manifest.yaml'; manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding='utf-8', newline=chr(10))
        return {'provider': 'specforge_quarantine_v1', 'reference': str(manifest_path.relative_to(layout.root)).replace(chr(92), '/')}, []
    except Exception as exc:
        shutil.rmtree(root, ignore_errors=True); return None, ['reconciliation_quarantine_failed:' + str(exc)]

def apply_reconciliation_recovery(layout, reconciliation_id):
    record, _ = reconciliation_record(layout, reconciliation_id)
    if not record: return {'applied': False, 'blockers': ['reconciliation_record_missing']}
    if record.get('profile') != 'material_reconciliation_v1': return {'applied': False, 'blockers': ['reconciliation_profile_invalid']}
    decision = (record.get('acknowledgement') or {}).get('decision')
    if record.get('status') != 'acknowledged' or decision not in {'undo', 'set_aside'}: return {'applied': False, 'blockers': ['reconciliation_recovery_not_authorized']}
    current, continuity = _reconciliation_candidate_current(layout, record)
    if not current: return {'applied': False, 'blockers': ['reconciliation_candidate_stale'], 'details': continuity}
    quarantine = None
    if decision == 'set_aside':
        quarantine, blockers = _quarantine_material(layout, record)
        if blockers: return {'applied': False, 'blockers': blockers}
    restored = _restore_trusted_git_material(layout, record)
    if not restored.get('restored'): return {'applied': False, 'blockers': restored.get('blockers') or ['trusted_material_restore_failed'], 'quarantine': quarantine}
    status = 'undone' if decision == 'undo' else 'quarantined'
    extra = {'recovery': {'provider': 'git', 'trusted_revision': restored.get('trusted_revision'), 'paths': restored.get('paths') or []}}
    if quarantine: extra['quarantine'] = quarantine
    rec_id, target, payload = _write_reconciliation_successor(layout, record, status, extra)
    return {'applied': True, 'decision': decision, 'reconciliation': rec_id, 'path': str(target.relative_to(layout.root)).replace(chr(92), '/'), 'quarantine': quarantine, 'restored': restored, 'record': payload, 'blockers': []}

def repair_authority_bookkeeping(layout,reconciliation_id=None):
    authority=load_authority(layout)
    state=authority_bookkeeping_state(layout,authority)
    if state.get('state')!='pointer_drift':
        return {'repaired':False,'blockers':['authority_bookkeeping_reconciliation_not_required'],'details':state}
    if not state.get('repairable'):
        return {'repaired':False,'blockers':state.get('blockers') or ['authority_bookkeeping_reconciliation_not_safe'],'details':state}
    source=None
    if reconciliation_id:
        source,_=reconciliation_record(layout,reconciliation_id)
        if not source:
            return {'repaired':False,'blockers':['reconciliation_record_missing']}
        if source.get('kind')!='authority_bookkeeping':
            return {'repaired':False,'blockers':['reconciliation_kind_mismatch']}
        current,continuity=_reconciliation_candidate_current(layout,source)
        if not current:
            return {'repaired':False,'blockers':['reconciliation_candidate_stale'],'details':continuity}
    latest=state['latest']; identity=current_identity(layout)
    updated=dict(authority)
    updated['trusted']=identity
    updated['accepted_checkpoint']={
        'id':latest.get('checkpoint'),
        'acceptance':latest.get('acceptance'),
        'candidate_material':latest.get('material'),
        'accepted_at':latest.get('accepted_at'),
    }
    successor=None
    if source:
        rec_id,target,payload=_write_reconciliation_successor(layout,source,'repaired',{
            'authority_bookkeeping':{
                'checkpoint':latest.get('checkpoint'),
                'acceptance':latest.get('acceptance'),
                'repairable':True,
            },
        })
        successor={'id':rec_id,'path':str(target.relative_to(layout.root)).replace('\\','/'),'record':payload}
        updated['reconciliation']={'profile':'material_reconciliation_v1','record':rec_id,'repaired_at':_now()}
    save_authority(layout,updated)
    return {'repaired':True,'trusted':identity,'accepted_checkpoint':updated['accepted_checkpoint'],'reconciliation':successor,'blockers':[]}

def evaluate(layout):
    authority=load_authority(layout); details={'project_format_mode':layout.mode,'integrity':integrity_summary(layout)}; blockers=[]
    if not authority: return {'valid':False,'authorized':False,'blockers':['trusted_material_baseline_missing'],'details':details}
    recs=records(layout)
    bookkeeping=authority_bookkeeping_state(layout,authority,recs)
    details['authority_bookkeeping']=bookkeeping
    if bookkeeping.get('state')=='pointer_drift':
        details['reconciliation']={'kind':'authority_bookkeeping','paths':[],'repairable':bool(bookkeeping.get('repairable'))}
        blockers.append('authority_bookkeeping_reconciliation_required'); blockers.extend(bookkeeping.get('blockers') or [])
        return {'valid':False,'authorized':False,'blockers':sorted(set(blockers)),'details':details}
    trusted=authority.get('trusted') or {}; provider=str(trusted.get('provider') or '').lower().replace('-','_'); revision=trusted.get('revision')
    if provider not in {'git','specforge_snapshot'} or not revision: return {'valid':False,'authorized':False,'blockers':['trusted_material_baseline_invalid'],'details':details}
    if provider=='git' and git_worktree_root(layout) is None: return {'valid':False,'authorized':False,'blockers':['trusted_material_provider_unavailable:git'],'details':details}
    state=material_difference_state(layout,provider,revision)
    diffs=state['material']; unclassified=state['unclassified']; boundary=state.get('boundary_blockers') or []
    impls=active_implementations(layout,recs); identity=current_identity(layout)['revision'] if provider=='git' else None
    chain=implementation_authority_chain(layout,impls,revision,provider,identity)
    op=authority.get('active_operation') or {}; upgrade=op.get('type')=='core_upgrade' and op.get('before')==revision
    details.update({'provider':provider,'trusted_revision':revision,'current_identity':identity,'material_differences':diffs,'unclassified_paths':unclassified,'material_boundary_blockers':boundary,'active_implementations':impls,'implementation_authority_chain':chain,'active_operation':op or None})
    if boundary:
        blockers.append('invalid_material_boundary'); blockers.extend('material_boundary:'+item.get('code','invalid')+((':'+str(item.get('path'))) if item.get('path') is not None else '') for item in boundary)
        details['reconciliation']={'kind':'ambiguous_material','paths':diffs,'reason':'invalid_material_boundary'}
        return {'valid':False,'authorized':False,'blockers':sorted(set(blockers)),'details':details}
    if unclassified:
        blockers.append('unclassified_project_paths_present'); blockers.extend('unclassified_project_path:'+x for x in unclassified)
        details['reconciliation']={'kind':'ambiguous_material','paths':diffs,'reason':'unclassified_project_paths_present'}
        return {'valid':False,'authorized':False,'blockers':sorted(set(blockers)),'details':details}
    if chain.get('blockers'):
        blockers.extend(chain.get('blockers') or []); blockers.append('material_reconciliation_required')
        details['reconciliation']={'kind':'ambiguous_material','paths':diffs,'reason':'stacked_material_authority_invalid'}
        return {'valid':False,'authorized':False,'blockers':sorted(set(blockers)),'details':details}
    layers=chain.get('layers') or []; covered=chain.get('covered_paths')
    if not diffs: return {'valid':True,'authorized':bool(layers or upgrade),'blockers':[],'details':details}
    if layers:
        unexplained=[] if covered is None else [x for x in diffs if x not in set(covered)]
        if unexplained:
            blockers.extend(['mixed_authorized_and_unexplained_material','material_reconciliation_required']); blockers.extend('unauthorized_material_path:'+x for x in unexplained)
            details['authorized_by']={'type':'implementation_chain','layers':layers,'covered_paths':covered}
            details['reconciliation']={'kind':'mixed_material','paths':unexplained,'authorized_paths':sorted(set(diffs)-set(unexplained))}
        else: details['authorized_by']={'type':'implementation_chain','layers':layers,'covered_paths':covered}
    elif upgrade:
        if provider=='git' and not upgrade_scope_ok(layout,diffs): blockers.append('managed_upgrade_scope_violation')
        else: details['authorized_by']=op
    else:
        blockers.extend(['unauthorized_material_changes','material_reconciliation_required']); blockers.extend('unauthorized_material_path:'+x for x in diffs)
        details['reconciliation']={'kind':'unexplained_material','paths':diffs}
    return {'valid':not blockers,'authorized':not blockers and bool(diffs),'blockers':sorted(set(blockers)),'details':details}

def establish_upgrade_authority(layout,current,target):
    identity=current_identity(layout); authority=load_authority(layout) or {'version':1,'trusted':identity}; trusted=authority.get('trusted') or {}
    if trusted.get('provider')!=identity['provider'] or trusted.get('revision')!=identity['revision']: raise RuntimeError('trusted_material_baseline_does_not_match_current_clean_state')
    authority['active_operation']={'type':'core_upgrade','id':f'core-{current}-to-{target}','provider':identity['provider'],'before':identity['revision'],'from_core_version':current,'to_core_version':target,'scope':'framework_core_and_manifest'}
    save_authority(layout,authority); return authority['active_operation']

def accept(layout):
    check=evaluate(layout)
    if not check.get('valid'): return {'accepted':False,'blockers':check.get('blockers') or []}
    authority=load_authority(layout); identity=current_identity(layout)
    if identity['provider']=='git':
        state=material_difference_state(layout,'git','HEAD')
        if state.get('boundary_blockers'):
            return {'accepted':False,'blockers':['invalid_material_boundary']}
        if state['unclassified']:
            return {'accepted':False,'blockers':['unclassified_project_paths_present']+['unclassified_project_path:'+p for p in state['unclassified']]}
        if state['material']: return {'accepted':False,'blockers':['material_worktree_not_clean']+['material_path:'+p for p in state['material']]}
    authority['trusted']=identity; authority.pop('active_operation',None); save_authority(layout,authority)
    return {'accepted':True,'provider':identity['provider'],'trusted_revision':identity['revision'],'blockers':[]}