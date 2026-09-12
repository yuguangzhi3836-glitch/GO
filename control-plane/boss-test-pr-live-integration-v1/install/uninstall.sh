#!/bin/sh
set -eu
role=${1:?role required}
valid_hash() {
  test "${#1}" = 64 && printf '%s' "$1" | grep -Eq '^[0-9a-f]{64}$'
}
valid_owner() {
  printf '%s' "$1" | grep -Eq '^[0-9]+:[0-9]+$'
}
valid_mode() {
  printf '%s' "$1" | grep -Eq '^[0-7]{3,4}$'
}
one_field() {
  awk -F'|' -v n="$1" -v f="$2" '$1==n { count++; value=$f } END { if (count != 1) exit 1; print value }' "$3"
}
case "$role" in
 command-center)
   backup=${GO_CC_ROLLBACK_BACKUP:-/var/lib/go-command-center/test-pr-install-backup}
   bridge=${GO_CC_BRIDGE_PATH:-/usr/local/libexec/go-boss-request-bridge}
   config=${GO_CC_CONFIG_PATH:-/etc/go-command-center/boss-request-bridge-v1.json}
   validate() {
     name=$1 path=$2
     recorded=$(one_field "$name" 2 "$backup/state.tsv")
     owner=$(one_field "$name" 3 "$backup/state.tsv")
     mode=$(one_field "$name" 4 "$backup/state.tsv")
     installed=$(one_field "$name" 2 "$backup/installed.tsv")
     valid_hash "$recorded" && valid_hash "$installed" && valid_owner "$owner" && valid_mode "$mode"
     test -f "$path" && test -f "$backup/$name"
     test "$(sha256sum "$path" | awk '{print $1}')" = "$installed"
     test "$(sha256sum "$backup/$name" | awk '{print $1}')" = "$recorded"
   }
   restore() {
     name=$1 path=$2
     cp -p "$backup/$name" "$path"
   }
   verify_restored() {
     name=$1 path=$2
     recorded=$(one_field "$name" 2 "$backup/state.tsv")
     owner=$(one_field "$name" 3 "$backup/state.tsv")
     mode=$(one_field "$name" 4 "$backup/state.tsv")
     test "$(sha256sum "$path" | awk '{print $1}')" = "$recorded"
     test "$(stat -c %u:%g "$path")" = "$owner"
     test "$(stat -c %a "$path")" = "$mode"
   }
   test -f "$backup/state.tsv" && test -f "$backup/installed.tsv"
   # Phase 1: validate every target and backup before any mutation.
   validate go-boss-request-bridge "$bridge"
   validate boss-request-bridge-v1.json "$config"
   # Phase 2: all validation passed; restore every target, then verify all.
   restore go-boss-request-bridge "$bridge"
   restore boss-request-bridge-v1.json "$config"
   verify_restored go-boss-request-bridge "$bridge"
   verify_restored boss-request-bridge-v1.json "$config"
   echo "ROLLBACK_STAGED_ONLY: services are not restarted automatically"
   ;;
 hk-staging)
   backup=${GO_HK_ROLLBACK_BACKUP:-/var/lib/go-hk-agent/test-pr-install-backup}
   transport=${GO_HK_TRANSPORT_PATH:-/opt/go-hk-agent-rebuilt/hk_agent/transport.py}
   agent_config=${GO_HK_AGENT_CONFIG_PATH:-/etc/go-hk-agent/agent.json}
   test_pr=${GO_HK_TEST_PR_PATH:-/opt/go-hk-agent-rebuilt/hk_agent/test_pr.py}
   dockerfile=${GO_HK_DOCKERFILE_PATH:-/usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1}
   validate() {
     name=$1 path=$2
     existed=$(one_field "$name" 2 "$backup/state.tsv")
     recorded=$(one_field "$name" 3 "$backup/state.tsv")
     owner=$(one_field "$name" 4 "$backup/state.tsv")
     mode=$(one_field "$name" 5 "$backup/state.tsv")
     installed=$(one_field "$name" 2 "$backup/installed.tsv")
     valid_hash "$installed"
     test -f "$path"
     test "$(sha256sum "$path" | awk '{print $1}')" = "$installed"
     if test "$existed" = present; then
       valid_hash "$recorded" && valid_owner "$owner" && valid_mode "$mode"
       test -f "$backup/$name"
       test "$(sha256sum "$backup/$name" | awk '{print $1}')" = "$recorded"
     elif test "$existed" = absent; then
       test -z "$recorded" && test -z "$owner" && test -z "$mode" && test ! -e "$backup/$name"
     else
       exit 65
     fi
   }
   restore() {
     name=$1 path=$2
     existed=$(one_field "$name" 2 "$backup/state.tsv")
     if test "$existed" = present; then
       cp -p "$backup/$name" "$path"
     else
       rm -- "$path"
     fi
   }
   verify_restored() {
     name=$1 path=$2
     existed=$(one_field "$name" 2 "$backup/state.tsv")
     if test "$existed" = present; then
       recorded=$(one_field "$name" 3 "$backup/state.tsv")
       owner=$(one_field "$name" 4 "$backup/state.tsv")
       mode=$(one_field "$name" 5 "$backup/state.tsv")
       test -f "$path"
       test "$(sha256sum "$path" | awk '{print $1}')" = "$recorded"
       test "$(stat -c %u:%g "$path")" = "$owner"
       test "$(stat -c %a "$path")" = "$mode"
     else
       test ! -e "$path"
     fi
   }
   test -f "$backup/state.tsv" && test -f "$backup/installed.tsv"
   # Phase 1: validate every target and backup before any mutation.
   validate transport.py "$transport"
   validate agent.json "$agent_config"
   validate test_pr.py "$test_pr"
   validate Dockerfile.go-application-python-v1 "$dockerfile"
   # Phase 2: all validation passed; restore/remove every target, then verify all.
   restore transport.py "$transport"
   restore agent.json "$agent_config"
   restore test_pr.py "$test_pr"
   restore Dockerfile.go-application-python-v1 "$dockerfile"
   verify_restored transport.py "$transport"
   verify_restored agent.json "$agent_config"
   verify_restored test_pr.py "$test_pr"
   verify_restored Dockerfile.go-application-python-v1 "$dockerfile"
   echo "ROLLBACK_STAGED_ONLY: services are not restarted automatically"
   ;;
 *) exit 64 ;;
esac
