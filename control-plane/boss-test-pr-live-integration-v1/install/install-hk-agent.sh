#!/bin/sh
set -eu
root=${1:?staged candidate root required}
"$root/install/preflight.sh" hk-staging
test "$(id -u)" = 0
install -d -m 0700 /var/lib/go-hk-agent/test-pr-install-backup
cp -p /opt/go-hk-agent-rebuilt/hk_agent/transport.py /var/lib/go-hk-agent/test-pr-install-backup/transport.py.pre-test-pr
install -o root -g root -m 0644 "$root/hk-staging/hk_agent/transport.py" /opt/go-hk-agent-rebuilt/hk_agent/transport.py
install -o root -g root -m 0644 "$root/hk-staging/hk_agent/test_pr.py" /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py
install -d -o root -g root -m 0755 /usr/local/libexec/go-hk-test-pr
install -o root -g root -m 0644 "$root/hk-staging/Dockerfile.go-application-python-v1" /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1
python3 - "$root/hk-staging/agent.test-pr.fragment.json" <<'PY'
import json, pathlib, sys
p=pathlib.Path("/etc/go-hk-agent/agent.json")
cfg=json.loads(p.read_text())
fragment=json.loads(pathlib.Path(sys.argv[1]).read_text())
if cfg.get("go_source_reader_key") not in (None, fragment["go_source_reader_key"]):
    raise SystemExit("unknown go source reader binding")
cfg.update(fragment)
t=p.with_suffix(".test-pr.tmp")
t.write_text(json.dumps(cfg, sort_keys=True, separators=(",",":"))+"\n")
t.chmod(0o640)
t.replace(p)
PY
echo "INSTALL_STAGED_ONLY: restart is a separately approved operation"
