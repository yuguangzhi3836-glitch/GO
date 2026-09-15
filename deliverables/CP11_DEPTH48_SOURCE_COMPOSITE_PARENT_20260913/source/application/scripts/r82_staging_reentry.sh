#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PYTHON=${PYTHON:-python3}
exec "$PYTHON" scripts/r82_staging_incident_resolution_controller.py "$@"
