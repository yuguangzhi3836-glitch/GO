#!/usr/bin/env python3
from __future__ import annotations
import os, socket
from contextlib import contextmanager
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:///:memory:')
os.environ.setdefault('PYTHONPATH', str(ROOT/'src'))
import sys
sys.path.insert(0,str(ROOT/'src'))

from go_hotel.services.hotel_discovery_orchestrator import HotelDiscoveryOrchestratorService, DiscoveryNetworkPolicyError

SERVICE=(ROOT/'src/go_hotel/services/hotel_discovery_orchestrator.py').read_text(encoding='utf-8')
ROUTES=(ROOT/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text(encoding='utf-8')


def block(msg):
    print('R8.2_DISCOVERY_SSRF_GUARD_GATE: BLOCK')
    print(msg)
    raise SystemExit(1)

def ok(name, value):
    print(f'{name}={"PASS" if value else "FAIL"}')
    if not value: block(name)

@contextmanager
def fake_dns(mapping, sequence=None):
    orig=socket.getaddrinfo
    calls={}
    def resolver(host, port, *a, **kw):
        h=str(host)
        calls[h]=calls.get(h,0)+1
        if sequence and h in sequence:
            vals=sequence[h]
            ip=vals[min(calls[h]-1,len(vals)-1)]
        else:
            ip=mapping.get(h,h)
        family=socket.AF_INET6 if ':' in ip else socket.AF_INET
        return [(family,socket.SOCK_STREAM,6,'',(ip,0,0,0) if family==socket.AF_INET6 else (ip,0))]
    socket.getaddrinfo=resolver
    try: yield calls
    finally: socket.getaddrinfo=orig

svc=HotelDiscoveryOrchestratorService()

# API bypass removed from discovery routes only.
discovery_tail=ROUTES.split('# Slice 1')[1]
ok('discovery_api_allow_private_removed','allow_private' not in discovery_tail)
ok('server_side_test_override_present','GO_DISCOVERY_ALLOW_PRIVATE_TEST' in SERVICE and 'env not in {"production","prod","staging"}' in SERVICE)
ok('manual_redirect_validation','follow_redirects=False' in SERVICE and 'redirect_chain' in SERVICE)
ok('connected_peer_validation','_verify_connected_peer' in SERVICE and 'DISCOVERY_CONNECTED_PEER_MISMATCH_BLOCKED' in SERVICE)
ok('dns_rebinding_guard','DISCOVERY_DNS_REBINDING_BLOCKED' in SERVICE)
ok('fetch_budget_present','GO_DISCOVERY_MAX_REDIRECTS' in SERVICE and 'GO_DISCOVERY_MAX_HTML_BYTES' in SERVICE and 'httpx.Timeout' in SERVICE)
ok('credential_logging_sanitized','_safe_url_for_log' in SERVICE and '_safe_hint_for_log' in SERVICE and '"network_audit"' in SERVICE)

# staging/prod cannot enable private override by env flag.
old_app=os.environ.get('APP_ENV'); old_flag=os.environ.get('GO_DISCOVERY_ALLOW_PRIVATE_TEST')
try:
    os.environ['APP_ENV']='staging'; os.environ['GO_DISCOVERY_ALLOW_PRIVATE_TEST']='1'
    ok('staging_private_override_forbidden',not svc._private_test_override())
    os.environ['APP_ENV']='production'
    ok('production_private_override_forbidden',not svc._private_test_override())
finally:
    if old_app is None: os.environ.pop('APP_ENV',None)
    else: os.environ['APP_ENV']=old_app
    if old_flag is None: os.environ.pop('GO_DISCOVERY_ALLOW_PRIVATE_TEST',None)
    else: os.environ['GO_DISCOVERY_ALLOW_PRIVATE_TEST']=old_flag

cases={
 'localhost_block':('localhost','127.0.0.1'),
 'rfc1918_block':('private.test','10.1.2.3'),
 'linklocal_metadata_block':('metadata.test','169.254.169.254'),
 'cgnat_block':('cgnat.test','100.64.0.1'),
 'ipv6_private_block':('v6private.test','fd00::1'),
}
for name,(host,ip) in cases.items():
    with fake_dns({host:ip}):
        try: svc._validate_url('http://'+host+'/')
        except DiscoveryNetworkPolicyError: passed=True
        else: passed=False
    ok(name,passed)

with fake_dns({'public.test':'93.184.216.34'}):
    try: x=svc._validate_url('https://public.test/hotel')
    except Exception: passed=False
    else: passed=x['resolved_ips']==['93.184.216.34']
ok('public_url_pass',passed)

for url in ['file:///etc/passwd','ftp://public.test/x','gopher://public.test/x']:
    with fake_dns({'public.test':'93.184.216.34'}):
        try: svc._validate_url(url)
        except DiscoveryNetworkPolicyError: passed=True
        else: passed=False
    ok('non_http_scheme_block_'+url.split(':',1)[0],passed)

try: svc._validate_url('https://user:secret@public.test/path')
except DiscoveryNetworkPolicyError: passed=True
else: passed=False
ok('url_credentials_block',passed)

# Public redirect to private is blocked before second request.
def redirect_handler(req):
    if req.url.host=='public.test':
        return httpx.Response(302,headers={'location':'http://private.test/secret'},request=req)
    return httpx.Response(200,headers={'content-type':'text/html'},text='<title>x</title>',request=req)
redirect_svc=HotelDiscoveryOrchestratorService(transport=httpx.MockTransport(redirect_handler))
with fake_dns({'public.test':'93.184.216.34','private.test':'10.0.0.5'}):
    try: redirect_svc._fetch_html('https://public.test/start')
    except DiscoveryNetworkPolicyError as exc: passed='PRIVATE_OR_SPECIAL' in str(exc)
    else: passed=False
ok('public_to_private_redirect_block',passed)

# Rebinding: first validation and immediate pre-connect resolution differ.
rebinding_svc=HotelDiscoveryOrchestratorService(transport=httpx.MockTransport(lambda req:httpx.Response(200,headers={'content-type':'text/html'},text='<title>x</title>',request=req)))
with fake_dns({},sequence={'rebind.test':['93.184.216.34','93.184.216.35']}):
    try: rebinding_svc._fetch_html('https://rebind.test/')
    except DiscoveryNetworkPolicyError as exc: passed=str(exc)=='DISCOVERY_DNS_REBINDING_BLOCKED'
    else: passed=False
ok('dns_rebinding_block',passed)

print('R8.2_DISCOVERY_SSRF_GUARD_GATE: PASS')
