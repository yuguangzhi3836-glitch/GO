#!/bin/sh
set -eu
python -m compileall -q src
pytest -q
alembic upgrade head
python scripts/production_readiness_gate.py
if [ -n "${REDIS_URL:-}" ]; then python scripts/queue_smoke.py; fi
if [ -n "${STAGING_BASE_URL:-}" ]; then python scripts/staging_smoke.py; fi
printf '%s\n' 'RELEASE_GATE=PASS'
