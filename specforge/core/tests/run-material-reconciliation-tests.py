#!/usr/bin/env python3
from pathlib import Path
import sys, tempfile, yaml

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from portable_fixture import create_project, git, install_controlled_change, write_yaml
from specforge_project import discover_layout, material_snapshot
from specforge_authority import (
    _git_material_paths_between,
    _proposal_material_scope_paths,
    apply_reconciliation_recovery,
    authority_bookkeeping_state,
    capture_reconciliation_observation,
    evaluate,
    load_authority,
    reconciliation_record,
    record_reconciliation_decision,
    repair_authority_bookkeeping,
)

MATERIAL_ROOTS = [
    'README.md',
    'product.txt',
    'model.txt',
    'specforge/SPECFORGE.md',
    'specforge/project.yaml',
    'specforge/core',
    'specforge/packs',
]


def expect(cond, name, detail=''):
    if not cond:
        print('FAIL:', name)
        if detail:
            print(detail)
        raise SystemExit(1)
    print('PASS:', name)


# CHG-1055: dot-prefixed material roots must survive proposal scope normalisation.
with tempfile.TemporaryDirectory(prefix='specforge-reconcile-dot-scope-') as td:
    project = Path(td) / 'project'
    create_project(
        project,
        CORE,
        git_backed=True,
        material_roots=MATERIAL_ROOTS + ['.github'],
    )
    workflow = project / '.github/workflows/candidate-a-evidence.yml'
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text('name: fixture\n', encoding='utf-8')
    layout = discover_layout(project)
    proposal = {
        'declared_scope': [
            {'operation': 'modify', 'path': '.github/workflows/candidate-a-evidence.yml'}
        ]
    }
    scope_paths = _proposal_material_scope_paths(layout, proposal)
    expect(
        scope_paths == ['.github/workflows/candidate-a-evidence.yml'],
        'dot-prefixed-material-scope-preserved',
        str(scope_paths),
    )

    git(project, 'add', '.github/workflows/candidate-a-evidence.yml')
    git(project, 'commit', '-m', 'dot-prefixed material baseline')
    before = git(project, 'rev-parse', 'HEAD').stdout.strip()
    workflow.write_text('name: fixture-updated\n', encoding='utf-8')
    git(project, 'add', '.github/workflows/candidate-a-evidence.yml')
    git(project, 'commit', '-m', 'dot-prefixed material change')
    after = git(project, 'rev-parse', 'HEAD').stdout.strip()
    material_paths, blockers = _git_material_paths_between(layout, before, after)
    expect(
        blockers == [],
        'dot-prefixed-lineage-diff-classifies-cleanly',
        str(blockers),
    )
    expect(
        material_paths == ['.github/workflows/candidate-a-evidence.yml'],
        'dot-prefixed-lineage-path-preserved',
        str(material_paths),
    )


def accepted_checkpoint_fixture(project, checkpoint='CHK-9901', acceptance='ACC-9901'):
    layout = discover_layout(project)
    snapshot = material_snapshot(layout)
    source = git(project, 'rev-parse', 'HEAD').stdout.strip()
    digest = 'sha256:fixture-change-set'
    write_yaml(project / 'specforge/history/checkpoints' / f'{checkpoint}.yaml', {
        'id': checkpoint,
        'title': 'Synthetic accepted checkpoint',
        'status': 'accepted',
        'included_changes': ['CHG-9000'],
        'included_changes_digest': digest,
        'candidate': {
            'material': {
                'provider': snapshot['provider'],
                'revision': snapshot['revision'],
                'file_count': snapshot['file_count'],
            },
            'source_revision': {'system': 'git', 'provider': 'git', 'revision': source},
        },
        'validation': [],
        'acceptance': {'current': acceptance},
        'metadata': {'created_at': '2026-01-01T00:00:00+00:00'},
    })
    write_yaml(project / 'specforge/history/acceptances' / f'{acceptance}.yaml', {
        'id': acceptance,
        'checkpoint': checkpoint,
        'decision': 'accepted',
        'candidate': {'material': {
            'provider': snapshot['provider'],
            'revision': snapshot['revision'],
            'file_count': snapshot['file_count'],
        }},
        'included_changes_digest': digest,
        'actor': {'type': 'human', 'id': 'fixture-product-owner'},
        'timestamp': '2026-01-01T00:00:01+00:00',
        'mechanism': {'type': 'test_fixture', 'reference': 'reconciliation'},
        'evidence': {'candidate_revision': snapshot['revision'], 'requirements': []},
    })
    return snapshot, source


