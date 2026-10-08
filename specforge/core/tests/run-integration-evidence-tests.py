#!/usr/bin/env python3
from copy import deepcopy
from pathlib import Path
import sys
import tempfile

CORE = Path(__file__).resolve().parents[1]
TOOLS = CORE / 'tools'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from portable_fixture import create_project, git, write_yaml
from specforge_project import discover_layout, material_snapshot
from specforge_integration import (
    PROFILE,
    build_git_integration_evidence,
    build_snapshot_integration_evidence,
    capture_target,
    material_snapshot_for_git_revision,
    verified_material_bridge,
    verify_integration_evidence,
)


def check(name, condition, detail=''):
    if not condition:
        if detail:
            print(detail)
        raise AssertionError(name)
    print('PASS', name)


def source_revision(before, after):
    return {
        'system': 'git',
        'before': before,
        'after': after,
        'material_effects': True,
        'verification_profile': PROFILE,
    }


def init_git_case(td):
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    git(root, 'branch', '-M', 'main')
    return root, state


def implement_feature(root, text='two\n'):
    before = git(root, 'rev-parse', 'main').stdout.strip()
    git(root, 'checkout', '-b', 'feature')
    (root / 'product.txt').write_text(text, encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'feature material implementation')
    after = git(root, 'rev-parse', 'HEAD').stdout.strip()
    return before, after


def implementation_record(source, integration):
    return {
        'source_revision': source,
        'integration': integration,
    }


# Direct/fast-forward integration: the implementation commit itself may be the target-line revision.
with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    target_before, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    git(root, 'merge', '--ff-only', 'feature')
    layout = discover_layout(root)
    captured = capture_target(layout, target_before)
    check('capture-target-resolves-pre-integration-state', captured['captured'] and captured['target_before'] == target_before)
    built = build_git_integration_evidence(layout, source_revision(state['trusted_revision'], source_after), 'main', target_before)
    check('direct-integration-builds', built['valid'], str(built))
    check('direct-integration-selects-source-commit', built['integration']['integrated_revision'] == source_after)
    verified = verify_integration_evidence(layout, implementation_record(source_revision(state['trusted_revision'], source_after), built['integration']), mode='transition')
    check('direct-integration-verifies', verified['valid'], str(verified))


# Normal merge: first-parent target transition must identify the merge commit, not the same-tree source commit.
with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    target_before, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    git(root, 'merge', '--no-ff', 'feature', '-m', 'merge governed implementation')
    merge_commit = git(root, 'rev-parse', 'HEAD').stdout.strip()
    layout = discover_layout(root)
    built = build_git_integration_evidence(layout, source_revision(state['trusted_revision'], source_after), 'main', target_before)
    check('normal-merge-builds', built['valid'], str(built))
    check('normal-merge-discovers-target-merge-not-source', built['integration']['integrated_revision'] == merge_commit and merge_commit != source_after)
    attack = build_git_integration_evidence(
        layout,
        source_revision(state['trusted_revision'], source_after),
        'main',
        target_before,
        integrated_revision=source_after,
    )
    check('arbitrary-same-tree-source-commit-rejected', not attack['valid'] and 'integration_revision_not_mechanically_discovered_target_transition' in attack['blockers'])
    verified = verify_integration_evidence(layout, implementation_record(source_revision(state['trusted_revision'], source_after), built['integration']), mode='transition')
    check('normal-merge-verifies', verified['valid'], str(verified))
    tampered = deepcopy(built['integration'])
    tampered['integrated_material']['revision'] = 'sha256:' + ('0' * 64)
    rejected = verify_integration_evidence(layout, implementation_record(source_revision(state['trusted_revision'], source_after), tampered), mode='transition')
    check('stored-equivalence-claim-cannot-override-material-mismatch', not rejected['valid'] and 'integration_material_identity_mismatch' in rejected['blockers'])

    # AC-1015-10: a real commit with matching material but outside the accepted current lineage is rejected.
    git(root, 'checkout', '-b', 'off-target', target_before)
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'same material outside accepted target lineage')
    off_target = git(root, 'rev-parse', 'HEAD').stdout.strip()
    off_material = material_snapshot_for_git_revision(discover_layout(root), off_target)
    git(root, 'checkout', 'main')
    off_line = deepcopy(built['integration'])
    off_line['integrated_revision'] = off_target
    off_line['integrated_material'] = {
        'provider': 'specforge_snapshot',
        'revision': off_material['snapshot']['revision'],
        'file_count': off_material['snapshot']['file_count'],
    }
    rejected = verify_integration_evidence(
        discover_layout(root),
        implementation_record(source_revision(state['trusted_revision'], source_after), off_line),
        mode='transition',
    )
    check(
        'integrated-revision-outside-current-lineage-rejected',
        not rejected['valid'] and 'integrated_revision_not_on_current_project_lineage' in rejected['blockers'],
        str(rejected),
    )


