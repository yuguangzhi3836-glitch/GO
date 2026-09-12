#!/bin/sh
set -eu
root=${1:?staged candidate root required}
(
  cd "$root"
  sha256sum -c SHA256SUMS
)
"$root/install/preflight.sh" hk-staging
test "$(id -u)" = 0
backup=/var/lib/go-hk-agent/test-pr-install-backup
test ! -e "$backup/state.tsv"
install -d -o root -g root -m 0700 "$backup"
record() {
  path=$1 name=$2
  if test -e "$path"; then
    printf '%s|present|%s|%s|%s\n' "$name" "$(sha256sum "$path" | awk '{print $1}')" "$(stat -c %u:%g "$path")" "$(stat -c %a "$path")" >> "$backup/state.tsv"
    cp -p "$path" "$backup/$name"
  else
    printf '%s|absent|||\n' "$name" >> "$backup/state.tsv"
  fi
}
record /opt/go-hk-agent-rebuilt/hk_agent/transport.py transport.py
record /etc/go-hk-agent/agent.json agent.json
record /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py test_pr.py
record /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1 Dockerfile.go-application-python-v1
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
agent_owner=$(awk -F'|' '$1=="agent.json"{print $4}' "$backup/state.tsv")
agent_mode=$(awk -F'|' '$1=="agent.json"{print $5}' "$backup/state.tsv")
chown "$agent_owner" /etc/go-hk-agent/agent.json
chmod "$agent_mode" /etc/go-hk-agent/agent.json
printf 'transport.py|%s\n' "$(sha256sum /opt/go-hk-agent-rebuilt/hk_agent/transport.py | awk '{print $1}')" > "$backup/installed.tsv"
printf 'agent.json|%s\n' "$(sha256sum /etc/go-hk-agent/agent.json | awk '{print $1}')" >> "$backup/installed.tsv"
printf 'test_pr.py|%s\n' "$(sha256sum /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py | awk '{print $1}')" >> "$backup/installed.tsv"
printf 'Dockerfile.go-application-python-v1|%s\n' "$(sha256sum /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1 | awk '{print $1}')" >> "$backup/installed.tsv"
test "$(awk '$2=="hk-staging/hk_agent/transport.py"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="transport.py"{print $2}' "$backup/installed.tsv")"
test "$(awk '$2=="hk-staging/hk_agent/test_pr.py"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="test_pr.py"{print $2}' "$backup/installed.tsv")"
test "$(awk '$2=="hk-staging/Dockerfile.go-application-python-v1"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="Dockerfile.go-application-python-v1"{print $2}' "$backup/installed.tsv")"
echo "INSTALL_STAGED_ONLY: restart is a separately approved operation"
