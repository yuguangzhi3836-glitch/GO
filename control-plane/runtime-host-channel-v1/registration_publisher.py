"""CC-side long-lived runtime-host registration rotator.

Proposed candidate path: control-plane/runtime-host-channel-v1/registration_publisher.py

One invocation publishes at most ONE new immutable, authority-signed generation to

    runtime-host-v1/registrations/<agent_id>-g<generation:06d>.json

Responsibilities, and nothing else:

  1. load the fixed root-owned config
  2. load the approval / deployment binding and recompute the plan digest locally
  3. observe the durable local generation state
  4. choose the next strictly increasing generation
  5. build the runtime-host-registration body
  6. sign it with the existing CC signer
  7. self-verify it with the matching public key
  8. persist the exact signed bytes durably BEFORE any network I/O
  9. publish the immutable registration object
 10. read the object back and compare byte for byte
 11. record the generation as published only after a confirmed readback

Refuses: task publication, arbitrary action, shell, deploy, reboot, host-selector
input, URL input, Production and HK actions. The only registration action is the
module constant channel.ACTION == 'RUNTIME_HOST_PROBE_V1'.

No command line arguments are accepted. Every path, remote and binding value comes
from the protected root-owned config files, never from a caller.

An unfinished publication is reconciled against the stored bytes: if the object is
still absent the identical key and the identical byte string are retried, and the
generation is never advanced on an unconfirmed write. One generation, one
signature, one immutable key, one exact byte string -- network retry is allowed,
semantic regeneration is not.
"""
import base64
import hashlib
import json
import os
import sys
import time

from cryptography.hazmat.primitives import serialization

from channel import ACTION, Reject, digest, identifier, registration, signed
from git_transport import GitTransport

CONFIG_DIR = "/etc/go-command-center/runtime-host-v1"
PUBLISHER_JSON = CONFIG_DIR + "/publisher.json"
APPROVAL_JSON = CONFIG_DIR + "/approval.json"
PLAN_JSON = CONFIG_DIR + "/install-plan.json"
KNOWN_HOSTS = CONFIG_DIR + "/github.com.known_hosts"
STATE_DIR = "/var/lib/go-command-center/runtime-host-v1"
GENERATION_STATE = STATE_DIR + "/registration-generation.json"

# Protocol maximum. The rotator never issues a longer window and never removes the
# channel.registration() ceiling; it stays at the 24h bound the contract allows.
REGISTRATION_LIFETIME_SECONDS = 86400
STATE_VERSION = 1
KEY_PREFIX = "registrations/"
PENDING_STATES = ("PREPARED", "ATTEMPTED")


def emit(obj):
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")
    sys.stdout.flush()


def die(reason, detail=""):
    emit({"status": "FAIL", "reason": reason, "detail": str(detail)[:200]})
    sys.exit(1)


def read_json(path):
    with open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def now_ts():
    return int(time.time())


def load_config():
    cfg = read_json(PUBLISHER_JSON)
    required = ("environment", "host_id", "agent_id", "candidate_sha", "plan_sha256",
                "executor_sha256", "evidence_key_sha256", "approval_ref",
                "required_approval_status", "deployment_first_generation",
                "signer_private_key", "signer_public_key", "tasks")
    for key in required:
        if key not in cfg:
            die("config_missing", key)
    for key in ("environment", "host_id", "agent_id", "approval_ref"):
        try:
            identifier(cfg[key])
        except Reject as exc:
            die("config_identifier", "%s:%s" % (key, exc))
    if not 0 < REGISTRATION_LIFETIME_SECONDS <= 86400:
        die("lifetime")
    first = cfg["deployment_first_generation"]
    if type(first) is not int or first < 1:
        die("config_first_generation", repr(first))
    status = cfg["required_approval_status"]
    if not isinstance(status, str) or not status.startswith("HUMAN_APPROVED"):
        die("config_approval_status", repr(status))
    block = cfg["tasks"]
    if not isinstance(block, dict):
        die("config_transport")
    for sub in ("remote", "branch", "key"):
        if sub not in block:
            die("config_missing", "tasks.%s" % sub)
    return cfg


def load_signer(cfg, private=False):
    path = cfg["signer_private_key"] if private else cfg["signer_public_key"]
    with open(path, "rb") as fh:
        data = fh.read()
    if private:
        return serialization.load_pem_private_key(data, password=None)
    try:
        return serialization.load_pem_public_key(data)
    except Exception:  # noqa: BLE001 -- fall back to the OpenSSH one-line form
        return serialization.load_ssh_public_key(data)