with tempfile.TemporaryDirectory(prefix='specforge-reconcile-clean-') as td:
    project = Path(td) / 'project'
    create_project(project, CORE, git_backed=True, material_roots=MATERIAL_ROOTS)
    layout = discover_layout(project)
    check = evaluate(layout)
    expect(check.get('valid') is True, 'clean-state-remains-valid', str(check))
    expect(not (check.get('details') or {}).get('reconciliation'), 'clean-state-creates-no-reconciliation', str(check))


with tempfile.TemporaryDirectory(prefix='specforge-reconcile-unexplained-') as td:
    project = Path(td) / 'project'
    create_project(project, CORE, git_backed=True, material_roots=MATERIAL_ROOTS)
    layout = discover_layout(project)
    readme = project / 'README.md'
    readme.write_text(readme.read_text(encoding='utf-8') + '\nmanual edit\n', encoding='utf-8')
    check = evaluate(layout)
    expect(check.get('valid') is False, 'unexplained-material-blocked', str(check))
    expect('material_reconciliation_required' in (check.get('blockers') or []), 'unexplained-material-routed-to-reconciliation', str(check))
    reconciliation = (check.get('details') or {}).get('reconciliation') or {}
    expect(reconciliation.get('kind') == 'unexplained_material', 'unexplained-material-classified', str(check))
    captured = capture_reconciliation_observation(layout, check)
    expect(captured.get('captured') is True, 'unexplained-observation-captured', str(captured))
    record = captured.get('record') or {}
    expect(record.get('status') == 'observed', 'captured-observation-is-not-authority', str(record))
    expect(record.get('provenance', {}).get('verified') is False, 'captured-observation-does-not-invent-provenance', str(record))
    expect('README.md' in record.get('material', {}).get('paths', []), 'captured-observation-binds-path', str(record))

    source_id = captured.get('reconciliation')
    kept = record_reconciliation_decision(
        layout,
        source_id,
        'keep',
        actor_id='fixture-product-owner',
        provenance_claim='Intentional manual edit',
        provenance_source='fixture-user',
    )
    expect(kept.get('recorded') is True, 'keep-decision-recorded-additively', str(kept))
    expect(kept.get('next_action') == 'prospective_adoption_proposal', 'keep-requires-prospective-adoption', str(kept))
    successor = kept.get('record') or {}
    expect(successor.get('supersedes') == source_id and successor.get('status') == 'acknowledged', 'keep-creates-successor-not-retroactive-authority', str(successor))
    original, _ = reconciliation_record(layout, source_id)
    expect(original.get('status') == 'observed' and not original.get('acknowledgement'), 'original-observation-remains-immutable', str(original))


with tempfile.TemporaryDirectory(prefix='specforge-reconcile-stale-') as td:
    project = Path(td) / 'project'
    create_project(project, CORE, git_backed=True, material_roots=MATERIAL_ROOTS)
    layout = discover_layout(project)
    readme = project / 'README.md'
    readme.write_text(readme.read_text(encoding='utf-8') + '\nmanual edit one\n', encoding='utf-8')
    captured = capture_reconciliation_observation(layout, evaluate(layout))
    rec_id = captured.get('reconciliation')
    readme.write_text(readme.read_text(encoding='utf-8') + 'manual edit two\n', encoding='utf-8')
    stale = record_reconciliation_decision(layout, rec_id, 'undo', actor_id='fixture-product-owner')
    expect(stale.get('recorded') is False, 'stale-observation-cannot-be-acted-on', str(stale))
    expect('reconciliation_candidate_stale' in (stale.get('blockers') or []), 'stale-observation-has-explicit-blocker', str(stale))


