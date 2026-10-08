#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import json as _json
import subprocess
import sys
import tempfile

CORE = Path(__file__).resolve().parents[1]
TOOLS = CORE / 'tools'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

from portable_fixture import (
    create_project,
    git,
    install_controlled_change,
    write_yaml,
    write_governance_tier_activation,
    persist_snapshot_manifest,
    canonical_digest,
)
from specforge_project import (
    discover_layout,
    iter_record_files,
    load_yaml,
    material_snapshot,
    read_project_governance_tier_state,
)
from specforge_governance_tier import (
    TIER_ORDER,
    GovernanceTierError,
    actual_diff_entries,
    activate,
    initialize_fresh_project,
    classify_entries,
    completion_tier,
    load_policy,
    prepare,
    validate_declared_scope,
)
from specforge_integration import PROFILE, build_git_integration_evidence, verify_integration_evidence

POLICY_PATH = CORE / 'policy' / 'governance-tier-policy.yaml'

_lifecycle_spec = importlib.util.spec_from_file_location('specforge_lifecycle_gt', TOOLS / 'specforge-lifecycle.py')
lifecycle = importlib.util.module_from_spec(_lifecycle_spec)
_lifecycle_spec.loader.exec_module(lifecycle)


def check(name, condition, detail=''):
    if not condition:
        if detail:
            print(detail)
        raise AssertionError(name)
    print('PASS', name)


def records(layout):
    out = {}
    for path in iter_record_files(layout):
        try:
            data = load_yaml(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get('id'):
            out[str(data['id'])] = (data, path)
    return out


def run_lifecycle(root, *args):
    tool = TOOLS / 'specforge-lifecycle.py'
    return subprocess.run(
        [sys.executable, '-B', str(tool), *args, '--root', str(root), '--json'],
        capture_output=True, text=True,
    )


def run_validator(root):
    tool = TOOLS / 'validate-specforge.py'
    return subprocess.run([sys.executable, '-B', str(tool), str(root)], capture_output=True, text=True)


def result_json(result):
    return _json.loads(result.stdout)


def approve(root, chg_id, prop_id, apr_id):
    prop_path = root / 'specforge/changes' / chg_id / f'{prop_id}.yaml'
    digest = canonical_digest(prop_path)
    write_yaml(root / 'specforge/changes' / chg_id / 'approvals' / f'{apr_id}.yaml', {
        'id': apr_id, 'change': chg_id, 'proposal': prop_id, 'decision': 'approved',
        'actor': {'type': 'human', 'id': 'fixture-product-owner'},
        'timestamp': '2026-01-01T00:00:00+00:00',
        'evidence': {'proposal_digest_algorithm': 'sha256', 'proposal_digest': digest, 'proposal_identity': prop_id},
    })
    chg_path = root / 'specforge/changes' / f'{chg_id}.yaml'
    chg = yaml.safe_load(chg_path.read_text(encoding='utf-8'))
    approvals = chg.get('approvals') or []
    if apr_id not in approvals:
        approvals.append(apr_id)
    chg['approvals'] = approvals
    write_yaml(chg_path, chg)
    return digest


# ---------------------------------------------------------------------------
# Classifier/policy unit tests, including the overlap-resolution cases
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    layout = discover_layout(root)
    policy = load_policy(POLICY_PATH)

    result = classify_entries([{'path': 'specforge/core/tests/run-new-tests.py', 'status': 'M'}], policy, layout)
    check('core-test-harness-modify-classifies-medium', result['classification'] == 'MEDIUM', result)

    result = classify_entries([{'path': 'README.md', 'status': 'A'}], policy, layout)
    check('ordinary-doc-classifies-low', result['classification'] == 'LOW', result)

    result = classify_entries([{'path': 'specforge/core/docs/specforge-core-product-spec-9.9.9.md', 'status': 'A'}], policy, layout)
    check('spec-doc-under-docs-still-classifies-high-despite-broader-low-rule', result['classification'] == 'HIGH', result)
    check('spec-doc-matched-by-authoritative-rule-not-ordinary-doc', 'authoritative_product_specification' in result['matched_rules'], result)

    result = classify_entries([{'path': 'unexpected/new/path.bin', 'status': 'A'}], policy, layout)
    check('unmatched-path-defaults-high', result['classification'] == 'HIGH', result)

    try:
        load_policy(Path(td) / 'nonexistent.yaml')
        raise AssertionError('expected policy load failure')
    except GovernanceTierError:
        print('PASS policy-load-failure-raises')

    for bad_scope in (None, [], [{'operation': 'unknown', 'path': 'x'}], [{'operation': 'rename', 'from': 'a'}]):
        try:
            validate_declared_scope(bad_scope)
            raise AssertionError(f'expected failure for {bad_scope}')
        except GovernanceTierError:
            pass
    print('PASS declared-scope-malformed-fails-closed')

    entries = validate_declared_scope([
        {'operation': 'add', 'path': 'specforge/core/tests/run-new-tests.py'},
        {'operation': 'rename', 'from': 'a.py', 'to': 'b.py'},
    ])
    check('declared-scope-valid-entries-expand-correctly', len(entries) == 3, entries)


# ---------------------------------------------------------------------------
# Exact Batty Joe held-out reproduction (frozen policy embedded verbatim)
# ---------------------------------------------------------------------------
BATTY_JOE_POLICY_YAML = """
version: 2
non_authoritative: true
tiers:
  LOW: 1
  MEDIUM: 2
  HIGH: 3
defaults:
  unmatched_tier: HIGH
rules:
  - id: protected_governance_control
    tier: HIGH
    globs: [specforge/core/**, specforge/packs/**, specforge/project.yaml, specforge/SPECFORGE.md, SPECFORGE.md, specforge.yaml, rules/**, schemas/**, tools/**, workflows/**]
  - id: authoritative_product_specification
    tier: HIGH
    globs: [batty-joe-dev-spec-*.yaml]
  - id: product_runtime_source
    tier: HIGH
    globs: [batty-joe.js, batty-joe-game.js, batty-joe-physics.js, batty-joe-levels.js, batty-joe-config.js, batty-joe-audio.js, batty-joe-storage.js, batty-joe.html, batty-joe.css]
  - id: repository_and_ci_infrastructure
    tier: MEDIUM
    globs: [.gitignore, .gitattributes, .github/**, pyproject.toml, requirements*.txt, package.json, package-lock.json, Makefile, experiments/**]
  - id: existing_test_harness_change
    tier: MEDIUM
    statuses: [M, D, R, C, T, U, X, B]
    globs: [tests/**, batty-joe-tests.js, batty-joe-tests.html]
  - id: new_ordinary_test
    tier: LOW
    statuses: [A]
    globs: [tests/**, batty-joe-tests.js, batty-joe-tests.html]
  - id: ordinary_documentation
    tier: LOW
    globs: [docs/**, README, README.*, '**/*.md']
"""

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    layout = discover_layout(root)
    batty_joe_policy = yaml.safe_load(BATTY_JOE_POLICY_YAML)
    entries = [
        {'path': 'experiments/specforge-risk-classifier.py', 'status': 'M'},
        {'path': 'tests/run-risk-classifier-tests.py', 'status': 'M'},
    ]
    result = classify_entries(entries, batty_joe_policy, layout)
    check('batty-joe-held-out-range-reproduces-medium', result['classification'] == 'MEDIUM', result)
    check(
        'batty-joe-held-out-matched-rules-exact',
        set(result['matched_rules']) == {'repository_and_ci_infrastructure', 'existing_test_harness_change'},
        result,
    )


# ---------------------------------------------------------------------------
# Unknown lifecycle_enforcement cannot bypass approval (schema and code level)
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    install_controlled_change(root, 'CHG-9101', status='approved', attempt=False, lifecycle_enforcement='controlled_v4_unsupported')
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'unsupported profile fixture')

    out = lifecycle.decision(root, 'CHG-9101', 'approved')
    check(
        'unsupported-lifecycle-enforcement-code-level-refused',
        not out['permitted'] and any('unsupported_lifecycle_enforcement' in b for b in out['blockers']),
        out,
    )

    result = run_validator(root)
    check(
        'unsupported-lifecycle-enforcement-schema-level-refused',
        result.returncode != 0 and 'Schema validation failed' in result.stdout,
        result.stdout,
    )


