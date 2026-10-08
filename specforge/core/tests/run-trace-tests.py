#!/usr/bin/env python3
from pathlib import Path
import json, subprocess, sys, tempfile, yaml

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_fixture import create_project, install_controlled_change

def run(root, change, *args):
    tool = root / 'specforge/core/tools/specforge-trace.py'
    return subprocess.run([sys.executable, '-B', str(tool), change, *args, '--root', str(root)], capture_output=True, text=True)

with tempfile.TemporaryDirectory(prefix='specforge-trace-') as td:
    root = Path(td) / 'repo'
    baseline = create_project(root, CORE, git_backed=True)
    install_controlled_change(root, 'CHG-9001', status='in_progress', attempt=True, before=baseline['trusted_revision'], after=baseline['head'], outcome='passed')
    result = run(root, 'CHG-9001'); assert result.returncode == 0, result.stderr
    for token in ('CHG-9001', 'IA-9001-01', 'PROP-9001-01', 'APR-9001', 'IMP-9001-01'):
        assert token in result.stdout, token
    result = run(root, 'CHG-9001', '--json'); assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['change']['id'] == 'CHG-9001'
    assert report['implementation_attempts'][0]['id'] == 'IMP-9001-01'
    result = run(root, 'CHG-9999'); assert result.returncode != 0 and 'Unknown change' in result.stderr
    change_path = root / 'specforge/changes/CHG-9001.yaml'
    change = yaml.safe_load(change_path.read_text(encoding='utf-8')); change['approvals'] = ['APR-9999']
    change_path.write_text(yaml.safe_dump(change, sort_keys=False), encoding='utf-8')
    result = run(root, 'CHG-9001')
    assert result.returncode == 0 and 'Missing approval APR-9999' in result.stdout
print('Trace tests PASSED')
