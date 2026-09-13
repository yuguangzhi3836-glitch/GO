from go_hotel.services.phase1_closure import phase1_closure_service as svc
def test_all_day_one_verticals_share_required_capability_contract():
 m=svc.capability_matrix();assert len(m['verticals'])==6 and all(len(x['capabilities'])==11 for x in m['verticals']) and not m['production_live']
def test_direct_first_wins_even_when_fallback_is_present():
 r=svc.select_source('HOTEL',[{'source_id':'f','source_type':'AUTHORIZED_FALLBACK','authorized':True,'available':True,'evidence_reference':'contract://f'},{'source_id':'d','source_type':'HOTEL_OFFICIAL_DIRECT','authorized':True,'available':True,'evidence_reference':'hotel://d'}]);assert r['selected_source_id']=='d' and r['route']=='OFFICIAL_DIRECT'
def test_fallback_requires_authority_availability_and_evidence():
 r=svc.select_source('FLIGHT',[{'source_id':'x','source_type':'AUTHORIZED_FALLBACK','authorized':True,'available':True,'evidence_reference':None}]);assert r['route']=='UNAVAILABLE' and not r['silent_fallback']
def test_evidence_policy_forbids_timeout_resend_and_mock_success():
 p=svc.evidence_policy();assert 'TIMEOUT_RESEND' in p['forbidden'] and 'MOCK_SUCCESS' in p['forbidden']
