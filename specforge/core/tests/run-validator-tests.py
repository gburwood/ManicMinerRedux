#!/usr/bin/env python3
from pathlib import Path
import json, subprocess, tempfile, shutil, sys, yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from portable_fixture import create_project, git, install_controlled_change, write_yaml, canonical_digest
from specforge_project import discover_layout, iter_record_files
from specforge_integration import PROFILE, build_git_integration_evidence

VALIDATOR = ROOT / 'tools' / 'validate-specforge.py'
EXAMPLE = ROOT / 'examples' / 'minimal'
EXPLICIT_ROOTS = [
    'product.txt',
    'model.txt',
    'README.md',
    'specforge/project.yaml',
    'specforge/SPECFORGE.md',
    'specforge/core',
    'specforge/packs',
]


def run(path, *extra):
    return subprocess.run([sys.executable, str(VALIDATOR), str(path), *map(str, extra)], capture_output=True, text=True)


def expect_pass(path, label, *extra):
    r = run(path, *extra)
    assert r.returncode == 0, f"{label}\n{r.stdout}\n{r.stderr}"


def expect_fail(path, text, label, *extra):
    r = run(path, *extra)
    assert r.returncode != 0, f"{label}: unexpectedly passed"
    assert text in r.stdout, f"{label}: expected {text!r}\n{r.stdout}"


expect_pass(EXAMPLE, 'minimal example should validate')

# Preserve the nested-project exclusion regression without depending on this repository's
# historical completed-change topology. The nested project must not become parent material.
with tempfile.TemporaryDirectory() as td:
    parent = Path(td) / 'parent'
    create_project(parent, ROOT, git_backed=True)
    shutil.copytree(EXAMPLE, parent / 'nested-example')
    expect_pass(parent, 'parent project should validate while excluding nested example project')

with tempfile.TemporaryDirectory() as td:
    bad = Path(td) / 'bad'
    shutil.copytree(EXAMPLE, bad)
    (bad / 'SPECFORGE.md').unlink()
    expect_fail(bad, 'Missing required file', 'missing bootstrap')

with tempfile.TemporaryDirectory() as td:
    bad = Path(td) / 'bad'
    shutil.copytree(EXAMPLE, bad)
    req = bad / 'spec/requirements/REQ-0001.yaml'
    data = yaml.safe_load(req.read_text())
    data['status'] = 'banana'
    req.write_text(yaml.safe_dump(data, sort_keys=False))
    expect_fail(bad, 'Schema validation failed', 'schema validation')

with tempfile.TemporaryDirectory() as td:
    bad = Path(td) / 'bad'
    shutil.copytree(EXAMPLE, bad)
    req = bad / 'spec/requirements/REQ-0001.yaml'
    data = yaml.safe_load(req.read_text())
    data['introduced']['by_change'] = 'CHG-9999'
    req.write_text(yaml.safe_dump(data, sort_keys=False))
    expect_fail(bad, 'Broken reference', 'broken reference')

with tempfile.TemporaryDirectory() as td:
    bad = Path(td) / 'bad'
    shutil.copytree(EXAMPLE, bad)
    prop = bad / 'changes/CHG-0001/PROP-0001-01.yaml'
    data = yaml.safe_load(prop.read_text())
    data['change'] = 'CHG-9999'
    prop.write_text(yaml.safe_dump(data, sort_keys=False))
    expect_fail(bad, 'Broken reference', 'proposal/change link')

with tempfile.TemporaryDirectory() as td:
    bad = Path(td) / 'bad'
    shutil.copytree(EXAMPLE, bad)
    appr = bad / 'changes/CHG-0001/approvals/APR-0001.yaml'
    data = yaml.safe_load(appr.read_text())
    data['proposal'] = 'PROP-9999-01'
    appr.write_text(yaml.safe_dump(data, sort_keys=False))
    expect_fail(bad, 'Broken reference', 'approval/proposal link')

with tempfile.TemporaryDirectory() as td:
    bad = Path(td) / 'bad'
    shutil.copytree(EXAMPLE, bad)
    manifest = bad / 'specforge.yaml'
    data = yaml.safe_load(manifest.read_text())
    data['paths']['changes'] = './does-not-exist'
    manifest.write_text(yaml.safe_dump(data, sort_keys=False))
    expect_fail(bad, 'Manifest path', 'missing manifest path')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'portable'
    create_project(portable, ROOT, git_backed=True)
    shutil.rmtree(portable / 'specforge/packs')
    shutil.rmtree(portable / 'specforge/decisions')
    expect_pass(portable, 'absent empty collection roots should validate')
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['packs'] = [{'id': 'missing-pack', 'version': '1.0.0', 'path': './specforge/packs/missing-pack', 'precedence': 1, 'extensions': []}]
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, "Manifest path 'packs'", 'missing declared pack collection')

