#!/bin/sh
set -eu
role=${1:?role required}
case "$role" in
 command-center)
   test -f /var/lib/go-command-center/test-pr-install-backup/go-boss-request-bridge.pre-test-pr
   echo "Operator must compare the backup SHA256 with recorded pre-install value before restoring."
   ;;
 hk-staging)
   test -f /var/lib/go-hk-agent/test-pr-install-backup/transport.py.pre-test-pr
   echo "Operator must compare the backup SHA256 with recorded pre-install value before restoring."
   ;;
 *) exit 64 ;;
esac
