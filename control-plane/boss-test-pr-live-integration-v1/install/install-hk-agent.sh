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
runtime_root=/var/lib/go-hk-test-pr
build_root=$runtime_root/builds
docker_dropin=/etc/systemd/system/go-hk-agent.service.d/30-test-pr-docker-access.conf
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
record_dir() {
  path=$1 name=$2
  if test -e "$path"; then
    test -d "$path" && test ! -L "$path"
    printf '%s|present||%s|%s\n' "$name" "$(stat -c %u:%g "$path")" "$(stat -c %a "$path")" >> "$backup/state.tsv"
  else
    printf '%s|absent|||\n' "$name" >> "$backup/state.tsv"
  fi
}
record /opt/go-hk-agent-rebuilt/hk_agent/transport.py transport.py
record /etc/go-hk-agent/agent.json agent.json
record /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py test_pr.py
record /opt/go-hk-agent-rebuilt/hk_agent/artifact_store.py artifact_store.py
record /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2 Dockerfile.go-application-python-v2
record "$docker_dropin" docker-access.conf
record_dir "$runtime_root" runtime_root
record_dir "$build_root" builds
install -o root -g root -m 0644 "$root/hk-staging/hk_agent/transport.py" /opt/go-hk-agent-rebuilt/hk_agent/transport.py
install -o root -g root -m 0644 "$root/hk-staging/hk_agent/test_pr.py" /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py
install -o root -g root -m 0644 "$root/hk-staging/hk_agent/artifact_store.py" /opt/go-hk-agent-rebuilt/hk_agent/artifact_store.py
# The sealed-artifact store.  It is owned by the agent's own account, not by root:
# the agent writes it (systemd User=go-hk-agent) while the Hong Kong executor only
# reads it, through sudo, as root.  "Which account may have written this evidence"
# must not depend on who happens to be reading, so the trusted owner is the writer.
#
# Created once and never re-created over existing content, and deliberately OUTSIDE
# this install/rollback unit: what it holds is immutable artifact evidence
# referenced by signed Evidence, not configuration.  A rollback that deleted it
# would destroy the only copy of a built candidate.  For the same reason an
# existing store is never re-owned to match this contract -- a mismatch is an
# operator review, not a chmod, because the directory is the sole copy of every
# candidate ever built here.
store_root=/var/lib/go-hk-artifacts
artifact_user=go-hk-agent
artifact_group=go-hk-agent
getent passwd "$artifact_user" >/dev/null 2>&1 || { echo "trusted writer account missing: $artifact_user" >&2; exit 1; }
getent group "$artifact_group" >/dev/null 2>&1 || { echo "trusted writer group missing: $artifact_group" >&2; exit 1; }
artifact_uid=$(id -u "$artifact_user")
artifact_gid=$(id -g "$artifact_user")
test "$artifact_uid" != 0 || { echo "trusted writer account resolves to root: $artifact_user" >&2; exit 1; }
for store_path in "$store_root" "$store_root/objects"; do
  test ! -L "$store_path" || { echo "refusing a symlinked store path: $store_path" >&2; exit 1; }
  if test -e "$store_path"; then
    test "$(stat -c %u:%g "$store_path")" = "$artifact_uid:$artifact_gid" \
      || { echo "STORE_OWNER_MISMATCH ($store_path): operator review required" >&2; exit 1; }
    test "$(stat -c %a "$store_path")" = 700 \
      || { echo "STORE_MODE_MISMATCH ($store_path): operator review required" >&2; exit 1; }
  else
    install -d -o "$artifact_uid" -g "$artifact_gid" -m 0700 "$store_path"
  fi
done
install -d -o root -g root -m 0755 /usr/local/libexec/go-hk-test-pr
install -o root -g root -m 0644 "$root/hk-staging/Dockerfile.go-application-python-v2" /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2
agent_uid=$(id -u go-hk-agent)
agent_gid=$(id -g go-hk-agent)
install -d -o root -g root -m 0711 "$runtime_root"
install -d -o "$agent_uid" -g "$agent_gid" -m 0700 "$build_root"
install -d -o root -g root -m 0755 "$(dirname "$docker_dropin")"
tmp_dropin=$(mktemp)
printf '%s\n' '[Service]' 'SupplementaryGroups=docker' > "$tmp_dropin"
install -o root -g root -m 0644 "$tmp_dropin" "$docker_dropin"
rm -f "$tmp_dropin"
systemctl daemon-reload
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
printf 'artifact_store.py|%s\n' "$(sha256sum /opt/go-hk-agent-rebuilt/hk_agent/artifact_store.py | awk '{print $1}')" >> "$backup/installed.tsv"
printf 'Dockerfile.go-application-python-v2|%s\n' "$(sha256sum /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2 | awk '{print $1}')" >> "$backup/installed.tsv"
printf 'docker-access.conf|%s\n' "$(sha256sum "$docker_dropin" | awk '{print $1}')" >> "$backup/installed.tsv"
printf 'runtime_root|directory|%s|%s\n' "$(stat -c %u:%g "$runtime_root")" "$(stat -c %a "$runtime_root")" >> "$backup/installed.tsv"
printf 'builds|directory|%s|%s\n' "$(stat -c %u:%g "$build_root")" "$(stat -c %a "$build_root")" >> "$backup/installed.tsv"
test "$(awk '$2=="hk-staging/hk_agent/transport.py"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="transport.py"{print $2}' "$backup/installed.tsv")"
test "$(awk '$2=="hk-staging/hk_agent/test_pr.py"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="test_pr.py"{print $2}' "$backup/installed.tsv")"
test "$(awk '$2=="hk-staging/hk_agent/artifact_store.py"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="artifact_store.py"{print $2}' "$backup/installed.tsv")"
test "$(awk '$2=="hk-staging/Dockerfile.go-application-python-v2"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="Dockerfile.go-application-python-v2"{print $2}' "$backup/installed.tsv")"
test "$(stat -c %u:%g "$runtime_root")" = 0:0
test "$(stat -c %a "$runtime_root")" = 711
test "$(stat -c %u:%g "$build_root")" = "$agent_uid:$agent_gid"
test "$(stat -c %a "$build_root")" = 700
# Read back the artifact store the agent will write and root will only read.
test "$(stat -c %u:%g "$store_root")" = "$artifact_uid:$artifact_gid"
test "$(stat -c %a "$store_root")" = 700
test "$(stat -c %u:%g "$store_root/objects")" = "$artifact_uid:$artifact_gid"
test "$(stat -c %a "$store_root/objects")" = 700
"$root/install/preflight.sh" hk-staging postinstall
echo "INSTALL_STAGED_ONLY: restart is a separately approved operation"
