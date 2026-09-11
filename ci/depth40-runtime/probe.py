"""Small packaged-runtime smoke, not browser or six-vertical acceptance."""
import hashlib
import http.cookiejar
import json
from pathlib import Path
import time
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler

TREE = '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'
client = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
checks = []


def call(path, body=None, host='127.0.0.1:18440'):
    request = Request('http://127.0.0.1:4187' + path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Host': host, 'Content-Type': 'application/json'})
    try: response = client.open(request, timeout=5)
    except HTTPError as exc: response = exc
    with response: return response.status, response.read(), response.headers


def check(name, condition):
    assert condition, name
    checks.append(name)


for _ in range(90):
    try:
        if call('/health')[0] == 200: break
    except (URLError, OSError): pass
    time.sleep(1)
else: raise RuntimeError('PACKAGED_RUNTIME_START_TIMEOUT')
check('health', call('/health')[0] == 200)
status, body, headers = call('/__acceptance/binding')
binding = json.loads(body)
check('source binding', status == 200 and binding['source_tree_sha256'] == TREE
      and binding['verified_source_files'] == 1271)
check('synthetic boundary', headers['X-GO-Acceptance'] == 'SYNTHETIC_ONLY')
check('foreign host rejected', call('/health', host='untrusted.invalid')[0] == 403)
fp = json.loads(Path('/opt/go/SOURCE_FINGERPRINT.json').read_text())
for page, filename in [('/go-app/', 'frontend/consumer/index.html'),
                       ('/go-admin/', 'frontend/admin/index.html'),
                       ('/supplier-console/', 'frontend/supplier/index.html')]:
    status, body, _ = call(page)
    check('exact page ' + page, status == 200 and hashlib.sha256(body).hexdigest() == fp[filename])
credentials = json.loads(Path('/state/session/credentials.private.json').read_text())
check('private credentials mode', Path('/state/session/credentials.private.json').stat().st_mode & 0o777 == 0o600)
c = credentials['consumer']
check('consumer HTTP login', call('/v1/consumer/auth/login', {'email': c['username'], 'password': c['password']})[0] == 200)
check('consumer HTTP identity', json.loads(call('/v1/consumer/me')[1])['data']['email'] == c['username'])
for role, actor in [('supplier', 'SUPPLIER_USER'), ('admin', 'GO_ADMIN')]:
    check(role + ' HTTP login', call('/bff/auth/login', {**credentials[role], 'expected_actor_type': actor})[0] == 200)
    check(role + ' HTTP identity', json.loads(call('/bff/auth/me')[1])['data']['actor_type'] == actor)
actual = {p.relative_to('/opt/go/source').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in Path('/opt/go/source').rglob('*') if p.is_file()}
check('source unchanged after boot', actual == fp)
import psycopg
check('bundled psycopg extension imports without RDS access', bool(psycopg.__version__))
repeat = subprocess.run([sys.executable, '-B', '/opt/go/source/scripts/acceptance_runtime.py',
        '--source','/opt/go/source','--fingerprint','/opt/go/SOURCE_FINGERPRINT.json',
        '--expected-tree',TREE,'--state','/state/session','--port','4186'],
        capture_output=True, timeout=20)
check('existing session refuses reinitialization', repeat.returncode != 0 and b'FileExistsError' in repeat.stderr)
print(json.dumps({'status': 'PASS', 'checks': checks, 'source_tree_sha256': TREE,
                  'scope': 'PACKAGED_RUNTIME_HTTP_SMOKE', 'browser_gate': 'HOLD',
                  'six_vertical_gate': 'HOLD', 'hong_kong_execution': 'NOT_RUN',
                  'final_release': 'HOLD', 'credentials_exported': False}))