# ---------------------------------------------------------------------------
# Namespace mapping: not-activated -> v1, active+known -> v2, active+unrecognized -> corrupted
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    layout = discover_layout(root)
    state = read_project_governance_tier_state(layout)
    check(
        'not-activated-maps-to-controlled-v1',
        state['status'] == 'not_activated' and state['effective_lifecycle_profile'] == 'controlled_v1',
        state,
    )

    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    state = read_project_governance_tier_state(layout)
    check(
        'active-known-profile-maps-to-controlled-v2',
        state['status'] == 'active' and state['effective_lifecycle_profile'] == 'controlled_v2',
        state,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[], enforcement_profile='unknown_future_profile')
    layout = discover_layout(root)
    state = read_project_governance_tier_state(layout)
    check('active-unrecognized-profile-is-corrupted', state['status'] == 'corrupted', state)


# ---------------------------------------------------------------------------
# Preparation: all pre-write refusals, event, two separate commits (git-backed)
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    layout = discover_layout(root)

    install_controlled_change(
        root, 'CHG-9201', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v1',
        declared_scope=[{'operation': 'add', 'path': 'specforge/core/docs/x.md'}],
    )
    result = prepare(layout, records(layout), 'PROP-9201-01')
    check(
        'prepare-refuses-when-not-declared-v2-or-v3',
        not result['prepared'] and 'change_not_declared_controlled_v2_or_v3' in result['blockers'], result,
    )

    install_controlled_change(
        root, 'CHG-9202', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'add', 'path': 'specforge/core/docs/x.md'}],
        governance_tier={'requested': 'LOW'},
    )
    result = prepare(layout, records(layout), 'PROP-9202-01')
    check(
        'prepare-refuses-when-project-not-active',
        not result['prepared'] and 'project_not_active_for_controlled_v2' in result['blockers'], result,
    )

    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    result = prepare(layout, records(layout), 'PROP-9202-01')
    check('prepare-succeeds-once-project-active', result['prepared'], result)
    check('prepare-writes-policy-digest', bool(result.get('policy_digest')), result)
    check('prepare-writes-forensic-event', (root / 'specforge/history/events' / f"{result['event']}.yaml").is_file(), result)

    install_controlled_change(
        root, 'CHG-9204', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v3',
        declared_scope=[{'operation': 'add', 'path': 'specforge/core/docs/v3.md'}],
        governance_tier={'requested': 'LOW'},
    )
    v3_result = prepare(layout, records(layout), 'PROP-9204-01')
    check('prepare-accepts-controlled-v3-successor-on-active-v2-project', v3_result['prepared'], v3_result)
    check('prepare-v3-writes-policy-digest', bool(v3_result.get('policy_digest')), v3_result)

    approve(root, 'CHG-9202', 'PROP-9202-01', 'APR-9202')
    result = prepare(layout, records(layout), 'PROP-9202-01')
    check(
        'prepare-refuses-once-currently-approved',
        not result['prepared'] and 'proposal_already_validly_approved' in result['blockers'], result,
    )

    prop_path = root / 'specforge/changes/CHG-9202/PROP-9202-01.yaml'
    prop_path.write_text(prop_path.read_text(encoding='utf-8') + '\n# tamper\n', encoding='utf-8')
    result = prepare(layout, records(layout), 'PROP-9202-01')
    check(
        'prepare-refuses-even-after-tamper-since-ever-approved',
        not result['prepared'] and 'proposal_previously_human_approved' in result['blockers'], result,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    install_controlled_change(
        root, 'CHG-9203', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'add', 'path': 'specforge/core/docs/x.md'}],
        governance_tier={'requested': 'LOW'},
    )
    git(root, 'add', 'specforge/changes', 'specforge/project.yaml', 'specforge/evidence')
    git(root, 'commit', '-m', 'draft controlled_v2 proposal')

    result = prepare(layout, records(layout), 'PROP-9203-01')
    check('prepare-succeeds-9203', result['prepared'], result)
    git(root, 'add', 'specforge/changes', 'specforge/evidence', 'specforge/history')
    git(root, 'commit', '-m', 'prepare PROP-9203-01')
    prepare_commit = git(root, 'rev-parse', 'HEAD').stdout.strip()

    approve(root, 'CHG-9203', 'PROP-9203-01', 'APR-9203')
    chg_path = root / 'specforge/changes/CHG-9203.yaml'
    chg = yaml.safe_load(chg_path.read_text(encoding='utf-8'))
    chg['status'] = 'approved'
    write_yaml(chg_path, chg)
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'Approve PROP-9203-01')
    approve_commit = git(root, 'rev-parse', 'HEAD').stdout.strip()
    check('prepare-and-approve-are-two-separate-commits', prepare_commit != approve_commit, (prepare_commit, approve_commit))

    r = run_lifecycle(root, 'transition', 'CHG-9203', '--to', 'approved')
    check('v2-fresh-approval-permitted-after-prepare-and-approve', r.returncode == 0, r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# Approval-time active-profile check for every declared profile; floor fires
# at approval, never at prepare
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[])
    install_controlled_change(root, 'CHG-9301', status='approved', attempt=False, lifecycle_enforcement='controlled_v1')
    r = run_lifecycle(root, 'transition', 'CHG-9301', '--to', 'approved')
    out = result_json(r)
    check(
        'v1-declaration-on-active-v2-project-ungrandfathered-refused',
        r.returncode != 0 and 'governance_tier_profile_mismatch' in out['blockers'], out,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    install_controlled_change(
        root, 'CHG-9302', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'modify', 'path': 'specforge/core/tools/x.py'}],
        governance_tier={'requested': 'LOW'},
    )
    prep = prepare(layout, records(layout), 'PROP-9302-01')
    check('prepare-does-not-enforce-floor', prep['prepared'], prep)
    approve(root, 'CHG-9302', 'PROP-9302-01', 'APR-9302')
    r = run_lifecycle(root, 'transition', 'CHG-9302', '--to', 'approved')
    out = result_json(r)
    check(
        'floor-violation-blocks-at-approval-not-prepare',
        r.returncode != 0 and 'governance_tier_floor_violation' in out['blockers'], out,
    )


