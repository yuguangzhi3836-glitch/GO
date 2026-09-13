#!/bin/sh
set -eu
base=${HK_AGENT_HOME:-/opt/go-hk-agent-rebuilt}
exec env PYTHONPATH="$base" python3 -m hk_agent.release_regression
