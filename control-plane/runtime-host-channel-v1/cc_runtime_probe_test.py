"""Bounded CC-side publisher/collector for the external C1 Runtime probe channel.

Proposed candidate path: control-plane/runtime-host-channel-v1/cc_runtime_probe_test.py
Installed on the Command Center as a LOCAL TEST PATCH. It does not touch the existing
Boss Request bridge and does not extend the legacy 6-action enum.

Exactly two fixed verbs, nothing else:

    publish-one-c1-probe   sign and durably publish exactly ONE RUNTIME_C1_PROBE_V1 task
    collect-c1-probe       read back and fully verify the final Runtime Evidence receipt

It carries its own durable outbox (`c1-probe-outbox.db`), separate from the older
single-host-probe outbox, so the previously retained task is never disturbed.

Refuses: arbitrary action / target / shell / service / URL / deploy / reboot arguments,
a second task, and any registration that does not authorize RUNTIME_C1_PROBE_V1.
No command line arguments beyond the single verb are accepted.
"""
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time

from cryptography.hazmat.primitives import serialization

from channel import (ACTIONS, RUNTIME_ACTION, Reject, canonical, digest, identifier,
                     registration, signed, verify_evidence, verified)
from git_transport import GitTransport

CONFIG_DIR = "/etc/go-command-center/runtime-host-v1"
PUBLISHER_JSON = CONFIG_DIR + "/publisher.json"
KNOWN_HOSTS = CONFIG_DIR + "/github.com.known_hosts"
EVIDENCE_PUBLIC = CONFIG_DIR + "/evidence.pub"
STATE_DIR = "/var/lib/go-command-center/runtime-host-v1"
OUTBOX_DB = STATE_DIR + "/c1-probe-outbox.db"

VERBS = ("publish-one-c1-probe", "collect-c1-probe")
KEY_PREFIX = "registrations/"
MAX_CANDIDATES = 4


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
                "executor_sha256", "evidence_key_sha256", "approval_ref",
                "signer_private_key", "signer_public_key", "tasks", "evidence")
    for key in required:
        if key not in cfg:
            die("config_missing", key)
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
    with open(EVIDENCE_PUBLIC, "rb") as fh:
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


def current_registration(cfg, signer_public, now):
    """Highest valid published registration that matches this deployment binding and
    authorizes the bridge action. Never a locally-fabricated or cached registration."""
    block = cfg["tasks"]
    repo = GitTransport(block["remote"], block["branch"], "registrations",
                        git_env=git_env(block["key"]))
    keys = [key for key in repo.keys() if key.startswith(KEY_PREFIX)]
    keys.sort(reverse=True)
    candidates = []
    for key in keys[:MAX_CANDIDATES]:
        raw = repo.read(key)
        if raw is None:
            continue
        try:
            body = registration(raw, signer_public, now)
        except Reject:
            continue
        if (body["environment"], body["host_id"], body["agent_id"]) != \
                (cfg["environment"], cfg["host_id"], cfg["agent_id"]):
            continue
        if body["candidate_sha"] != cfg["candidate_sha"] \
                or body["plan_sha256"] != cfg["plan_sha256"] \
                or body["executor_sha256"] != cfg["executor_sha256"] \
                or body["evidence_key_sha256"] != cfg["evidence_key_sha256"]:
            continue
        if RUNTIME_ACTION not in body["actions"]:
            continue
        candidates.append((body["generation"], key, raw, body))
    if not candidates:
        raise Reject("no_registration_authorizes_c1_probe")
    return max(candidates, key=lambda item: item[0])


