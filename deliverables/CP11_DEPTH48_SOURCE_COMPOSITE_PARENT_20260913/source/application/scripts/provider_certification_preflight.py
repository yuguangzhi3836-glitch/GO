"""Inspect named sandbox inputs locally; never make a network request."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

REQUIRED = ('STRIPE_TEST_SECRET_KEY', 'SITEMINDER_CHANNELS_PLUS_BASE_URL',
    'SITEMINDER_CHANNELS_PLUS_API_ID', 'SITEMINDER_CHANNELS_PLUS_API_KEY',
    'SITEMINDER_CERT_PROPERTIES_QUERY_JSON', 'SITEMINDER_CERT_PROPERTY_UUID',
    'SITEMINDER_CERT_LOCK_BODY_JSON', 'SITEMINDER_CERT_CONFIRM_BODY_JSON')

def inspect_inputs(values):
    missing = [name for name in REQUIRED if not values.get(name)]
    invalid = []
    key = values.get('STRIPE_TEST_SECRET_KEY', '')
    if key and not key.startswith(('sk_test_', 'rk_test_')):
        invalid.append('STRIPE_TEST_KEY_REQUIRED')
    if values.get('STRIPE_API_BASE', 'https://api.stripe.com').rstrip('/') != 'https://api.stripe.com':
        invalid.append('STRIPE_OFFICIAL_API_REQUIRED')
    base = values.get('SITEMINDER_CHANNELS_PLUS_BASE_URL')
    if base:
        try:
            url = urlsplit(base); host = (url.hostname or '').lower()
            if (url.scheme != 'https' or not host or url.username or url.password or
                url.query or url.fragment or host in ('localhost','::1','0.0.0.0') or
                host.startswith('127.') or host.endswith(('.invalid','.example','.test','.localhost'))):
                invalid.append('SITEMINDER_EXTERNAL_HTTPS_ENDPOINT_REQUIRED')
        except ValueError:
            invalid.append('SITEMINDER_EXTERNAL_HTTPS_ENDPOINT_REQUIRED')
    for name in ('SITEMINDER_CERT_PROPERTIES_QUERY_JSON', 'SITEMINDER_CERT_LOCK_BODY_JSON', 'SITEMINDER_CERT_CONFIRM_BODY_JSON'):
        if values.get(name):
            try:
                if not isinstance(json.loads(values[name]), dict): raise ValueError()
            except (ValueError, TypeError): invalid.append(name + '_OBJECT_REQUIRED')
    ready = not missing and not invalid
    return {'gate': 'INPUTS_READY_NOT_CERTIFIED' if ready else 'BLOCK',
        'ready': ready, 'missing_required_inputs': missing, 'invalid_input_codes': invalid,
        'external_calls': 0, 'credential_values_recorded': False,
        'external_certification': 'NOT_RUN', 'final_release': 'HOLD'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args();result=inspect_inputs(os.environ)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return 0 if result['ready'] else 2

if __name__ == '__main__': raise SystemExit(main())
