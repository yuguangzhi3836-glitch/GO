#!/bin/sh
set -eu
root=${1:?staged candidate root required}
"$root/install/preflight.sh" command-center
test "$(id -u)" = 0
install -d -m 0700 /var/lib/go-command-center/test-pr-install-backup
cp -p /usr/local/libexec/go-boss-request-bridge /var/lib/go-command-center/test-pr-install-backup/go-boss-request-bridge.pre-test-pr
install -o root -g root -m 0755 "$root/command-center/go-boss-request-bridge" /usr/local/libexec/go-boss-request-bridge
install -o root -g root -m 0600 "$root/command-center/boss-request-bridge-v1.3.json" /etc/go-command-center/boss-request-bridge-v1.json
sha256sum /usr/local/libexec/go-boss-request-bridge
echo "INSTALL_STAGED_ONLY: restart is a separately approved operation"