# --- CHG-1018: explicit material boundary validator contract ---

# --- CHG-1020: evidence is not a canonical governance-record root ---

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'presentation-evidence'
    create_project(portable, ROOT, git_backed=True)
    presentation = portable / 'specforge/evidence/presentations/PRES-20260918T100000000000Z.yaml'
    write_yaml(presentation, {
        'id': 'PRES-20260918T100000000000Z',
        'type': 'proposal_presentation',
        'proposal': 'PROP-9000-01',
        'proposal_digest': '0' * 64,
        'presented_at': '2026-09-18T10:00:00+00:00',
        'summary': 'Fixture presentation evidence.',
        'user_prompt': 'Shall I make this change?',
    })
    expect_pass(portable, 'presentation evidence should not be classified as a canonical governance record')
    layout = discover_layout(portable)
    discovered = {path.resolve() for path in iter_record_files(layout)}
    assert presentation.resolve() not in discovered, 'presentation evidence leaked into canonical record discovery'

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'unknown-canonical-id'
    create_project(portable, ROOT, git_backed=True)
    write_yaml(portable / 'specforge/changes/MYSTERY-0001.yaml', {
        'id': 'MYSTERY-0001',
        'note': 'Unknown IDs in canonical governance trees must still fail closed.',
    })
    expect_fail(portable, 'Unrecognised canonical id MYSTERY-0001', 'unknown canonical governance id still fails closed')


with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'explicit-valid'
    create_project(portable, ROOT, git_backed=True, material_roots=EXPLICIT_ROOTS)
    expect_pass(portable, 'valid explicit material boundary should validate')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'explicit-project-wide'
    create_project(portable, ROOT, git_backed=True, material_roots=EXPLICIT_ROOTS)
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['material']['roots'] = ['.']
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, 'material_root_project_wide_forbidden', 'validator rejects project-wide explicit material root')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'explicit-non-material-overlap'
    create_project(portable, ROOT, git_backed=True, material_roots=EXPLICIT_ROOTS)
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['material']['roots'] = ['specforge/history']
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, 'material_root_non_material_overlap', 'validator rejects explicit root overlapping Core non-material infrastructure')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'explicit-unknown'
    create_project(portable, ROOT, git_backed=True, material_roots=EXPLICIT_ROOTS)
    unknown = portable / 'new-engine'
    unknown.mkdir()
    (unknown / 'engine.txt').write_text('unknown\n', encoding='utf-8')
    expect_fail(portable, 'unclassified_project_paths_present', 'validator rejects unclassified explicit project path')


with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'v3-valid'
    state = create_project(root, ROOT, git_backed=True)
    git(root, 'branch', '-M', 'main')
    before = state['trusted_revision']
    install_controlled_change(
        root,
        'CHG-9016',
        status='in_progress',
        attempt=True,
        before=before,
        outcome='in_progress',
        verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start validator v3 fixture')
    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'validator v3 material')
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
    assert built['valid'], built
    install_controlled_change(
        root,
        'CHG-9016',
        status='completed',
        attempt=True,
        before=before,
        after=after,
        outcome='passed',
        integration=built['integration'],
        verification_profile=PROFILE,
    )
    write_yaml(root / 'specforge/evidence/material-authority.yaml', {
        'version': 1,
        'trusted': {'provider': 'git', 'revision': after},
    })
    git(root, 'add', 'specforge/changes', 'specforge/evidence/material-authority.yaml')
    git(root, 'commit', '-m', 'record completed v3 evidence and trusted material baseline')
    expect_pass(root, 'completed v3 integration evidence should validate statically')

    attempt_path = root / 'specforge/changes/CHG-9016/implementation/IMP-9016-01.yaml'
    attempt = yaml.safe_load(attempt_path.read_text(encoding='utf-8'))
    attempt['integration']['integrated_material']['revision'] = 'sha256:' + ('0' * 64)
    attempt_path.write_text(yaml.safe_dump(attempt, sort_keys=False), encoding='utf-8', newline='\n')
    expect_fail(root, 'integration_material_identity_mismatch', 'validator rejects tampered v3 material equivalence')

