#!/bin/bash
# Install the CC / HK GitHub witness credential.
#
# Requires bash, because the interactive path needs `read -s` to suppress echo and
# `read -s` is not POSIX. `/bin/sh` on the target hosts is dash and would fail.
#
# The credential is read from STDIN only. It is never taken from argv, never
# echoed, never written to a log, and never placed in shell history. Run it on the
# target host as root:
#
#   sudo bash install-github-witness-credential.sh --host cc --apply
#   (paste the token, then press Enter - input is not echoed)
#
# or, if the value already lives in a file you control:
#
#   sudo bash install-github-witness-credential.sh --host cc --apply < /path/to/secret
#
# Without --apply it prints the plan and changes nothing.
#
# Scope of this script: create/replace exactly one file, with the mode and owner the
# witness expects. It does not restart a service, does not touch the key directory's
# permissions, and does not modify any other credential.
set -eu

HOST=""
APPLY=0
VERIFY=1

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --no-verify) VERIFY=0; shift ;;
    --verify) VERIFY=1; shift ;;
    -h|--help)
      sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
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

# Read the credential. Two modes, because the two ways of running this script carry
# different risks:
#
#   interactive (stdin is a TTY)
#       Echo is disabled with `stty -echo` BEFORE the prompt is printed, and restored
#       afterwards including on a signal. `read -s` alone is not enough: it only
#       disables echo for the duration of the read, so bytes that reach the terminal
#       before the read starts are already echoed by the line discipline. Turning echo
#       off first closes that window. Exactly one line is read: an interactive user
#       ends the value with Enter, and a second read would block.
#
#   piped (stdin is a file or pipe)
#       Read the line, then require end-of-input. A piped value that continues on a
#       second line is a mistake, not a credential.
if [ -t 0 ]; then
  SAVED_STTY=""
  if command -v stty >/dev/null 2>&1; then
    SAVED_STTY="$(stty -g 2>/dev/null || true)"
  fi
  restore_echo() {
    if [ -n "${SAVED_STTY:-}" ]; then
      stty "$SAVED_STTY" 2>/dev/null || true
    fi
  }
  if [ -n "$SAVED_STTY" ]; then
    stty -echo 2>/dev/null || true
    trap restore_echo EXIT INT TERM
  fi
  printf 'paste the token, then press Enter. Input is NOT echoed: ' >&2
  IFS= read -r TOKEN || true
  restore_echo
  trap - EXIT INT TERM
  printf '\n' >&2
  INTERACTIVE=1
else
  IFS= read -r TOKEN || true
  INTERACTIVE=0
fi

if [ -z "${TOKEN:-}" ]; then
  echo "refusing: empty credential (nothing on stdin)" >&2
  exit 65
fi
if [ "$INTERACTIVE" -eq 0 ]; then
  if IFS= read -r EXTRA; then
    echo "refusing: credential spans multiple lines" >&2
    exit 65
  fi
fi

