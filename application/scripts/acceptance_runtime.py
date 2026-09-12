"""Candidate-bound, disposable HTTP acceptance runtime. Never a staging deployer.

Only a new state directory is accepted. Inherited application configuration is
discarded. The application can listen, but cannot initiate network connections.
This is SQLite/HTTP verification, not browser, PostgreSQL or provider certification.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import sys


def tree_hash(fingerprint):
    return hashlib.sha256(''.join(f'{p}\0{h}\n' for p, h in sorted(fingerprint.items())).encode()).hexdigest()


def verify_source(root, fingerprint, expected):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('SOURCE_DIRECTORY_REQUIRED')
    if not isinstance(fingerprint, dict) or not fingerprint or tree_hash(fingerprint) != expected:
        raise ValueError('SOURCE_TREE_MISMATCH')
    for rel, digest in fingerprint.items():
        p = PurePosixPath(rel)
        if p.is_absolute() or '..' in p.parts or '\\' in rel or str(p) != rel:
            raise ValueError('UNSAFE_SOURCE_PATH')
        target = root / rel
        if any(x.is_symlink() for x in [target, *target.parents] if x != root.parent):
            raise ValueError('SOURCE_SYMLINK')
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('SOURCE_FILE_MISMATCH:' + rel)
    actual = set()
    for p in root.rglob('*'):
        if p.is_symlink():
            raise ValueError('SOURCE_SYMLINK')
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            actual.add(rel)
    if actual != set(fingerprint):
        raise ValueError('UNTRACKED_SOURCE_FILE')
    return len(fingerprint)


def isolated_environment(state, credentials, inherited):
    # Do not propagate DATABASE_URL, proxy settings, .env, cloud credentials or
    # arbitrary Python paths from the operator's session into the app process.
    env = {k: inherited[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TZ') if k in inherited}
    env.update({
        'APP_ENV': 'local', 'GO_ACCEPTANCE_ONLY': '1',
        'DATABASE_URL': 'sqlite+pysqlite:///' + str(state / 'acceptance.db'),
        'JWT_SIGNING_KEY': secrets.token_hex(32),
        'CONNECTOR_VAULT_MASTER_KEY': secrets.token_hex(32),
        'WEBHOOK_SECRET': secrets.token_hex(32),
        'BOOTSTRAP_ADMIN_USERNAME': credentials['admin']['username'],
        'BOOTSTRAP_ADMIN_PASSWORD': credentials['admin']['password'],
        'BOOTSTRAP_SUPPLIER_USERNAME': credentials['supplier']['username'],
        'BOOTSTRAP_SUPPLIER_PASSWORD': credentials['supplier']['password'],
        'BOOTSTRAP_SUPPLIER_ID': 'sup_acceptance_isolated',
        'VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED': 'false',
        'HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED': 'false',
        'MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED': 'false',
        'READINESS_REQUIRE_POSTGRES': 'false', 'OIDC_ENABLED': 'false',
        'MFA_REQUIRED_FOR_ADMIN': 'false', 'COOKIE_SECURE': 'false',
        'MOBILE_PUSH_MODE': 'mock', 'OUTBOX_TRANSPORT': 'logging',
        'PYTHONDONTWRITEBYTECODE': '1',
    })
    return env


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')


def network_guard(event, args):
    if event in {'socket.connect', 'socket.sendto', 'socket.sendmsg', 'socket.getaddrinfo',
                 'socket.gethostbyname', 'socket.gethostbyaddr', 'subprocess.Popen',
                 'os.system', 'os.posix_spawn', 'os.exec'}:
        raise PermissionError('ISOLATED_RUNTIME_OUTBOUND_DISABLED')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--fingerprint', required=True, type=Path)
    parser.add_argument('--expected-tree', required=True)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--port', type=int, default=4186)
    parser.add_argument('--journey-suppliers', action='store_true',
                        help='Create separate identities for the built-in synthetic sources')
    a = parser.parse_args()
    if not 1024 <= a.port <= 65535:
        raise ValueError('UNPRIVILEGED_PORT_REQUIRED')
    root = a.source.absolute()
    fp = json.loads(a.fingerprint.read_text())
    count = verify_source(root, fp, a.expected_tree)
    state = a.state.absolute()
    if state == root or root in state.parents or state.is_symlink():
        raise ValueError('SEPARATE_STATE_REQUIRED')
    # mkdir(exist_ok=False) is also the atomic guard against accidental reuse.
    state.mkdir(mode=0o700, parents=False, exist_ok=False)
    credentials = {r: {'username': 'acceptance-' + r + '@example.test',
                       'password': secrets.token_urlsafe(32)} for r in ('consumer', 'supplier', 'admin')}
    private_json(state / 'credentials.private.json', credentials)
    env = isolated_environment(state, credentials, os.environ)
    os.environ.clear(); os.environ.update(env)
    os.chdir(state)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / 'src'))
    sys.addaudithook(network_guard)
    from go_hotel.db.models import Base
    from go_hotel.db.session import engine
    if engine.url.get_backend_name() != 'sqlite' or Path(engine.url.database) != state / 'acceptance.db':
        raise ValueError('ISOLATED_DATABASE_BINDING_REQUIRED')
    Base.metadata.create_all(engine)
    from go_hotel.security.service import identity_service
    from go_hotel.consumer.service import consumer_service
    identity_service.bootstrap()
    if a.journey_suppliers:
        # These are the existing simulator source identities, not ownership
        # rewrites. The original unrelated supplier remains a negative fixture.
        suppliers = {'HOTEL': 'sup_mock', **{v: v.lower() + '-engineering-source'
            for v in ('FLIGHT', 'RAIL', 'RIDE', 'RENTAL', 'ATTRACTION')}}
        fixtures = {}
        for vertical, supplier_id in suppliers.items():
            account = {'username': 'acceptance-' + vertical.lower() + '-supplier@example.test',
                       'password': secrets.token_urlsafe(32), 'supplier_id': supplier_id}
            identity_service.ensure_user(account['username'], account['password'],
                'SUPPLIER_USER', supplier_id, ['SUPPLIER_OWNER'])
            fixtures[vertical] = account
        private_json(state / 'suppliers.private.json', fixtures)
    consumer = consumer_service.register(credentials['consumer']['username'],
        credentials['consumer']['password'], 'GO 隔离验收账户')
    from go_hotel.main import app
    from fastapi import Request
    from starlette.responses import JSONResponse
    binding = {'schema': 'go.isolated-runtime.v1', 'source_tree_sha256': a.expected_tree,
        'verified_source_files': count, 'python': sys.version, 'pid': os.getpid(),
        'mode': 'ISOLATED_SQLITE_HTTP', 'data_class': 'SYNTHETIC_ONLY',
        'database': 'NEW_PRIVATE_SQLITE', 'outbound_network': 'PYTHON_AUDIT_DENY',
        'background_workers': 'DISABLED', 'browser_gate': 'HOLD',
        'postgres_gate': 'NOT_RUN', 'final_release': 'HOLD',
        'packages': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}}
    private_json(state / 'runtime-binding.json', binding)
    private_json(state / 'fixture-identities.json', {
        'consumer': {'alias': 'acceptance-consumer', 'user_id': consumer['user_id'], 'go_id': consumer['go_id']},
        'supplier': {'alias': 'acceptance-supplier', 'actor_type': 'SUPPLIER_USER', 'supplier_id': 'sup_acceptance_isolated'},
        'admin': {'alias': 'acceptance-admin', 'actor_type': 'GO_ADMIN'}})

    @app.get('/__acceptance/binding')
    def acceptance_binding():
        return {k: v for k, v in binding.items() if k not in {'pid', 'packages'}}

    @app.middleware('http')
    async def acceptance_boundary(request: Request, call_next):
        # Keep this service on a loopback origin. A future externally served
        # acceptance deployment needs its own reviewed TLS/origin configuration.
        if request.headers.get('host') not in {f'127.0.0.1:{a.port}', f'localhost:{a.port}'}:
            return JSONResponse({'detail': 'ISOLATED_ORIGIN_REQUIRED'}, status_code=403)
        response = await call_next(request)
        response.headers['X-GO-Acceptance'] = 'SYNTHETIC_ONLY'
        response.headers['X-GO-Source-Tree'] = a.expected_tree
        response.headers['Cache-Control'] = 'no-store'
        return response

    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=a.port, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