# --- CHG-1027: historical integration-evidence correction overlay ---

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'v3-corrected-history'
    state = create_project(root, ROOT, git_backed=True)
    git(root, 'branch', '-M', 'main')
    before = state['trusted_revision']
    install_controlled_change(
        root,
        'CHG-9027',
        status='in_progress',
        attempt=True,
        before=before,
        outcome='in_progress',
        verification_profile=PROFILE,
    )
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'start corrected-history validator fixture')
    target_before = git(root, 'rev-parse', 'HEAD').stdout.strip()
    (root / 'product.txt').write_text('two\n', encoding='utf-8', newline='\n')
    git(root, 'add', 'product.txt')
    git(root, 'commit', '-m', 'corrected-history material')
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
    assert built['valid'], built
    actual_material = built['integration']['implementation_material']['revision']
    file_count = built['integration']['implementation_material']['file_count']
    wrong_material = 'sha256:' + ('7' * 64)
    broken_integration = yaml.safe_load(yaml.safe_dump(built['integration']))
    broken_integration['implementation_material']['revision'] = wrong_material
    broken_integration['integrated_material']['revision'] = wrong_material
    install_controlled_change(
        root,
        'CHG-9027',
        status='completed',
        attempt=True,
        before=before,
        after=after,
        outcome='passed',
        integration=broken_integration,
        verification_profile=PROFILE,
    )
    write_yaml(root / 'specforge/evidence/material-authority.yaml', {
        'version': 1,
        'trusted': {'provider': 'git', 'revision': after},
    })
    git(root, 'add', 'specforge/changes', 'specforge/evidence/material-authority.yaml')
    git(root, 'commit', '-m', 'record wrong historical digest evidence')
    expect_fail(
        root,
        'implementation_material_recomputation_mismatch',
        'historical wrong digest fails before correction overlay',
    )
    write_yaml(root / 'specforge/history/events/EVT-990027.yaml', {
        'id': 'EVT-990027',
        'timestamp': '2026-09-18T14:11:06+01:00',
        'actor': {'type': 'automated_system', 'id': 'fixture'},
        'event_type': 'integration_evidence_correction',
        'entity': {'type': 'implementation', 'id': 'IMP-9027-01'},
        'related': {'change': 'CHG-9027', 'implementation_attempt': 'IMP-9027-01'},
        'evidence': {
            'source_revision_after': after,
            'integrated_revision': built['integration']['integrated_revision'],
            'original': {
                'implementation_material': wrong_material,
                'integrated_material': wrong_material,
            },
            'corrected': {
                'material': actual_material,
                'file_count': file_count,
            },
        },
    })
    expect_pass(root, 'historical completed change validates through forensic correction overlay')

# --- CHG-1017: manifest/installed-core/package/self-referencing consistency ---

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'core-version-drift'
    create_project(portable, ROOT, git_backed=True)
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['specforge']['core_version'] = '0.1.0-alpha.1-drift'
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, 'Manifest specforge.core_version', 'core_version vs installed core.yaml mismatch')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'data-model-version-drift'
    create_project(portable, ROOT, git_backed=True)
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['specforge']['data_model_version'] = '0.1.0-alpha.1-drift'
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, 'Manifest specforge.data_model_version', 'data_model_version vs installed core.yaml mismatch')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'package-version-drift'
    create_project(portable, ROOT, git_backed=True)
    package = portable / 'specforge/core/package.yaml'
    data = yaml.safe_load(package.read_text(encoding='utf-8'))
    data['package']['version'] = '0.1.0-alpha.1-drift'
    package.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, "package.yaml's declared version", 'package/core version mismatch, independent of a correct project.yaml')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'self-ref-product-spec-consistent'
    create_project(portable, ROOT, git_backed=True, self_referencing_product_specification=True)
    expect_pass(portable, 'consistent self-referencing product specification should validate')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'self-ref-product-spec-embedded-mismatch'
    create_project(portable, ROOT, git_backed=True, self_referencing_product_specification=True)
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['specification']['product_specification'] = './specforge/core/docs/specforge-core-product-spec-0.1.0-alpha.14.md'
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, 'product_specification self-references', 'self-referencing product-spec embedded-version mismatch')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'self-ref-product-spec-current-version-mismatch'
    create_project(portable, ROOT, git_backed=True, self_referencing_product_specification=True)
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['specification']['current_version'] = '9.9.9-mismatch'
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, 'product_specification self-references', 'self-referencing product-spec current_version mismatch')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'self-ref-data-model-consistent-mixed'
    create_project(portable, ROOT, git_backed=True, self_referencing_canonical_data_model=True)
    expect_pass(portable, 'own product spec + Core canonical data model (mixed reference) should validate, current_version unconstrained')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'self-ref-data-model-embedded-mismatch'
    create_project(portable, ROOT, git_backed=True, self_referencing_canonical_data_model=True)
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['specification']['canonical_data_model'] = './specforge/core/docs/specforge-core-canonical-data-model-0.1.0-alpha.4.md'
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, 'canonical_data_model self-references', 'self-referencing canonical-data-model embedded-version mismatch')

