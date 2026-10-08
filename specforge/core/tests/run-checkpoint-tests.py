#!/usr/bin/env python3
from pathlib import Path
import importlib.util, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('specforge_checkpoint',ROOT/'tools/specforge-checkpoint.py')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
assert module.change_set_digest(['CHG-0002','CHG-0001'])==module.change_set_digest(['CHG-0001','CHG-0002'])
assert module._validation_passes({'validation':[{'requirement':'review','status':'passed'}]},['review'])==[]
assert module._validation_passes({'validation':[]},['inspection'])==['checkpoint_validation_missing:inspection']
assert hasattr(module,'finalise_prospective')
assert hasattr(module,'_pfa_preflight')
assert hasattr(module,'integrity_checkpoint_status')
original_load=module.load_authority
original_identity=module.current_identity
original_path=module.authority_path
module.load_authority=lambda layout:{'version':1,'trusted':{'provider':'git','revision':'old'},'active_operation':{'type':'x'}}
module.current_identity=lambda layout:{'provider':'git','revision':'new'}
module.authority_path=lambda layout:Path('/tmp/material-authority.yaml')
checkpoint={
    'candidate':{
        'material':{
            'provider':'specforge_snapshot',
            'revision':'sha256:candidate',
            'file_count':7,
        }
    }
}
acceptance={'timestamp':'2026-10-05T09:40:00Z'}
path,authority,error=module._accepted_authority_update(object(),'CHK-9999','ACC-9999',checkpoint,acceptance)
assert error is None
assert path==Path('/tmp/material-authority.yaml')
assert authority['trusted']=={'provider':'git','revision':'new'}
assert authority['accepted_checkpoint']=={
    'id':'CHK-9999',
    'acceptance':'ACC-9999',
    'candidate_material':{
        'provider':'specforge_snapshot',
        'revision':'sha256:candidate',
        'file_count':7,
    },
    'accepted_at':'2026-10-05T09:40:00Z',
}
assert 'active_operation' not in authority
module.load_authority=original_load
module.current_identity=original_identity
module.authority_path=original_path
doc=(ROOT/'docs/specforge-core-product-spec-0.1.0-alpha.21.md').read_text(encoding='utf-8').lower()
assert 'prospective' in doc and 'pfa' in doc
for forbidden in ('sprint','system test','qa'):
    assert forbidden not in doc
print('Checkpoint tests PASSED')

assert hasattr(module, 'finalise_direct')
assert hasattr(module, '_cap_preflight')
assert (ROOT/'schemas/checkpoint-acceptance-proof.schema.json').is_file()
