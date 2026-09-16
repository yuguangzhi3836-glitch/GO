#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "must run as root on the authorized long-running host" >&2
  exit 1
fi
if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
  echo "systemd is required" >&2
  exit 1
fi

SOURCE_DIR=${1:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
ENV_FILE=${2:-/etc/go-cell-orchestrator.env}
PROBE_ENV_FILE=${3:-/etc/go-cell-runtime-liveness.env}
INSTALL_DIR=/opt/go-cell-orchestrator/current/ci/runtime_liveness
STATE_DIR=/var/lib/go-cell-orchestrator

test -r "$ENV_FILE" || { echo "missing $ENV_FILE" >&2; exit 1; }
test -r "$PROBE_ENV_FILE" || { echo "missing $PROBE_ENV_FILE" >&2; exit 1; }
set -a
. "$ENV_FILE"
set +a

id go-cell-orchestrator >/dev/null 2>&1 || \
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin go-cell-orchestrator
id go-cell-monitor >/dev/null 2>&1 || \
  useradd --system --home-dir /var/lib/go-cell-runtime-liveness --shell /usr/sbin/nologin go-cell-monitor
install -d -m 0755 "$INSTALL_DIR"
install -d -o go-cell-orchestrator -g go-cell-orchestrator -m 0700 "$STATE_DIR"
install -m 0755 "$SOURCE_DIR/durable_orchestrator.py" "$INSTALL_DIR/"
install -m 0755 "$SOURCE_DIR/probe_external_orchestrator.py" "$INSTALL_DIR/"
install -m 0644 "$SOURCE_DIR/validate_runtime_liveness.py" "$INSTALL_DIR/"
install -m 0755 "$SOURCE_DIR/validate_orchestrator_config.py" "$INSTALL_DIR/"
install -m 0755 "$SOURCE_DIR/seed_ledger_tasks.py" "$INSTALL_DIR/"
install -m 0755 "$SOURCE_DIR/worker_launch_adapter.py" "$INSTALL_DIR/"

python3 "$SOURCE_DIR/validate_orchestrator_config.py" \
  --database "$STATE_DIR/orchestrator.sqlite3" \
  --tls-cert /etc/go-cell-orchestrator/tls.crt \
  --tls-key /etc/go-cell-orchestrator/tls.key

install -m 0644 "$SOURCE_DIR/systemd/go-cell-orchestrator.service.example" \
  /etc/systemd/system/go-cell-orchestrator.service
install -m 0644 "$SOURCE_DIR/systemd/go-cell-runtime-liveness.service.example" \
  /etc/systemd/system/go-cell-runtime-liveness.service
install -m 0644 "$SOURCE_DIR/systemd/go-cell-runtime-liveness.timer.example" \
  /etc/systemd/system/go-cell-runtime-liveness.timer

systemctl daemon-reload
systemctl enable --now go-cell-orchestrator.service
systemctl enable --now go-cell-runtime-liveness.timer
systemctl is-active --quiet go-cell-orchestrator.service
systemctl is-active --quiet go-cell-runtime-liveness.timer
curl --fail --silent --show-error --cacert /etc/go-cell-orchestrator/tls.crt \
  https://127.0.0.1:8443/readyz
echo
echo "GO Cell orchestrator installed and ready; seed reviewed unfinished tasks separately."
