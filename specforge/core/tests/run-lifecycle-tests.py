#!/usr/bin/env python3
from pathlib import Path
import importlib.util, json, os, shutil, subprocess, sys, tempfile, yaml

CORE = Path(__file__).resolve().parents[1]
TOOLS = CORE / 'tools'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Portable fixture repositories must preserve the bytes copied into them. Inherited
# host core.autocrlf settings can otherwise rewrite the Git representation and create
# false immutable-material drift on Windows even when line endings are non-material.
_git_config_count = int(os.environ.get('GIT_CONFIG_COUNT', '0') or '0')
os.environ[f'GIT_CONFIG_KEY_{_git_config_count}'] = 'core.autocrlf'
os.environ[f'GIT_CONFIG_VALUE_{_git_config_count}'] = 'false'
os.environ['GIT_CONFIG_COUNT'] = str(_git_config_count + 1)

from portable_fixture import create_project, git, install_controlled_change, write_yaml, canonical_digest
from specforge_project import discover_layout, iter_record_files, load_yaml
from specforge_integration import PROFILE, build_git_integration_evidence

_lifecycle_spec = importlib.util.spec_from_file_location('specforge_lifecycle_chg1035', TOOLS / 'specforge-lifecycle.py')
lifecycle_module = importlib.util.module_from_spec(_lifecycle_spec)
_lifecycle_spec.loader.exec_module(lifecycle_module)


def run(root, *args):
    tool = root / 'specforge/core/tools/specforge-lifecycle.py'
    return subprocess.run([sys.executable, '-B', str(tool), *args, '--root', str(root), '--json'], capture_output=True, text=True)


def check(name, condition, detail=''):
    if not condition:
        if detail:
            print(detail)
        raise AssertionError(name)
    print('PASS', name)


