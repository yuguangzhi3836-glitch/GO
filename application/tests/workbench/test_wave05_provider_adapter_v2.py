from go_hotel.core.provider_adapter_contract_v2 import VERTICAL_PROFILES, validate_provider_adapter_contract_v2
from go_hotel.connectors.provider_adapter_contract import ProviderContractError


def completed(vertical: str):
    profile=VERTICAL_PROFILES[vertical]
    return {
      'vertical': vertical,
      'provider': {'provider_code':f'TEST_{vertical}','supplier_legal_name':'Sandbox Supplier Legal Entity','environment':'SANDBOX'},
      'contract_source': {'authority':'SIGNED_SUPPLIER_DOCUMENTATION','documentation_reference':'contract://signed-docs/v1','documentation_version':'v1','documentation_hash':'a'*64},
      'transport': {'base_url':'https://sandbox.supplier.example','auth':{'method':'BEARER','credential_reference':f'vault://providers/{vertical.lower()}/sandbox'},'ip_allowlist_reference':'allowlist://controlled-egress'},
      'operations': {op:{'method':'POST' if op not in {'query','search'} else 'GET','path':f'/contracted/{op}','request_mapping':{'go':'supplier'},'response_mapping':{'supplier':'go'}} for op in profile['operations']},
      'canonical_mapping': {section:{'supplier_field':'go_field'} for section in profile['canonical']},
      'webhook': {'callback_path':f'/internal/providers/{vertical.lower()}/webhook','event_mapping':{'supplier.event':'GO_EVENT'},'signature':{'scheme':'HMAC_SHA256','signature_header':'X-Signature','timestamp_header':'X-Timestamp','secret_reference':f'vault://providers/{vertical.lower()}/webhook','replay_tolerance_seconds':300}},
      'error_mapping': {'supplier_to_go':{'TIMEOUT':'UPSTREAM_TIMEOUT'},'unknown_error_policy':'FAIL_CLOSED'},
      'limits': {'requests_per_second':5,'max_concurrency':10,'connect_timeout_ms':3000,'read_timeout_ms':5000,'max_attempts':3,'retryable_go_errors':['UPSTREAM_TIMEOUT']},
      'attestation': {'contract_reference':f'contract://{vertical.lower()}/sandbox','sandbox_account_reference':'sandbox-account://provider','test_entity_reference':f'supplier-test://{vertical.lower()}/entity','authorized_scope':['SANDBOX_READINESS'],'evidence_references':['evidence://signed-docs'],'prepared_by':'go-platform','prepared_at':'2026-08-31T18:40:00+08:00','external_transport_verified':False},
    }


def test_all_six_vertical_profiles_are_readiness_only():
    assert set(VERTICAL_PROFILES) == {'HOTEL','FLIGHT','RAIL','RENTAL','RIDE','ATTRACTION'}
    for vertical in VERTICAL_PROFILES:
        n=validate_provider_adapter_contract_v2(completed(vertical))
        assert n['vertical'] == vertical
        assert n['production_live'] is False
        assert n['external_transport_verified'] is False
        assert n['readiness_state'] == 'PROVIDER_CONTRACT_READY_NOT_EXTERNALLY_VERIFIED'


def test_inline_provider_secret_is_rejected():
    bad=completed('FLIGHT')
    bad['transport']['auth']['token']='inline-forbidden'
    try:
        validate_provider_adapter_contract_v2(bad)
        assert False
    except ProviderContractError as exc:
        assert str(exc) == 'INLINE_SECRET_FORBIDDEN'


def test_unknown_supplier_error_policy_must_fail_closed():
    bad=completed('RAIL')
    bad['error_mapping']['unknown_error_policy']='ALLOW'
    try:
        validate_provider_adapter_contract_v2(bad)
        assert False
    except ProviderContractError as exc:
        assert str(exc) == 'UNKNOWN_ERROR_MUST_FAIL_CLOSED'