with tempfile.TemporaryDirectory() as td:
    portable = Path(td) / 'unmanaged-core-version-drift'
    create_project(portable, ROOT, git_backed=False)
    manifest = portable / 'specforge/project.yaml'
    data = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    data['specforge']['core_version'] = '0.1.0-alpha.1-drift'
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    expect_fail(portable, 'Manifest specforge.core_version', 'unmanaged-folder core_version vs installed core.yaml mismatch')

# --- CHG-1023: change-scoped incremental validation ---

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'scoped-validation'
    state = create_project(root, ROOT, git_backed=True)
    baseline = state['trusted_revision']

    install_controlled_change(
        root,
        'CHG-9020',
        status='completed',
        attempt=True,
        before=baseline,
        after=baseline,
        outcome='passed',
        verification_profile=PROFILE,
    )
    install_controlled_change(root, 'CHG-9021', status='approved', attempt=False)
    git(root, 'add', 'specforge/changes')
    git(root, 'commit', '-m', 'scoped validator fixture')

    full = run(root)
    assert full.returncode != 0, 'full validation should reject bad historical material evidence'
    assert 'completion lacks passing implementation' in full.stdout, full.stdout + full.stderr

    scoped = run(root, '--change', 'CHG-9021')
    assert scoped.returncode == 0, scoped.stdout + scoped.stderr
    assert 'Validation mode: change_scoped' in scoped.stdout
    assert 'Scoped changes: CHG-9021' in scoped.stdout

    target_path = root / 'specforge/changes/CHG-9021.yaml'
    target = yaml.safe_load(target_path.read_text(encoding='utf-8'))
    target.setdefault('relationships', {})['depends_on'] = ['CHG-9020']
    target_path.write_text(yaml.safe_dump(target, sort_keys=False), encoding='utf-8', newline='\n')

    dependent = run(root, '--change', 'CHG-9021')
    assert dependent.returncode != 0, dependent.stdout + dependent.stderr
    assert 'completion lacks passing implementation' in dependent.stdout
    assert 'CHG-9020' in dependent.stdout

    missing = run(root, '--change', 'CHG-9999')
    assert missing.returncode != 0
    assert 'Scoped validation target missing or not a change: CHG-9999' in missing.stdout


# CHG-1032: the School Project 10 external-delivery bypass must fail closed.
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / 'managed-completion-guard'
    create_project(root, ROOT, git_backed=True)
    evidence = root / 'specforge/evidence'
    sessions = evidence / 'managed-sessions'
    sessions.mkdir(parents=True, exist_ok=True)
    session = 'SESSION-SP10'
    (sessions / f'{session}.json').write_text(
        json.dumps({
            'type': 'managed_interaction_session',
            'session': session,
            'completion_guard_version': 1,
            'started_at': '2026-09-22T10:00:00.000Z',
            'project_definition': {'state': 'defined', 'path': 'PROJECT.md', 'sha256': '0' * 64},
        }, indent=2) + '\n',
        encoding='utf-8',
        newline='\n',
    )
    (evidence / 'interaction-metrics.jsonl').write_text(
        json.dumps({
            'event_id': 'SP10-1',
            'timestamp': '2026-09-22T10:05:00.000Z',
            'phase': 'product_validation_completed',
            'session': session,
        }) + '\n',
        encoding='utf-8',
        newline='\n',
    )
    expect_fail(
        root,
        'Managed completion guard violation for SESSION-SP10: material completion evidence exists without a governed change or completion receipt',
        'School Project 10 external-delivery bypass must fail closed',
    )

    completions = evidence / 'completions'
    completions.mkdir(parents=True, exist_ok=True)
    (completions / f'{session}.json').write_text(
        json.dumps({
            'type': 'managed_completion_receipt',
            'receipt_version': 1,
            'outcome': 'non_delivery',
            'session': session,
            'reason': 'The interaction ended without delivering project material.',
            'closed_at': '2026-09-22T10:06:00.000Z',
        }, indent=2) + '\n',
        encoding='utf-8',
        newline='\n',
    )
    expect_pass(root, 'explicit non-delivery closure should satisfy the managed completion guard')

    # CHG-1035: receipt version must exactly match historical v2 and new v3 session guards.
    metrics = evidence / 'interaction-metrics.jsonl'
    with metrics.open('a', encoding='utf-8', newline='\n') as handle:
        for version in (2, 3):
            sid = f'SESSION-RECEIPT-V{version}'
            write_yaml_path = sessions / f'{sid}.json'
            write_yaml_path.write_text(json.dumps({
                'type': 'managed_interaction_session',
                'session': sid,
                'completion_guard_version': version,
                'started_at': f'2026-09-23T1{version}:00:00.000Z',
                'request': {'digest': 'sha256:' + ('a' * 64)},
                'project_definition': {'state': 'undefined', 'path': None},
                'project_definition_reconciliation': {'required': False},
            }, indent=2) + '\n', encoding='utf-8', newline='\n')
            (completions / f'{sid}.json').write_text(json.dumps({
                'type': 'managed_completion_receipt',
                'receipt_version': version,
                'outcome': 'non_delivery',
                'session': sid,
                'reason': f'guard-v{version} compatibility',
                'closed_at': f'2026-09-23T1{version}:01:00.000Z',
            }, indent=2) + '\n', encoding='utf-8', newline='\n')
            handle.write(json.dumps({
                'event_id': f'RECEIPT-V{version}',
                'timestamp': f'2026-09-23T1{version}:00:30.000Z',
                'phase': 'product_validation_completed',
                'session': sid,
            }) + '\n')
    expect_pass(root, 'guard-v2 and guard-v3 matching non-delivery receipts should validate')

    bad_v3 = completions / 'SESSION-RECEIPT-V3.json'
    bad_data = json.loads(bad_v3.read_text(encoding='utf-8'))
    bad_data['receipt_version'] = 2
    bad_v3.write_text(json.dumps(bad_data, indent=2) + '\n', encoding='utf-8', newline='\n')
    expect_fail(root, 'receipt identity invalid', 'mismatched guard-v3 receipt version must fail')