def result_json(result):
    return json.loads(result.stdout)


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    install_controlled_change(root, 'CHG-9003', status='approved', attempt=False)
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'portable lifecycle fixture')
    r = run(root, 'bootstrap')
    check('bootstrap-ready', r.returncode == 0, r.stdout + r.stderr)
    r = run(root, 'transition', 'CHG-9003', '--to', 'in_progress')
    check('exact-approval-permits-implementation', r.returncode == 0, r.stdout + r.stderr)


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    before = state['trusted_revision']
    install_controlled_change(root, 'CHG-9004', status='in_progress', attempt=True, before=before, outcome='in_progress')
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start portable implementation')
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'portable material implementation')
    core_meta = root / 'specforge/core/core.yaml'
    meta = yaml.safe_load(core_meta.read_text(encoding='utf-8'))
    meta['material_revision']['verification_profile'] = 'immutable_material_v2'
    core_meta.write_text(yaml.safe_dump(meta, sort_keys=False), encoding='utf-8', newline='\n')
    git(root, 'add', 'specforge/core/core.yaml')
    git(root, 'commit', '-m', 'fixture v2 profile')
    after = git(root, 'rev-parse', 'HEAD').stdout.strip()
    install_controlled_change(root, 'CHG-9004', status='validated', attempt=True, before=before, after=after, outcome='passed')
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'record passed portable implementation')
    r = run(root, 'transition', 'CHG-9004', '--to', 'completed')
    check('v2-completed-change-has-valid-completion-evidence', r.returncode == 0, r.stdout + r.stderr)


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    before = state['trusted_revision']
    install_controlled_change(root, 'CHG-9005', status='validated', attempt=True, before=before, outcome='passed')
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'missing source-after fixture')
    r = run(root, 'transition', 'CHG-9005', '--to', 'completed')
    out = result_json(r)
    check(
        'completion-refused-without-evidence',
        r.returncode != 0 and (
            'passed_implementation_with_required_evidence_and_source_revision_missing' in out.get('blockers', [])
            or 'integration_evidence_required_by_current_material_profile' in out.get('blockers', [])
        ),
        r.stdout + r.stderr,
    )


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    rec = install_controlled_change(root, 'CHG-9006', status='approved', attempt=False)
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'proposal tamper fixture')
    rec['proposal_path'].write_text(rec['proposal_path'].read_text(encoding='utf-8') + '\n# tamper\n', encoding='utf-8')
    r = run(root, 'transition', 'CHG-9006', '--to', 'in_progress')
    out = result_json(r)
    check('proposal-digest-tamper-blocked', r.returncode != 0 and 'valid_exact_human_approval_missing' in out.get('blockers', []), r.stdout + r.stderr)


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    equal = state['trusted_revision']
    install_controlled_change(root, 'CHG-9007', status='validated', attempt=True, before=equal, after=equal, outcome='passed')
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'false completion fixture')
    r = run(root, 'transition', 'CHG-9007', '--to', 'completed')
    out = result_json(r)
    check(
        'false-completion-refused',
        r.returncode != 0 and 'passed_implementation_with_required_evidence_and_source_revision_missing' in out.get('blockers', []),
        r.stdout + r.stderr,
    )


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    git(root, 'branch', '-M', 'main')
    before = state['trusted_revision']
    install_controlled_change(
        root,
        'CHG-9015',
        status='in_progress',
        attempt=True,
        before=before,
        outcome='in_progress',
        verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start v3 governed implementation')
    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()

    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'v3 material implementation')
    after = git(root, 'rev-parse', 'HEAD').stdout.strip()

    layout = discover_layout(root)
    built = build_git_integration_evidence(
        layout,
        {
            'system': 'git',
            'before': before,
            'after': after,
            'material_effects': True,
            'verification_profile': PROFILE,
        },
        'main',
        target_before,
    )
    check('v3-lifecycle-fixture-integration-built', built['valid'], str(built))
    install_controlled_change(
        root,
        'CHG-9015',
        status='validated',
        attempt=True,
        before=before,
        after=after,
        outcome='passed',
        integration=built['integration'],
        verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'record v3 integration evidence')

    r = run(root, 'transition', 'CHG-9015', '--to', 'completed')
    check('v3-integration-aware-completion-permitted', r.returncode == 0, r.stdout + r.stderr)

    attempt_path = root / 'specforge/changes/CHG-9015/implementation/IMP-9015-01.yaml'
    attempt = yaml.safe_load(attempt_path.read_text(encoding='utf-8'))
    attempt.pop('integration', None)
    attempt_path.write_text(yaml.safe_dump(attempt, sort_keys=False), encoding='utf-8', newline='\n')
    r = run(root, 'transition', 'CHG-9015', '--to', 'completed')
    out = result_json(r)
    check(
        'v3-completion-refused-without-integration-evidence',
        r.returncode != 0 and 'integration_evidence_required_by_current_material_profile' in out.get('blockers', []),
        r.stdout + r.stderr,
    )

