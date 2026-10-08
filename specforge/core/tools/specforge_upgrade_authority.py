from specforge_authority import current_identity, load_authority, material_differences, material_snapshot, save_authority


def establish_upgrade_authority(layout, current, target):
    identity = current_identity(layout)
    authority = load_authority(layout) or {'version': 1, 'trusted': identity}
    trusted = authority.get('trusted') or {}
    provider = str(trusted.get('provider') or '').lower().replace('-', '_')
    revision = trusted.get('revision')
    if provider != identity['provider'] or not revision:
        raise RuntimeError('trusted_material_baseline_does_not_match_current_clean_state')
    if provider == 'git':
        if material_differences(layout, 'git', revision):
            raise RuntimeError('trusted_material_baseline_does_not_match_current_clean_state')
    elif material_snapshot(layout)['revision'] != revision:
        raise RuntimeError('trusted_material_baseline_does_not_match_current_clean_state')
    authority['active_operation'] = {
        'type': 'core_upgrade',
        'id': f'core-{current}-to-{target}',
        'provider': provider,
        'before': revision,
        'from_core_version': current,
        'to_core_version': target,
        'scope': 'framework_core_and_manifest',
    }
    save_authority(layout, authority)
    return authority['active_operation']
