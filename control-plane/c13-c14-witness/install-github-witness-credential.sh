#!/bin/sh
# Install the CC / HK GitHub witness credential.
#
# The credential is read from STDIN only. It is never taken from argv, never
# echoed, never written to a log, and never placed in shell history. Run it on the
# target host as root:
#
#   sudo sh install-github-witness-credential.sh --host cc --apply < /path/to/secret
#
# or interactively, so the value never touches the filesystem first:
#
#   sudo sh install-github-witness-credential.sh --host cc --apply
#   (paste the token, then Ctrl-D)
#
# Without --apply it prints the plan and changes nothing.
#
# Scope of this script: create/replace exactly one file, with the mode and owner the
# witness expects. It does not restart a service, does not touch the key directory's
# permissions, and does not modify any other credential.
set -eu

HOST=""
APPLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done

if [ -z "$HOST" ]; then
  echo "usage: $0 --host cc|hk [--apply]" >&2
  exit 64
fi

case "$HOST" in
  cc)
    TARGET_DIR="/etc/go-command-center/keys"
    TARGET="${TARGET_DIR}/github-witness-reader.token"
    TARGET_OWNER="root:root"
    ;;
  hk)
    TARGET_DIR="/etc/go-hk-agent/keys"
    TARGET="${TARGET_DIR}/github-witness-reader.token"
    TARGET_OWNER="go-hk-agent:go-hk-agent"
    ;;
  *)
    echo "unknown host: $HOST" >&2
    exit 64
    ;;
esac

PURPOSE="GO C13/C14 Lite acceptance witness: GitHub Actions readback only"
SCOPE="repository yuguangzhi3836-glitch/GO; actions:read contents:read metadata:read"

if [ ! -d "$TARGET_DIR" ]; then
  echo "refusing: key directory does not exist: $TARGET_DIR" >&2
  exit 65
fi

echo "credential purpose : $PURPOSE"
echo "credential scope   : $SCOPE"
echo "target path        : $TARGET"
echo "target owner       : $TARGET_OWNER"
echo "target mode        : 0600"
echo "directory perms    : unchanged"
echo "services restarted : none"

if [ "$APPLY" -ne 1 ]; then
  echo "DRY_RUN=YES (pass --apply to install)"
  exit 0
fi

# Read the credential. ``read -r`` keeps backslashes literal; a second read detects
# a multi-line value, which is always a mistake.
IFS= read -r TOKEN || true
if [ -z "${TOKEN:-}" ]; then
  echo "refusing: empty credential on stdin" >&2
  exit 65
fi
if IFS= read -r EXTRA; then
  echo "refusing: credential spans multiple lines" >&2
  exit 65
fi
case "$TOKEN" in
  *[[:space:]]*) echo "refusing: credential contains whitespace" >&2; exit 65 ;;
esac

umask 077
OLD_MODE="absent"
if [ -f "$TARGET" ]; then
  OLD_MODE="$(stat -c '%a' "$TARGET")"
fi

printf '%s' "$TOKEN" > "$TARGET"
unset TOKEN
chown "$TARGET_OWNER" "$TARGET"
chmod 0600 "$TARGET"

NEW_MODE="$(stat -c '%a' "$TARGET")"
NEW_OWNER="$(stat -c '%U:%G' "$TARGET")"
NEW_SIZE="$(stat -c '%s' "$TARGET")"

echo "installed          : $TARGET"
echo "previous mode      : $OLD_MODE"
echo "new mode           : $NEW_MODE"
echo "new owner          : $NEW_OWNER"
echo "value length       : $NEW_SIZE"
echo "TOKEN_CONTENT_REDACTED=YES"

if [ "$NEW_MODE" != "600" ] || [ "$NEW_OWNER" != "$TARGET_OWNER" ]; then
  echo "refusing: installed file does not have the expected custody" >&2
  exit 65
fi

echo "NEXT: run the witness readback to prove the credential works:"
echo "  ${HOST}_probe: control-plane/c13-c14-witness/lw_readback.py --host $HOST --role c14 ..."