# CHG-1023: completion uses scoped repository validation, explicit bootstrap remains full.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)

    historical = state['trusted_revision']
    install_controlled_change(
        root,
        'CHG-9020',
        status='completed',
        attempt=True,
        before=historical,
        after=historical,
        outcome='passed',
        verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'bad unrelated historical completion')

    full_bootstrap = run(root, 'bootstrap')
    check('explicit-bootstrap-remains-full-and-sees-bad-history', full_bootstrap.returncode != 0, full_bootstrap.stdout + full_bootstrap.stderr)

    current = git(root, 'rev-parse', 'HEAD').stdout.strip()
    install_controlled_change(
        root,
        'CHG-9021',
        status='validated',
        attempt=True,
        before=current,
        after=current,
        outcome='passed',
        verification_profile=PROFILE,
    )
    attempt_path = root / 'specforge/changes/CHG-9021/implementation/IMP-9021-01.yaml'
    attempt = yaml.safe_load(attempt_path.read_text(encoding='utf-8'))
    attempt['source_revision']['material_effects'] = False
    attempt_path.write_text(yaml.safe_dump(attempt, sort_keys=False), encoding='utf-8', newline='\n')
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'record non-material scoped completion fixture')

    scoped_completion = run(root, 'transition', 'CHG-9021', '--to', 'completed')
    check('completion-ignores-unrelated-bad-history', scoped_completion.returncode == 0, scoped_completion.stdout + scoped_completion.stderr)

    change_path = root / 'specforge/changes/CHG-9021.yaml'
    change = yaml.safe_load(change_path.read_text(encoding='utf-8'))
    change.setdefault('relationships', {})['depends_on'] = ['CHG-9020']
    change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding='utf-8', newline='\n')
    dependent_completion = run(root, 'transition', 'CHG-9021', '--to', 'completed')
    check(
        'completion-validates-bad-explicit-dependency',
        dependent_completion.returncode != 0 and 'bootstrap:repository_validation_failed' in result_json(dependent_completion).get('blockers', []),
        dependent_completion.stdout + dependent_completion.stderr,
    )