with tempfile.TemporaryDirectory(prefix='specforge-reconcile-ambiguous-') as td:
    project = Path(td) / 'project'
    create_project(project, CORE, git_backed=True, material_roots=MATERIAL_ROOTS)
    layout = discover_layout(project)
    snapshot = material_snapshot(layout)
    root = project / 'specforge/evidence/reconciliations'
    write_yaml(root / 'REC-0001.yaml', {
        'id': 'REC-0001',
        'profile': 'material_reconciliation_v1',
        'kind': 'ambiguous_material',
        'status': 'blocked',
        'created_at': '2026-01-01T00:00:00+00:00',
        'trusted': {'provider': 'git', 'revision': git(project, 'rev-parse', 'HEAD').stdout.strip()},
        'observed': {'provider': 'git', 'revision': git(project, 'rev-parse', 'HEAD').stdout.strip()},
        'material': {
            'paths': [],
            'snapshot': {'provider': snapshot['provider'], 'revision': snapshot['revision'], 'file_count': snapshot['file_count']},
            'path_digests': {},
        },
        'provenance': {'claim': None, 'source': None, 'verified': False},
        'blockers': ['ambiguous_fixture'],
    })
    unsafe = record_reconciliation_decision(layout, 'REC-0001', 'keep', actor_id='fixture-product-owner')
    expect(unsafe.get('recorded') is False, 'ambiguous-material-cannot-one-click-keep', str(unsafe))
    expect('ambiguous_material_requires_manager_review' in (unsafe.get('blockers') or []), 'ambiguous-material-fails-closed', str(unsafe))
    leave = record_reconciliation_decision(layout, 'REC-0001', 'leave_untouched', actor_id='fixture-product-owner')
    expect(leave.get('recorded') is True and leave.get('next_action') == 'remain_blocked', 'ambiguous-material-can-only-remain-blocked', str(leave))


