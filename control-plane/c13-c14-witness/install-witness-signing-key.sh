#!/bin/bash
# Install the C13/C14 Lite witness Ed25519 signing key.
#
#   bash install-witness-signing-key.sh --host cc [--apply] [--force]
#
# Requires bash and openssl. Generation happens **on this host**: the key is never
# generated elsewhere and copied here, and it is never copied off this host.
#
# The private half is written straight to its final path with its final permissions.
# It is never printed, echoed, logged, written to a temporary file, or passed on a
# command line. Only public facts are reported: the key id, the fingerprint, the public
# key and the paths.
#
# This script does not restart a service, does not touch any other key, and does not
# change the key directory's permissions. If nothing needs a restart to pick the key up,
# nothing is restarted.
set -eu

HOST=""
APPLY=0
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done

if [ -z "$HOST" ]; then
  echo "usage: $0 --host cc|hk [--apply] [--force]" >&2
  exit 64
fi

# Custody is derived from the host's own systemd configuration and from the key
# directory's existing contents, not guessed:
#
#   CC  /etc/go-command-center/keys is 0700 root:root, and the unit that reads it
#       (go-boss-request-bridge.service) runs as User=root Group=root. The existing
#       signing key in that directory, task-manifest-signing.pem, is root:root 0600.
#   HK  /etc/go-hk-agent/keys is 0700 go-hk-agent:go-hk-agent, and the unit that reads
#       it (go-hk-agent.service) runs as User=go-hk-agent Group=go-hk-agent. The
#       existing signing key, evidence-signing.pem, is go-hk-agent:go-hk-agent 0600,
#       and its public counterpart evidence-signing.pub is root:go-hk-agent 0640.
case "$HOST" in
  cc)
    KEY_DIR="/etc/go-command-center/keys"
    PRIVATE_NAME="c13-c14-witness-ed25519.pem"
    PUBLIC_NAME="c13-c14-witness-ed25519.pub"
    PRIVATE_OWNER="root:root"
    PUBLIC_OWNER="root:root"
    PUBLIC_MODE="0644"
    PURPOSE="c13c14-acceptance-witness"
    CONSUMER="go-boss-request-bridge.service (User=root Group=root)"
    ;;
  hk)
    KEY_DIR="/etc/go-hk-agent/keys"
    PRIVATE_NAME="c13-c14-witness-ed25519.pem"
    PUBLIC_NAME="c13-c14-witness-ed25519.pub"
    PRIVATE_OWNER="go-hk-agent:go-hk-agent"
    PUBLIC_OWNER="root:go-hk-agent"
    PUBLIC_MODE="0640"
    PURPOSE="c13c14-acceptance-witness-hk"
    CONSUMER="go-hk-agent.service (User=go-hk-agent Group=go-hk-agent)"
    ;;
  *)
    echo "unknown host: $HOST" >&2
    exit 64 ;;
esac

PRIVATE_PATH="${KEY_DIR}/${PRIVATE_NAME}"
PUBLIC_PATH="${KEY_DIR}/${PUBLIC_NAME}"

if [ ! -d "$KEY_DIR" ]; then
  echo "refusing: key directory does not exist: $KEY_DIR" >&2
  exit 65
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "refusing: openssl not found" >&2
  exit 65
fi

# Check the intended owner before generating anything. Discovering a missing user after
# the private key is already on disk would leave it with the wrong custody, and the
# obvious "fix it afterwards" is exactly how a key ends up briefly world-readable.
for pair in "$PRIVATE_OWNER" "$PUBLIC_OWNER"; do
  owner_user="${pair%%:*}"
  owner_group="${pair##*:}"
  if ! getent passwd "$owner_user" >/dev/null 2>&1; then
    echo "refusing: user does not exist: $owner_user" >&2
    exit 65
  fi
  if ! getent group "$owner_group" >/dev/null 2>&1; then
    echo "refusing: group does not exist: $owner_group" >&2
    exit 65
  fi
done
unset owner_user owner_group pair