def git_env(key_path):
    return {
        "GIT_SSH_COMMAND": "ssh -i %s -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
                           "-o UserKnownHostsFile=%s -o BatchMode=yes" % (key_path, KNOWN_HOSTS),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def registration_transport(cfg):
    """Same repository and branch as the task channel, append-only namespace."""
    block = cfg["tasks"]
    return GitTransport(block["remote"], block["branch"], "registrations",
                        git_env=git_env(block["key"]))


def check_binding(cfg, approval, plan, plan_bytes):
    """Recompute everything locally; refuse on the first mismatch."""
    recomputed_plan = hashlib.sha256(plan_bytes).hexdigest()
    if recomputed_plan != cfg["plan_sha256"]:
        die("plan_sha256_recompute_mismatch", recomputed_plan)
    binding = approval.get("binding")
    if not isinstance(binding, dict):
        die("approval_binding_shape")
    for field, expected in (("plan_sha256", recomputed_plan),
                            ("executor_sha256", cfg["executor_sha256"]),
                            ("evidence_key_sha256", cfg["evidence_key_sha256"]),
                            ("candidate", cfg["candidate_sha"]),
                            ("environment", cfg["environment"]),
                            ("host_id", cfg["host_id"]),
                            ("agent_id", cfg["agent_id"])):
        if binding.get(field) != expected:
            die("approval_%s_mismatch" % field)
    if approval.get("approval_ref") != cfg["approval_ref"]:
        die("approval_ref_mismatch")
    status = approval.get("approval_status")
    if status != cfg["required_approval_status"] or not str(status).startswith("HUMAN_APPROVED"):
        die("approval_status")
    if plan.get("environment") != cfg["environment"] or plan.get("host_id") != cfg["host_id"] \
            or plan.get("agent_id") != cfg["agent_id"]:
        die("plan_identity_mismatch")
    if (plan.get("candidate") or {}).get("sha") != cfg["candidate_sha"]:
        die("plan_candidate_mismatch")
    if (plan.get("management_agent") or {}).get("executor_sha256") != cfg["executor_sha256"]:
        die("plan_executor_mismatch")
    if (plan.get("evidence_key") or {}).get("evidence_key_sha256") != cfg["evidence_key_sha256"]:
        die("plan_evidence_key_mismatch")
    return recomputed_plan


# ---- durable generation state ------------------------------------------------

def bootstrap_state(cfg):
    return {"version": STATE_VERSION,
            "environment": cfg["environment"],
            "host_id": cfg["host_id"],
            "agent_id": cfg["agent_id"],
            # nothing published by this rotator yet; the floor comes from config
            "last_generation": cfg["deployment_first_generation"] - 1,
            "pending": None}


def save_state(state):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    tmp = GENERATION_STATE + ".tmp.%d" % os.getpid()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, GENERATION_STATE)
    os.chmod(GENERATION_STATE, 0o600)


def load_state(cfg):
    if not os.path.exists(GENERATION_STATE):
        return bootstrap_state(cfg)
    state = read_json(GENERATION_STATE)
    for key in ("version", "environment", "host_id", "agent_id", "last_generation", "pending"):
        if key not in state:
            die("state_missing", key)
    if state["version"] != STATE_VERSION:
        die("state_version", repr(state["version"]))
    if (state["environment"], state["host_id"], state["agent_id"]) != \
            (cfg["environment"], cfg["host_id"], cfg["agent_id"]):
        die("state_identity_mismatch")
    if type(state["last_generation"]) is not int or state["last_generation"] < 1:
        die("state_generation", repr(state["last_generation"]))
    # A generation may never move backwards, and it may never fall below the
    # configured deployment floor.
    if state["last_generation"] < cfg["deployment_first_generation"] - 1:
        die("state_generation_rollback", state["last_generation"])
    pending = state["pending"]
    if pending is not None:
        if not isinstance(pending, dict) or pending.get("state") not in PENDING_STATES:
            die("state_pending_shape")
    return state


def build_body(cfg, generation, now):
    return {
        "version": 1,
        "kind": "runtime-host-registration",
        "environment": cfg["environment"],
        "host_id": cfg["host_id"],
        "agent_id": cfg["agent_id"],
        "generation": generation,
        "candidate_sha": cfg["candidate_sha"],
        "plan_sha256": cfg["plan_sha256"],
        "executor_sha256": cfg["executor_sha256"],
        "evidence_key_sha256": cfg["evidence_key_sha256"],
        "approval_ref": cfg["approval_ref"],
        "issued_at": now,
        "expires_at": now + REGISTRATION_LIFETIME_SECONDS,
        "actions": [ACTION],
    }