# ---------------------------------------------------------------------------
# Stale-policy-after-approval and its recovery path
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    install_controlled_change(
        root, 'CHG-9401', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'add', 'path': 'specforge/core/docs/x.md'}],
        governance_tier={'requested': 'LOW'},
    )
    prep = prepare(layout, records(layout), 'PROP-9401-01')
    check('prepare-succeeds-9401', prep['prepared'], prep)
    original_digest = canonical_digest(root / 'specforge/changes/CHG-9401/PROP-9401-01.yaml')
    approve(root, 'CHG-9401', 'PROP-9401-01', 'APR-9401')

    policy_path = root / 'specforge/core/policy/governance-tier-policy.yaml'
    policy_data = yaml.safe_load(policy_path.read_text(encoding='utf-8'))
    policy_data['rules'].append({'id': 'fixture_drift_rule', 'tier': 'HIGH', 'globs': ['drift-marker/**']})
    write_yaml(policy_path, policy_data)

    r = run_lifecycle(root, 'transition', 'CHG-9401', '--to', 'approved')
    out = result_json(r)
    check('stale-policy-blocks-fresh-approval-after-drift', r.returncode != 0 and 'stale_policy_digest' in out['blockers'], out)

    result = prepare(layout, records(layout), 'PROP-9401-01')
    check(
        'prepare-still-refuses-ever-approved-even-under-stale-policy',
        not result['prepared']
        and ('proposal_previously_human_approved' in result['blockers'] or 'proposal_already_validly_approved' in result['blockers']),
        result,
    )

    write_yaml(root / 'specforge/changes/CHG-9401/PROP-9401-02.yaml', {
        'id': 'PROP-9401-02', 'change': 'CHG-9401', 'revision': 2, 'status': 'awaiting_approval',
        'previous_proposal': 'PROP-9401-01', 'based_on_impact_analysis': ['IA-9401-01'],
        'proposed_specification_version': '1.0.1', 'behaviour_summary': 'Recovery revision after stale-policy.',
        'requirement_changes': {'add': [], 'modify': [], 'deprecate': [], 'supersede': []},
        'acceptance_criteria': {'add': [{'id': 'AC-9401-02', 'text': 'Recovery.'}]}, 'approvals': [],
        'declared_scope': [{'operation': 'add', 'path': 'specforge/core/docs/x.md'}],
        'governance_tier': {'requested': 'LOW'},
    })
    chg_path = root / 'specforge/changes/CHG-9401.yaml'
    chg = yaml.safe_load(chg_path.read_text(encoding='utf-8'))
    chg['proposal'] = {'current': 'PROP-9401-02'}
    chg['approvals'] = []
    write_yaml(chg_path, chg)

    result = prepare(layout, records(layout), 'PROP-9401-02')
    check('new-revision-can-be-prepared-fresh', result['prepared'], result)
    approve(root, 'CHG-9401', 'PROP-9401-02', 'APR-9402')
    r = run_lifecycle(root, 'transition', 'CHG-9401', '--to', 'approved')
    check('new-revision-approval-succeeds', r.returncode == 0, r.stdout + r.stderr)
    check(
        'original-approved-proposal-never-mutated',
        canonical_digest(root / 'specforge/changes/CHG-9401/PROP-9401-01.yaml') == original_digest,
        'original proposal bytes changed',
    )


