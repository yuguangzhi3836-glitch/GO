from go_hotel.services.rc20_module_depth import readiness


def test_rc20_requires_five_real_dimensions_for_every_vertical():
    data = readiness()
    assert data['release_target'] == 'RC20'
    assert [x['dimension'] for x in data['pass_dimensions']] == [
        'NORMAL_PATH','EXCEPTION_RECOVERY','STATE_MACHINE','EVIDENCE_CHAIN','HUMAN_OPERABLE'
    ]
    assert len(data['verticals']) == 6
    for v in data['verticals']:
        assert len(v['dimensions']) == 5
        assert all(d['requirements'] for d in v['dimensions'])
        assert v['rc20_pass_state'] == 'STAGING_E2E_REQUIRED'
        assert v['external_live_state'] == 'PROVIDER_REQUIRED'


def test_rc20_does_not_equate_code_or_gate_with_external_live():
    data = readiness()
    assert '不得标记 LIVE' in data['external_live_note']
    assert data['overall_state'].endswith('STAGING_E2E_REQUIRED')