# Squash integration: source-after ancestry is intentionally not required on the accepted line.
with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    target_before, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    git(root, 'merge', '--squash', 'feature')
    git(root, 'commit', '-m', 'squash governed implementation')
    squash_commit = git(root, 'rev-parse', 'HEAD').stdout.strip()
    check('squash-source-not-ancestor-of-target', git(root, 'merge-base', '--is-ancestor', source_after, squash_commit, check=False).returncode != 0)
    layout = discover_layout(root)
    built = build_git_integration_evidence(layout, source_revision(state['trusted_revision'], source_after), 'main', target_before)
    check('squash-integration-builds', built['valid'], str(built))
    check('squash-discovers-integrated-revision', built['integration']['integrated_revision'] == squash_commit)
    verified = verify_integration_evidence(layout, implementation_record(source_revision(state['trusted_revision'], source_after), built['integration']), mode='transition')
    check('batty-joe-chg0012-squash-topology-verifies-without-repair-merge', verified['valid'], str(verified))

    historical = implementation_record(source_revision(state['trusted_revision'], '0' * 40), deepcopy(built['integration']))
    static = verify_integration_evidence(layout, historical, mode='static')
    check('static-v3-survives-unreachable-source-object-using-persisted-material-proof', static['valid'], str(static))
    live = verify_integration_evidence(layout, historical, mode='transition')
    check('transition-v3-still-requires-live-source-evidence', not live['valid'] and 'source_revision_after_not_git_commit' in live['blockers'])


