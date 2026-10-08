#!/usr/bin/env python3
from pathlib import Path
import hashlib, importlib.util, json, os, shutil, subprocess, sys, tempfile, yaml

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_fixture import create_project, git, install_controlled_change, write_yaml

CORE_META = yaml.safe_load((CORE / 'core.yaml').read_text(encoding='utf-8'))
TARGET_CORE_VERSION = CORE_META['core_version']
TARGET_DATA_MODEL_VERSION = CORE_META['data_model_version']
assert TARGET_CORE_VERSION == '0.1.0-beta.1'
assert TARGET_DATA_MODEL_VERSION == '0.1.0-alpha.10'
assert (CORE_META.get('managed_progress') or {}).get('profile') == 'managed_progress_v1'
assert (CORE_META.get('integrity') or {}).get('routine_profile') == 'incremental_integrity_v1'


def run(tool, args, cwd=None):
    env = os.environ.copy(); env['PYTHONDONTWRITEBYTECODE'] = '1'
    return subprocess.run([sys.executable, '-B', str(tool), *args], cwd=cwd, capture_output=True, text=True, env=env)

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def tree_digest(root):
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith(('.pyc', '.pyo'))):
        h.update(path.relative_to(root).as_posix().encode('utf-8')); h.update(b'\0'); h.update(path.read_bytes()); h.update(b'\0')
    return h.hexdigest()

