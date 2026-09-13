#!/usr/bin/env bash
set -euo pipefail
python scripts/sprint2d_preflight.py || true
python scripts/sprint2d_live_infra_gate.py || true
python scripts/sprint2d_association_gate.py || true
python scripts/sprint2d_gate_ledger.py --show
