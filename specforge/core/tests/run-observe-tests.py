#!/usr/bin/env python3
from pathlib import Path
import json, subprocess, sys, tempfile

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_fixture import create_project, git

def run(root, *args):
    tool = root / 'specforge/core/tools/specforge-observe.py'
    result = subprocess.run([sys.executable, '-B', str(tool), *args, '--root', str(root), '--json'], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)

with tempfile.TemporaryDirectory(prefix='specforge-observe-') as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True, material_roots=['./README.md', './specforge/core'])
    first = run(root, 'mark', 'request_received', '--change', 'CHG-OBSERVE')
    assert first['mark']['source_control']['provider'] == 'git'
    (root / 'README.md').write_text('material change\n', encoding='utf-8')
    git(root, 'add', 'README.md'); git(root, 'commit', '-m', 'material change')
    evidence = root / 'specforge/evidence/observer-note.txt'
    evidence.write_text('governance evidence\n', encoding='utf-8')
    git(root, 'add', 'specforge/evidence'); git(root, 'commit', '-m', 'governance evidence')
    run(root, 'mark', 'validation_started', '--change', 'CHG-OBSERVE')
    run(root, 'mark', 'validation_started', '--change', 'CHG-OBSERVE')
    run(root, 'mark', 'validation_completed', '--change', 'CHG-OBSERVE')
    run(root, 'mark', 'change_completed', '--change', 'CHG-OBSERVE')
    report = run(root, 'summary', '--change', 'CHG-OBSERVE')
    amp = report['repository_amplification']
    assert amp['available'] is True
    assert amp['total_commits'] == 2, amp
    assert amp['material_changing_commits'] == 1, amp
    assert amp['governance_evidence_only_commits'] == 1, amp
    assert report['validation_attempts']['repeated_attempts']['legacy_validation'] == 1
    assert report['validation_attempts']['total_repeated_attempts'] == 1


    metrics = root / 'specforge/evidence/interaction-metrics.jsonl'

    def observed(phases):
        metrics.write_text(
            ''.join(
                json.dumps({
                    'event_id': f'ACT-{index}',
                    'timestamp': f'2026-09-24T09:{index:02d}:00.000Z',
                    'phase': phase,
                    'change': 'CHG-ACTIVITY',
                    **({'note': note} if note else {}),
                }) + '\n'
                for index, (phase, note) in enumerate(phases, start=1)
            ),
            encoding='utf-8',
        )
        return run(root, 'summary', '--change', 'CHG-ACTIVITY')

    implementation = observed([('request_received', None), ('implementation_started', 'Editing the approved files')])
    assert implementation['current_activity']['state'] == 'implementation'
    assert implementation['current_activity']['active'] is True
    assert implementation['current_activity']['elapsed_seconds'] is not None

    product_validation = observed([
        ('request_received', None),
        ('implementation_started', None),
        ('product_validation_started', 'Browser smoke is running'),
    ])
    assert product_validation['current_activity']['state'] == 'product_validation'
    assert product_validation['current_activity']['detail'] == 'Browser smoke is running'

    specforge_validation = observed([
        ('request_received', None),
        ('implementation_started', None),
        ('implementation_completed', None),
        ('specforge_validation_started', 'Immutable lineage passed; repository integrity is running'),
    ])
    assert specforge_validation['current_activity']['state'] == 'specforge_validation'
    assert 'repository integrity' in specforge_validation['current_activity']['detail']

    approval_wait = observed([('request_received', None), ('proposal_presented', None)])
    assert approval_wait['current_activity']['state'] == 'approval_wait'
    assert approval_wait['current_activity']['category'] == 'user_wait'

    clarification_wait = observed([('request_received', None), ('clarification_requested', None)])
    assert clarification_wait['current_activity']['state'] == 'clarification_wait'

    metrics.write_text('', encoding='utf-8')
    unavailable = run(root, 'summary', '--change', 'CHG-ACTIVITY')
    assert unavailable['current_activity']['state'] == 'unavailable'
    assert unavailable['current_activity']['elapsed_seconds'] is None

print('Observer amplification tests PASSED')