print('Validator tests PASSED')


# CHG-1030 regression: checkpoint records are canonical validator types.
_validator_text = (ROOT / 'tools/validate-specforge.py').read_text(encoding='utf-8')
assert '("checkpoint", re.compile' in _validator_text
assert '("checkpoint-acceptance", re.compile' in _validator_text


# CHG-1033 regression: PFA is canonical, human-authored and single-use.
_validator_text = (ROOT / 'tools/validate-specforge.py').read_text(encoding='utf-8')
assert '("prospective-finalisation-authority", re.compile' in _validator_text
assert 'Prospective finalisation authority replay detected' in _validator_text
assert (ROOT / 'schemas/prospective-finalisation-authority.schema.json').is_file()


# CHG-1034 regression: controlled_v3, CAP and session-guard-v2 contracts are validator-visible.
_validator_text_1034 = (ROOT / 'tools/validate-specforge.py').read_text(encoding='utf-8')
assert '("checkpoint-acceptance-proof", re.compile' in _validator_text_1034
assert 'controlled_v3 implementation predates approval' in _validator_text_1034
assert 'Checkpoint acceptance proof replay detected' in _validator_text_1034
assert 'PROJECT.md current-work binding is stale' in _validator_text_1034
assert 'controlled_v3 clarification required' in _validator_text_1034
assert (ROOT / 'schemas/checkpoint-acceptance-proof.schema.json').is_file()

# CHG-1049 reconciliation compatibility contract
_contract_core=Path(__file__).resolve().parents[1]
_source=(_contract_core/"tools"/"validate-specforge.py").read_text(encoding="utf-8")
assert 'project-definition reconciliation mode missing' in _source
assert 'unknown project-definition reconciliation mode' in _source
assert 'context_only proposal includes project definition' in _source

# CHG-1048 regression: unsupported definition formats and unknown nested fields fail closed.
def _chg1048_definition_format_fail_closed_contract():
    import copy as _copy, json as _json
    from pathlib import Path as _Path
    import jsonschema as _jsonschema
    _schema=_json.loads((_Path(__file__).resolve().parents[1]/"schemas"/"proposal.schema.json").read_text(encoding="utf-8"))
    _base={"id":"PROP-9998-01","change":"CHG-9998","revision":1,"status":"draft","behaviour_summary":"fixture","project_definition_reconciliation":{"path":"PROJECT.md","sha256":"0"*64,"request_digest":"sha256:"+"1"*64,"change":"CHG-9998","mode":"context_only","definition_format_version":2}}
    _validator=_jsonschema.Draft202012Validator(_schema)
    for _bad in [1,3,0,"2",None,True,False]:
        _x=_copy.deepcopy(_base);_x["project_definition_reconciliation"]["definition_format_version"]=_bad
        assert list(_validator.iter_errors(_x)), _bad
    _x=_copy.deepcopy(_base);_x["project_definition_reconciliation"]["unexpected_field"]="nope"
    assert list(_validator.iter_errors(_x))