def load_upgrade_module():
    tools = CORE / 'tools'
    sys.path.insert(0, str(tools))
    spec = importlib.util.spec_from_file_location('specforge_upgrade_under_test', tools / 'specforge-upgrade.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def recording_tempdirs(module):
    real = module.tempfile.TemporaryDirectory
    created = []
    class RecordingTemporaryDirectory:
        def __init__(self, *args, **kwargs): self.inner = real(*args, **kwargs)
        def __enter__(self):
            path = self.inner.__enter__(); created.append(Path(path).resolve()); return path
        def __exit__(self, *args): return self.inner.__exit__(*args)
    module.tempfile.TemporaryDirectory = RecordingTemporaryDirectory
    return created

def assert_external(paths, project):
    project = project.resolve()
    for path in paths:
        try: path.relative_to(project)
        except ValueError: continue
        raise AssertionError(f'rollback scratch created inside project: {path}')

def stage_distribution(project, version, formats):
    core = project / 'specforge-dist' / version / 'core'
    shutil.copytree(CORE, core, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    meta = yaml.safe_load((core / 'core.yaml').read_text(encoding='utf-8')); meta['core_version'] = version; meta.setdefault('compatibility', {})['project_formats'] = formats
    (core / 'core.yaml').write_text(yaml.safe_dump(meta, sort_keys=False), encoding='utf-8')
    pkg = yaml.safe_load((core / 'package.yaml').read_text(encoding='utf-8')); pkg['package']['version'] = version; pkg['compatibility']['project_formats'] = formats
    (core / 'package.yaml').write_text(yaml.safe_dump(pkg, sort_keys=False), encoding='utf-8')
    return core

with tempfile.TemporaryDirectory() as td:
    fixture = Path(td) / 'repo'
    create_project(fixture, CORE, git_backed=True)
    install_controlled_change(fixture, 'CHG-9002', status='completed', attempt=False)
    git(fixture, 'add', 'specforge/changes'); git(fixture, 'commit', '-m', 'portable preserved governance record')
    candidate = stage_distribution(fixture, '0.1.0-alpha.11-test', [1])
    tool = candidate / 'tools/specforge-upgrade.py'
    change = fixture / 'specforge/changes/CHG-9002.yaml'; before = digest(change)
    r = run(tool, ['upgrade', '--root', str(fixture), '--apply', '--json'])
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout); assert data['applied'] and data['authority']['type'] == 'core_upgrade'; assert digest(change) == before
    guard = fixture / 'specforge/core/tools/specforge-authorization.py'
    r = run(guard, ['--root', str(fixture), '--json']); assert r.returncode == 0, r.stdout + r.stderr
    (fixture / 'README.md').write_text((fixture / 'README.md').read_text(encoding='utf-8') + '\nout-of-scope\n', encoding='utf-8')
    r = run(guard, ['--root', str(fixture), '--json']); assert r.returncode != 0 and 'managed_upgrade_scope_violation' in r.stdout

with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'batty-joe-shaped'
    create_project(fixture, CORE, git_backed=True, declared_core_version='0.1.0-alpha.8')
    shutil.rmtree(fixture / 'specforge/packs'); shutil.rmtree(fixture / 'specforge/decisions')
    install_controlled_change(fixture, 'CHG-0008', status='approved', attempt=False)
    (fixture / 'specforge/history/events').mkdir(parents=True, exist_ok=True)
    (fixture / 'specforge/history/events/.gitkeep').write_text('', encoding='utf-8')
    product = fixture / 'product.txt'; product_before = digest(product)
    change = fixture / 'specforge/changes/CHG-0008.yaml'; change_before = digest(change)
    git(fixture, 'add', '.'); git(fixture, 'commit', '-m', 'Batty Joe shaped alpha.8 baseline')
    candidate = base / 'candidate' / 'core'
    shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode == 0, result.stdout + result.stderr
    upgraded = json.loads(result.stdout)
    assert upgraded['applied'] and upgraded['current_core_version'] == '0.1.0-alpha.8'
    assert digest(product) == product_before and digest(change) == change_before
    assert not (fixture / 'specforge/packs').exists() and (fixture / 'specforge/decisions').is_dir()
    validator = fixture / 'specforge/core/tools/validate-specforge.py'
    result = run(validator, [str(fixture)])
    assert result.returncode == 0, result.stdout + result.stderr
    git(fixture, 'add', '.'); git(fixture, 'commit', '-m', 'Apply managed Core upgrade')
    checkout = base / 'fresh-checkout'
    result = subprocess.run(['git', 'clone', '--quiet', '--local', '--no-hardlinks', str(fixture), str(checkout)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    validator = checkout / 'specforge/core/tools/validate-specforge.py'
    result = run(validator, [str(checkout)])
    assert result.returncode == 0, result.stdout + result.stderr
    authority = yaml.safe_load((checkout / 'specforge/evidence/material-authority.yaml').read_text(encoding='utf-8'))
    assert authority['active_operation']['type'] == 'core_upgrade'

with tempfile.TemporaryDirectory() as td:
    fixture = Path(td) / 'rollback-existing-authority'
    create_project(fixture, CORE, git_backed=True)
    candidate = stage_distribution(fixture, '0.1.0-alpha.12-rollback-test', [1])
    upgrade = load_upgrade_module(); created = recording_tempdirs(upgrade)
    core_before = tree_digest(fixture / 'specforge/core')
    manifest_path = fixture / 'specforge/project.yaml'; manifest_before = manifest_path.read_bytes()
    authority_path = fixture / 'specforge/evidence/material-authority.yaml'; authority_before = authority_path.read_bytes()
    evidence_path = fixture / 'specforge/evidence/upgrades/core-0.1.0-alpha.11-to-0.1.0-alpha.12-rollback-test.yaml'
    def fail_after_authority(*_args, **_kwargs): raise RuntimeError('injected failure after authority establishment')
    upgrade.write_evidence = fail_after_authority
    try: upgrade.apply(fixture, candidate)
    except RuntimeError as exc: assert 'injected failure' in str(exc)
    else: raise AssertionError('controlled post-authority failure was not raised')
    assert tree_digest(fixture / 'specforge/core') == core_before
    assert manifest_path.read_bytes() == manifest_before
    assert authority_path.read_bytes() == authority_before
    assert not evidence_path.exists()
    assert_external(created, fixture)

with tempfile.TemporaryDirectory() as td:
    fixture = Path(td) / 'rollback-absent-authority'
    create_project(fixture, CORE, git_backed=True)
    authority_path = fixture / 'specforge/evidence/material-authority.yaml'
    authority_path.unlink(); git(fixture, 'add', '-u'); git(fixture, 'commit', '-m', 'fixture without material authority')
    candidate = stage_distribution(fixture, '0.1.0-alpha.12-no-authority-test', [1])
    upgrade = load_upgrade_module(); created = recording_tempdirs(upgrade)
    core_before = tree_digest(fixture / 'specforge/core')
    manifest_path = fixture / 'specforge/project.yaml'; manifest_before = manifest_path.read_bytes()
    upgrade.write_evidence = fail_after_authority
    try: upgrade.apply(fixture, candidate)
    except RuntimeError as exc: assert 'injected failure' in str(exc)
    else: raise AssertionError('controlled post-authority failure was not raised')
    assert tree_digest(fixture / 'specforge/core') == core_before
    assert manifest_path.read_bytes() == manifest_before
    assert not authority_path.exists()
    assert_external(created, fixture)

with tempfile.TemporaryDirectory() as td:
    fixture = Path(td) / 'external-scratch-success'
    create_project(fixture, CORE, git_backed=True)
    candidate = stage_distribution(fixture, '0.1.0-alpha.12-success-test', [1])
    upgrade = load_upgrade_module(); created = recording_tempdirs(upgrade)
    result = upgrade.apply(fixture, candidate)
    assert result['applied'] and result['authority']['type'] == 'core_upgrade'
    assert created
    assert_external(created, fixture)

# --- CHG-1017: data_model_version transactional write; ordinary downstream fields untouched ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'downstream-plain'
    create_project(fixture, CORE, git_backed=True, declared_core_version='0.1.0-alpha.14', declared_data_model_version='0.1.0-alpha.4')
    product_before = digest(fixture / 'product.txt'); model_before = digest(fixture / 'model.txt')
    spec_before = yaml.safe_load((fixture / 'specforge/project.yaml').read_text(encoding='utf-8'))['specification']
    # create_project already leaves a clean committed tree; nothing further to commit here.
    candidate = base / 'candidate' / 'core'; shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data['applied']
    manifest = yaml.safe_load((fixture / 'specforge/project.yaml').read_text(encoding='utf-8'))
    assert manifest['specforge']['core_version'] == TARGET_CORE_VERSION
    assert manifest['specforge']['data_model_version'] == TARGET_DATA_MODEL_VERSION
    assert manifest['specification'] == spec_before, 'ordinary downstream specification fields must be byte-identical'
    assert digest(fixture / 'product.txt') == product_before and digest(fixture / 'model.txt') == model_before
    validator = fixture / 'specforge/core/tools/validate-specforge.py'
    vr = run(validator, [str(fixture)])
    assert vr.returncode == 0, vr.stdout + vr.stderr

# --- CHG-1017: product-spec self-reference rebinds itself and current_version together ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'self-ref-product-spec'
    create_project(fixture, CORE, git_backed=True, declared_core_version='0.1.0-alpha.14', declared_data_model_version='0.1.0-alpha.4',
                   self_referencing_product_specification=True)
    # create_project already leaves a clean committed tree; nothing further to commit here.
    candidate = base / 'candidate' / 'core'; shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = yaml.safe_load((fixture / 'specforge/project.yaml').read_text(encoding='utf-8'))
    spec = manifest['specification']
    assert spec['product_specification'] == f'./specforge/core/docs/specforge-core-product-spec-{TARGET_CORE_VERSION}.md'
    assert spec['current_version'] == TARGET_CORE_VERSION
    assert spec['canonical_data_model'] == './model.txt', 'canonical_data_model must stay untouched when only product_specification self-references'
    validator = fixture / 'specforge/core/tools/validate-specforge.py'
    vr = run(validator, [str(fixture)])
    assert vr.returncode == 0, vr.stdout + vr.stderr

# --- CHG-1017: canonical-data-model self-reference rebinds alone; Batty-Joe-shaped mixed case ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'self-ref-data-model-mixed'
    create_project(fixture, CORE, git_backed=True, declared_core_version='0.1.0-alpha.14', declared_data_model_version='0.1.0-alpha.4',
                   self_referencing_canonical_data_model=True)
    manifest_path = fixture / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['specification']['current_version'] = '1.5.0'
    write_yaml(manifest_path, manifest)
    git(fixture, 'add', '.'); git(fixture, 'commit', '-m', 'Batty-Joe-shaped mixed baseline: own spec, Core data model, own version')
    new_head = git(fixture, 'rev-parse', 'HEAD').stdout.strip()
    write_yaml(fixture / 'specforge/evidence/material-authority.yaml', {'version': 1, 'trusted': {'provider': 'git', 'revision': new_head}})
    git(fixture, 'add', 'specforge/evidence/material-authority.yaml'); git(fixture, 'commit', '-m', 'anchor trusted baseline for test fixture')
    candidate = base / 'candidate' / 'core'; shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    spec = manifest['specification']
    assert spec['canonical_data_model'] == f'./specforge/core/docs/specforge-core-canonical-data-model-{TARGET_DATA_MODEL_VERSION}.md'
    assert spec['product_specification'] == './product.txt', 'own product specification must remain untouched'
    assert spec['current_version'] == '1.5.0', 'own current_version must remain untouched by a canonical_data_model-only rebind'
    validator = fixture / 'specforge/core/tools/validate-specforge.py'
    vr = run(validator, [str(fixture)])
    assert vr.returncode == 0, vr.stdout + vr.stderr

# --- CHG-1017: both fields self-reference simultaneously and independently ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'self-ref-both'
    create_project(fixture, CORE, git_backed=True, declared_core_version='0.1.0-alpha.14', declared_data_model_version='0.1.0-alpha.4',
                   self_referencing_product_specification=True, self_referencing_canonical_data_model=True)
    # create_project already leaves a clean committed tree; nothing further to commit here.
    candidate = base / 'candidate' / 'core'; shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = yaml.safe_load((fixture / 'specforge/project.yaml').read_text(encoding='utf-8'))
    spec = manifest['specification']
    assert spec['product_specification'] == f'./specforge/core/docs/specforge-core-product-spec-{TARGET_CORE_VERSION}.md'
    assert spec['canonical_data_model'] == f'./specforge/core/docs/specforge-core-canonical-data-model-{TARGET_DATA_MODEL_VERSION}.md'
    assert spec['current_version'] == TARGET_CORE_VERSION
    validator = fixture / 'specforge/core/tools/validate-specforge.py'
    vr = run(validator, [str(fixture)])
    assert vr.returncode == 0, vr.stdout + vr.stderr

# --- CHG-1017: missing candidate target doc refuses the whole upgrade before any mutation ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'self-ref-target-doc-missing'
    create_project(fixture, CORE, git_backed=True, declared_core_version='0.1.0-alpha.14', declared_data_model_version='0.1.0-alpha.4',
                   self_referencing_product_specification=True)
    # create_project already leaves a clean committed tree; nothing further to commit here.
    core_before = tree_digest(fixture / 'specforge/core')
    manifest_path = fixture / 'specforge/project.yaml'; manifest_before = manifest_path.read_bytes()
    candidate = stage_distribution(fixture, '0.1.0-alpha.99-missing-doc-test', [1])
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert not data.get('applied')
    assert any('self_referencing_product_specification_target_doc_missing' in b for b in data['blockers']), data['blockers']
    assert tree_digest(fixture / 'specforge/core') == core_before
    assert manifest_path.read_bytes() == manifest_before
    upgrades_dir = fixture / 'specforge/evidence/upgrades'
    assert not upgrades_dir.exists() or not list(upgrades_dir.glob('*.yaml'))

# --- CHG-1017: source-state preflight -- project/core version drift blocks before authority, all files unchanged ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'source-core-drift'
    create_project(fixture, CORE, git_backed=True)
    manifest_path = fixture / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['specforge']['core_version'] = '0.1.0-alpha.14'
    write_yaml(manifest_path, manifest)
    git(fixture, 'add', '.'); git(fixture, 'commit', '-m', 'introduce project/core version drift')
    core_before = tree_digest(fixture / 'specforge/core')
    manifest_before = manifest_path.read_bytes()
    authority_path = fixture / 'specforge/evidence/material-authority.yaml'; authority_before = authority_path.read_bytes()
    candidate = base / 'candidate' / 'core'; shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert not data.get('applied')
    assert any(b.startswith('source_core_version_inconsistent:') for b in data['blockers']), data['blockers']
    assert 'authority' not in data, 'authority must never be established when the source-state preflight refuses'
    assert tree_digest(fixture / 'specforge/core') == core_before
    assert manifest_path.read_bytes() == manifest_before
    assert authority_path.read_bytes() == authority_before
    assert not (fixture / 'specforge/evidence/upgrades').exists()

# --- CHG-1017: source-state preflight -- package/core version drift blocks before mutation ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'source-package-drift'
    create_project(fixture, CORE, git_backed=True)
    package_path = fixture / 'specforge/core/package.yaml'
    package = yaml.safe_load(package_path.read_text(encoding='utf-8'))
    package['package']['version'] = '0.1.0-alpha.14'
    write_yaml(package_path, package)
    git(fixture, 'add', '.'); git(fixture, 'commit', '-m', 'introduce package/core version drift')
    core_before = tree_digest(fixture / 'specforge/core')
    manifest_path = fixture / 'specforge/project.yaml'; manifest_before = manifest_path.read_bytes()
    candidate = base / 'candidate' / 'core'; shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert not data.get('applied')
    assert any(b.startswith('source_package_version_inconsistent:') for b in data['blockers']), data['blockers']
    assert tree_digest(fixture / 'specforge/core') == core_before
    assert manifest_path.read_bytes() == manifest_before

# --- CHG-1017: source-state preflight -- data-model version drift blocks before mutation ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'source-data-model-drift'
    create_project(fixture, CORE, git_backed=True)
    manifest_path = fixture / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['specforge']['data_model_version'] = '0.1.0-alpha.4'
    write_yaml(manifest_path, manifest)
    git(fixture, 'add', '.'); git(fixture, 'commit', '-m', 'introduce data-model version drift')
    core_before = tree_digest(fixture / 'specforge/core')
    manifest_before = manifest_path.read_bytes()
    candidate = base / 'candidate' / 'core'; shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert not data.get('applied')
    assert any(b.startswith('source_data_model_version_inconsistent:') for b in data['blockers']), data['blockers']
    assert tree_digest(fixture / 'specforge/core') == core_before
    assert manifest_path.read_bytes() == manifest_before

# --- CHG-1017: source-state preflight -- stale self-referencing field blocks before mutation, never silently repaired ---
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'source-self-ref-stale'
    create_project(fixture, CORE, git_backed=True, declared_core_version='0.1.0-alpha.14', declared_data_model_version='0.1.0-alpha.4',
                   self_referencing_product_specification=True)
    manifest_path = fixture / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['specification']['product_specification'] = './specforge/core/docs/specforge-core-product-spec-0.1.0-alpha.13.md'
    write_yaml(manifest_path, manifest)
    git(fixture, 'add', '.'); git(fixture, 'commit', '-m', 'introduce stale self-referencing product-spec path')
    core_before = tree_digest(fixture / 'specforge/core')
    manifest_before = manifest_path.read_bytes()
    candidate = base / 'candidate' / 'core'; shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert not data.get('applied')
    assert any(b.startswith('source_self_referencing_product_specification_inconsistent:') for b in data['blockers']), data['blockers']
    assert tree_digest(fixture / 'specforge/core') == core_before
    assert manifest_path.read_bytes() == manifest_before

# CHG-1035: upgrading an existing unactivated project must not silently fresh-initialize it.
with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    fixture = base / 'existing-unactivated-alpha21'
    create_project(
        fixture, CORE, git_backed=True,
        declared_core_version='0.1.0-alpha.21',
        declared_data_model_version='0.1.0-alpha.9',
    )
    candidate = base / 'candidate-alpha25' / 'core'
    shutil.copytree(CORE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    tool = candidate / 'tools/specforge-upgrade.py'
    result = run(tool, ['upgrade', '--root', str(fixture), '--distribution', str(candidate), '--apply', '--json'])
    assert result.returncode == 0, result.stdout + result.stderr
    upgraded_manifest = yaml.safe_load((fixture / 'specforge/project.yaml').read_text(encoding='utf-8'))
    assert 'governance_tier' not in upgraded_manifest
    assert not (fixture / 'specforge/evidence/governance-tier-grandfather.yaml').exists()

print('Upgrade tests PASSED')

assert (CORE / 'schemas/checkpoint-acceptance-proof.schema.json').is_file()
assert (CORE / 'docs/specforge-core-product-spec-0.1.0-alpha.25.md').is_file()
assert (CORE / 'docs/specforge-core-canonical-data-model-0.1.0-alpha.10.md').is_file()

# Alpha.25 integrity trust is never inferred from an upgrade alone: one deep audit must initialise it.
with tempfile.TemporaryDirectory() as td:
    fixture = Path(td) / 'integrity-initialisation'
    create_project(fixture, CORE, git_backed=True, initialize_governance_tier=True)
    integrity = fixture / 'specforge/core/tools/specforge-integrity.py'
    result = run(integrity, ['status', '--root', str(fixture), '--json'])
    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status['deep_audit_required'] is True
    state = fixture / 'specforge/evidence/integrity/state.json'
    result = run(integrity, ['full', '--root', str(fixture), '--state-output', str(state), '--progress-file', '-', '--json'])
    assert result.returncode == 0, result.stdout + result.stderr
    audited = json.loads(result.stdout)
    assert audited['ok'] and audited['mode'] == 'full_integrity_v1'


# CHG-1049 reconciliation compatibility contract
_contract_core=Path(__file__).resolve().parents[1]
_source=(_contract_core/"tools"/"specforge-upgrade.py").read_text(encoding="utf-8")
assert 'context_only' in _source
assert 'durable_update' in _source

# CHG-1044: configured evidence/governance roots are preserved and used for upgrade evidence.
with tempfile.TemporaryDirectory(prefix='specforge-upgrade-paths-') as td:
    fixture=Path(td)/'repo'
    create_project(fixture,CORE,git_backed=True)
    manifest_path=fixture/'specforge/project.yaml'
    manifest=yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest.setdefault('paths',{})['evidence']='./audit/evidence'
    manifest['paths']['changes']='./governance/changes'
    manifest['paths']['decisions']='./governance/decisions'
    manifest['paths']['history']='./governance/history'
    write_yaml(manifest_path,manifest)
    module=load_upgrade_module(); layout=module.discover_layout(fixture)
    path=module.evidence_path(layout,'0.1.0-a','0.1.0-b')
    assert path.resolve()==(fixture/'audit/evidence/upgrades/core-0.1.0-a-to-0.1.0-b.yaml').resolve(),path
    candidate=stage_distribution(fixture,'0.1.0-alpha.99-test',[1])
    planned=module.plan(fixture,candidate)
    assert planned['permitted'],planned
    assert 'audit/evidence' in planned['preserve'],planned['preserve']
    assert 'governance/changes' in planned['preserve'],planned['preserve']
print('PASS configured-upgrade-paths')
