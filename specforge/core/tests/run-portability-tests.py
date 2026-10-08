#!/usr/bin/env python3
from pathlib import Path
import json, os, subprocess, sys, tempfile

CORE = Path(__file__).resolve().parents[1]
TESTS = CORE / 'tests'
sys.path.insert(0, str(TESTS))
from portable_fixture import create_project

TARGETS = sorted(path.name for path in TESTS.glob('run-*-tests.py') if path.name != 'run-portability-tests.py')
if 'run-integration-evidence-tests.py' not in TARGETS:
    raise AssertionError('integration evidence regression runner missing from distributed Core')
if not (CORE / 'schemas/checkpoint-acceptance-proof.schema.json').is_file():
    raise AssertionError('CHG-1034 CAP schema missing from distributed Core')
core_meta = __import__('yaml').safe_load((CORE / 'core.yaml').read_text(encoding='utf-8'))
if core_meta.get('core_version') != '0.1.0-beta.1' or core_meta.get('data_model_version') != '0.1.0-alpha.10':
    raise AssertionError('beta.1 current distribution identity missing')
if (core_meta.get('managed_completion') or {}).get('profile') != 'managed_completion_guard_v3':
    raise AssertionError('CHG-1035 managed completion guard v3 not advertised')
if (core_meta.get('managed_progress') or {}).get('profile') != 'managed_progress_v1':
    raise AssertionError('CHG-1039 managed progress v1 not advertised')
if (core_meta.get('integrity') or {}).get('routine_profile') != 'incremental_integrity_v1':
    raise AssertionError('CHG-1040 incremental integrity v1 not advertised')
if (core_meta.get('integrity') or {}).get('full_profile') != 'full_integrity_v1':
    raise AssertionError('CHG-1040 full integrity v1 not advertised')
if 'run-incremental-integrity-tests.py' not in TARGETS:
    raise AssertionError('CHG-1040 incremental integrity regression runner missing')

with tempfile.TemporaryDirectory(prefix='specforge-portability-') as td:
    host = Path(td) / 'minimal-host'
    create_project(host, CORE, git_backed=True)

    # CHG-1045: assurance capability reporting is explicit and fail-closed.
    managed = host / 'specforge/core/tools/specforge-managed.py'
    env = dict(os.environ)
    env.pop('SPECFORGE_EXECUTION_CAPABILITIES', None)
    missing = subprocess.run(
        [sys.executable, '-B', str(managed), 'capabilities', '--root', str(host), '--require', 'workflow_dispatch', '--json'],
        cwd=host, env=env, capture_output=True, text=True
    )
    if missing.returncode == 0:
        raise AssertionError('missing workflow_dispatch capability was reported as available')
    missing_out = json.loads(missing.stdout)
    if missing_out.get('permitted') is not False or 'execution_channel_capability_unavailable:workflow_dispatch' not in missing_out.get('blockers', []):
        raise AssertionError('workflow_dispatch capability blocker is not deterministic')

    env['SPECFORGE_EXECUTION_CAPABILITIES'] = 'python_runtime,workflow_dispatch'
    available = subprocess.run(
        [sys.executable, '-B', str(managed), 'capabilities', '--root', str(host),
         '--require', 'workflow_dispatch', '--require', 'python_runtime', '--json'],
        cwd=host, env=env, capture_output=True, text=True
    )
    if available.returncode:
        raise AssertionError(f'advertised execution capabilities were rejected\n{available.stdout}\n{available.stderr}')
    available_out = json.loads(available.stdout)
    if available_out.get('permitted') is not True:
        raise AssertionError('advertised execution capabilities were not permitted')
    print('PASS dogfood-s04-unavailable-workflow-dispatch-blocks')
    print('PASS helpdesk-s11-host-portable-capability-reporting')

    for name in TARGETS:
        script = host / 'specforge/core/tests' / name
        result = subprocess.run([sys.executable, '-B', str(script)], cwd=host, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(f'{name} failed in minimal independent host\n{result.stdout}\n{result.stderr}')
        print('PASS minimal-host-' + name.removeprefix('run-').removesuffix('.py'))

print('Portability regression tests PASSED')

assert (CORE / 'docs/specforge-core-product-spec-0.1.0-alpha.26.md').is_file()
assert (CORE / 'docs/specforge-core-canonical-data-model-0.1.0-alpha.11.md').is_file()
_schema=(CORE/'schemas/proposal.schema.json').read_text(encoding='utf-8')
assert 'context_only' in _schema and 'durable_update' in _schema

# CHG-1048 regression: historical reconciliation records may omit definition_format_version.
def _chg1048_historical_omission_contract():
    import json as _json
    from pathlib import Path as _Path
    import jsonschema as _jsonschema
    _schema=_json.loads((_Path(__file__).resolve().parents[1]/"schemas"/"proposal.schema.json").read_text(encoding="utf-8"))
    _proposal={"id":"PROP-9997-01","change":"CHG-9997","revision":1,"status":"draft","behaviour_summary":"historical fixture","project_definition_reconciliation":{"path":"PROJECT.md","sha256":"0"*64,"request_digest":"sha256:"+"1"*64,"change":"CHG-9997"}}
    _jsonschema.Draft202012Validator(_schema).validate(_proposal)
_chg1048_historical_omission_contract()