_chg1048_definition_format_fail_closed_contract()


# CHG-1046 regression: experiment is an explicit classification, not a governance exemption.
def _chg1046_experiment_classification_contract():
    import copy as _copy
    import jsonschema as _jsonschema

    _schema = json.loads((ROOT / 'schemas/change.schema.json').read_text(encoding='utf-8'))
    _validator = _jsonschema.Draft202012Validator(_schema)
    _base = {
        'id': 'CHG-9046',
        'title': 'Experimental validation fixture',
        'classification': 'experiment',
        'status': 'approved',
        'sources': [{'type': 'manual', 'reference': 'CHG-1046 regression'}],
        'request': {'summary': 'Exercise experiment classification.'},
    }
    _existing = [
        'feature', 'behaviour_change', 'defect', 'specification_defect',
        'refactor', 'documentation', 'tooling_infrastructure', 'unknown',
    ]
    for _classification in [*_existing, 'experiment']:
        _record = _copy.deepcopy(_base)
        _record['classification'] = _classification
        assert not list(_validator.iter_errors(_record)), _classification
    for _bad in ['made_up_classification', 'Experiment', '']:
        _record = _copy.deepcopy(_base)
        _record['classification'] = _bad
        assert list(_validator.iter_errors(_record)), _bad
    _malformed = _copy.deepcopy(_base)
    del _malformed['request']
    assert list(_validator.iter_errors(_malformed))

    def _mark_experiment(root, change_id):
        change_path = root / 'specforge/changes' / f'{change_id}.yaml'
        change = yaml.safe_load(change_path.read_text(encoding='utf-8'))
        change['classification'] = 'experiment'
        write_yaml(change_path, change)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'experiment-valid'
        create_project(root, ROOT, git_backed=True)
        install_controlled_change(root, 'CHG-9046', status='approved', lifecycle_enforcement='controlled_v3')
        _mark_experiment(root, 'CHG-9046')
        expect_pass(root, 'experiment classification with ordinary controlled-v3 approval should validate')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'experiment-no-approval'
        create_project(root, ROOT, git_backed=True)
        install_controlled_change(root, 'CHG-9047', status='approved', lifecycle_enforcement='controlled_v3', skip_approval=True)
        _mark_experiment(root, 'CHG-9047')
        assert run(root).returncode != 0, 'experiment classification must not bypass required approval'

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'experiment-stale-approval'
        create_project(root, ROOT, git_backed=True)
        state = install_controlled_change(root, 'CHG-9048', status='approved', lifecycle_enforcement='controlled_v3')
        _mark_experiment(root, 'CHG-9048')
        proposal = yaml.safe_load(state['proposal_path'].read_text(encoding='utf-8'))
        proposal['behaviour_summary'] = 'tampered after approval'
        write_yaml(state['proposal_path'], proposal)
        assert run(root).returncode != 0, 'experiment classification must not bypass stale proposal-digest approval checks'

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'experiment-missing-proof'
        create_project(root, ROOT, git_backed=True)
        install_controlled_change(root, 'CHG-9049', status='approved', lifecycle_enforcement='controlled_v3')
        _mark_experiment(root, 'CHG-9049')
        (root / 'specforge/evidence/informed-approvals/PRES-9049.yaml').unlink()
        assert run(root).returncode != 0, 'experiment classification must not bypass informed-approval evidence'

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'experiment-incomplete-completion'
        create_project(root, ROOT, git_backed=True)
        install_controlled_change(root, 'CHG-9050', status='completed', attempt=False, lifecycle_enforcement='controlled_v3')
        _mark_experiment(root, 'CHG-9050')
        assert run(root).returncode != 0, 'experiment classification must not make an unevidenced completion valid'

_chg1046_experiment_classification_contract()