with tempfile.TemporaryDirectory(prefix='specforge-reconcile-mixed-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True, material_roots=MATERIAL_ROOTS)
    trusted = state['trusted_revision']
    install_controlled_change(
        project,
        'CHG-9002',
        status='in_progress',
        attempt=True,
        before=trusted,
        outcome='in_progress',
        lifecycle_enforcement='controlled_v3',
        declared_scope=[{'operation': 'modify', 'path': 'README.md'}],
    )
    git(project, 'add', 'specforge/changes', 'specforge/evidence')
    git(project, 'commit', '-m', 'start scoped implementation')
    (project / 'README.md').write_text('approved scope edit\n', encoding='utf-8')
    (project / 'product.txt').write_text('unexplained side edit\n', encoding='utf-8')
    check = evaluate(discover_layout(project))
    expect(check.get('valid') is False, 'mixed-material-blocked', str(check))
    expect('mixed_authorized_and_unexplained_material' in (check.get('blockers') or []), 'mixed-state-detected', str(check))
    reconciliation = (check.get('details') or {}).get('reconciliation') or {}
    expect(reconciliation.get('kind') == 'mixed_material', 'mixed-state-classified', str(check))
    expect(reconciliation.get('paths') == ['product.txt'], 'mixed-state-isolates-unexplained-path', str(check))


with tempfile.TemporaryDirectory(prefix='specforge-reconcile-bookkeeping-') as td:
    project = Path(td) / 'project'
    create_project(project, CORE, git_backed=True, material_roots=MATERIAL_ROOTS)
    snapshot, _ = accepted_checkpoint_fixture(project)
    git(project, 'add', 'specforge/history')
    git(project, 'commit', '-m', 'record accepted checkpoint without authority pointer update')
    layout = discover_layout(project)
    state = authority_bookkeeping_state(layout)
    expect(state.get('state') == 'pointer_drift', 'accepted-checkpoint-pointer-drift-detected', str(state))
    expect(state.get('repairable') is True, 'pointer-drift-repairable-only-when-candidate-current', str(state))
    check = evaluate(layout)
    expect(check.get('valid') is False, 'pointer-drift-blocks-normal-authority', str(check))
    expect('authority_bookkeeping_reconciliation_required' in (check.get('blockers') or []), 'pointer-drift-has-dedicated-blocker', str(check))
    captured = capture_reconciliation_observation(layout, check)
    expect(captured.get('captured') is True, 'bookkeeping-observation-captured', str(captured))
    rec_id = captured.get('reconciliation')
    repaired = repair_authority_bookkeeping(layout, rec_id)
    expect(repaired.get('repaired') is True, 'canonical-pointer-drift-repaired', str(repaired))
    authority = load_authority(layout)
    accepted = authority.get('accepted_checkpoint') or {}
    expect(accepted.get('id') == 'CHK-9901' and accepted.get('acceptance') == 'ACC-9901', 'repair-binds-canonical-acceptance', str(authority))
    expect((accepted.get('candidate_material') or {}).get('revision') == snapshot['revision'], 'repair-does-not-change-accepted-candidate', str(authority))
    source, _ = reconciliation_record(layout, rec_id)
    expect(source.get('status') == 'observed', 'bookkeeping-observation-remains-immutable', str(source))
    successor = (repaired.get('reconciliation') or {}).get('record') or {}
    expect(successor.get('status') == 'repaired' and successor.get('supersedes') == rec_id, 'bookkeeping-repair-is-additive-successor', str(successor))



with tempfile.TemporaryDirectory(prefix='specforge-reconcile-undo-') as td:
    project = Path(td) / 'project'
    create_project(project, CORE, git_backed=True, material_roots=MATERIAL_ROOTS)
    layout = discover_layout(project)
    readme = project / 'README.md'
    trusted_text = readme.read_text(encoding='utf-8')
    readme.write_text(trusted_text + '\nmanual undo candidate\n', encoding='utf-8')
    captured = capture_reconciliation_observation(layout, evaluate(layout))
    observed_id = captured.get('reconciliation')
    acknowledged = record_reconciliation_decision(layout, observed_id, 'undo', actor_id='fixture-product-owner')
    expect(acknowledged.get('recorded') is True, 'undo-decision-recorded-additively', str(acknowledged))
    acknowledged_id = acknowledged.get('reconciliation')
    applied = apply_reconciliation_recovery(layout, acknowledged_id)
    expect(applied.get('applied') is True, 'undo-restores-exact-trusted-material', str(applied))
    expect(readme.read_text(encoding='utf-8') == trusted_text, 'undo-restores-original-file-bytes', readme.read_text(encoding='utf-8'))
    expect(evaluate(layout).get('valid') is True, 'undo-leaves-material-authority-clean', str(evaluate(layout)))
    successor, _ = reconciliation_record(layout, applied.get('reconciliation'))
    expect(successor.get('status') == 'undone' and successor.get('supersedes') == acknowledged_id, 'undo-is-additive-successor', str(successor))


with tempfile.TemporaryDirectory(prefix='specforge-reconcile-quarantine-') as td:
    project = Path(td) / 'project'
    create_project(project, CORE, git_backed=True, material_roots=MATERIAL_ROOTS)
    layout = discover_layout(project)
    product = project / 'product.txt'
    trusted_text = product.read_text(encoding='utf-8')
    external_text = trusted_text + '\nmanual quarantine candidate\n'
    product.write_text(external_text, encoding='utf-8')
    captured = capture_reconciliation_observation(layout, evaluate(layout))
    observed_id = captured.get('reconciliation')
    acknowledged = record_reconciliation_decision(layout, observed_id, 'set_aside', actor_id='fixture-product-owner')
    expect(acknowledged.get('recorded') is True, 'set-aside-decision-recorded-additively', str(acknowledged))
    acknowledged_id = acknowledged.get('reconciliation')
    applied = apply_reconciliation_recovery(layout, acknowledged_id)
    expect(applied.get('applied') is True, 'set-aside-restores-trusted-material', str(applied))
    expect(product.read_text(encoding='utf-8') == trusted_text, 'set-aside-restores-original-file-bytes', product.read_text(encoding='utf-8'))
    quarantine = applied.get('quarantine') or {}
    reference = quarantine.get('reference')
    expect(quarantine.get('provider') == 'specforge_quarantine_v1' and reference, 'set-aside-records-provider-neutral-quarantine-reference', str(applied))
    manifest = project / reference
    expect(manifest.is_file(), 'set-aside-preserves-quarantine-manifest', str(manifest))
    preserved = manifest.parent / 'files' / 'product.txt'
    expect(preserved.is_file() and preserved.read_text(encoding='utf-8') == external_text, 'set-aside-preserves-external-file-bytes', str(preserved))
    expect(evaluate(layout).get('valid') is True, 'set-aside-leaves-material-authority-clean', str(evaluate(layout)))
    successor, _ = reconciliation_record(layout, applied.get('reconciliation'))
    expect(successor.get('status') == 'quarantined' and successor.get('supersedes') == acknowledged_id, 'set-aside-is-additive-successor', str(successor))



# CHG-1055: revalidation records for one material candidate collapse without losing
# earlier distinct material candidates for the same active change.
with tempfile.TemporaryDirectory(prefix='specforge-reconcile-material-candidate-') as td:
    project=Path(td)/'project'
    state=create_project(project,CORE,git_backed=True,material_roots=MATERIAL_ROOTS)
    trusted=state['trusted_revision']
    ids=install_controlled_change(
        project,'CHG-9100',status='in_progress',attempt=True,before=trusted,outcome='blocked',
        lifecycle_enforcement='controlled_v3',
        declared_scope=[{'operation':'modify','path':'README.md'}]
    )
    git(project,'add','specforge/changes','specforge/evidence'); git(project,'commit','-m','register first attempt')
    first=project/'specforge/changes/CHG-9100/implementation/IMP-9100-01.yaml'
    (project/'README.md').write_text('first material candidate\n',encoding='utf-8')
    git(project,'add','README.md'); git(project,'commit','-m','first material candidate')
    candidate_one=git(project,'rev-parse','HEAD').stdout.strip()
    first_imp=yaml.safe_load(first.read_text(encoding='utf-8'))
    first_imp['source_revision']['after']=candidate_one
    first.write_text(yaml.safe_dump(first_imp,sort_keys=False),encoding='utf-8',newline='\n')
    git(project,'add',str(first.relative_to(project))); git(project,'commit','-m','bind first material candidate')

    second=project/'specforge/changes/CHG-9100/implementation/IMP-9100-02.yaml'
    revalidation=yaml.safe_load(first.read_text(encoding='utf-8'))
    revalidation['id']='IMP-9100-02'
    revalidation['attempt']=2
    revalidation['outcome']='passed'
    revalidation['source_revision']['before']=git(project,'rev-parse','HEAD').stdout.strip()
    second.write_text(yaml.safe_dump(revalidation,sort_keys=False),encoding='utf-8',newline='\n')
    change_path=project/'specforge/changes/CHG-9100.yaml'
    change=yaml.safe_load(change_path.read_text(encoding='utf-8'))
    change['implementation']['attempts'].append('IMP-9100-02')
    change_path.write_text(yaml.safe_dump(change,sort_keys=False),encoding='utf-8',newline='\n')
    git(project,'add','specforge/changes'); git(project,'commit','-m','record revalidation attempt')

    check=evaluate(discover_layout(project))
    expect(check.get('valid') is True,'duplicate-revalidation-collapses-same-material-candidate',str(check))
    chain=(check.get('details') or {}).get('implementation_authority_chain') or {}
    attempts=[x.get('attempt') for x in chain.get('layers') or []]
    expect(attempts==['IMP-9100-01'],'original-material-attempt-represents-candidate',str(chain))

    third=project/'specforge/changes/CHG-9100/implementation/IMP-9100-03.yaml'
    third_before=git(project,'rev-parse','HEAD').stdout.strip()
    (project/'README.md').write_text('second material candidate\n',encoding='utf-8')
    git(project,'add','README.md'); git(project,'commit','-m','second material candidate')
    candidate_two=git(project,'rev-parse','HEAD').stdout.strip()
    later=yaml.safe_load(first.read_text(encoding='utf-8'))
    later['id']='IMP-9100-03'
    later['attempt']=3
    later['outcome']='blocked'
    later['source_revision']['before']=third_before
    later['source_revision']['after']=candidate_two
    third.write_text(yaml.safe_dump(later,sort_keys=False),encoding='utf-8',newline='\n')
    change=yaml.safe_load(change_path.read_text(encoding='utf-8'))
    change['implementation']['attempts'].append('IMP-9100-03')
    change_path.write_text(yaml.safe_dump(change,sort_keys=False),encoding='utf-8',newline='\n')
    git(project,'add','specforge/changes'); git(project,'commit','-m','record distinct later material candidate')
    check=evaluate(discover_layout(project))
    expect(check.get('valid') is True,'distinct-material-candidates-for-one-change-remain-layered',str(check))
    chain=(check.get('details') or {}).get('implementation_authority_chain') or {}
    attempts=[x.get('attempt') for x in chain.get('layers') or []]
    expect(attempts==['IMP-9100-01','IMP-9100-03'],'same-change-distinct-candidates-retained',str(chain))


# CHG-1055: ordered descendant implementation layers may explain approved material without advancing trust.
with tempfile.TemporaryDirectory(prefix='specforge-reconcile-stacked-') as td:
    project=Path(td)/'project'
    state=create_project(project,CORE,git_backed=True,material_roots=MATERIAL_ROOTS)
    trusted=state['trusted_revision']
    install_controlled_change(project,'CHG-9101',status='in_progress',attempt=True,before=trusted,outcome='blocked',lifecycle_enforcement='controlled_v3',declared_scope=[{'operation':'modify','path':'README.md'}])
    git(project,'add','specforge/changes','specforge/evidence'); git(project,'commit','-m','start first stacked layer')
    (project/'README.md').write_text('stacked layer one\n',encoding='utf-8'); git(project,'add','README.md'); git(project,'commit','-m','first stacked material')
    (project/'product.txt').write_text('pre-existing prospective adoption\n',encoding='utf-8'); git(project,'add','product.txt'); git(project,'commit','-m','pre-existing later-scope material')
    second_before=git(project,'rev-parse','HEAD').stdout.strip()
    install_controlled_change(project,'CHG-9102',status='in_progress',attempt=True,before=second_before,outcome='in_progress',lifecycle_enforcement='controlled_v3',declared_scope=[{'operation':'modify','path':'product.txt'}])
    git(project,'add','specforge/changes','specforge/evidence'); git(project,'commit','-m','start second stacked layer')
    layout=discover_layout(project); check=evaluate(layout)
    expect(check.get('valid') is True,'stacked-descendant-layers-authorize-current-material',str(check))
    chain=(check.get('details') or {}).get('implementation_authority_chain') or {}
    expect([x.get('attempt') for x in chain.get('layers') or []]==['IMP-9101-01','IMP-9102-01'],'stacked-layers-ordered-by-lineage',str(chain))
    expect((chain.get('layers') or [])[0].get('outcome')=='blocked','blocked-layer-may-explain-presence-only',str(chain))
    expect((load_authority(layout).get('trusted') or {}).get('revision')==trusted,'stacked-evaluation-does-not-advance-trust',str(load_authority(layout)))
    (project/'model.txt').write_text('uncovered material\n',encoding='utf-8')
    uncovered=evaluate(layout)
    expect(uncovered.get('valid') is False,'stacked-uncovered-material-fails-closed',str(uncovered))
    expect('unauthorized_material_path:model.txt' in (uncovered.get('blockers') or []),'stacked-uncovered-path-is-explicit',str(uncovered))

with tempfile.TemporaryDirectory(prefix='specforge-reconcile-divergent-stack-') as td:
    project=Path(td)/'project'
    create_project(project,CORE,git_backed=True,material_roots=MATERIAL_ROOTS)
    base=git(project,'rev-parse','HEAD').stdout.strip()
    git(project,'checkout','-b','layer-a'); (project/'README.md').write_text('branch a\n',encoding='utf-8'); git(project,'add','README.md'); git(project,'commit','-m','layer a material'); before_a=git(project,'rev-parse','HEAD').stdout.strip()
    git(project,'checkout','-b','layer-b',base); (project/'product.txt').write_text('branch b\n',encoding='utf-8'); git(project,'add','product.txt'); git(project,'commit','-m','layer b material'); before_b=git(project,'rev-parse','HEAD').stdout.strip()
    git(project,'checkout','-b','merged-stack',before_a); git(project,'merge','--no-ff',before_b,'-m','merge divergent layer baselines')
    install_controlled_change(project,'CHG-9111',status='in_progress',attempt=True,before=before_a,outcome='blocked',lifecycle_enforcement='controlled_v3',declared_scope=[{'operation':'modify','path':'README.md'}])
    install_controlled_change(project,'CHG-9112',status='in_progress',attempt=True,before=before_b,outcome='in_progress',lifecycle_enforcement='controlled_v3',declared_scope=[{'operation':'modify','path':'product.txt'}])
    git(project,'add','specforge/changes','specforge/evidence'); git(project,'commit','-m','register divergent stacked authorities')
    divergent=evaluate(discover_layout(project))
    expect(divergent.get('valid') is False,'divergent-stacked-baselines-fail-closed',str(divergent))
    expect(any(str(x).startswith('stacked_material_lineage_incomparable:') for x in divergent.get('blockers') or []),'divergent-stack-has-lineage-blocker',str(divergent))


print('Material reconciliation regression tests PASSED')
