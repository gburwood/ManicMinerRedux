#!/usr/bin/env python3
from pathlib import Path
import json, subprocess, sys, tempfile

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_fixture import create_project, git, install_controlled_change, write_yaml

EXPLICIT_ROOTS = [
    'product.txt',
    'model.txt',
    'README.md',
    'specforge/project.yaml',
    'specforge/SPECFORGE.md',
    'specforge/core',
    'specforge/packs',
]


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)

def expect(cond, name, detail=''):
    if not cond:
        print('FAIL:', name); print(detail); raise SystemExit(1)
    print('PASS:', name)

with tempfile.TemporaryDirectory(prefix='specforge-auth-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True)
    trusted = state['trusted_revision']
    install_controlled_change(project, 'CHG-9001', status='approved', attempt=False)
    git(project, 'add', 'specforge/changes'); git(project, 'commit', '-m', 'portable governed fixture')
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')

    expect(guard_run().returncode == 0, 'clean-project-valid')
    readme = project / 'README.md'; original = readme.read_text(encoding='utf-8')
    readme.write_text(original + '\nunauthorized edit\n', encoding='utf-8')
    u = guard_run(); expect(u.returncode != 0, 'unauthorized-material-blocked', u.stdout); expect('README.md' in u.stdout, 'unauthorized-path-reported', u.stdout)
    git(project, 'add', 'README.md'); git(project, 'commit', '-m', 'unauthorized commit'); u = guard_run(); expect(u.returncode != 0, 'unauthorized-commit-remains-blocked', u.stdout)

    git(project, 'reset', '--hard', trusted)
    write_yaml(project / 'specforge/evidence/material-authority.yaml', {'version': 1, 'trusted': {'provider': 'git', 'revision': trusted}})
    install_controlled_change(project, 'CHG-9001', status='in_progress', attempt=True, before=trusted, outcome='in_progress')
    git(project, 'add', 'specforge/evidence/material-authority.yaml', 'specforge/changes'); git(project, 'commit', '-m', 'start authorized implementation')
    readme.write_text(original + '\nauthorized edit\n', encoding='utf-8')
    a = guard_run(); expect(a.returncode == 0, 'authorized-material-permitted', a.stdout); expect(json.loads(a.stdout).get('authorized') is True, 'active-authorization-reported', a.stdout)
    git(project, 'add', 'README.md'); git(project, 'commit', '-m', 'authorized material')
    acc = guard_run('accept'); expect(acc.returncode == 0, 'trusted-baseline-advances-after-clean-commit', acc.stdout)
    expect(guard_run().returncode == 0, 'accepted-state-valid')

# --- CHG-1017 revision 6: controlled_v2 active implementations ---

with tempfile.TemporaryDirectory(prefix='specforge-auth-v2-git-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True)
    trusted = state['trusted_revision']
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')

    install_controlled_change(project, 'CHG-9002', status='in_progress', attempt=True, before=trusted,
                               outcome='in_progress', lifecycle_enforcement='controlled_v2')
    git(project, 'add', 'specforge/changes'); git(project, 'commit', '-m', 'start git-backed controlled_v2 implementation')
    readme = project / 'README.md'; original = readme.read_text(encoding='utf-8')
    readme.write_text(original + '\ncontrolled_v2 authorized edit\n', encoding='utf-8')
    a = guard_run(); expect(a.returncode == 0, 'git-backed-controlled-v2-material-permitted', a.stdout)
    expect(json.loads(a.stdout).get('authorized') is True, 'git-backed-controlled-v2-authorization-reported', a.stdout)

with tempfile.TemporaryDirectory(prefix='specforge-auth-v2-snapshot-') as td:
    project = Path(td) / 'project'
    create_project(project, CORE, git_backed=False)
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')
    sys.path.insert(0, str(CORE / 'tools'))
    from specforge_project import discover_layout, material_snapshot
    layout = discover_layout(project)
    snapshot = material_snapshot(layout)
    write_yaml(project / 'specforge/evidence/material-authority.yaml', {'version': 1, 'trusted': {'provider': 'specforge_snapshot', 'revision': snapshot['revision']}})
    install_controlled_change(project, 'CHG-9003', status='in_progress', attempt=True, before=snapshot['revision'],
                               outcome='in_progress', lifecycle_enforcement='controlled_v2')
    imp_path = project / 'specforge/changes/CHG-9003/implementation/IMP-9003-01.yaml'
    import yaml as _yaml
    imp = _yaml.safe_load(imp_path.read_text(encoding='utf-8'))
    imp['source_revision']['system'] = 'specforge_snapshot'
    write_yaml(imp_path, imp)
    readme = project / 'README.md'; readme.write_text(readme.read_text(encoding='utf-8') + '\nunmanaged controlled_v2 authorized edit\n', encoding='utf-8')
    a = guard_run(); expect(a.returncode == 0, 'unmanaged-folder-controlled-v2-material-permitted', a.stdout)
    expect(json.loads(a.stdout).get('authorized') is True, 'unmanaged-folder-controlled-v2-authorization-reported', a.stdout)

with tempfile.TemporaryDirectory(prefix='specforge-auth-v3-git-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True)
    trusted = state['trusted_revision']
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')

    install_controlled_change(project, 'CHG-9010', status='in_progress', attempt=True, before=trusted,
                               outcome='in_progress', lifecycle_enforcement='controlled_v3')
    git(project, 'add', 'specforge/changes', 'specforge/evidence'); git(project, 'commit', '-m', 'start git-backed controlled_v3 implementation')
    readme = project / 'README.md'; original = readme.read_text(encoding='utf-8')
    readme.write_text(original + '\ncontrolled_v3 authorized edit\n', encoding='utf-8')
    a = guard_run(); expect(a.returncode == 0, 'git-backed-controlled-v3-material-permitted', a.stdout)
    expect(json.loads(a.stdout).get('authorized') is True, 'git-backed-controlled-v3-authorization-reported', a.stdout)

with tempfile.TemporaryDirectory(prefix='specforge-auth-ready-checkpoint-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True)
    trusted = state['trusted_revision']
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')

    install_controlled_change(project, 'CHG-9011', status='ready_for_checkpoint', attempt=True, before=trusted,
                               outcome='passed', lifecycle_enforcement='controlled_v3')
    git(project, 'add', 'specforge/changes', 'specforge/evidence'); git(project, 'commit', '-m', 'ready-for-checkpoint implementation')
    readme = project / 'README.md'; readme.write_text(readme.read_text(encoding='utf-8') + '\\nready candidate material\\n', encoding='utf-8')
    ready = guard_run()
    expect(ready.returncode == 0, 'ready-for-checkpoint-material-remains-authorized', ready.stdout)
    ready_data = json.loads(ready.stdout)
    expect(ready_data.get('authorized') is True, 'ready-for-checkpoint-authorization-reported', ready.stdout)
    active = ready_data.get('details', {}).get('active_implementations') or []
    expect(len(active) == 1 and active[0].get('change') == 'CHG-9011',
           'ready-for-checkpoint-authority-bound-to-current-change', ready.stdout)

    change_path = project / 'specforge/changes/CHG-9011.yaml'
    import yaml as _yaml_ready
    change = _yaml_ready.safe_load(change_path.read_text(encoding='utf-8'))
    change['status'] = 'completed'
    write_yaml(change_path, change)
    git(project, 'add', 'specforge/changes/CHG-9011.yaml'); git(project, 'commit', '-m', 'complete change without advancing authority')
    completed = guard_run()
    expect(completed.returncode != 0, 'completed-change-does-not-retain-implementation-authority', completed.stdout)
    expect('unauthorized_material_changes' in completed.stdout,
           'completed-change-requires-trusted-authority-advance', completed.stdout)

with tempfile.TemporaryDirectory(prefix='specforge-auth-v2-unsupported-profile-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True)
    trusted = state['trusted_revision']
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')

    install_controlled_change(project, 'CHG-9004', status='in_progress', attempt=True, before=trusted,
                               outcome='in_progress', lifecycle_enforcement='controlled_v3_unsupported')
    git(project, 'add', 'specforge/changes'); git(project, 'commit', '-m', 'start unsupported-profile implementation')
    readme = project / 'README.md'; readme.write_text(readme.read_text(encoding='utf-8') + '\nunsupported profile edit\n', encoding='utf-8')
    u = guard_run(); expect(u.returncode != 0, 'unsupported-lifecycle-profile-never-authorizes', u.stdout)

with tempfile.TemporaryDirectory(prefix='specforge-auth-v2-mismatched-binding-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True)
    trusted = state['trusted_revision']
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')

    install_controlled_change(project, 'CHG-9005', status='in_progress', attempt=True, before=trusted,
                               outcome='in_progress', lifecycle_enforcement='controlled_v2')
    # tamper with the approved proposal after its digest was bound, so exact_approval() no longer matches
    prop_path = project / 'specforge/changes/CHG-9005/PROP-9005-01.yaml'
    prop = prop_path.read_text(encoding='utf-8') + '\n# tampered after approval\n'
    prop_path.write_text(prop, encoding='utf-8')
    git(project, 'add', 'specforge/changes'); git(project, 'commit', '-m', 'start implementation with tampered proposal binding')
    readme = project / 'README.md'; readme.write_text(readme.read_text(encoding='utf-8') + '\nunauthorized edit despite v2 status\n', encoding='utf-8')
    u = guard_run(); expect(u.returncode != 0, 'controlled-v2-mismatched-proposal-binding-never-authorizes', u.stdout)
    expect('unauthorized_material_changes' in u.stdout, 'controlled-v2-unauthorized-material-fails-closed', u.stdout)

with tempfile.TemporaryDirectory(prefix='specforge-auth-v2-stale-baseline-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True)
    trusted = state['trusted_revision']
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')

    # implementation-attempt's source_revision.before deliberately does not match the trusted baseline
    install_controlled_change(project, 'CHG-9006', status='in_progress', attempt=True, before='0' * 40,
                               outcome='in_progress', lifecycle_enforcement='controlled_v2')
    git(project, 'add', 'specforge/changes'); git(project, 'commit', '-m', 'start implementation with stale trusted-baseline binding')
    readme = project / 'README.md'; readme.write_text(readme.read_text(encoding='utf-8') + '\nunauthorized edit, stale baseline\n', encoding='utf-8')
    u = guard_run(); expect(u.returncode != 0, 'controlled-v2-stale-trusted-baseline-never-authorizes', u.stdout)

# --- CHG-1018: an active implementation never authorizes an unclassified explicit-boundary path. ---
with tempfile.TemporaryDirectory(prefix='specforge-auth-explicit-boundary-') as td:
    project = Path(td) / 'project'
    state = create_project(project, CORE, git_backed=True, material_roots=EXPLICIT_ROOTS)
    trusted = state['trusted_revision']
    guard = project / 'specforge/core/tools/specforge-authorization.py'
    def guard_run(*extra): return run(sys.executable, '-B', str(guard), *extra, '--root', str(project), '--json')

    install_controlled_change(project, 'CHG-9007', status='in_progress', attempt=True, before=trusted,
                               outcome='in_progress', lifecycle_enforcement='controlled_v2')
    git(project, 'add', 'specforge/changes'); git(project, 'commit', '-m', 'start explicit-boundary implementation')
    unknown = project / 'new-engine'
    unknown.mkdir()
    (unknown / 'engine.txt').write_text('not declared\n', encoding='utf-8')
    u = guard_run()
    expect(u.returncode != 0, 'explicit-unclassified-path-blocks-active-implementation', u.stdout)
    expect('unclassified_project_paths_present' in u.stdout, 'explicit-unclassified-authorization-blocker-reported', u.stdout)
    expect('new-engine' in u.stdout, 'explicit-unclassified-authorization-path-reported', u.stdout)

print('Authorization regression tests PASSED')