# CHG-1054: bounded historical-evidence compatibility.
def _chg1054_historical_compatibility_contract():
    project_root = ROOT.parent.parent
    if (project_root / "specforge/changes/CHG-1053.yaml").is_file():
        real = run(project_root, '--change', 'CHG-1053')
        real_output = real.stdout + real.stderr
        assert "Schema validation failed for specforge/changes/CHG-1053/PROP-1053-01.yaml at declared_scope" not in real_output, real_output
        assert "controlled_v3 approval proof proposal binding mismatch in specforge/changes/CHG-1052/approvals/APR-1056.yaml" not in real_output, real_output
        assert "controlled_v3 approval proof proposal binding mismatch in specforge/changes/CHG-1053/approvals/APR-1057.yaml" not in real_output, real_output
        assert "controlled_v3 implementation predates approval in specforge/changes/CHG-1053/implementation/IMP-1053-01.yaml" not in real_output, real_output
        assert "Checkpoint acceptance proof chronology invalid in specforge/history/acceptance-proofs/CAP-0006.yaml" not in real_output, real_output

    def make_legacy_fixture(root):
        create_project(root, ROOT, git_backed=True)
        state = install_controlled_change(root, 'CHG-9060', status='approved', lifecycle_enforcement='controlled_v3')
        proof = root / 'specforge/evidence/informed-approvals/PRES-9060.yaml'
        proof_data = yaml.safe_load(proof.read_text(encoding='utf-8'))
        proof_data.pop('type', None)
        write_yaml(proof, proof_data)
        git(root, 'add', 'specforge/changes', 'specforge/evidence')
        git(root, 'commit', '-m', 'legacy proof fixture')
        proof_digest = canonical_digest(proof)
        hec = root / 'specforge/evidence/historical-compatibility/HEC-9060.yaml'
        write_yaml(hec, {
            'id': 'HEC-9060', 'type': 'historical_evidence_compatibility', 'change': 'CHG-9060', 'version': 1,
            'created_at': '2099-01-02T00:00:00+00:00', 'effective_before': '2099-01-01T00:00:00+00:00',
            'rules': [{
                'id': 'HEC-9060-R01', 'issue': 'legacy_approval_proof_missing_type', 'status': 'active',
                'target': {'id': 'PRES-9060', 'path': 'specforge/evidence/informed-approvals/PRES-9060.yaml', 'sha256': proof_digest},
                'allowed_difference': 'Only the historical type marker is absent.',
                'evidence': {'approval': state['approval'], 'proposal': state['proposal'], 'expected_missing_field': 'type', 'expected_type_value': 'informed_approval_proof'},
            }],
        })
        git(root, 'add', str(hec.relative_to(root)))
        git(root, 'commit', '-m', 'register bounded historical proof compatibility')
        return state, proof, hec

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'legacy-proof'
        make_legacy_fixture(root)
        expect_pass(root, 'registered exact legacy missing-type proof should validate')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'stale-digest'
        _, _, hec = make_legacy_fixture(root)
        data = yaml.safe_load(hec.read_text(encoding='utf-8'))
        data['rules'][0]['target']['sha256'] = '0' * 64
        write_yaml(hec, data)
        expect_fail(root, 'Historical compatibility target digest mismatch', 'stale compatibility digest fails closed')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'wrong-target'
        _, _, hec = make_legacy_fixture(root)
        data = yaml.safe_load(hec.read_text(encoding='utf-8'))
        data['rules'][0]['target']['id'] = 'PRES-WRONG'
        write_yaml(hec, data)
        expect_fail(root, 'controlled_v3 approval proof proposal binding mismatch', 'wrong compatibility target does not suppress proof error')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'malformed-hec'
        _, _, hec = make_legacy_fixture(root)
        data = yaml.safe_load(hec.read_text(encoding='utf-8'))
        data.pop('effective_before')
        write_yaml(hec, data)
        expect_fail(root, 'Historical compatibility schema validation failed', 'malformed HEC evidence fails closed')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'unregistered-legacy'
        _, _, hec = make_legacy_fixture(root)
        hec.unlink()
        expect_fail(root, 'controlled_v3 approval proof proposal binding mismatch', 'unregistered legacy-shaped proof still fails')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'current-strict'
        _, _, hec = make_legacy_fixture(root)
        data = yaml.safe_load(hec.read_text(encoding='utf-8'))
        data['effective_before'] = '2000-01-01T00:00:00+00:00'
        write_yaml(hec, data)
        expect_fail(root, 'Historical compatibility target is not historical before cutoff', 'current evidence cannot opt into HEC')

_chg1054_historical_compatibility_contract()


