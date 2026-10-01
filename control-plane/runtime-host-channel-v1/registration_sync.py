"""rt01-side runtime-host registration synchroniser.

Proposed candidate path: control-plane/runtime-host-channel-v1/registration_sync.py
Installed on the Runtime Host at:

    /opt/go/runtime-host-agent/registration_sync.py

and run periodically by `go-runtime-host-registration-sync.timer`.

Responsibilities, and nothing else:

  1. use the existing tasks READ deploy key
  2. list runtime-host-v1/registrations/
  3. consider only registrations whose body agent_id is this host's agent
  4. for each candidate verify: CC signer signature, environment, host_id,
     agent_id, action list, candidate_sha, executor_sha256 (recomputed locally
     from the installed Management Agent bundle), evidence_key_sha256 (recomputed
     locally from the installed Evidence public key), and the plan binding
  5. pick the highest valid generation
  6. only accept remote_generation >= local_generation
  7. when it is higher, atomically replace /etc/go-runtime-host/registration.json
  8. install it root:root 0600
  9. read it back and verify the signature again
 10. print a short JSON status

Refuses: any private key input, arbitrary URL, arbitrary repository, arbitrary
path, task execution, Runtime.enqueue(), and any shell influenced by remote data.

The synchroniser is deliberately a separate unit of responsibility from the
Management Agent: a failed refresh changes nothing about the task protocol, and
the Agent keeps running on the last valid signed registration.

No command line arguments are accepted.
"""
import hashlib
import json
import os
import sys
import time

from cryptography.hazmat.primitives import serialization

from adapter import protected_read
from agent_service import compute_executor_sha256
from channel import Reject, registration, verified
from git_transport import GitTransport

CONFIG_PATH = "/etc/go-runtime-host/registration-sync.json"
KEY_PREFIX = "registrations/"

# The rotator publishes every 12h and a registration is valid for at most 24h, so
# any still-usable generation is always among the newest few names. The scan is
# bounded so that a year of history cannot turn one timer tick into hundreds of
# repository clones.
MAX_CANDIDATES = 4


def emit(obj):
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")
    sys.stdout.flush()


def fail(reason, detail=""):
    emit({"status": "REFUSED", "reason": reason, "detail": str(detail)[:200]})
    return 1


def check_path(value, name):
    if not isinstance(value, str) or not value.startswith("/") or ".." in value.split("/"):
        raise Reject("config_path:%s" % name)
    return value


def check_remote(value, name):
    if not isinstance(value, str) or value.startswith("-") or "\n" in value \
            or not value.startswith("git@"):
        raise Reject("config_remote:%s" % name)
    return value


def load_config():
    cfg = json.loads(protected_read(CONFIG_PATH).decode("utf-8"))
    for key in ("environment", "host_id", "agent_id", "candidate_sha", "plan_sha256",
                "registration_path", "authority_public_path", "evidence_public_path",
                "bundle_dir", "registrations"):
        if key not in cfg:
            raise Reject("config_missing:%s" % key)
    for key in ("registration_path", "authority_public_path", "evidence_public_path",
                "bundle_dir"):
        check_path(cfg[key], key)
    block = cfg["registrations"]
    for sub in ("remote", "branch", "key", "known_hosts"):
        if sub not in block:
            raise Reject("config_missing:registrations.%s" % sub)
    check_remote(block["remote"], "registrations.remote")
    check_path(block["key"], "registrations.key")
    check_path(block["known_hosts"], "registrations.known_hosts")
    return cfg


def load_public(path):
    data = protected_read(path)
    try:
        return serialization.load_pem_public_key(data)
    except Exception:  # noqa: BLE001 -- fall back to the OpenSSH one-line form
        return serialization.load_ssh_public_key(data)


