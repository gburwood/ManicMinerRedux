#!/usr/bin/env python3
from pathlib import Path
import subprocess, sys, tempfile

CORE_ROOT = Path(__file__).resolve().parents[1]
TOOLS = CORE_ROOT / 'tools'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from specforge_project import discover_layout, git_worktree_root, material_snapshot, verify_source_revision
from portable_fixture import create_project, git, install_controlled_change

EXPLICIT_ROOTS = [
    'product.txt',
    'model.txt',
    'README.md',
    'specforge/project.yaml',
    'specforge/SPECFORGE.md',
    'specforge/core',
    'specforge/packs',
]


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print('PASS', name)


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE_ROOT, git_backed=True)
    before = state['trusted_revision']
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'material implementation')
    after = git(root, 'rev-parse', 'HEAD').stdout.strip()
    layout = discover_layout(root)
    result = verify_source_revision(layout, {'system': 'git', 'before': before, 'after': after}, mode='transition', require_provider=True)
    check('git-captured-material-valid', result['valid'])
    (root / 'specforge/history/EVT-test.yaml').write_text('id: EVT-999999\n', encoding='utf-8')
    result = verify_source_revision(layout, {'system': 'git', 'before': before, 'after': after}, mode='transition', require_provider=True)
    check('git-governance-bookkeeping-does-not-block', result['valid'])
    cache = root / 'specforge/core/tools/__pycache__/portable_fixture.cpython-314.pyc'
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b'fixture bytecode noise')
    result = verify_source_revision(layout, {'system': 'git', 'before': before, 'after': after}, mode='transition', require_provider=True)
    check('git-transient-noise-does-not-block', result['valid'] and not result['details'].get('material_differences'))
    (root / 'product.txt').write_text('three\n', encoding='utf-8', newline='\n')
    result = verify_source_revision(layout, {'system': 'git', 'before': before, 'after': after}, mode='transition', require_provider=True)
    check('git-uncaptured-material-blocked', not result['valid'] and 'uncaptured_material_changes' in result['blockers'] and 'product.txt' in result['details'].get('material_differences', []))
    result = verify_source_revision(layout, {'system': 'git', 'before': after, 'after': after}, mode='static', require_provider=False)
    check('git-same-revision-blocked', not result['valid'] and 'source_revision_not_advanced' in result['blockers'])
    result = verify_source_revision(layout, {'system': 'git', 'before': before, 'after': '0' * 40}, mode='static', require_provider=False)
    check('git-nonexistent-revision-blocked', not result['valid'] and 'source_revision_after_not_git_commit' in result['blockers'])


# CHG-1018: explicit_v1 checks the whole current boundary, including unchanged tracked unknown paths.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'explicit-repo'
    state = create_project(root, CORE_ROOT, git_backed=True, material_roots=EXPLICIT_ROOTS)
    before = state['trusted_revision']
    (root / 'unknown-module').mkdir()
    (root / 'unknown-module/file.txt').write_text('unknown\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'unknown-module/file.txt')
    git(root, 'commit', '-m', 'commit unknown explicit-boundary path')
    after = git(root, 'rev-parse', 'HEAD').stdout.strip()
    layout = discover_layout(root)
    result = verify_source_revision(
        layout,
        {'system': 'git', 'before': before, 'after': after, 'material_effects': True},
        mode='transition',
        require_provider=True,
    )
    check(
        'explicit-git-tracked-unknown-path-blocked-by-source-revision',
        not result['valid']
        and 'unclassified_project_paths_present' in result['blockers']
        and 'unknown-module' in result['details'].get('unclassified_paths', []),
    )


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE_ROOT, git_backed=True)
    git(root, 'branch', '-M', 'main')
    before = state['trusted_revision']
    git(root, 'checkout', '-b', 'feature')
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'reviewed source implementation')
    source_after = git(root, 'rev-parse', 'HEAD').stdout.strip()
    git(root, 'checkout', 'main')
    git(root, 'merge', '--squash', 'feature')
    git(root, 'commit', '-m', 'squash integration')
    layout = discover_layout(root)
    result = verify_source_revision(
        layout,
        {'system': 'git', 'before': before, 'after': source_after},
        mode='static',
        require_provider=False,
    )
    check(
        'v2-squash-still-rejected-by-after-head-lineage',
        not result['valid'] and 'source_revision_lineage_invalid:after_head' in result['blockers'],
    )


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    create_project(root, CORE_ROOT, git_backed=False)
    layout = discover_layout(root)
    before = material_snapshot(layout)['revision']
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    after = material_snapshot(layout)['revision']
    result = verify_source_revision(layout, {'system': 'specforge_snapshot', 'before': before, 'after': after}, mode='transition', require_provider=True)
    check('snapshot-captured-material-valid', result['valid'])
    (root / 'specforge/evidence/note.txt').write_text('bookkeeping\n', encoding='utf-8')
    check('snapshot-governance-does-not-change-digest', material_snapshot(layout)['revision'] == after)
    result = verify_source_revision(layout, {'system': 'specforge_snapshot', 'before': before, 'after': after}, mode='transition', require_provider=True)
    check('snapshot-governance-bookkeeping-does-not-block', result['valid'])
    (root / 'product.txt').write_text('three\n', encoding='utf-8', newline='\n')
    result = verify_source_revision(layout, {'system': 'specforge_snapshot', 'before': before, 'after': after}, mode='transition', require_provider=True)
    check('snapshot-uncaptured-material-blocked', not result['valid'] and 'uncaptured_material_changes' in result['blockers'])


with tempfile.TemporaryDirectory() as td:
    parent = Path(td) / 'parent'
    parent.mkdir()
    git(parent, 'init')
    project = parent / 'nested-project'
    create_project(project, CORE_ROOT, git_backed=False)
    layout = discover_layout(project)
    check('unrelated-parent-git-not-selected', git_worktree_root(layout) is None)
    check('nested-unmanaged-project-has-snapshot', material_snapshot(layout)['revision'].startswith('sha256:'))


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'repo'
    state = create_project(root, CORE_ROOT, git_backed=True)
    equal = state['trusted_revision']
    install_controlled_change(root, 'CHG-9008', status='completed', attempt=True, before=equal, after=equal, outcome='passed')
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'portable equal-revision false completion')
    validator = root / 'specforge/core/tools/validate-specforge.py'
    result = subprocess.run([sys.executable, '-B', str(validator), str(root)], capture_output=True, text=True)
    check('validator-rejects-equal-false-completion', result.returncode != 0)

print('Source revision tests PASSED')