# ---------------------------------------------------------------------------
# Completion: dual-policy, escalation, downgrade-permitted, integrated endpoint
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    git(root, 'branch', '-M', 'main')
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    before = state['trusted_revision']

    install_controlled_change(
        root, 'CHG-9501', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'modify', 'path': 'product.txt'}], governance_tier={'requested': 'HIGH'},
    )
    prep = prepare(layout, records(layout), 'PROP-9501-01')
    check('completion-fixture-prepared', prep['prepared'], prep)
    approve(root, 'CHG-9501', 'PROP-9501-01', 'APR-9501')
    chg_path = root / 'specforge/changes/CHG-9501.yaml'
    chg = yaml.safe_load(chg_path.read_text(encoding='utf-8'))
    chg['status'] = 'approved'
    write_yaml(chg_path, chg)
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'approve CHG-9501')

    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()
    git(root, 'checkout', '-b', 'feature-9501')
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'feature implementation')
    source_after = git(root, 'rev-parse', 'HEAD').stdout.strip()
    git(root, 'checkout', 'main')
    git(root, 'merge', '--no-ff', 'feature-9501', '-m', 'merge governed implementation')
    merge_commit = git(root, 'rev-parse', 'HEAD').stdout.strip()
    check('integrated-revision-differs-from-source-after', merge_commit != source_after, (merge_commit, source_after))

    layout = discover_layout(root)
    built = build_git_integration_evidence(
        layout, {'system': 'git', 'before': before, 'after': source_after, 'material_effects': True, 'verification_profile': PROFILE},
        'main', target_before,
    )
    check('completion-integration-evidence-builds', built['valid'], built)
    check('completion-integrated-revision-is-merge-commit', built['integration']['integrated_revision'] == merge_commit, built)

    implementation = {
        'proposal': 'PROP-9501-01',
        'source_revision': {'before': before, 'after': source_after},
        'integration': built['integration'],
    }
    tier_result = completion_tier(layout, records(layout), implementation)
    check('completion-tier-classifies-against-integrated-endpoint', tier_result['valid'], tier_result)
    check('completion-tier-no-escalation-when-at-governed-tier', not tier_result['blockers'], tier_result)

    install_controlled_change(
        root, 'CHG-9502', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'add', 'path': 'specforge/core/docs/y.md'}], governance_tier={'requested': 'LOW'},
    )
    prep2 = prepare(layout, records(layout), 'PROP-9502-01')
    check('escalation-fixture-prepared', prep2['prepared'], prep2)
    implementation2 = {
        'proposal': 'PROP-9502-01',
        'source_revision': {'before': before, 'after': source_after},
        'integration': built['integration'],
    }
    tier_result2 = completion_tier(layout, records(layout), implementation2)
    check(
        'completion-tier-escalation-detected',
        tier_result2['valid'] and 'governance_tier_escalation' in tier_result2['blockers'], tier_result2,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    git(root, 'branch', '-M', 'main')
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    before = state['trusted_revision']

    install_controlled_change(
        root, 'CHG-9503', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'modify', 'path': 'product.txt'}], governance_tier={'requested': 'HIGH'},
    )
    prep = prepare(layout, records(layout), 'PROP-9503-01')
    check('dual-policy-fixture-prepared', prep['prepared'], prep)

    policy_path = root / 'specforge/core/policy/governance-tier-policy.yaml'
    policy_data = yaml.safe_load(policy_path.read_text(encoding='utf-8'))
    policy_data['defaults']['unmatched_tier'] = 'LOW'
    write_yaml(policy_path, policy_data)

    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'implementation under weakened current policy')
    after = git(root, 'rev-parse', 'HEAD').stdout.strip()

    implementation = {
        'proposal': 'PROP-9503-01',
        'source_revision': {'before': before, 'after': after},
        'integration': {'provider': 'git', 'integrated_revision': after},
    }
    tier_result = completion_tier(layout, records(layout), implementation)
    check(
        'dual-policy-archived-policy-still-governs-despite-weaker-current',
        tier_result['valid'] and tier_result['archived_tier'] == 'HIGH', tier_result,
    )
    check('dual-policy-effective-actual-is-higher-of-two', tier_result['effective_actual'] == 'HIGH', tier_result)