# Strip anything a terminal or paste mode may have injected.
#
# A GitHub credential value is [A-Za-z0-9_] and nothing else, so any other byte is an
# artefact. This is not hypothetical: the first real install of this script stored a
# value with a stray ESC (0x1b) in front of it, which GitHub answered with
# "401 Bad credentials" - a message that points at the credential rather than at the
# paste, with nothing visible in the terminal to explain it. The count of removed
# characters is reported, so the removal is never silent.
#
# Bracketed-paste markers are removed first and whole. Leaving them to the general
# filter would keep their digits ("[200~" -> "200") and produce a value that fails the
# prefix check - correct to refuse, but a worse outcome than simply unwrapping it.
TOKEN="${TOKEN//$'\x1b'\[200~/}"
TOKEN="${TOKEN//$'\x1b'\[201~/}"
CLEANED="$(printf '%s' "$TOKEN" | tr -cd 'A-Za-z0-9_')"
REMOVED=$(( ${#TOKEN} - ${#CLEANED} ))
if [ "$REMOVED" -gt 0 ]; then
  echo "note: removed $REMOVED non-credential character(s) injected by the terminal" >&2
fi
TOKEN="$CLEANED"
unset CLEANED

case "$TOKEN" in
  github_pat_*|ghp_*|gho_*|ghu_*|ghs_*|ghr_*) ;;
  *) echo "refusing: value does not start with a known GitHub credential prefix" >&2
     exit 65 ;;
esac
if [ "${#TOKEN}" -lt 20 ]; then
  echo "refusing: value is too short to be a credential (${#TOKEN} characters)" >&2
  exit 65
fi

umask 077
OLD_MODE="absent"
if [ -f "$TARGET" ]; then
  OLD_MODE="$(stat -c '%a' "$TARGET")"
fi

printf '%s' "$TOKEN" > "$TARGET"
chown "$TARGET_OWNER" "$TARGET"
chmod 0600 "$TARGET"

# Read it back and compare before letting go of the expected value. The point is to
# catch a write that did not round-trip - nothing here should be able to change the
# value, so a mismatch means the filesystem or the shell did something unexpected.
INSTALLED="$(cat "$TARGET")"
if [ "$INSTALLED" != "$TOKEN" ]; then
  echo "refusing: the installed value does not round-trip" >&2
  exit 65
fi
unset INSTALLED

# Optional end-to-end check: does GitHub accept this credential, and can it see the
# repository? Reported as status codes only; the value is never printed or logged.
VERIFY_RESULT="not requested"
if [ "$VERIFY" -eq 1 ]; then
  BEARER="$TOKEN"
  if command -v curl >/dev/null 2>&1; then
    USER_CODE="$(curl -s -o /dev/null -m 20 -w '%{http_code}' \
      -H "Authorization: Bearer $BEARER" -H 'Accept: application/vnd.github+json' \
      -H 'User-Agent: go-witness-install' https://api.github.com/user || echo 000)"
    REPO_CODE="$(curl -s -o /dev/null -m 20 -w '%{http_code}' \
      -H "Authorization: Bearer $BEARER" -H 'Accept: application/vnd.github+json' \
      -H 'User-Agent: go-witness-install' \
      https://api.github.com/repos/yuguangzhi3836-glitch/GO || echo 000)"
    echo "verify  GET /user               : $USER_CODE"
    echo "verify  GET /repos/<GO>         : $REPO_CODE"
    case "$USER_CODE:$REPO_CODE" in
      200:200) VERIFY_RESULT="PASS" ;;
      401:*)   VERIFY_RESULT="FAIL_CREDENTIAL_REJECTED" ;;
      200:404) VERIFY_RESULT="FAIL_REPOSITORY_OUT_OF_SCOPE" ;;
      000:*)   VERIFY_RESULT="SKIPPED_NETWORK" ;;
      *)       VERIFY_RESULT="INCONCLUSIVE" ;;
    esac
  else
    VERIFY_RESULT="SKIPPED_NO_CURL"
  fi
fi
unset TOKEN

NEW_MODE="$(stat -c '%a' "$TARGET")"
NEW_OWNER="$(stat -c '%U:%G' "$TARGET")"
NEW_SIZE="$(stat -c '%s' "$TARGET")"

echo "installed          : $TARGET"
echo "previous mode      : $OLD_MODE"
echo "new mode           : $NEW_MODE"
echo "new owner          : $NEW_OWNER"
echo "value length       : $NEW_SIZE"
echo "value round-trips  : YES"
echo "token  echoed      : NO"
echo "token  committed   : NO"
echo "TOKEN_CONTENT_REDACTED=YES"
echo "VERIFY             : $VERIFY_RESULT"

if [ "$NEW_MODE" != "600" ] || [ "$NEW_OWNER" != "$TARGET_OWNER" ]; then
  echo "refusing: installed file does not have the expected custody" >&2
  exit 65
fi

case "$VERIFY_RESULT" in
  FAIL_*) echo "the credential is installed but GitHub rejected it: re-check the token and re-run" >&2
          exit 65 ;;
esac

echo "NEXT: run the witness readback to prove the credential works:"
echo "  ${HOST}_probe: control-plane/c13-c14-witness/lw_readback.py --host $HOST --role c14 ..."