echo "purpose            : $PURPOSE"
echo "algorithm          : Ed25519 (PKCS8 PEM, unencrypted)"
echo "generated on       : this host ($(hostname)) - never copied in from elsewhere"
echo "private path       : $PRIVATE_PATH"
echo "private custody    : $PRIVATE_OWNER 0600"
echo "public path        : $PUBLIC_PATH"
echo "public custody     : $PUBLIC_OWNER $PUBLIC_MODE (OpenSSH format)"
echo "consuming unit     : $CONSUMER"
echo "other keys touched : none"
echo "key dir perms      : unchanged"
echo "services restarted : none"

if [ -e "$PRIVATE_PATH" ] || [ -e "$PUBLIC_PATH" ]; then
  if [ "$FORCE" -ne 1 ]; then
    echo "refusing: a witness key already exists at this path." >&2
    echo "          Regenerating would invalidate every record signed with it." >&2
    echo "          Pass --force only if you intend to rotate and re-witness." >&2
    exit 65
  fi
  echo "note: --force given; an existing key will be replaced"
fi

if [ "$APPLY" -ne 1 ]; then
  echo "DRY_RUN=YES (pass --apply to generate and install)"
  exit 0
fi

umask 077
openssl genpkey -algorithm ED25519 -out "$PRIVATE_PATH" 2>/dev/null
chown "$PRIVATE_OWNER" "$PRIVATE_PATH"
chmod 0600 "$PRIVATE_PATH"

# Derive the public half and write it in the directory's existing .pub format, which is
# OpenSSH for both hosts. A private temporary file is avoided: the public key is derived
# and written in one step.
python3 - "$PRIVATE_PATH" "$PUBLIC_PATH" <<'PY'
import pathlib
import sys

from cryptography.hazmat.primitives import serialization

private_path, public_path = sys.argv[1], sys.argv[2]
private = serialization.load_pem_private_key(pathlib.Path(private_path).read_bytes(), password=None)
public = private.public_key()
openssh = public.public_bytes(serialization.Encoding.OpenSSH,
                              serialization.PublicFormat.OpenSSH)
pathlib.Path(public_path).write_bytes(openssh + b"\n")
PY

chown "$PUBLIC_OWNER" "$PUBLIC_PATH"
chmod "$PUBLIC_MODE" "$PUBLIC_PATH"

# Prove the two halves belong together before reporting success: a mismatch here would
# mean the file on disk is not the key the witness will sign with.
python3 - "$PRIVATE_PATH" "$PUBLIC_PATH" <<'PY'
import hashlib
import pathlib
import sys

from cryptography.hazmat.primitives import serialization

private_path, public_path = sys.argv[1], sys.argv[2]
private = serialization.load_pem_private_key(pathlib.Path(private_path).read_bytes(), password=None)
from_private = private.public_key().public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
from_public = serialization.load_ssh_public_key(
    pathlib.Path(public_path).read_bytes().strip()).public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

print("private algo       :", private.__class__.__name__)
print("public algo        :", serialization.load_ssh_public_key(
    pathlib.Path(public_path).read_bytes().strip()).__class__.__name__)
print("halves agree       :", "YES" if from_private == from_public else "NO")
print("key_id             :", hashlib.sha256(from_private).hexdigest()[:16])
print("fingerprint        : sha256:" + hashlib.sha256(from_private).hexdigest())
print("public key (OpenSSH):", pathlib.Path(public_path).read_text().strip())
if from_private != from_public:
    raise SystemExit("refusing: the derived public key does not match the private key")
PY

PRIV_MODE="$(stat -c '%a' "$PRIVATE_PATH")"
PRIV_OWNER_NOW="$(stat -c '%U:%G' "$PRIVATE_PATH")"
PUB_MODE="$(stat -c '%a' "$PUBLIC_PATH")"
PUB_OWNER_NOW="$(stat -c '%U:%G' "$PUBLIC_PATH")"

echo "installed private  : $PRIV_OWNER_NOW $PRIV_MODE"
echo "installed public   : $PUB_OWNER_NOW $PUB_MODE"
echo "PRIVATE_KEY_PRINTED=NO"
echo "PRIVATE_KEY_COPIED=NO"
echo "NEXT: run lw_keycheck.py --host $HOST to prove the algorithm, the derivation, the"
echo "      key id, a real signature and a tamper rejection."