def evidence_key_sha256(public_key):
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def build_git_env(key_path, known_hosts):
    return {
        "GIT_SSH_COMMAND": "ssh -i %s -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
                           "-o UserKnownHostsFile=%s -o BatchMode=yes" % (key_path, known_hosts),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def registration_transport(cfg):
    block = cfg["registrations"]
    return GitTransport(block["remote"], block["branch"], "registrations",
                        git_env=build_git_env(block["key"], block["known_hosts"]))


def observe_local_generation(cfg, authority_public):
    """Signature-verified local generation, or (0, None) when nothing is installed.

    Expiry is intentionally not applied to the installed copy: a newer candidate
    must be able to replace a registration that has just run out.
    """
    try:
        raw = protected_read(cfg["registration_path"])
    except (Reject, OSError):
        return 0, None
    body = verified(raw, authority_public)
    generation = body.get("generation")
    if type(generation) is not int or generation < 1:
        raise Reject("local_generation")
    if (body.get("environment"), body.get("host_id"), body.get("agent_id")) != \
            (cfg["environment"], cfg["host_id"], cfg["agent_id"]):
        raise Reject("local_identity")
    return generation, raw


def candidate_bodies(cfg, authority_public, transport, expected, now):
    """Valid candidates only, newest names first, bounded scan."""
    keys = [key for key in transport.keys() if key.startswith(KEY_PREFIX)]
    keys.sort(reverse=True)
    candidates = []
    for key in keys[:MAX_CANDIDATES]:
        raw = transport.read(key)
        if raw is None:
            continue
        try:
            body = registration(raw, authority_public, now)
        except Reject:
            continue
        if (body["environment"], body["host_id"], body["agent_id"]) != \
                (cfg["environment"], cfg["host_id"], cfg["agent_id"]):
            continue
        mismatch = [field for field, value in expected.items() if body[field] != value]
        if mismatch:
            continue
        candidates.append((body["generation"], key, raw))
    return candidates


def atomic_install(path, raw):
    directory = os.path.dirname(path)
    tmp = os.path.join(directory, ".registration.json.tmp.%d" % os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.chown(tmp, 0, 0)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sync_once(cfg, transport, clock):
    authority_public = load_public(cfg["authority_public_path"])
    evidence_public = load_public(cfg["evidence_public_path"])
    executor_sha256, bundle_files = compute_executor_sha256(cfg["bundle_dir"])

    expected = {
        "candidate_sha": cfg["candidate_sha"],
        "plan_sha256": cfg["plan_sha256"],
        "executor_sha256": executor_sha256,
        "evidence_key_sha256": evidence_key_sha256(evidence_public),
    }

    local_generation, local_raw = observe_local_generation(cfg, authority_public)
    now = clock()
    candidates = candidate_bodies(cfg, authority_public, transport, expected, now)

    base = {"status": "PASS", "verb": "registration-sync",
            "environment": cfg["environment"], "host_id": cfg["host_id"],
            "agent_id": cfg["agent_id"], "local_generation": local_generation,
            "candidates": len(candidates), "executor_sha256": executor_sha256,
            "bundle_files": bundle_files}

    if not candidates:
        emit(dict(base, result="NO_CANDIDATE"))
        return 0

    generation, key, raw = max(candidates, key=lambda item: item[0])
    if generation < local_generation:
        raise Reject("rollback")
    if generation == local_generation:
        if raw != local_raw:
            raise Reject("same_generation_conflict")
        emit(dict(base, result="UP_TO_DATE", generation=generation, key=key))
        return 0

    atomic_install(cfg["registration_path"], raw)
    back = protected_read(cfg["registration_path"])
    if back != raw:
        raise Reject("readback_mismatch")
    body = registration(back, authority_public, now)
    emit(dict(base, result="UPDATED", generation=body["generation"], key=key,
              previous_generation=local_generation,
              file_sha256=hashlib.sha256(back).hexdigest(),
              issued_at=body["issued_at"], expires_at=body["expires_at"],
              readback_verified=True))
    return 0


def main(argv):
    if len(argv) != 1:
        return fail("usage", "no arguments are accepted")
    try:
        cfg = load_config()
    except Reject as exc:
        return fail("config", exc)
    except Exception as exc:  # noqa: BLE001
        return fail("config_io", type(exc).__name__)
    try:
        return sync_once(cfg, registration_transport(cfg), lambda: int(time.time()))
    except Reject as exc:
        return fail("refused", exc)
    except Exception as exc:  # noqa: BLE001 -- fail closed
        return fail("error", type(exc).__name__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