# ---------------------------------------------------------------------------
# Snapshot-provider completion, via the real specforge-revision.py capture() path
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=False)
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)

    revision_tool = TOOLS / 'specforge-revision.py'
    r = subprocess.run([sys.executable, '-B', str(revision_tool), 'capture', '--root', str(root), '--json'], capture_output=True, text=True)
    check('snapshot-capture-succeeds', r.returncode == 0, r.stdout + r.stderr)
    before_revision = _json.loads(r.stdout)['revision']

    install_controlled_change(
        root, 'CHG-9504', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'modify', 'path': 'product.txt'}], governance_tier={'requested': 'HIGH'},
    )
    prep = prepare(layout, records(layout), 'PROP-9504-01')
    check('snapshot-completion-fixture-prepared', prep['prepared'], prep)

    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    r2 = subprocess.run([sys.executable, '-B', str(revision_tool), 'capture', '--root', str(root), '--json'], capture_output=True, text=True)
    check('snapshot-after-capture-succeeds', r2.returncode == 0, r2.stdout + r2.stderr)
    after_revision = _json.loads(r2.stdout)['revision']

    implementation = {
        'proposal': 'PROP-9504-01',
        'source_revision': {'before': before_revision, 'after': after_revision},
        'integration': {'provider': 'specforge_snapshot', 'integrated_revision': after_revision},
    }
    tier_result = completion_tier(layout, records(layout), implementation)
    check('snapshot-completion-tier-via-real-capture-path', tier_result['valid'], tier_result)

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=False)
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    before_revision = material_snapshot(layout)['revision']
    install_controlled_change(
        root, 'CHG-9505', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'modify', 'path': 'product.txt'}], governance_tier={'requested': 'HIGH'},
    )
    prepare(layout, records(layout), 'PROP-9505-01')
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    after_revision = material_snapshot(layout)['revision']
    implementation = {
        'proposal': 'PROP-9505-01',
        'source_revision': {'before': before_revision, 'after': after_revision},
        'integration': {'provider': 'specforge_snapshot', 'integrated_revision': after_revision},
    }
    tier_result = completion_tier(layout, records(layout), implementation)
    check(
        'snapshot-completion-fails-closed-without-manifest',
        not tier_result['valid'] and 'snapshot_before_manifest_missing' in tier_result['blockers'], tier_result,
    )


# ---------------------------------------------------------------------------
# Rename/copy fail-upward: byte-identical and modified (edited) cases
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=False)
    layout = discover_layout(root)

    rename_policy = {
        'tiers': {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}, 'defaults': {'unmatched_tier': 'LOW'},
        'rules': [
            {'id': 'rename_high', 'tier': 'HIGH', 'statuses': ['R'], 'globs': ['**']},
            {'id': 'delete_low', 'tier': 'LOW', 'statuses': ['D'], 'globs': ['**']},
            {'id': 'add_low', 'tier': 'LOW', 'statuses': ['A'], 'globs': ['**']},
        ],
    }
    before_digest = persist_snapshot_manifest(root, [{'path': 'old.txt', 'sha256': 'a' * 64}])
    after_digest = persist_snapshot_manifest(root, [{'path': 'new.txt', 'sha256': 'b' * 64}])
    entries = actual_diff_entries(layout, 'specforge_snapshot', 'sha256:' + before_digest, 'sha256:' + after_digest)
    result = classify_entries(entries, rename_policy, layout)
    check('snapshot-modified-rename-fails-upward-to-high', result['classification'] == 'HIGH', (entries, result))

    copy_policy = {
        'tiers': {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}, 'defaults': {'unmatched_tier': 'LOW'},
        'rules': [
            {'id': 'copy_high', 'tier': 'HIGH', 'statuses': ['C'], 'globs': ['**']},
            {'id': 'add_low', 'tier': 'LOW', 'statuses': ['A'], 'globs': ['**']},
        ],
    }
    bd2 = persist_snapshot_manifest(root, [{'path': 'a.txt', 'sha256': 'c' * 64}])
    ad2 = persist_snapshot_manifest(
        root, [{'path': 'a.txt', 'sha256': 'c' * 64}, {'path': 'b.txt', 'sha256': 'd' * 64}],
    )
    entries2 = actual_diff_entries(layout, 'specforge_snapshot', 'sha256:' + bd2, 'sha256:' + ad2)
    result2 = classify_entries(entries2, copy_policy, layout)
    check(
        'snapshot-modified-copy-source-persists-no-deletion-fails-upward-to-high',
        result2['classification'] == 'HIGH', (entries2, result2),
    )

    bd3 = persist_snapshot_manifest(root, [])
    ad3 = persist_snapshot_manifest(root, [{'path': 'new.txt', 'sha256': 'e' * 64}])
    entries3 = actual_diff_entries(layout, 'specforge_snapshot', 'sha256:' + bd3, 'sha256:' + ad3)
    check('pure-addition-has-no-rename-candidate', not any(e['status'] == 'R' for e in entries3), entries3)
    check('pure-addition-has-copy-candidate-accepted-tradeoff', any(e['status'] == 'C' for e in entries3), entries3)


