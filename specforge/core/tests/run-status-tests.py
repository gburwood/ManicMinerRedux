#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, subprocess, sys, tempfile, yaml

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_fixture import create_project, install_controlled_change

def run(root, *args):
    tool = root / 'specforge/core/tools/specforge-status.py'
    return subprocess.run([sys.executable, '-B', str(tool), '--root', str(root), *args], capture_output=True, text=True)

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

with tempfile.TemporaryDirectory(prefix='specforge-status-') as td:
    root = Path(td) / 'repo'
    create_project(root, CORE, git_backed=True)
    install_controlled_change(root, 'CHG-9001', status='approved')
    install_controlled_change(root, 'CHG-9002', status='completed')
    install_controlled_change(root, 'CHG-9003', status='approved', lifecycle_enforcement='controlled_v3')
    install_controlled_change(root, 'CHG-9004', status='awaiting_approval', lifecycle_enforcement='controlled_v3', skip_approval=True)
    install_controlled_change(root, 'CHG-9005', status='completed', lifecycle_enforcement='controlled_v3')
    install_controlled_change(root, 'CHG-9006', status='ready_for_checkpoint', lifecycle_enforcement='controlled_v3')
    result = run(root, '--json'); assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    expected_core = yaml.safe_load((CORE / 'core.yaml').read_text(encoding='utf-8'))['core_version']
    assert report['project']['id'] == 'PRJ-PORTABLE'
    assert report['specforge']['core_version'] == expected_core
    assert any(item['id'] == 'CHG-9002' for item in report['changes']['terminal'])
    assert any(item['id'] == 'CHG-9003' for item in report['changes']['open'])
    controlled_v3 = next(item for item in report['changes']['open'] if item['id'] == 'CHG-9003')
    assert controlled_v3['effective_approval']['status'] == 'approved'
    assert controlled_v3['governance_mode'] == 'controlled_v3'
    cont_approval = json.loads(run(root, '--continuation', 'CHG-9004', '--json').stdout)
    assert cont_approval['next_action'] == 'approval' and cont_approval['human_boundary'] is True
    cont_work = json.loads(run(root, '--continuation', 'CHG-9003', '--json').stdout)
    assert cont_work['next_action'] == 'implementation_validation' and cont_work['blocked'] is False
    cont_checkpoint = json.loads(run(root, '--continuation', 'CHG-9006', '--json').stdout)
    assert cont_checkpoint['next_action'] == 'checkpoint_presentation'
    cont_done = json.loads(run(root, '--continuation', 'CHG-9005', '--json').stdout)
    assert cont_done['next_action'] is None and cont_done['blocked'] is False
    continuation_before = digest(root / 'specforge/changes/CHG-9003.yaml')
    assert run(root, '--continuation', 'CHG-9003', '--json').returncode == 0
    assert digest(root / 'specforge/changes/CHG-9003.yaml') == continuation_before
    open_change = next(item for item in report['changes']['open'] if item['id'] == 'CHG-9001')
    assert open_change['current_links']['impact_analysis']['id'] == 'IA-9001-01'
    assert open_change['current_links']['proposal']['id'] == 'PROP-9001-01'
    assert open_change['effective_approval']['status'] == 'approved'
    result = run(root); assert result.returncode == 0, result.stderr
    for token in ('SpecForge project status', 'PRJ-PORTABLE', 'CHG-9001', 'PROP-9001-01', 'APR-9001'):
        assert token in result.stdout, token
    tracked = root / 'specforge/changes/CHG-9001.yaml'; before = digest(tracked)
    assert run(root, '--json').returncode == 0 and digest(tracked) == before
    data = yaml.safe_load(tracked.read_text(encoding='utf-8')); data['impact_analysis']['current'] = 'IA-9999-01'
    tracked.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    broken = json.loads(run(root, '--json').stdout)
    assert 'CHG-9001: Missing impact analysis IA-9999-01' in broken['gaps']
print('Status tests PASSED')

with tempfile.TemporaryDirectory(prefix='specforge-cross-ref-status-') as td:
    root=Path(td)/'repo'
    create_project(root,CORE,git_backed=True)
    baseline=subprocess.run(['git','-C',str(root),'rev-parse','--abbrev-ref','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    subprocess.run(['git','-C',str(root),'checkout','-b','governed-work'],check=True,capture_output=True,text=True)
    install_controlled_change(root,'CHG-9090',status='approved',lifecycle_enforcement='controlled_v3')
    subprocess.run(['git','-C',str(root),'add','specforge/changes'],check=True)
    subprocess.run(['git','-C',str(root),'commit','-m','governed work on other ref'],check=True,capture_output=True,text=True)
    subprocess.run(['git','-C',str(root),'checkout',baseline],check=True,capture_output=True,text=True)
    result=run(root,'--continuation','CHG-9090','--json')
    report=json.loads(result.stdout)
    assert result.returncode==1,report
    assert report['discoverable'] is True and report['blocked'] is True,report
    assert 'explicit_workspace_switch_required' in report['blockers'],report
    assert any('governed-work' in item['refs'] for item in report['candidates']),report
print('PASS cross-ref-continuation-discovery')

# CHG-1052: the guided front door must remain a consumer of canonical continuation.
_managed_1052 = (CORE / 'tools/specforge-managed.py').read_text(encoding='utf-8')
assert 'GUIDE_PROFILE = "guided_non_expert_v1"' in _managed_1052
assert 'def guided_non_expert(' in _managed_1052
assert '_continuation_summary(layout, selected)' in _managed_1052
assert '"ambiguous_continuation"' in _managed_1052
assert '"current_workspace_missing_required_change"' in _managed_1052