# Rebase-style integration: target advances with governance-only material, source commit is rewritten, then target fast-forwards.
with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    _original_target, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    history = root / 'specforge/history/EVT-rebase-fixture.yaml'
    history.write_text('fixture: governance-only target advance\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'specforge/history/EVT-rebase-fixture.yaml')
    git(root, 'commit', '-m', 'governance-only target advance')
    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()
    git(root, 'checkout', 'feature')
    git(root, 'rebase', 'main')
    rebased_after = git(root, 'rev-parse', 'HEAD').stdout.strip()
    git(root, 'checkout', 'main')
    git(root, 'merge', '--ff-only', 'feature')
    check('rebase-rewrites-source-commit', rebased_after != source_after)
    check('original-source-not-ancestor-after-rebase', git(root, 'merge-base', '--is-ancestor', source_after, rebased_after, check=False).returncode != 0)
    layout = discover_layout(root)
    built = build_git_integration_evidence(layout, source_revision(state['trusted_revision'], source_after), 'main', target_before)
    check('rebase-integration-builds-from-original-reviewed-source-material', built['valid'], str(built))
    check('rebase-discovers-rewritten-target-revision', built['integration']['integrated_revision'] == rebased_after)
    verified = verify_integration_evidence(layout, implementation_record(source_revision(state['trusted_revision'], source_after), built['integration']), mode='transition')
    check('rebase-integration-verifies', verified['valid'], str(verified))


# Integration containing additional material must not be accepted as equivalent.
with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    target_before, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    git(root, 'merge', '--squash', 'feature')
    (root / 'extra.txt').write_text('not reviewed\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'extra.txt')
    git(root, 'commit', '-m', 'squash with extra material')
    layout = discover_layout(root)
    built = build_git_integration_evidence(layout, source_revision(state['trusted_revision'], source_after), 'main', target_before)
    check('changed-integrated-material-rejected', not built['valid'] and 'integration_material_not_found_on_target_first_parent_path' in built['blockers'])


# Missing or false target provenance fails closed.
with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    target_before, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    git(root, 'merge', '--squash', 'feature')
    git(root, 'commit', '-m', 'squash governed implementation')
    layout = discover_layout(root)
    missing = build_git_integration_evidence(layout, source_revision(state['trusted_revision'], source_after), 'main', '0' * 40)
    check('missing-target-before-fails-closed', not missing['valid'] and 'integration_target_before_not_git_commit' in missing['blockers'])


# Git checkout normalization must not create false material drift. Commit-to-commit identity
# stays byte-exact, while live capture uses Git's provider-native diff semantics.
with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    git(root, 'config', 'core.autocrlf', 'true')
    target_before, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    git(root, 'merge', '--ff-only', 'feature')
    # Force a checkout through Git's configured text conversion on platforms where it applies.
    git(root, 'checkout', '--', 'product.txt')
    layout = discover_layout(root)
    revision = material_snapshot_for_git_revision(layout, source_after)
    check('arbitrary-git-revision-materialises', revision['valid'], str(revision))
    built = build_git_integration_evidence(
        layout, source_revision(state['trusted_revision'], source_after), 'main', target_before
    )
    verified = verify_integration_evidence(
        layout,
        implementation_record(source_revision(state['trusted_revision'], source_after), built['integration']),
        mode='transition',
    )
    check('git-autocrlf-checkout-does-not-create-false-material-drift', verified['valid'], str(verified))


# Provider-neutral direct snapshot integration remains supported without Git.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'snapshot-project'
    create_project(root, CORE, git_backed=False)
    layout = discover_layout(root)
    before = material_snapshot(layout)['revision']
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    after = material_snapshot(layout)['revision']
    source = {
        'system': 'specforge_snapshot',
        'before': before,
        'after': after,
        'material_effects': True,
        'verification_profile': PROFILE,
    }
    built = build_snapshot_integration_evidence(layout, source)
    check('snapshot-direct-integration-builds', built['valid'], str(built))
    verified = verify_integration_evidence(layout, implementation_record(source, built['integration']), mode='transition')
    check('snapshot-direct-integration-verifies', verified['valid'], str(verified))
    equal = dict(source)
    equal['before'] = after
    rejected = build_snapshot_integration_evidence(layout, equal)
    check('snapshot-material-effects-must-advance', not rejected['valid'] and 'source_revision_not_advanced' in rejected['blockers'])

# CHG-1027: static-only forensic correction overlay for historical wrong digest evidence.
def write_integration_correction(root, event_id, implementation_id, record, corrected_material, file_count, **overrides):
    source = record['source_revision']
    integration = record['integration']
    evidence = {
        'source_revision_after': source['after'],
        'integrated_revision': integration['integrated_revision'],
        'original': {
            'implementation_material': integration['implementation_material']['revision'],
            'integrated_material': integration['integrated_material']['revision'],
        },
        'corrected': {
            'material': corrected_material,
            'file_count': file_count,
        },
    }
    evidence.update(overrides)
    write_yaml(root / 'specforge/history/events' / f'{event_id}.yaml', {
        'id': event_id,
        'timestamp': '2026-09-18T14:11:06+01:00',
        'actor': {'type': 'automated_system', 'id': 'fixture'},
        'event_type': 'integration_evidence_correction',
        'entity': {'type': 'implementation', 'id': implementation_id},
        'evidence': evidence,
    })


with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    target_before, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    git(root, 'merge', '--no-ff', 'feature', '-m', 'merge governed historical fixture')
    layout = discover_layout(root)
    built = build_git_integration_evidence(
        layout,
        source_revision(state['trusted_revision'], source_after),
        'main',
        target_before,
    )
    check('correction-fixture-builds-valid-evidence', built['valid'], str(built))
    implementation = {
        'id': 'IMP-9901-01',
        'source_revision': source_revision(state['trusted_revision'], source_after),
        'integration': deepcopy(built['integration']),
    }
    actual_material = built['integration']['implementation_material']['revision']
    file_count = built['integration']['implementation_material']['file_count']
    wrong_material = 'sha256:' + ('1' * 64)
    implementation['integration']['implementation_material']['revision'] = wrong_material
    implementation['integration']['integrated_material']['revision'] = wrong_material

    rejected = verify_integration_evidence(layout, implementation, mode='static')
    check(
        'historical-wrong-digest-rejected-without-correction',
        not rejected['valid']
        and 'implementation_material_recomputation_mismatch' in rejected['blockers']
        and 'integrated_material_recomputation_mismatch' in rejected['blockers'],
        str(rejected),
    )

    write_integration_correction(
        root, 'EVT-990001', 'IMP-9901-01', implementation, actual_material, file_count
    )
    accepted = verify_integration_evidence(discover_layout(root), implementation, mode='static')
    check(
        'valid-static-correction-accepted',
        accepted['valid']
        and accepted['details']['forensic_integration_correction']['event'] == 'EVT-990001',
        str(accepted),
    )

    transition = verify_integration_evidence(discover_layout(root), implementation, mode='transition')
    check(
        'transition-mode-ignores-correction-overlay',
        not transition['valid']
        and 'implementation_material_recomputation_mismatch' in transition['blockers'],
        str(transition),
    )

    correction_path = root / 'specforge/history/events/EVT-990001.yaml'
    correction = __import__('yaml').safe_load(correction_path.read_text(encoding='utf-8'))
    correction['evidence']['corrected']['material'] = 'sha256:' + ('2' * 64)
    write_yaml(correction_path, correction)
    forged = verify_integration_evidence(discover_layout(root), implementation, mode='static')
    check(
        'forged-corrected-digest-rejected',
        not forged['valid'] and 'integration_evidence_correction_corrected_material_mismatch' in forged['blockers'],
        str(forged),
    )

    correction['evidence']['corrected']['material'] = actual_material
    correction['evidence']['corrected']['file_count'] = file_count + 1
    write_yaml(correction_path, correction)
    wrong_count = verify_integration_evidence(discover_layout(root), implementation, mode='static')
    check(
        'wrong-correction-file-count-rejected',
        not wrong_count['valid'] and 'integration_evidence_correction_file_count_mismatch' in wrong_count['blockers'],
        str(wrong_count),
    )

    correction['evidence']['corrected']['file_count'] = file_count
    correction['evidence']['source_revision_after'] = target_before
    write_yaml(correction_path, correction)
    wrong_source = verify_integration_evidence(discover_layout(root), implementation, mode='static')
    check(
        'wrong-correction-source-commit-rejected',
        not wrong_source['valid'] and 'integration_evidence_correction_source_revision_mismatch' in wrong_source['blockers'],
        str(wrong_source),
    )

    correction['evidence']['source_revision_after'] = source_after
    write_yaml(correction_path, correction)
    write_integration_correction(
        root, 'EVT-990002', 'IMP-9901-01', implementation, actual_material, file_count
    )
    ambiguous = verify_integration_evidence(discover_layout(root), implementation, mode='static')
    check(
        'ambiguous-corrections-fail-closed',
        not ambiguous['valid'] and 'integration_evidence_correction_ambiguous' in ambiguous['blockers'],
        str(ambiguous),
    )



# CHG-1029: a verified bridge exposes independently recomputed canonical material endpoints.
with tempfile.TemporaryDirectory() as td:
    root, state = init_git_case(td)
    target_before, source_after = implement_feature(root)
    git(root, 'checkout', 'main')
    git(root, 'merge', '--ff-only', 'feature')
    layout = discover_layout(root)
    built = build_git_integration_evidence(
        layout,
        source_revision(state['trusted_revision'], source_after),
        'main',
        target_before,
    )
    implementation = {
        'id': 'IMP-9929-01',
        'change': 'CHG-9929',
        'source_revision': source_revision(state['trusted_revision'], source_after),
        'integration': built['integration'],
    }
    bridge = verified_material_bridge(layout, implementation)
    start_snapshot = material_snapshot_for_git_revision(layout, state['trusted_revision'])['snapshot']['revision']
    end_snapshot = material_snapshot_for_git_revision(layout, source_after)['snapshot']['revision']
    check(
        'verified-material-bridge-recomputes-git-endpoints',
        bridge['valid']
        and bridge['start_material'] == start_snapshot
        and bridge['end_material'] == end_snapshot,
        str(bridge),
    )

    git(root, 'checkout', '-b', 'unrelated', target_before)
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'same material off accepted current lineage')
    off_line = git(root, 'rev-parse', 'HEAD').stdout.strip()
    git(root, 'checkout', 'main')
    forged = deepcopy(implementation)
    forged['integration']['integrated_revision'] = off_line
    off_snapshot = material_snapshot_for_git_revision(discover_layout(root), off_line)['snapshot']
    forged['integration']['integrated_material'] = {
        'provider': 'specforge_snapshot',
        'revision': off_snapshot['revision'],
        'file_count': off_snapshot['file_count'],
    }
    rejected = verified_material_bridge(discover_layout(root), forged)
    check(
        'verified-material-bridge-rejects-off-lineage-same-material',
        not rejected['valid'] and 'successor_integration_evidence_invalid' in rejected['blockers'],
        str(rejected),
    )

print('Integration evidence tests PASSED')


# CHG-1058: bounded historical integration verification.
import specforge_integration as integration_module

CHG1058_MATERIAL_ROOTS = [
    './product.txt',
    './model.txt',
    './README.md',
    './specforge/SPECFORGE.md',
    './specforge/project.yaml',
    './specforge/core',
]


def init_chg1058_git_case(td):
    root = Path(td) / 'repo'
    state = create_project(
        root,
        CORE,
        git_backed=True,
        material_roots=CHG1058_MATERIAL_ROOTS,
    )
    git(root, 'branch', '-M', 'main')
    return root, state


with tempfile.TemporaryDirectory() as td:
    root, state = init_chg1058_git_case(td)
    layout = discover_layout(root)
    commits = [git(root, 'rev-parse', 'HEAD').stdout.strip()]
    for index in range(12):
        (root / 'product.txt').write_text(f'history-{index}\n', encoding='utf-8', newline='\n')
        git(root, 'add', 'product.txt')
        git(root, 'commit', '-m', f'historical material {index}')
        commits.append(git(root, 'rev-parse', 'HEAD').stdout.strip())

    integration_module._HISTORICAL_SNAPSHOT_CACHE.clear()
    integration_module._HISTORICAL_BLOB_SHA256_CACHE.clear()
    for commit in commits:
        fast = integration_module.material_snapshot_for_git_revision(layout, commit)
        slow = integration_module._canonical_material_snapshot_for_git_revision(layout, commit)
        check(
            'chg1058-fast-snapshot-matches-canonical-' + commit[:8],
            fast['valid'] == slow['valid']
            and (fast.get('snapshot') or {}).get('revision') == (slow.get('snapshot') or {}).get('revision')
            and (fast.get('snapshot') or {}).get('file_count') == (slow.get('snapshot') or {}).get('file_count'),
            str({'fast': fast, 'slow': slow}),
        )


with tempfile.TemporaryDirectory() as td:
    root, state = init_chg1058_git_case(td)
    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()
    reviewed_text = 'reviewed-first-match\n'
    (root / 'product.txt').write_text(reviewed_text, encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'reviewed material first appears')
    first = git(root, 'rev-parse', 'HEAD').stdout.strip()
    first_material = integration_module.material_snapshot_for_git_revision(
        discover_layout(root), first
    )['snapshot']['revision']

    (root / 'product.txt').write_text('different-middle\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'reviewed material disappears')

    (root / 'product.txt').write_text(reviewed_text, encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'reviewed material reappears')
    later = git(root, 'rev-parse', 'HEAD').stdout.strip()

    discovery = integration_module.discover_integrated_revision(
        discover_layout(root), target_before, 'HEAD', first_material
    )
    check(
        'chg1058-first-material-appearance-remains-authoritative',
        discovery['valid'] and discovery['integrated_revision'] == first and first != later,
        str(discovery),
    )


with tempfile.TemporaryDirectory() as td:
    root, state = init_chg1058_git_case(td)
    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()
    for index in range(30):
        (root / 'product.txt').write_text(f'bounded-{index}\n', encoding='utf-8', newline='\n')
        git(root, 'add', 'product.txt')
        git(root, 'commit', '-m', f'bounded history {index}')
    target = git(root, 'rev-parse', 'HEAD').stdout.strip()
    target_material = integration_module.material_snapshot_for_git_revision(
        discover_layout(root), target
    )['snapshot']['revision']

    original_oracle = integration_module._canonical_material_snapshot_for_git_revision
    calls = {'count': 0}
    def counting_oracle(layout, commit):
        calls['count'] += 1
        return original_oracle(layout, commit)

    integration_module._HISTORICAL_SNAPSHOT_CACHE.clear()
    integration_module._HISTORICAL_BLOB_SHA256_CACHE.clear()
    integration_module._canonical_material_snapshot_for_git_revision = counting_oracle
    try:
        discovery = integration_module.discover_integrated_revision(
            discover_layout(root), target_before, 'HEAD', target_material
        )
    finally:
        integration_module._canonical_material_snapshot_for_git_revision = original_oracle
    check(
        'chg1058-long-history-discovers-target',
        discovery['valid'] and discovery['integrated_revision'] == target,
        str(discovery),
    )
    check(
        'chg1058-canonical-materialisations-bounded-not-per-commit',
        calls['count'] <= 2,
        f"canonical materialisations={calls['count']}",
    )


with tempfile.TemporaryDirectory() as left_td, tempfile.TemporaryDirectory() as right_td:
    left, _ = init_chg1058_git_case(left_td)
    right, _ = init_chg1058_git_case(right_td)
    left_id = integration_module._repository_identity(discover_layout(left))
    right_id = integration_module._repository_identity(discover_layout(right))
    check(
        'chg1058-cache-is-repository-bound',
        left_id and right_id and left_id != right_id,
        str({'left': left_id, 'right': right_id}),
    )
