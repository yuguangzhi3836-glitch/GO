#!/bin/sh
set -eu
role=${1:?role required}
case "$role" in
 command-center)
   backup=/var/lib/go-command-center/test-pr-install-backup
   restore() {
     name=$1 path=$2
     recorded=$(awk -F'|' -v n="$name" '$1==n{print $2}' "$backup/state.tsv")
     owner=$(awk -F'|' -v n="$name" '$1==n{print $3}' "$backup/state.tsv")
     mode=$(awk -F'|' -v n="$name" '$1==n{print $4}' "$backup/state.tsv")
     installed=$(awk -F'|' -v n="$name" '$1==n{print $2}' "$backup/installed.tsv")
     test -n "$recorded" && test -n "$installed"
     test "$(sha256sum "$path" | awk '{print $1}')" = "$installed"
     test "$(sha256sum "$backup/$name" | awk '{print $1}')" = "$recorded"
     cp -p "$backup/$name" "$path"
     test "$(stat -c %u:%g "$path")" = "$owner"
     test "$(stat -c %a "$path")" = "$mode"
   }
   test -f "$backup/state.tsv" && test -f "$backup/installed.tsv"
   restore go-boss-request-bridge /usr/local/libexec/go-boss-request-bridge
   restore boss-request-bridge-v1.json /etc/go-command-center/boss-request-bridge-v1.json
   echo "ROLLBACK_STAGED_ONLY: services are not restarted automatically"
   ;;
 hk-staging)
   backup=/var/lib/go-hk-agent/test-pr-install-backup
   restore() {
     name=$1 path=$2
     existed=$(awk -F'|' -v n="$name" '$1==n{print $2}' "$backup/state.tsv")
     recorded=$(awk -F'|' -v n="$name" '$1==n{print $3}' "$backup/state.tsv")
     owner=$(awk -F'|' -v n="$name" '$1==n{print $4}' "$backup/state.tsv")
     mode=$(awk -F'|' -v n="$name" '$1==n{print $5}' "$backup/state.tsv")
     installed=$(awk -F'|' -v n="$name" '$1==n{print $2}' "$backup/installed.tsv")
     test -n "$existed" && test -n "$installed" && test -e "$path"
     test "$(sha256sum "$path" | awk '{print $1}')" = "$installed"
     if test "$existed" = present; then
       test "$(sha256sum "$backup/$name" | awk '{print $1}')" = "$recorded"
       cp -p "$backup/$name" "$path"
       test "$(stat -c %u:%g "$path")" = "$owner"
       test "$(stat -c %a "$path")" = "$mode"
     elif test "$existed" = absent; then
       rm -- "$path"
     else
       exit 65
     fi
   }
   test -f "$backup/state.tsv" && test -f "$backup/installed.tsv"
   restore transport.py /opt/go-hk-agent-rebuilt/hk_agent/transport.py
   restore agent.json /etc/go-hk-agent/agent.json
   restore test_pr.py /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py
   restore Dockerfile.go-application-python-v1 /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1
   echo "ROLLBACK_STAGED_ONLY: services are not restarted automatically"
   ;;
 *) exit 64 ;;
esac
