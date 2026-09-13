#!/bin/sh
set -eu
root=${1:?staged candidate root required}
(
  cd "$root"
  sha256sum -c SHA256SUMS
)
"$root/install/preflight.sh" command-center
test "$(id -u)" = 0
backup=/var/lib/go-command-center/test-pr-install-backup
test ! -e "$backup/state.tsv"
install -d -o root -g root -m 0700 "$backup"
record() {
  path=$1 name=$2
  printf '%s|%s|%s|%s\n' "$name" "$(sha256sum "$path" | awk '{print $1}')" "$(stat -c %u:%g "$path")" "$(stat -c %a "$path")" >> "$backup/state.tsv"
  cp -p "$path" "$backup/$name"
}
record /usr/local/libexec/go-boss-request-bridge go-boss-request-bridge
record /etc/go-command-center/boss-request-bridge-v1.json boss-request-bridge-v1.json
install -o root -g root -m 0750 "$root/command-center/go-boss-request-bridge" /usr/local/libexec/go-boss-request-bridge
install -o root -g root -m 0600 "$root/command-center/boss-request-bridge-v1.3.json" /etc/go-command-center/boss-request-bridge-v1.json
printf 'go-boss-request-bridge|%s\n' "$(sha256sum /usr/local/libexec/go-boss-request-bridge | awk '{print $1}')" > "$backup/installed.tsv"
printf 'boss-request-bridge-v1.json|%s\n' "$(sha256sum /etc/go-command-center/boss-request-bridge-v1.json | awk '{print $1}')" >> "$backup/installed.tsv"
test "$(awk '$2=="command-center/go-boss-request-bridge"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="go-boss-request-bridge"{print $2}' "$backup/installed.tsv")"
test "$(awk '$2=="command-center/boss-request-bridge-v1.3.json"{print $1}' "$root/SHA256SUMS")" = "$(awk -F'|' '$1=="boss-request-bridge-v1.json"{print $2}' "$backup/installed.tsv")"
echo "INSTALL_STAGED_ONLY: restart is a separately approved operation"