class Outbox:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS outbox (
            task_id TEXT PRIMARY KEY, task_digest TEXT, raw BLOB, state TEXT, created_at INTEGER,
            registration_raw BLOB, generation INTEGER)""")

    def existing(self):
        return self.db.execute("SELECT task_id,state FROM outbox").fetchall()

    def prepare(self, task_id, task_digest, raw, registration_raw, generation):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM outbox").fetchone():
                raise Reject("second_task_refused")
            self.db.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?)",
                            (task_id, task_digest, raw, "PREPARED", now_ts(),
                             registration_raw, generation))
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
            return self.db.execute(
                "SELECT task_id,task_digest,raw,state,registration_raw,generation FROM outbox WHERE task_id=?",
                (task_id,)).fetchone()
        return self.db.execute(
            "SELECT task_id,task_digest,raw,state,registration_raw,generation FROM outbox LIMIT 1").fetchone()


def cmd_publish_one_c1_probe(cfg):
    signer_public = load_signer(cfg, private=False)
    generation, key, reg_raw, reg = current_registration(cfg, signer_public, now_ts())

    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    outbox = Outbox(OUTBOX_DB)
    if outbox.existing():
        die("task_already_published_refuse_second")

    now = now_ts()
    task_id = "rh-c1probe-" + secrets.token_hex(8)
    identifier(task_id)
    task = {
        "version": 1,
        "kind": "runtime-host-task",
        "task_id": task_id,
        "nonce": secrets.token_hex(24),
        "environment": reg["environment"],
        "host_id": reg["host_id"],
        "agent_id": reg["agent_id"],
        "generation": reg["generation"],
        "registration_sha256": digest(reg),
        "action": RUNTIME_ACTION,
        "parameters": {},
        "issued_at": now,
        "expires_at": min(now + 300, reg["expires_at"]),
    }
    raw = signed(task, load_signer(cfg, private=True))
    task_digest = digest(task)

    outbox.prepare(task_id, task_digest, raw, reg_raw, generation)
    dest = "tasks/" + task_id + ".json"

    # Durable ATTEMPTED strictly before any network I/O.
    outbox.mark_attempted(task_id)
    tasks = transport(cfg, "tasks")
    tasks.create(dest, raw)
    remote = tasks.read(dest)
    if remote is None:
        die("publication_unresolved", task_id)
    if remote != raw:
        die("publication_conflict", task_id)
    outbox.mark_published(task_id)

    emit({"status": "PASS", "verb": "publish-one-c1-probe", "task_id": task_id,
          "task_sha256": task_digest, "key": "runtime-host-v1/" + dest,
          "outbox_state": outbox.get(task_id)[3], "action": RUNTIME_ACTION,
          "parameters": {}, "registration_key": key, "generation": generation,
          "registration_sha256": digest(reg),
          "expires_at": task["expires_at"], "readback_identical": True})


def cmd_collect_c1_probe(cfg):
    signer_public = load_signer(cfg, private=False)
    outbox = Outbox(OUTBOX_DB)
    row = outbox.get()
    if not row:
        die("no_task_in_outbox")
    task_id, task_digest, raw_task, state, reg_raw, generation = row
    if state != "PUBLISHED":
        die("task_not_published", state)
    task = verified(raw_task, signer_public)
    reg = registration(reg_raw, signer_public, now_ts())

    evidence = transport(cfg, "evidence")
    dest = "evidence/" + task_id + ".json"
    raw = evidence.read(dest)
    if raw is None:
        die("evidence_pending")

    result = verify_evidence(raw, load_evidence_public(), task, reg, now_ts())
    if result["runtime_acceptance"] != "SUCCEEDED":
        die("runtime_acceptance_not_succeeded", result["runtime_acceptance"])
    emit({"status": "PASS", "verb": "collect-c1-probe", "task_id": task_id,
          "evidence_key": dest, "host_id": result["host_id"], "agent_id": result["agent_id"],
          "generation": result["generation"], "executor_sha256": result["executor_sha256"],
          "status_field": result["status"],
          "runtime_acceptance": result["runtime_acceptance"],
          "runtime_task_id": result["runtime_task_id"],
          "runtime_owner_c": result["runtime_owner_c"],
          "runtime_kind": result["runtime_kind"],
          "runtime_event_hash": result["runtime_event_hash"],
          "runtime_result_sha256": result["runtime_result_sha256"],
          "observed_at": result["observed_at"], "all_bindings_verified": True})


def main(argv):
    if len(argv) != 2:
        die("usage", "expected exactly one verb: " + " | ".join(VERBS))
    verb = argv[1]
    if verb not in VERBS:
        die("unknown_verb", verb)
    cfg = load_publisher()
    if verb == "publish-one-c1-probe":
        return cmd_publish_one_c1_probe(cfg)
    return cmd_collect_c1_probe(cfg)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Reject as exc:
        die("refused", exc)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- fail closed
        die("error", type(exc).__name__ + ":" + str(exc)[:120])