# ---------------------------------------------------------------------------
# Grandfather/anchor: mutation detection, asymmetric corruption, validator flagging
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    evidence_path = root / 'specforge/evidence/governance-tier-grandfather.yaml'
    data = yaml.safe_load(evidence_path.read_text(encoding='utf-8'))
    data['proposal_digests'] = ['f' * 64]
    write_yaml(evidence_path, data)
    state = read_project_governance_tier_state(layout)
    check('mutated-grandfather-file-detected-as-corrupted', state['status'] == 'corrupted', state)

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    manifest_path = root / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['governance_tier'] = {'enforcement_profile': 'deterministic_tier_v1'}
    write_yaml(manifest_path, manifest)
    layout = discover_layout(root)
    state = read_project_governance_tier_state(layout)
    check('profile-present-without-anchor-is-corrupted', state['status'] == 'corrupted', state)

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    manifest_path = root / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['governance_tier'] = {'grandfather_digest': 'a' * 64}
    write_yaml(manifest_path, manifest)
    layout = discover_layout(root)
    state = read_project_governance_tier_state(layout)
    check('anchor-present-without-profile-is-corrupted', state['status'] == 'corrupted', state)

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[])
    install_controlled_change(
        root, 'CHG-9601', status='completed', attempt=True, lifecycle_enforcement='controlled_v1',
        before='0' * 40, after='1' * 40, outcome='passed',
    )
    result = run_validator(root)
    check(
        'direct-edit-completed-v1-on-active-v2-project-ungrandfathered-flagged',
        result.returncode != 0 and 'Governance-tier profile mismatch' in result.stdout, result.stdout,
    )


# ---------------------------------------------------------------------------
# Validator floor-contract reconstruction (validator parity for direct edits)
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[])
    install_controlled_change(
        root, 'CHG-9602', status='approved', attempt=False, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'add', 'path': 'specforge/core/docs/z.md'}], governance_tier={'requested': 'LOW'},
    )
    result = run_validator(root)
    check(
        'validator-rejects-approved-v2-change-missing-policy-digest',
        result.returncode != 0 and 'policy_digest missing' in result.stdout, result.stdout,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    install_controlled_change(
        root, 'CHG-9603', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'modify', 'path': 'specforge/core/tools/x.py'}], governance_tier={'requested': 'LOW'},
    )
    prep = prepare(layout, records(layout), 'PROP-9603-01')
    check('validator-floor-fixture-prepared', prep['prepared'], prep)
    approve(root, 'CHG-9603', 'PROP-9603-01', 'APR-9603')
    chg_path = root / 'specforge/changes/CHG-9603.yaml'
    chg = yaml.safe_load(chg_path.read_text(encoding='utf-8'))
    chg['status'] = 'approved'
    write_yaml(chg_path, chg)
    result = run_validator(root)
    check(
        'validator-rejects-requested-tier-below-archived-floor',
        result.returncode != 0 and 'below the' in result.stdout and 'floor' in result.stdout, result.stdout,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)

    # An authorizing in-progress v1 implementation, grandfathered at activation, covering the
    # uncommitted material diff this fixture will produce (project.yaml, the drifted policy
    # file) under the pre-existing (CHG-1009-era) material-authorization mechanism, which this
    # fixture's diff would otherwise trip independent of anything governance-tier-specific.
    install_controlled_change(root, 'CHG-9699', status='in_progress', attempt=True, before=state['trusted_revision'], outcome='in_progress')
    authorizing_digest = canonical_digest(root / 'specforge/changes/CHG-9699/PROP-9699-01.yaml')
    write_governance_tier_activation(root, proposal_digests=[authorizing_digest])
    layout = discover_layout(root)
    install_controlled_change(
        root, 'CHG-9604', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'add', 'path': 'specforge/core/docs/z2.md'}], governance_tier={'requested': 'LOW'},
    )
    prep = prepare(layout, records(layout), 'PROP-9604-01')
    check('staleness-companion-fixture-prepared', prep['prepared'], prep)
    approve(root, 'CHG-9604', 'PROP-9604-01', 'APR-9604')
    chg_path = root / 'specforge/changes/CHG-9604.yaml'
    chg = yaml.safe_load(chg_path.read_text(encoding='utf-8'))
    chg['status'] = 'approved'
    write_yaml(chg_path, chg)

    policy_path = root / 'specforge/core/policy/governance-tier-policy.yaml'
    policy_data = yaml.safe_load(policy_path.read_text(encoding='utf-8'))
    policy_data['rules'].append({'id': 'fixture_drift_rule_2', 'tier': 'HIGH', 'globs': ['some-other-path/**']})
    write_yaml(policy_path, policy_data)

    result = run_validator(root)
    check('validator-does-not-re-check-staleness-statically', result.returncode == 0, result.stdout)


