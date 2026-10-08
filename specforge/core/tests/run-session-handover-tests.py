#!/usr/bin/env python3
from pathlib import Path
import json, os, subprocess, sys, tempfile, yaml

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_fixture import canonical_digest, create_project, git, install_controlled_change, write_yaml

with tempfile.TemporaryDirectory(prefix='specforge-handover-') as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True, initialize_governance_tier=True)
    tools = root / 'specforge/core/tools'
    env = os.environ.copy(); env['PYTHONDONTWRITEBYTECODE'] = '1'

    defined = subprocess.run([
        sys.executable, '-B', str(tools / 'specforge-managed.py'), 'define',
        '--root', str(root),
        '--purpose', 'Maintain a portable governed handover test project',
        '--deliverable', 'A governed software project',
        '--audience', 'Project users',
        '--json',
    ], capture_output=True, text=True, env=env)
    assert defined.returncode == 0, defined.stdout + defined.stderr
    assert json.loads(defined.stdout)['created'] is True

    git(root, 'add', 'PROJECT.md', 'specforge/project.yaml')
    git(root, 'commit', '-m', 'fixture project definition')
    trusted = git(root, 'rev-parse', 'HEAD').stdout.strip()
    write_yaml(
        root / 'specforge/evidence/material-authority.yaml',
        {'version': 1, 'trusted': {'provider': 'git', 'revision': trusted}},
    )
    git(root, 'add', 'specforge/evidence/material-authority.yaml')
    git(root, 'commit', '-m', 'trust fixture project definition')

    installed = install_controlled_change(
        root,
        'CHG-9001',
        status='awaiting_approval',
        skip_approval=True,
        lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'modify', 'path': 'README.md'}],
        governance_tier={'requested': 'LOW'},
    )

    prepared = subprocess.run([
        sys.executable, '-B', str(tools / 'specforge-governance-tier.py'), 'prepare',
        installed['proposal'],
        '--root', str(root),
        '--json',
    ], capture_output=True, text=True, env=env)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    prepared_data = json.loads(prepared.stdout)
    assert prepared_data['prepared'] is True

    proposal_path = root / 'specforge/changes/CHG-9001/PROP-9001-01.yaml'
    proposal = yaml.safe_load(proposal_path.read_text(encoding='utf-8'))
    tier = proposal.get('governance_tier') or {}
    assert tier.get('requested') == 'LOW'
    assert tier.get('calculated_minimum') == 'LOW'
    assert isinstance(tier.get('policy_digest'), str) and len(tier['policy_digest']) == 64

    digest = canonical_digest(proposal_path)
    write_yaml(
        root / 'specforge/changes/CHG-9001/approvals/APR-9001.yaml',
        {
            'id': 'APR-9001',
            'change': 'CHG-9001',
            'proposal': 'PROP-9001-01',
            'decision': 'approved',
            'actor': {'type': 'human', 'id': 'fixture-product-owner'},
            'timestamp': '2026-01-01T00:00:00+00:00',
            'evidence': {
                'proposal_digest_algorithm': 'sha256',
                'proposal_digest': digest,
                'proposal_identity': 'PROP-9001-01',
            },
            'mechanism': {'type': 'test_fixture', 'reference': 'session-handover-contract'},
        },
    )
    change_path = root / 'specforge/changes/CHG-9001.yaml'
    change_data = yaml.safe_load(change_path.read_text(encoding='utf-8'))
    change_data['approvals'] = ['APR-9001']
    change_data['status'] = 'approved'
    write_yaml(change_path, change_data)
    boot = subprocess.run([sys.executable, '-B', str(tools / 'specforge-lifecycle.py'), 'bootstrap', '--root', str(root), '--json'], capture_output=True, text=True, env=env)
    assert boot.returncode == 0, boot.stdout + boot.stderr
    data = json.loads(boot.stdout)
    expected_core = yaml.safe_load((CORE / 'core.yaml').read_text(encoding='utf-8'))['core_version']
    assert data['ready'] is True and data['blockers'] == []
    assert data['details']['project_format'] == 1 and data['details']['core_version'] == expected_core
    managed = subprocess.run([
        sys.executable, '-B', str(tools / 'specforge-managed.py'), 'begin',
        '--root', str(root), '--session', 'SESSION-HANDOVER',
        '--request', 'Continue the governed portable change', '--change', 'CHG-9001', '--json'
    ], capture_output=True, text=True, env=env)
    assert managed.returncode == 0, managed.stdout + managed.stderr
    managed_data = json.loads(managed.stdout)
    assert managed_data['completion_guard']['version'] == 3
    guard = json.loads((root / 'specforge/evidence/managed-sessions/SESSION-HANDOVER.json').read_text(encoding='utf-8'))
    assert guard['request']['digest'].startswith('sha256:')
    assert 'project_definition_reconciliation' in guard
    assert guard['completion_guard_version'] == 3
    status = subprocess.run([sys.executable, '-B', str(tools / 'specforge-status.py'), '--root', str(root), '--json'], capture_output=True, text=True, env=env)
    assert status.returncode == 0, status.stdout + status.stderr
    report = json.loads(status.stdout)
    assert report['project']['id'] == 'PRJ-PORTABLE' and not report['gaps']
    change = next(item for item in report['changes']['open'] if item['id'] == 'CHG-9001')
    assert change['authority_state'] == 'approved'
    assert change['current_links']['proposal']['id'] == 'PROP-9001-01'
    assert change['effective_approval']['status'] == 'approved'
    guide = subprocess.run([
        sys.executable, '-B', str(tools / 'specforge-managed.py'), 'guide',
        '--root', str(root), '--change', 'CHG-9001', '--session', 'SESSION-HANDOVER', '--json'
    ], capture_output=True, text=True, env=env)
    assert guide.returncode == 0, guide.stdout + guide.stderr
    guidance = json.loads(guide.stdout)
    assert guidance['contract'] == 'guided_non_expert_v1'
    assert guidance['resolved'] == {'change': 'CHG-9001', 'session': 'SESSION-HANDOVER'}
    assert guidance['internal_next_action'] == 'implementation_validation'
    assert guidance['human_decision_required'] is False
print('Session handover tests PASSED')
