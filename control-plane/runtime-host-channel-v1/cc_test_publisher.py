"""Minimal CC-side test publisher for the runtime-host test channel.

Proposed candidate path: control-plane/runtime-host-channel-v1/cc_test_publisher.py
This round it is installed as a LOCAL TEST PATCH. It does not touch the existing
Boss Request bridge and does not extend the legacy 6-action enum.

Exactly three fixed verbs, nothing else:

    sign-registration   build + sign the runtime-host registration, self-verify, persist
    publish-one-probe   build + sign + durably publish exactly ONE RUNTIME_HOST_PROBE_V1 task
    collect-evidence    read back and fully verify the Evidence receipt

Refuses: arbitrary action / target / shell / service / URL / deploy / reboot arguments.
The only task action is the module constant channel.ACTION == 'RUNTIME_HOST_PROBE_V1'.
"""
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time

from cryptography.hazmat.primitives import serialization

from channel import (ACTION, Reject, canonical, decode, digest, registration,
                     signed, verify_evidence, verified)
from git_transport import GitTransport

CONFIG_DIR = "/etc/go-command-center/runtime-host-v1"
PUBLISHER_JSON = CONFIG_DIR + "/publisher.json"
APPROVAL_JSON = CONFIG_DIR + "/approval.json"
PLAN_JSON = CONFIG_DIR + "/install-plan.json"
KNOWN_HOSTS = CONFIG_DIR + "/github.com.known_hosts"
REGISTRATION_OUT = "/var/lib/go-command-center/runtime-host-v1/registration.json"
STATE_DIR = "/var/lib/go-command-center/runtime-host-v1"
OUTBOX_DB = STATE_DIR + "/outbox.db"

VERBS = ("sign-registration", "publish-one-probe", "collect-evidence")


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


def load_publisher():
    cfg = read_json(PUBLISHER_JSON)
    required = ("environment", "host_id", "agent_id", "candidate_sha", "plan_sha256",
                "executor_sha256", "evidence_key_sha256", "approval_ref", "generation",
                "signer_private_key", "signer_public_key", "tasks", "evidence",
                "registration_max_lifetime_seconds")
    for key in required:
        if key not in cfg:
            die("config_missing", key)
    if cfg["registration_max_lifetime_seconds"] > 86400:
        die("config_lifetime")
    return cfg


def load_signer(cfg, private=False):
    path = cfg["signer_private_key"] if private else cfg["signer_public_key"]
    with open(path, "rb") as fh:
        data = fh.read()
    if private:
        return serialization.load_pem_private_key(data, password=None)
    try:
        return serialization.load_pem_public_key(data)
    except Exception:  # noqa: BLE001
        return serialization.load_ssh_public_key(data)


def load_evidence_public():
    with open(CONFIG_DIR + "/evidence.pub", "rb") as fh:
        return serialization.load_pem_public_key(fh.read())