# ---------------------------------------------------------------------------
# CHG-1035 fresh-project initialization: pre-history, pre-baseline, integrity-anchored
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'fresh'
    create_project(root, CORE, git_backed=False)
    layout = discover_layout(root)
    initialized = initialize_fresh_project(layout, records(layout))
    check('fresh-initialization-succeeds-before-baseline', initialized['initialized'], initialized)
    layout = discover_layout(root)
    state = read_project_governance_tier_state(layout)
    check('fresh-initialization-is-active', state['status'] == 'active', state)
    check('fresh-initialization-provenance-recorded', state.get('activation_provenance') == 'fresh_project_bootstrap_v1', state)
    evidence = yaml.safe_load((root / 'specforge/evidence/governance-tier-grandfather.yaml').read_text(encoding='utf-8'))
    check('fresh-initialization-grandfather-set-empty', evidence['proposal_digests'] == [], evidence)
    repeated = initialize_fresh_project(layout, records(layout))
    check('fresh-initialization-refuses-active-project', not repeated['initialized'] and 'project_already_active' in repeated['blockers'], repeated)

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'partial'
    create_project(root, CORE, git_backed=False)
    manifest_path = root / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['governance_tier'] = {'enforcement_profile': 'deterministic_tier_v1'}
    write_yaml(manifest_path, manifest)
    layout = discover_layout(root)
    result = initialize_fresh_project(layout, records(layout))
    check('fresh-initialization-refuses-partial-state', not result['initialized'] and 'governance_tier_activation_state_corrupted' in result['blockers'], result)

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'history'
    create_project(root, CORE, git_backed=False)
    install_controlled_change(root, 'CHG-9750', status='awaiting_approval', skip_approval=True)
    layout = discover_layout(root)
    result = initialize_fresh_project(layout, records(layout))
    check('fresh-initialization-refuses-governed-history', not result['initialized'] and 'fresh_project_governed_history_exists' in result['blockers'], result)

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'baseline'
    create_project(root, CORE, git_backed=True)
    layout = discover_layout(root)
    result = initialize_fresh_project(layout, records(layout))
    check('fresh-initialization-refuses-existing-trusted-baseline', not result['initialized'] and 'fresh_project_trusted_material_baseline_exists' in result['blockers'], result)


# ---------------------------------------------------------------------------
# Activation: authorization checked before idempotency, all failure modes,
# byte-for-byte-unchanged on failure, idempotency, unmanaged-folder, and
# exclusion of a forged v2-declaring change from the grandfather set
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    layout = discover_layout(root)

    result = activate(layout, records(layout), 'CHG-9701')
    check('activate-refuses-missing-authorizing-change', not result['activated'] and 'authorizing_change_missing' in result['blockers'], result)

    install_controlled_change(
        root, 'CHG-9702', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v1',
        artifacts_expected={'modify': ['specforge/project.yaml'], 'evidence_roots': ['specforge/evidence/governance-tier-grandfather.yaml']},
    )
    before_manifest_bytes = (root / 'specforge/project.yaml').read_bytes()
    result = activate(layout, records(layout), 'CHG-9702')
    check('activate-refuses-no-valid-approval', not result['activated'] and 'authorizing_change_not_validly_approved' in result['blockers'], result)
    check('activate-no-writes-on-authorization-failure', (root / 'specforge/project.yaml').read_bytes() == before_manifest_bytes, 'project.yaml mutated')
    check(
        'activate-no-grandfather-file-on-authorization-failure',
        not (root / 'specforge/evidence/governance-tier-grandfather.yaml').is_file(), 'evidence file created',
    )

    install_controlled_change(
        root, 'CHG-9703', status='approved', attempt=False, lifecycle_enforcement='controlled_v1',
        artifacts_expected={'modify': ['specforge/project.yaml']},
    )
    result = activate(layout, records(layout), 'CHG-9703')
    check('activate-refuses-insufficient-scope', not result['activated'] and 'authorizing_proposal_scope_insufficient' in result['blockers'], result)

    install_controlled_change(
        root, 'CHG-9708', status='approved', attempt=False, lifecycle_enforcement='controlled_v2',
        declared_scope=[{'operation': 'add', 'path': 'x.md'}], governance_tier={'requested': 'LOW'},
    )
    forged_digest = canonical_digest(root / 'specforge/changes/CHG-9708/PROP-9708-01.yaml')

    install_controlled_change(
        root, 'CHG-9704', status='approved', attempt=False, lifecycle_enforcement='controlled_v1',
        artifacts_expected={'modify': ['specforge/project.yaml'], 'evidence_roots': ['specforge/evidence/governance-tier-grandfather.yaml']},
    )
    authorizing_digest = canonical_digest(root / 'specforge/changes/CHG-9704/PROP-9704-01.yaml')
    result = activate(layout, records(layout), 'CHG-9704')
    check('activate-succeeds-with-sufficient-authorization', result['activated'], result)

    evidence = yaml.safe_load((root / 'specforge/evidence/governance-tier-grandfather.yaml').read_text(encoding='utf-8'))
    check('activation-excludes-forged-v2-declaring-change', forged_digest not in evidence['proposal_digests'], evidence)
    check('activation-includes-legitimate-v1-authorizing-change', authorizing_digest in evidence['proposal_digests'], evidence)

    layout2 = discover_layout(root)
    # declares controlled_v2, since the project is now active and that is the only profile an
    # otherwise-fully-authorizing change could declare at this point -- isolating idempotency
    # from the (already separately tested) profile-match half of authorization.
    install_controlled_change(
        root, 'CHG-9705', status='approved', attempt=False, lifecycle_enforcement='controlled_v2',
        artifacts_expected={'modify': ['specforge/project.yaml'], 'evidence_roots': ['specforge/evidence/governance-tier-grandfather.yaml']},
    )
    result = activate(layout2, records(layout2), 'CHG-9705')
    check('activate-refuses-when-already-active', not result['activated'] and result['blockers'] == ['project_already_active'], result)

    install_controlled_change(root, 'CHG-9707', status='awaiting_approval', skip_approval=True, lifecycle_enforcement='controlled_v1')
    result = activate(layout2, records(layout2), 'CHG-9707')
    check(
        'activate-reports-authorization-failure-before-idempotency-on-active-project',
        not result['activated']
        and 'authorizing_change_not_validly_approved' in result['blockers']
        and 'project_already_active' not in result['blockers'],
        result,
    )

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=False)
    layout = discover_layout(root)
    install_controlled_change(
        root, 'CHG-9706', status='approved', attempt=False, lifecycle_enforcement='controlled_v1',
        artifacts_expected={'modify': ['specforge/project.yaml'], 'evidence_roots': ['specforge/evidence/governance-tier-grandfather.yaml']},
    )
    result = activate(layout, records(layout), 'CHG-9706')
    check('activate-succeeds-on-unmanaged-folder-project', result['activated'], result)