# CHG-1054 rev2: active_with_notes is exact-target, noted, and fail-closed.
def _chg1054_active_with_notes_contract():
    import jsonschema as _jsonschema
    schema = json.loads((ROOT / 'schemas/historical-evidence-compatibility.schema.json').read_text(encoding='utf-8'))
    validator = _jsonschema.Draft202012Validator(schema)
    base_rule = {
        'id': 'HEC-9999-R01', 'issue': 'checkpoint_creation_chronology', 'status': 'active_with_notes',
        'target': {'id': 'CAP-9999', 'path': 'specforge/history/acceptance-proofs/CAP-9999.yaml', 'sha256': '0' * 64},
        'allowed_difference': 'fixture', 'evidence': {},
    }
    registry = {
        'id': 'HEC-9999', 'type': 'historical_evidence_compatibility', 'change': 'CHG-9999', 'version': 1,
        'created_at': '2099-01-02T00:00:00+00:00', 'effective_before': '2099-01-01T00:00:00+00:00',
        'rules': [base_rule],
    }
    assert list(validator.iter_errors(registry)), 'active_with_notes must require a permanent note'
    registry['rules'][0]['notes'] = 'ALLOW WITH NOTES: chronology cannot now be reconstructed.'
    assert not list(validator.iter_errors(registry)), 'noted active_with_notes shape should satisfy the closed schema'

    project_root = ROOT.parent.parent
    if not (project_root / 'specforge/evidence/historical-compatibility/HEC-0001.yaml').is_file():
        return
    with tempfile.TemporaryDirectory() as td:
        clone = Path(td) / 'repo'
        r = subprocess.run(['git', 'clone', '--local', str(project_root), str(clone)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        hec = clone / 'specforge/evidence/historical-compatibility/HEC-0001.yaml'
        original = yaml.safe_load(hec.read_text(encoding='utf-8'))

        contradictory = yaml.safe_load(yaml.safe_dump(original))
        contradictory['rules'][3]['evidence']['contradictory_provider_evidence_found'] = True
        write_yaml(hec, contradictory)
        expect_fail(clone, 'Checkpoint acceptance proof chronology invalid in specforge/history/acceptance-proofs/CAP-0006.yaml', 'contradictory chronology evidence fails closed', '--change', 'CHG-1054')

        wrong_target = yaml.safe_load(yaml.safe_dump(original))
        wrong_target['rules'][3]['target']['id'] = 'CAP-WRONG'
        write_yaml(hec, wrong_target)
        expect_fail(clone, 'Checkpoint acceptance proof chronology invalid in specforge/history/acceptance-proofs/CAP-0006.yaml', 'wrong active-with-notes target fails closed', '--change', 'CHG-1054')

        blocked = yaml.safe_load(yaml.safe_dump(original))
        blocked['rules'][3]['status'] = 'blocked'
        write_yaml(hec, blocked)
        expect_fail(clone, 'Checkpoint acceptance proof chronology invalid in specforge/history/acceptance-proofs/CAP-0006.yaml', 'unregistered or inactive chronology gap remains invalid', '--change', 'CHG-1054')

        write_yaml(hec, original)
        expect_pass(clone, 'exact CAP-0006 active-with-notes compatibility validates', '--change', 'CHG-1054')

_chg1054_active_with_notes_contract()


# CHG-1057: full-validator lifecycle progress is bounded, monotonic and visible
# through the existing structured progress contract.
def _chg1057_lifecycle_progress_contract():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'progress-contract'
        create_project(root, ROOT, git_backed=True)
        for number in range(9100, 9115):
            install_controlled_change(
                root,
                f'CHG-{number}',
                status='awaiting_approval',
                skip_approval=True,
                lifecycle_enforcement='controlled_v3',
            )
        progress = Path(td) / 'progress.jsonl'
        result = run(root, '--progress-file', progress)
        assert result.returncode == 0, result.stdout + result.stderr
        rows = [
            json.loads(line)
            for line in progress.read_text(encoding='utf-8').splitlines()
            if line.strip()
        ]
        lifecycle = [row for row in rows if row.get('phase') == 'lifecycle_validation']
        assert len(lifecycle) >= 3, lifecycle
        total = lifecycle[0]['total']
        assert lifecycle[0]['processed'] == 0, lifecycle
        assert lifecycle[-1]['processed'] == total, lifecycle
        assert any(0 < row['processed'] < total for row in lifecycle), lifecycle
        assert any(
            str(row.get('substage') or '').startswith('checking governed change ')
            for row in lifecycle
        ), lifecycle
        processed = [row['processed'] for row in lifecycle]
        assert processed == sorted(processed), processed
        assert all(0 <= value <= total for value in processed), processed
        assert len(lifecycle) <= 22, 'lifecycle progress must stay bounded rather than emit once per record'
        stderr_rows = [
            line for line in result.stderr.splitlines()
            if line.startswith('SPECFORGE_PROGRESS ')
        ]
        assert stderr_rows, 'structured progress must be relayed to stderr when a progress file is active'


_chg1057_lifecycle_progress_contract()