# ---- rotation ----------------------------------------------------------------

def resolve_pending(state, transport):
    """Reconcile an unfinished publication using the already-stored bytes.

    The pending entry holds one generation, one signature, one immutable key and one
    exact byte string. The identical bytes may be pushed again when the object is
    still absent; nothing is ever re-signed, re-based or re-generated.
    """
    pending = state["pending"]
    raw = base64.b64decode(pending["raw"])
    if hashlib.sha256(raw).hexdigest() != pending["file_sha256"]:
        die("state_bytes_mismatch", pending["generation"])

    remote = transport.read(pending["key"])
    retried = False
    if remote is None:
        # Retry the identical key and byte string. A repeat of the same bytes is
        # idempotent in the transport; a different body would not be.
        retried = True
        transport.create(pending["key"], raw)
        remote = transport.read(pending["key"])

    if remote is None:
        # Nothing was published. Leave the pending entry exactly as it is.
        die("publication_still_absent", pending["generation"])
    if remote != raw:
        # Something else is at that key. Never overwrite it and never advance.
        die("publication_conflict", pending["generation"])

    state["last_generation"] = pending["generation"]
    state["pending"] = None
    save_state(state)
    emit({"status": "PASS", "verb": "resolve-pending",
          "generation": state["last_generation"], "key": pending["key"],
          "file_sha256": pending["file_sha256"], "readback_identical": True,
          "retried_identical_bytes": retried,
          "last_generation": state["last_generation"]})
    return 0


def rotate(cfg, transport, clock):
    with open(PLAN_JSON, "rb") as fh:
        plan_bytes = fh.read()
    plan = json.loads(plan_bytes.decode("utf-8"))
    approval = read_json(APPROVAL_JSON)
    recomputed_plan = check_binding(cfg, approval, plan, plan_bytes)

    state = load_state(cfg)
    if state["pending"] is not None:
        return resolve_pending(state, transport)

    now = clock()
    generation = max(state["last_generation"] + 1, cfg["deployment_first_generation"])
    body = build_body(cfg, generation, now)
    raw = signed(body, load_signer(cfg, private=True))

    # Self-verify with the matching public key before anything is persisted.
    verified_body = registration(raw, load_signer(cfg, private=False), now)

    key = "%s%s-g%06d.json" % (KEY_PREFIX, cfg["agent_id"], generation)
    state["pending"] = {"generation": generation, "key": key,
                        "digest": digest(verified_body),
                        "file_sha256": hashlib.sha256(raw).hexdigest(),
                        "raw": base64.b64encode(raw).decode("ascii"),
                        "state": "PREPARED"}
    # Durable exact bytes strictly before any network I/O.
    save_state(state)
    state["pending"]["state"] = "ATTEMPTED"
    save_state(state)

    transport.create(key, raw)
    remote = transport.read(key)
    if remote is None:
        # The pending entry survives; the next tick retries the identical bytes.
        die("publication_unresolved", generation)
    if remote != raw:
        die("publication_conflict", generation)

    state["last_generation"] = generation
    state["pending"] = None
    save_state(state)
    emit({"status": "PASS", "verb": "publish-registration",
          "generation": generation, "key": key,
          "registration_sha256": digest(verified_body),
          "file_sha256": hashlib.sha256(raw).hexdigest(),
          "bytes": len(raw),
          "issued_at": verified_body["issued_at"],
          "expires_at": verified_body["expires_at"],
          "actions": verified_body["actions"],
          "approval_ref": verified_body["approval_ref"],
          "plan_sha256_recomputed": recomputed_plan,
          "readback_identical": True,
          "self_verified": True,
          "last_generation": state["last_generation"]})
    return 0


def main(argv):
    if len(argv) != 1:
        die("usage", "no arguments are accepted")
    if not 0 < REGISTRATION_LIFETIME_SECONDS <= 86400:
        die("lifetime")
    cfg = load_config()
    return rotate(cfg, registration_transport(cfg), now_ts)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Reject as exc:
        die("refused", exc)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- fail closed
        die("error", type(exc).__name__ + ":" + str(exc)[:120])
