#!/usr/bin/env python3
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from go_hotel.connectors.provider_adapter_contract import (
    contains_placeholders,
    validate_provider_adapter_contract,
    ProviderContractError,
)
from go_hotel.connectors.named_provider_adapter import NamedProviderAdapterTemplate

TEMPLATE_DIR = ROOT/'specs/provider_adapters'
required_templates = [
    'tongcheng_sandbox_template.json',
    'agoda_sandbox_template.json',
    'generic_named_supplier_sandbox_template.json',
]


def completed(template: dict) -> dict:
    d = copy.deepcopy(template)
    d.pop('template_status', None)
    d['provider']['supplier_legal_name'] = 'Sandbox Supplier Legal Entity'
    if str(d['provider'].get('provider_code','')).startswith('__'):
        d['provider']['provider_code'] = 'GENERIC_NAMED_SUPPLIER'
    d['contract_source'].update({
        'documentation_reference': 'contract://signed-docs/v1',
        'documentation_version': 'v1',
        'documentation_hash': 'a'*64,
    })
    d['transport']['base_url'] = 'https://sandbox.supplier.example'
    d['transport']['auth'] = {'method':'BEARER','credential_reference':'vault://hotel-supply/sandbox/provider'}
    d['transport']['ip_allowlist_reference'] = 'allowlist://go-hk-staging-egress'
    for name, op in d['operations'].items():
        op['method'] = 'POST' if name in {'quote','book','cancel'} else 'GET'
        op['path'] = f'/contracted/{name}'
        op['request_mapping'] = {'go_input':'supplier_input'}
        op['response_mapping'] = {'supplier_output':'go_output'}
    for section in d['canonical_mapping']:
        d['canonical_mapping'][section] = {'supplier_field':'go_field'}
    d['webhook']['signature'].update({
        'scheme':'HMAC_SHA256',
        'signature_header':'X-Supplier-Signature',
        'timestamp_header':'X-Supplier-Timestamp',
        'secret_reference':'vault://hotel-supply/sandbox/webhook',
    })
    d['webhook']['event_mapping'] = {'supplier.event':'GO_EVENT'}
    d['error_mapping']['supplier_to_go'] = {'SUPPLIER_TIMEOUT':'UPSTREAM_TIMEOUT'}
    d['limits'].update({
        'requests_per_second': 5,
        'max_concurrency': 10,
        'connect_timeout_ms': 3000,
        'read_timeout_ms': 5000,
        'max_attempts': 3,
        'retryable_go_errors': ['UPSTREAM_TIMEOUT','UPSTREAM_RATE_LIMITED'],
    })
    d['attestation'].update({
        'contract_reference':'contract://hotel-supply/sandbox',
        'sandbox_account_reference':'sandbox-account://provider',
        'test_property_reference':'supplier-property://test-hotel-001',
        'evidence_references':['evidence://signed-docs','evidence://credential-approval'],
        'prepared_by':'go-platform',
        'prepared_at':'2026-08-24T03:30:00+08:00',
        'external_transport_verified':False,
    })
    return d

checks = {}
for name in required_templates:
    p = TEMPLATE_DIR/name
    checks[f'template_exists:{name}'] = p.is_file()
    if p.is_file():
        raw = json.loads(p.read_text())
        checks[f'template_incomplete_until_signed_docs:{name}'] = raw.get('template_status') == 'INCOMPLETE_UNTIL_SIGNED_SUPPLIER_DOCUMENTATION' and contains_placeholders(raw)
        checks[f'template_no_invented_transport:{name}'] = str(raw['transport']['base_url']).startswith('__REQUIRED_')
        full = completed(raw)
        try:
            normalized = validate_provider_adapter_contract(full)
            adapter = NamedProviderAdapterTemplate(normalized)
            checks[f'completed_contract_valid:{name}'] = True
            checks[f'operations_ready:{name}'] = all(adapter.prepare(op).url.startswith('https://sandbox.supplier.example/') for op in ('availability','quote','book','query','cancel'))
            checks[f'webhook_fail_closed:{name}'] = adapter.error_contract()['unknown_error_policy'] == 'FAIL_CLOSED'
            checks[f'external_starts_unverified:{name}'] = normalized['external_transport_verified'] is False and normalized['production_live'] is False
        except Exception:
            checks[f'completed_contract_valid:{name}'] = False

# Inline secrets must be rejected.
bad = completed(json.loads((TEMPLATE_DIR/'generic_named_supplier_sandbox_template.json').read_text()))
bad['transport']['auth']['token'] = 'do-not-allow-inline'
try:
    validate_provider_adapter_contract(bad)
    checks['inline_secret_rejected'] = False
except ProviderContractError as exc:
    checks['inline_secret_rejected'] = str(exc) == 'INLINE_SECRET_FORBIDDEN'

service=(ROOT/'src/go_hotel/services/hotel_supply_sandbox.py').read_text()
route=(ROOT/'src/go_hotel/api/routes/hotel_supply_sandbox.py').read_text()
checks.update({
    'service_persists_contract_in_existing_capability_matrix': 'provider_adapter_contract' in service and 'ConnectorCapabilityMatrixRow' in service,
    'service_state_not_external_verified': 'PROVIDER_CONTRACT_READY_NOT_EXTERNALLY_VERIFIED' in service,
    'admin_contract_route_present': '/provider-adapter-contract' in route,
    'admin_readiness_route_present': '/provider-adapter-readiness' in route,
    'payment_out_of_scope': 'payment_scope' in service and 'OUT_OF_SCOPE' in service,
})

for k,v in checks.items():
    print(f'{k}={"PASS" if v else "FAIL"}')
if not all(checks.values()):
    raise SystemExit(1)
print('R8.2_PROVIDER_ADAPTER_CONTRACT_GATE: PASS')
