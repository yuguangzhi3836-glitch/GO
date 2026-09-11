"""Exact eight-role launcher. No migrations, provisioning, shell or auto-rollback."""
import json
import os
import sys
from preflight import Hold, WORKERS, run, emit_failure, verify_source


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {'api', 'preflight', 'source-check', *WORKERS}:
        raise Hold('FIXED_SERVICE_ROLE_REQUIRED')
    role = sys.argv[1]
    if role == 'source-check':
        print(json.dumps({'status': 'PASS', **verify_source()})); return
    result = run()
    print(json.dumps({'status': 'PASS_READ_ONLY', 'role': role, **result}), flush=True)
    if role == 'preflight':
        return
    if role == 'api':
        # Forwarded headers are intentionally disabled pending a verified HK proxy mapping.
        args = [sys.executable, '-B', '-m', 'uvicorn', 'go_hotel.main:app', '--host', '0.0.0.0',
                '--port', '8000', '--no-proxy-headers', '--no-access-log']
    else:
        args = [sys.executable, '-B', '-m', 'go_hotel.workers.' + WORKERS[role]]
    os.execv(sys.executable, args)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit_failure(exc)
        sys.exit(2)