def git_env(key_path):
    return {
        "GIT_SSH_COMMAND": "ssh -i %s -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
                           "-o UserKnownHostsFile=%s -o BatchMode=yes" % (key_path, KNOWN_HOSTS),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def transport(cfg, kind):
    block = cfg[kind]
    return GitTransport(block["remote"], block["branch"], kind, git_env=git_env(block["key"]))


def check_binding(cfg, approval, plan):
    """Recompute everything locally; refuse on the first mismatch."""
    plan_bytes = open(PLAN_JSON, "rb").read()
    recomputed_plan = hashlib.sha256(plan_bytes).hexdigest()
    if recomputed_plan != cfg["plan_sha256"]:
        die("plan_sha256_recompute_mismatch", recomputed_plan)
    if approval["binding"]["plan_sha256"] != recomputed_plan:
        die("approval_plan_mismatch")
    if approval["binding"]["executor_sha256"] != cfg["executor_sha256"]:
        die("approval_executor_mismatch")
    if approval["binding"]["evidence_key_sha256"] != cfg["evidence_key_sha256"]:
        die("approval_evidence_key_mismatch")
    if approval["binding"]["candidate"] != cfg["candidate_sha"]:
        die("approval_candidate_mismatch")
    if approval["binding"]["environment"] != cfg["environment"]:
        die("approval_environment_mismatch")
    if approval["binding"]["host_id"] != cfg["host_id"]:
        die("approval_host_mismatch")
    if approval["binding"]["agent_id"] != cfg["agent_id"]:
        die("approval_agent_mismatch")
    if approval["approval_ref"] != cfg["approval_ref"]:
        die("approval_ref_mismatch")
    if approval["approval_status"] != "HUMAN_APPROVED_BOUNDED_TEST":
        die("approval_status")
    if plan["environment"] != cfg["environment"] or plan["host_id"] != cfg["host_id"] \
            or plan["agent_id"] != cfg["agent_id"]:
        die("plan_identity_mismatch")
    if plan["candidate"]["sha"] != cfg["candidate_sha"]:
        die("plan_candidate_mismatch")
    if plan["management_agent"]["executor_sha256"] != cfg["executor_sha256"]:
        die("plan_executor_mismatch")
    if plan["evidence_key"]["evidence_key_sha256"] != cfg["evidence_key_sha256"]:
        die("plan_evidence_key_mismatch")
    return recomputed_plan


def cmd_sign_registration(cfg):
    approval = read_json(APPROVAL_JSON)
    plan = read_json(PLAN_JSON)
    recomputed_plan = check_binding(cfg, approval, plan)

    now = now_ts()
    body = {
        "version": 1,
        "kind": "runtime-host-registration",
        "environment": cfg["environment"],
        "host_id": cfg["host_id"],
        "agent_id": cfg["agent_id"],
        "generation": cfg["generation"],
        "candidate_sha": cfg["candidate_sha"],
        "plan_sha256": cfg["plan_sha256"],
        "executor_sha256": cfg["executor_sha256"],
        "evidence_key_sha256": cfg["evidence_key_sha256"],
        "approval_ref": cfg["approval_ref"],
        "issued_at": now,
        "expires_at": now + cfg["registration_max_lifetime_seconds"],
        "actions": [ACTION],
    }
    raw = signed(body, load_signer(cfg, private=True))

    # self-verify with the public key before persisting
    pub = load_signer(cfg, private=False)
    verified_body = registration(raw, pub, now)

    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    if os.path.exists(REGISTRATION_OUT):
        die("registration_exists_refuse_overwrite")
    fd = os.open(REGISTRATION_OUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)

    with open(REGISTRATION_OUT, "rb") as fh:
        stored = fh.read()
    if stored != raw:
        die("registration_readback_mismatch")

    emit({"status": "PASS", "verb": "sign-registration",
          "registration_sha256": digest(verified_body),
          "file_sha256": hashlib.sha256(raw).hexdigest(),
          "bytes": len(raw),
          "path": REGISTRATION_OUT,
          "generation": verified_body["generation"],
          "issued_at": verified_body["issued_at"],
          "expires_at": verified_body["expires_at"],
          "actions": verified_body["actions"],
          "plan_sha256_recomputed": recomputed_plan,
          "self_verified": True})


class Outbox:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS outbox (
            task_id TEXT PRIMARY KEY, task_digest TEXT, raw BLOB, state TEXT, created_at INTEGER)""")

    def existing(self):
        return self.db.execute("SELECT task_id,state FROM outbox").fetchall()

    def prepare(self, task_id, task_digest, raw):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM outbox").fetchone():
                raise Reject("second_task_refused")
            self.db.execute("INSERT INTO outbox VALUES (?,?,?,?,?)",
                            (task_id, task_digest, raw, "PREPARED", now_ts()))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def mark_attempted(self, task_id):
        self.db.execute("UPDATE outbox SET state='ATTEMPTED' WHERE task_id=? AND state='PREPARED'",
                        (task_id,))

    def mark_published(self, task_id):
        self.db.execute("UPDATE outbox SET state='PUBLISHED' WHERE task_id=? AND state='ATTEMPTED'",
                        (task_id,))

    def get(self, task_id=None):
        if task_id:
            return self.db.execute("SELECT task_id,task_digest,raw,state FROM outbox WHERE task_id=?",
                                   (task_id,)).fetchone()
        return self.db.execute("SELECT task_id,task_digest,raw,state FROM outbox LIMIT 1").fetchone()


def cmd_publish_one_probe(cfg):
    registration_raw = open(REGISTRATION_OUT, "rb").read()
    reg = registration(registration_raw, load_signer(cfg, private=False), now_ts())

    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    outbox = Outbox(OUTBOX_DB)
    if outbox.existing():
        die("task_already_published_refuse_second")

    now = now_ts()
    task_id = "rh-probe-" + secrets.token_hex(8)
    nonce = secrets.token_hex(24)
    task = {
        "version": 1,
        "kind": "runtime-host-task",
        "task_id": task_id,
        "nonce": nonce,
        "environment": reg["environment"],
        "host_id": reg["host_id"],
        "agent_id": reg["agent_id"],
        "generation": reg["generation"],
        "registration_sha256": digest(reg),
        "action": ACTION,
        "parameters": {},
        "issued_at": now,
        "expires_at": min(now + 300, reg["expires_at"]),
    }
    raw = signed(task, load_signer(cfg, private=True))
    task_digest = digest(task)

    outbox.prepare(task_id, task_digest, raw)
    key = "tasks/" + task_id + ".json"

    # durable ATTEMPTED strictly before any network I/O
    outbox.mark_attempted(task_id)
    tasks = transport(cfg, "tasks")
    state = outbox.get(task_id)[3]
    if state == "ATTEMPTED":
        tasks.create(key, raw)
    remote = tasks.read(key)
    if remote is None:
        die("publication_unresolved_no_retry")
    if remote != raw:
        die("publication_conflict")
    outbox.mark_published(task_id)

    emit({"status": "PASS", "verb": "publish-one-probe", "task_id": task_id,
          "task_sha256": task_digest, "key": "runtime-host-v1/" + key,
          "outbox_state": outbox.get(task_id)[3], "action": ACTION,
          "expires_at": task["expires_at"], "readback_identical": True})


def cmd_collect_evidence(cfg):
    registration_raw = open(REGISTRATION_OUT, "rb").read()
    reg = registration(registration_raw, load_signer(cfg, private=False), now_ts())

    outbox = Outbox(OUTBOX_DB)
    row = outbox.get()
    if not row:
        die("no_task_in_outbox")
    task_id, task_digest, raw_task, state = row
    if state != "PUBLISHED":
        die("task_not_published", state)
    task = verified(raw_task, load_signer(cfg, private=False))

    evidence = transport(cfg, "evidence")
    dest = "evidence/" + task_id + ".json"
    raw = evidence.read(dest)
    if raw is None:
        die("evidence_pending")

    result = verify_evidence(raw, load_evidence_public(), task, reg, now_ts())
    emit({"status": "PASS", "verb": "collect-evidence", "task_id": task_id,
          "evidence_key": dest, "host_id": result["host_id"], "agent_id": result["agent_id"],
          "generation": result["generation"], "executor_sha256": result["executor_sha256"],
          "status_field": result["status"], "runtime_acceptance": result["runtime_acceptance"],
          "observed_at": result["observed_at"], "all_bindings_verified": True})


def main(argv):
    if len(argv) != 2:
        die("usage", "expected exactly one verb: " + " | ".join(VERBS))
    verb = argv[1]
    if verb not in VERBS:
        die("unknown_verb", verb)
    cfg = load_publisher()
    if verb == "sign-registration":
        return cmd_sign_registration(cfg)
    if verb == "publish-one-probe":
        return cmd_publish_one_probe(cfg)
    return cmd_collect_evidence(cfg)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Reject as exc:
        die("refused", exc)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- fail closed
        die("error", type(exc).__name__ + ":" + str(exc)[:120])