# CHG-1028: lifecycle bootstrap aligns with repository-validator empty-collection semantics.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    decisions = root / 'specforge/decisions'
    if decisions.exists():
        shutil.rmtree(decisions)
    r = run(root, 'bootstrap')
    check(
        'bootstrap-allows-absent-empty-decisions-collection',
        r.returncode == 0 and 'missing_path:decisions' not in result_json(r).get('blockers', []),
        r.stdout + r.stderr,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    packs = root / 'specforge/packs'
    if packs.exists():
        shutil.rmtree(packs)
    r = run(root, 'bootstrap')
    check(
        'bootstrap-allows-absent-packs-when-none-installed',
        r.returncode == 0 and 'missing_path:packs' not in result_json(r).get('blockers', []),
        r.stdout + r.stderr,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    manifest_path = root / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['packs'] = [{
        'id': 'missing-pack',
        'version': '0.1.0',
        'path': './specforge/packs/missing-pack',
        'precedence': 10,
        'extensions': ['rules'],
    }]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding='utf-8', newline='\n')
    packs = root / 'specforge/packs'
    if packs.exists():
        shutil.rmtree(packs)
    r = run(root, 'bootstrap')
    check(
        'bootstrap-requires-packs-path-when-pack-installed',
        r.returncode != 0 and 'missing_path:packs' in result_json(r).get('blockers', []),
        r.stdout + r.stderr,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    evidence = root / 'specforge/evidence'
    if evidence.exists():
        shutil.rmtree(evidence)
    r = run(root, 'bootstrap')
    check(
        'bootstrap-still-requires-mandatory-evidence-path',
        r.returncode != 0 and 'missing_path:evidence' in result_json(r).get('blockers', []),
        r.stdout + r.stderr,
    )



# CHG-1029: later completed governed material can bridge an older completion, but only uniquely.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    git(root, 'branch', '-M', 'main')
    before = state['trusted_revision']

    # Older governed change: material one -> two, valid evidence, left open.
    install_controlled_change(
        root, 'CHG-9030', status='in_progress', attempt=True, before=before,
        outcome='in_progress', verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start older governed change')
    target_before_1 = git(root, 'rev-parse', 'HEAD').stdout.strip()
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'older governed material')
    after_1 = git(root, 'rev-parse', 'HEAD').stdout.strip()
    built_1 = build_git_integration_evidence(
        discover_layout(root),
        {'system': 'git', 'before': before, 'after': after_1, 'material_effects': True, 'verification_profile': PROFILE},
        'main', target_before_1,
    )
    check('successor-chain-source-evidence-built', built_1['valid'], str(built_1))
    install_controlled_change(
        root, 'CHG-9030', status='validated', attempt=True, before=before, after=after_1,
        outcome='passed', integration=built_1['integration'], verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'record older governed evidence')

    # First completed successor: two -> three.
    before_2 = git(root, 'rev-parse', 'HEAD').stdout.strip()
    install_controlled_change(
        root, 'CHG-9031', status='in_progress', attempt=True, before=before_2,
        outcome='in_progress', verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start first successor')
    target_before_2 = git(root, 'rev-parse', 'HEAD').stdout.strip()
    (root / 'product.txt').write_text('three\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'first successor material')
    after_2 = git(root, 'rev-parse', 'HEAD').stdout.strip()
    built_2 = build_git_integration_evidence(
        discover_layout(root),
        {'system': 'git', 'before': before_2, 'after': after_2, 'material_effects': True, 'verification_profile': PROFILE},
        'main', target_before_2,
    )
    check('successor-chain-first-bridge-built', built_2['valid'], str(built_2))
    install_controlled_change(
        root, 'CHG-9031', status='completed', attempt=True, before=before_2, after=after_2,
        outcome='passed', integration=built_2['integration'], verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'complete first successor')

    # Second completed successor: three -> four, proving multi-hop chaining.
    before_3 = git(root, 'rev-parse', 'HEAD').stdout.strip()
    install_controlled_change(
        root, 'CHG-9032', status='in_progress', attempt=True, before=before_3,
        outcome='in_progress', verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start second successor')
    target_before_3 = git(root, 'rev-parse', 'HEAD').stdout.strip()
    (root / 'product.txt').write_text('four\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'second successor material')
    after_3 = git(root, 'rev-parse', 'HEAD').stdout.strip()
    built_3 = build_git_integration_evidence(
        discover_layout(root),
        {'system': 'git', 'before': before_3, 'after': after_3, 'material_effects': True, 'verification_profile': PROFILE},
        'main', target_before_3,
    )
    check('successor-chain-second-bridge-built', built_3['valid'], str(built_3))
    install_controlled_change(
        root, 'CHG-9032', status='completed', attempt=True, before=before_3, after=after_3,
        outcome='passed', integration=built_3['integration'], verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'complete second successor')

    bridged = run(root, 'transition', 'CHG-9030', '--to', 'completed')
    check('multi-hop-governed-successor-chain-permits-older-completion', bridged.returncode == 0, bridged.stdout + bridged.stderr)

    # A successor that is no longer completed cannot bridge.
    successor_2_path = root / 'specforge/changes/CHG-9032.yaml'
    successor_2 = yaml.safe_load(successor_2_path.read_text(encoding='utf-8'))
    successor_2['status'] = 'validated'
    successor_2_path.write_text(yaml.safe_dump(successor_2, sort_keys=False), encoding='utf-8', newline='\n')
    incomplete = run(root, 'transition', 'CHG-9030', '--to', 'completed')
    check(
        'incomplete-successor-cannot-bridge',
        incomplete.returncode != 0 and 'governed_successor_material_chain_incomplete' in result_json(incomplete).get('blockers', []),
        incomplete.stdout + incomplete.stderr,
    )
    successor_2['status'] = 'completed'
    successor_2_path.write_text(yaml.safe_dump(successor_2, sort_keys=False), encoding='utf-8', newline='\n')

    # Exact human approval remains mandatory for a completed successor.
    saved_approvals = list(successor_2.get('approvals') or [])
    successor_2['approvals'] = []
    successor_2_path.write_text(yaml.safe_dump(successor_2, sort_keys=False), encoding='utf-8', newline='\n')
    unapproved = run(root, 'transition', 'CHG-9030', '--to', 'completed')
    check(
        'unapproved-successor-cannot-bridge',
        unapproved.returncode != 0 and 'governed_successor_material_chain_incomplete' in result_json(unapproved).get('blockers', []),
        unapproved.stdout + unapproved.stderr,
    )
    successor_2['approvals'] = saved_approvals
    successor_2_path.write_text(yaml.safe_dump(successor_2, sort_keys=False), encoding='utf-8', newline='\n')

    # A second otherwise-valid bridge from the same material is ambiguity, never a tie-break.
    install_controlled_change(
        root, 'CHG-9033', status='completed', attempt=True, before=before_3, after=after_3,
        outcome='passed', integration=built_3['integration'], verification_profile=PROFILE,
    )
    ambiguous = run(root, 'transition', 'CHG-9030', '--to', 'completed')
    check(
        'ambiguous-successor-chain-fails-closed',
        ambiguous.returncode != 0 and 'governed_successor_material_chain_ambiguous' in result_json(ambiguous).get('blockers', []),
        ambiguous.stdout + ambiguous.stderr,
    )
    shutil.rmtree(root / 'specforge/changes/CHG-9033')
    (root / 'specforge/changes/CHG-9033.yaml').unlink()

    # Material not covered by any completed successor remains ordinary uncaptured drift.
    (root / 'product.txt').write_text('five\n', encoding='utf-8', newline='\n')
    unexplained = run(root, 'transition', 'CHG-9030', '--to', 'completed')
    check(
        'unexplained-post-successor-material-still-blocked',
        unexplained.returncode != 0 and 'governed_successor_material_chain_incomplete' in result_json(unexplained).get('blockers', []),
        unexplained.stdout + unexplained.stderr,
    )

# CHG-1035: production controlled_v3 chronology parses real datetimes and fails before approval.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'chronology'
    create_project(root, CORE, git_backed=False)
    change_id = 'CHG-9090'
    prop_id = 'PROP-9090-01'
    apr_id = 'APR-9090'
    imp_id = 'IMP-9090-01'
    change_dir = root / 'specforge/changes' / change_id
    proposal_path = change_dir / f'{prop_id}.yaml'
    write_yaml(proposal_path, {'id': prop_id, 'change': change_id, 'revision': 1, 'status': 'awaiting_approval'})
    digest = canonical_digest(proposal_path)
    write_yaml(change_dir / 'approvals' / f'{apr_id}.yaml', {
        'id': apr_id, 'change': change_id, 'proposal': prop_id, 'decision': 'approved',
        'actor': {'type': 'human', 'id': 'fixture-owner'},
        'timestamp': '2026-09-23T14:00:00+00:00',
        'evidence': {'proposal_digest': digest},
    })
    write_yaml(root / 'specforge/changes' / f'{change_id}.yaml', {
        'id': change_id, 'status': 'in_progress', 'proposal': {'current': prop_id},
        'approvals': [apr_id], 'implementation': {'attempts': [imp_id]},
        'governance': {'lifecycle_enforcement': 'controlled_v3'},
    })
    implementation_path = change_dir / 'implementation' / f'{imp_id}.yaml'
    write_yaml(implementation_path, {
        'id': imp_id, 'change': change_id, 'proposal': prop_id,
        'started_at': '2026-09-23T13:59:59+00:00',
    })
    layout = discover_layout(root)
    recs = lifecycle_module.records(layout)
    blockers = lifecycle_module._controlled_v3_implementation_chronology_blockers(
        layout, recs, recs[change_id][0], recs[imp_id][0]
    )
    check('controlled-v3-implementation-before-approval-blocked', blockers == ['controlled_v3_implementation_predates_approval'], blockers)

    implementation = yaml.safe_load(implementation_path.read_text(encoding='utf-8'))
    implementation['started_at'] = '2026-09-23T14:00:01+00:00'
    write_yaml(implementation_path, implementation)
    recs = lifecycle_module.records(layout)
    blockers = lifecycle_module._controlled_v3_implementation_chronology_blockers(
        layout, recs, recs[change_id][0], recs[imp_id][0]
    )
    check('controlled-v3-implementation-after-approval-passes-chronology', blockers == [], blockers)


print('Lifecycle tests PASSED')


# CHG-1030 regression: lifecycle exposes checkpoint readiness without redefining completion.
_lifecycle_text = (CORE / 'tools/specforge-lifecycle.py').read_text(encoding='utf-8')
assert 'def checkpoint_readiness_gate' in _lifecycle_text
assert 'ready_for_checkpoint' in _lifecycle_text


# CHG-1034 regression: controlled_v3 is a supported prospective successor profile.
_lifecycle_1034 = (CORE / 'tools/specforge-lifecycle.py').read_text(encoding='utf-8')
assert '"controlled_v3"' in _lifecycle_1034
assert 'controlled_v3_implementation_predates_approval' in _lifecycle_1034
assert 'successor_v3' in _lifecycle_1034


# CHG-1054: HEC evidence is validation-only and cannot create active lifecycle authority.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'hec-not-authority'
    create_project(root, CORE, git_backed=True)
    install_controlled_change(root, 'CHG-9061', status='proposed', lifecycle_enforcement='controlled_v3', skip_approval=True)
    proof = root / 'specforge/evidence/informed-approvals/PRES-9061.yaml'
    write_yaml(proof, {
        'proposal': 'PROP-9061-01', 'proposal_digest': '0' * 64, 'presentation': 'PRES-9061',
        'change': 'CHG-9061', 'decision': 'approved', 'actor': {'type': 'human', 'id': 'fixture-product-owner'},
        'received_at': '2026-01-01T00:00:00+00:00',
    })
    git(root, 'add', 'specforge/changes', 'specforge/evidence')
    git(root, 'commit', '-m', 'unapproved change plus historical-shaped evidence')
    write_yaml(root / 'specforge/evidence/historical-compatibility/HEC-9061.yaml', {
        'id': 'HEC-9061', 'type': 'historical_evidence_compatibility', 'change': 'CHG-9061', 'version': 1,
        'created_at': '2099-01-02T00:00:00+00:00', 'effective_before': '2099-01-01T00:00:00+00:00',
        'rules': [{
            'id': 'HEC-9061-R01', 'issue': 'legacy_approval_proof_missing_type', 'status': 'active_with_notes',
            'target': {'id': 'PRES-9061', 'path': 'specforge/evidence/informed-approvals/PRES-9061.yaml', 'sha256': canonical_digest(proof)},
            'allowed_difference': 'Fixture compatibility must not become authority.',
            'evidence': {'approval': 'APR-9061', 'proposal': 'PROP-9061-01', 'expected_missing_field': 'type', 'expected_type_value': 'informed_approval_proof'},
            'notes': 'ALLOW WITH NOTES: fixture still cannot create active authority.',
        }],
    })
    git(root, 'add', 'specforge/evidence/historical-compatibility')
    git(root, 'commit', '-m', 'register non-authorising HEC fixture')
    r = run(root, 'transition', 'CHG-9061', '--to', 'in_progress')
    out = result_json(r)
    check('historical-compatibility-does-not-create-active-approval', r.returncode != 0 and 'valid_exact_human_approval_missing' in out.get('blockers', []), r.stdout + r.stderr)


# CHG-1055: blocked material authority does not satisfy lifecycle completion.
with tempfile.TemporaryDirectory() as td:
    root=Path(td)/'blocked-layer-not-complete'
    state=create_project(root,CORE,git_backed=True)
    install_controlled_change(root,'CHG-9062',status='validated',attempt=True,before=state['trusted_revision'],outcome='blocked',lifecycle_enforcement='controlled_v3',declared_scope=[{'operation':'modify','path':'README.md'}])
    git(root,'add','specforge/changes','specforge/evidence'); git(root,'commit','-m','blocked implementation completion fixture')
    r=run(root,'transition','CHG-9062','--to','completed')
    check('blocked-layer-cannot-satisfy-lifecycle-completion',r.returncode!=0,r.stdout+r.stderr)
