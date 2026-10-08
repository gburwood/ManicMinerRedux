#!/usr/bin/env python3
from pathlib import Path
import hashlib, shutil, subprocess, sys, yaml


def write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8', newline='\n')


def canonical_digest(path):
    text = path.read_bytes().decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def git(root, *args, check=True):
    r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return r


def create_project(dst, core_root, git_backed=True, declared_core_version=None, declared_data_model_version=None,
                    self_referencing_product_specification=False, self_referencing_canonical_data_model=False,
                    material_roots=None, initialize_governance_tier=False):
    dst.mkdir(parents=True, exist_ok=True)
    sf = dst / 'specforge'
    for rel in ('packs', 'changes', 'decisions', 'history', 'evidence'):
        (sf / rel).mkdir(parents=True, exist_ok=True)
    shutil.copytree(core_root, sf / 'core', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', '.pytest_cache'))
    meta = yaml.safe_load((sf / 'core/core.yaml').read_text(encoding='utf-8'))
    core_version = declared_core_version or meta['core_version']
    data_model = declared_data_model_version or meta['data_model_version']
    if declared_core_version or declared_data_model_version:
        meta['core_version'] = core_version
        meta['data_model_version'] = data_model
        write_yaml(sf / 'core/core.yaml', meta)
        package_path = sf / 'core/package.yaml'
        package = yaml.safe_load(package_path.read_text(encoding='utf-8'))
        package['package']['version'] = core_version
        write_yaml(package_path, package)
    if self_referencing_product_specification:
        product_specification = f'./specforge/core/docs/specforge-core-product-spec-{core_version}.md'
        current_version = core_version
    else:
        product_specification = './product.txt'
        current_version = '1.0.0'
    canonical_data_model = (
        f'./specforge/core/docs/specforge-core-canonical-data-model-{data_model}.md'
        if self_referencing_canonical_data_model else './model.txt'
    )
    manifest = {
        'specforge': {'project_format': 1, 'core_version': core_version, 'data_model_version': data_model},
        'project': {'id': 'PRJ-PORTABLE', 'name': 'Portable Core Test Fixture'},
        'specification': {
            'product_specification': product_specification,
            'canonical_data_model': canonical_data_model,
            'current_version': current_version,
        },
        'paths': {
            'core': './specforge/core', 'packs': './specforge/packs', 'schemas': './specforge/core/schemas',
            'rules': './specforge/core/rules', 'workflows': './specforge/core/workflows', 'tools': './specforge/core/tools',
            'tests': './specforge/core/tests', 'examples': './specforge/core/examples', 'changes': './specforge/changes',
            'decisions': './specforge/decisions', 'history': './specforge/history', 'evidence': './specforge/evidence',
        },
        'packs': [],
        'ownership': {
            'framework_owned': ['./specforge/core', './specforge/packs'],
            'project_owned': ['./specforge/project.yaml', './specforge/changes', './specforge/decisions', './specforge/history', './specforge/evidence'],
        },
        'policy': {
            'approval_mode': 'controlled', 'emergency_changes': 'allowed', 'trivial_change_exemption': 'allowed',
            'forensic_traceability': 'required', 'repository_completeness': 'required',
        },
    }
    if material_roots is not None:
        manifest['material'] = {'mode': 'explicit_v1', 'roots': list(material_roots)}
    write_yaml(sf / 'project.yaml', manifest)
    (sf / 'SPECFORGE.md').write_text('# Portable SpecForge test fixture\n', encoding='utf-8', newline='\n')
    (dst / 'product.txt').write_text('one\n', encoding='utf-8', newline='\n')
    (dst / 'model.txt').write_text('model\n', encoding='utf-8', newline='\n')
    (dst / 'README.md').write_text('portable fixture\n', encoding='utf-8', newline='\n')
    if initialize_governance_tier:
        tool = sf / 'core/tools/specforge-governance-tier.py'
        result = subprocess.run(
            [sys.executable, '-B', str(tool), 'initialize', '--root', str(dst), '--json'],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise AssertionError('fresh governance-tier initialization failed:\n' + result.stdout + result.stderr)
    if not git_backed:
        return {'trusted_revision': None, 'head': None}
    git(dst, 'init')
    git(dst, 'config', 'user.email', 'fixture@example.invalid')
    git(dst, 'config', 'user.name', 'Portable Fixture')
    git(dst, 'add', '.')
    git(dst, 'commit', '-m', 'fixture material baseline')
    trusted = git(dst, 'rev-parse', 'HEAD').stdout.strip()
    write_yaml(sf / 'evidence/material-authority.yaml', {'version': 1, 'trusted': {'provider': 'git', 'revision': trusted}})
    git(dst, 'add', 'specforge/evidence/material-authority.yaml')
    git(dst, 'commit', '-m', 'record trusted material baseline')
    return {'trusted_revision': trusted, 'head': git(dst, 'rev-parse', 'HEAD').stdout.strip()}


def install_pack_copy(root, source_pack, precedence=10):
    source_pack = Path(source_pack)
    meta = yaml.safe_load((source_pack / 'pack.yaml').read_text(encoding='utf-8'))
    target = root / 'specforge/packs' / meta['id']
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source_pack, target)
    manifest_path = root / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    entry = {
        'id': meta['id'],
        'version': str(meta['version']),
        'path': f"./specforge/packs/{meta['id']}",
        'precedence': precedence,
        'extensions': list(meta.get('extensions') or []),
    }
    manifest['packs'] = [item for item in manifest.get('packs', []) if item.get('id') != meta['id']]
    manifest['packs'].append(entry)
    write_yaml(manifest_path, manifest)
    return entry


def install_controlled_change(
    root,
    change_id='CHG-9001',
    status='approved',
    attempt=False,
    before=None,
    after=None,
    outcome='in_progress',
    integration=None,
    verification_profile=None,
    lifecycle_enforcement='controlled_v1',
    declared_scope=None,
    governance_tier=None,
    artifacts_expected=None,
    skip_approval=False,
    approval_timestamp='2026-01-01T00:00:00+00:00',
    implementation_started_at='2026-01-01T00:00:01+00:00',
):
    number = change_id.split('-')[-1]
    ia_id = f'IA-{number}-01'
    prop_id = f'PROP-{number}-01'
    apr_id = f'APR-{number}'
    imp_id = f'IMP-{number}-01'
    base = root / 'specforge/changes'
    write_yaml(base / change_id / f'{ia_id}.yaml', {
        'id': ia_id, 'change': change_id, 'revision': 1,
        'affected': {'capabilities': ['portable-test']},
        'summary': 'Portable synthetic impact analysis.'
    })
    prop_path = base / change_id / f'{prop_id}.yaml'
    proposal = {
        'id': prop_id, 'change': change_id, 'revision': 1, 'status': 'awaiting_approval',
        'based_on_impact_analysis': [ia_id], 'proposed_specification_version': '1.0.1',
        'behaviour_summary': 'Portable synthetic governed change.',
        'requirement_changes': {'add': [], 'modify': [], 'deprecate': [], 'supersede': []},
        'acceptance_criteria': {'add': [{'id': f'AC-{number}-01', 'text': 'Portable fixture criterion.'}]},
        'approvals': [],
    }
    if declared_scope is not None:
        proposal['declared_scope'] = declared_scope
    if governance_tier is not None:
        proposal['governance_tier'] = governance_tier
    if artifacts_expected is not None:
        proposal['artifacts_expected'] = artifacts_expected
    write_yaml(prop_path, proposal)
    digest = canonical_digest(prop_path)
    if not skip_approval:
        evidence = {'proposal_digest_algorithm': 'sha256', 'proposal_digest': digest, 'proposal_identity': prop_id}
        if lifecycle_enforcement == 'controlled_v3':
            proof = root / 'specforge/evidence/informed-approvals' / f'PRES-{number}.yaml'
            write_yaml(proof, {
                'type': 'informed_approval_proof',
                'proposal': prop_id,
                'proposal_digest': digest,
                'change': change_id,
                'presentation': f'PRES-{number}',
                'session': f'SESSION-{number}',
                'presented_at': '2025-12-31T23:59:59+00:00',
                'decision': 'approved',
                'approval_text': 'Yes',
                'actor': {'type': 'human', 'id': 'fixture-product-owner'},
                'received_at': approval_timestamp,
            })
            evidence['informed_approval_proof'] = str(proof.relative_to(root)).replace('\\', '/')
            evidence['received_at'] = approval_timestamp
        write_yaml(base / change_id / 'approvals' / f'{apr_id}.yaml', {
            'id': apr_id, 'change': change_id, 'proposal': prop_id, 'decision': 'approved',
            'actor': {'type': 'human', 'id': 'fixture-product-owner'},
            'timestamp': approval_timestamp,
            'scope': {'proposed_specification_version': '1.0.1', 'proposal_sha256': digest},
            'evidence': evidence,
            'mechanism': {'type': 'test_fixture', 'reference': 'portable-governance'},
        })
    attempts = [imp_id] if attempt else []
    write_yaml(base / f'{change_id}.yaml', {
        'id': change_id, 'title': 'Portable synthetic change', 'classification': 'defect',
        'status': status, 'priority': 'normal',
        'sources': [{'type': 'manual', 'reference': 'portable-test'}],
        'request': {'summary': 'Portable synthetic governed change.'},
        'clarification': {'required': False},
        'relationships': {'depends_on': [], 'conflicts_with': [], 'related_to': [], 'supersedes': [], 'parent': None, 'children': []},
        'impact_analysis': {'current': ia_id}, 'proposal': {'current': prop_id},
        'approvals': [] if skip_approval else [apr_id],
        'implementation': {'attempts': attempts}, 'requirements': {'affected': []}, 'release': {'completed_in': None},
        'governance': {'lifecycle_enforcement': lifecycle_enforcement, 'enforced_from_change': change_id},
    })
    if attempt:
        src = {'system': 'git'}
        if before is not None:
            src['before'] = before
        if after is not None:
            src['after'] = after
        if verification_profile is not None:
            src['verification_profile'] = verification_profile
        record = {
            'id': imp_id, 'change': change_id, 'proposal': prop_id, 'attempt': 1,
            'started_at': implementation_started_at,
            'actor': {'type': 'ai', 'id': 'portable-fixture'},
            'source_revision': src,
            'outcome': outcome,
            'validation_checks': [{
                'name': 'portable-fixture-validation',
                'required': True,
                'status': 'passed' if outcome == 'passed' else 'blocked'
            }],
            'tests': {
                'status': 'passed' if outcome == 'passed' else 'blocked',
                'passed': ['portable-fixture'] if outcome == 'passed' else [],
                'failed': []
            },
        }
        if integration is not None:
            record['integration'] = integration
        write_yaml(base / change_id / 'implementation' / f'{imp_id}.yaml', record)
    return {
        'change': change_id,
        'impact': ia_id,
        'proposal': prop_id,
        'approval': apr_id,
        'attempt': imp_id,
        'proposal_path': prop_path,
    }


def write_governance_tier_activation(root, proposal_digests=None, enforcement_profile='deterministic_tier_v1'):
    """Directly write a pre-activated governance_tier state, bypassing the activate() ceremony.

    For fixtures that need an already-active project as a given precondition, without
    constructing a full authorizing change each time. Returns the grandfather digest written.
    """
    evidence_path = root / 'specforge/evidence/governance-tier-grandfather.yaml'
    write_yaml(evidence_path, {
        'version': 1,
        'captured_at': '2026-01-01T00:00:00+00:00',
        'authorizing_change': 'CHG-9000',
        'proposal_digests': sorted(proposal_digests or []),
    })
    grandfather_digest = canonical_digest(evidence_path)
    manifest_path = root / 'specforge/project.yaml'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    manifest['governance_tier'] = {
        'enforcement_profile': enforcement_profile,
        'grandfather_digest': grandfather_digest,
    }
    write_yaml(manifest_path, manifest)
    return grandfather_digest


def write_policy_archive(root, policy_path):
    """Archive a policy file exactly as archive_policy() would, for fixtures that need a
    pre-existing archive without running prepare()."""
    digest = canonical_digest(policy_path)
    archive_root = root / 'specforge/evidence/governance-tier-policy'
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / f'{digest}.yaml'
    text = policy_path.read_bytes().decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    target.write_text(text, encoding='utf-8', newline='\n')
    return digest


def persist_snapshot_manifest(root, entries):
    """Write a pre-existing material-manifest evidence file for a synthetic set of
    path/digest entries, for fixtures that need completion-time diffing without going
    through a real capture(). The digest key is computed the same way material_snapshot()
    computes it, matching read_material_manifest()'s own integrity recomputation exactly.
    """
    manifest_bytes = ''.join(f"{e['path']}\0{e['sha256']}\n" for e in sorted(entries, key=lambda e: e['path'])).encode('utf-8')
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    target = root / 'specforge/evidence/material-manifests' / f'{digest}.yaml'
    write_yaml(target, {'revision': f'sha256:{digest}', 'entries': entries})
    return digest