# ---------------------------------------------------------------------------
# Material sequencing: pre/post-integration activation
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    git(root, 'branch', '-M', 'main')
    before = state['trusted_revision']

    install_controlled_change(root, 'CHG-9801', status='in_progress', attempt=True, before=before, outcome='in_progress', verification_profile=PROFILE)
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start governed implementation')
    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()

    write_governance_tier_activation(root, proposal_digests=[])
    git(root, 'add', 'specforge/project.yaml', 'specforge/evidence')
    git(root, 'commit', '-m', 'activate governance-tier v2 as part of implementation')
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'material implementation')
    after = git(root, 'rev-parse', 'HEAD').stdout.strip()

    layout = discover_layout(root)
    built = build_git_integration_evidence(
        layout, {'system': 'git', 'before': before, 'after': after, 'material_effects': True, 'verification_profile': PROFILE},
        'main', target_before,
    )
    check('pre-integration-activation-captured-in-implementation-material', built['valid'], built)

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE, git_backed=True)
    git(root, 'branch', '-M', 'main')
    before = state['trusted_revision']

    install_controlled_change(root, 'CHG-9802', status='in_progress', attempt=True, before=before, outcome='in_progress', verification_profile=PROFILE)
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start governed implementation 2')
    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'material implementation 2')
    after = git(root, 'rev-parse', 'HEAD').stdout.strip()

    layout = discover_layout(root)
    built = build_git_integration_evidence(
        layout, {'system': 'git', 'before': before, 'after': after, 'material_effects': True, 'verification_profile': PROFILE},
        'main', target_before,
    )
    check('post-freeze-integration-evidence-built', built['valid'], built)

    write_governance_tier_activation(root, proposal_digests=[])
    layout = discover_layout(root)
    implementation_record = {
        'source_revision': {'before': before, 'after': after, 'material_effects': True},
        'integration': built['integration'],
    }
    verified = verify_integration_evidence(layout, implementation_record, mode='transition')
    check(
        'post-integration-activation-detected-as-uncaptured-material-drift',
        not verified['valid'] and 'uncaptured_material_changes' in verified['blockers'], verified,
    )


# ---------------------------------------------------------------------------
# No change identifier, project name, or narrative judgement hard-coded in
# classification logic or policy
# ---------------------------------------------------------------------------
policy_text = POLICY_PATH.read_text(encoding='utf-8')
check(
    'policy-has-no-hardcoded-change-identifiers',
    not any(tok in policy_text for tok in ('CHG-1016', 'CHG-0012', 'Batty Joe', 'batty-joe')), policy_text,
)
import inspect
evaluation_logic_source = ''.join(inspect.getsource(fn) for fn in (classify_entries, load_policy, actual_diff_entries))
check(
    'classifier-evaluation-logic-has-no-hardcoded-change-identifiers',
    'CHG-1016' not in evaluation_logic_source and 'CHG-0012' not in evaluation_logic_source,
    evaluation_logic_source,
)

print('Governance-tier tests PASSED')

# CHG-1044 host-project semantics: authoritative spec stays HIGH, declared ordinary material can be LOW,
# and protected surfaces cannot be declassified even by a broad host ordinary rule.
with tempfile.TemporaryDirectory(prefix='specforge-host-tier-') as td:
    root=Path(td)/'repo'
    create_project(root,CORE,git_backed=True)
    manifest_path=root/'specforge/project.yaml'
    manifest=yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest.setdefault('specification',{})['product_specification']='./HOST-SPEC.md'
    manifest.setdefault('governance_tier',{})['host_classification']={
        'ordinary_globs':['src/**'], 'ordinary_tier':'LOW', 'authoritative_globs':['contracts/**']
    }
    write_yaml(manifest_path,manifest)
    (root/'HOST-SPEC.md').write_text('# host spec\n',encoding='utf-8')
    (root/'src').mkdir(); (root/'src/app.weird').write_text('x',encoding='utf-8')
    layout=discover_layout(root); policy=load_policy(POLICY_PATH)
    spec_result=classify_entries([{'path':'HOST-SPEC.md','status':'M'}],policy,layout)
    app_result=classify_entries([{'path':'src/app.weird','status':'M'}],policy,layout)
    protected_result=classify_entries([{'path':'specforge/core/tools/specforge-status.py','status':'M'}],policy,layout)
    check('host-authoritative-markdown-is-high',spec_result['classification']=='HIGH',spec_result)
    check('host-explicit-ordinary-material-is-low',app_result['classification']=='LOW',app_result)
    check('protected-core-cannot-be-declassified',protected_result['classification']=='HIGH',protected_result)
