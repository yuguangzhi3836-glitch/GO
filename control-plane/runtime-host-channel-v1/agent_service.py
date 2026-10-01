"""Minimal resident entry point for the runtime-host Management Agent.

Proposed PR290 source fix. Belongs at:
    control-plane/runtime-host-channel-v1/agent_service.py

Scope (deliberately minimal -- PR290 ships library code only, no resident entry):
  1. load fixed root-owned config
  2. load registration (authority-signed bytes)
  3. load the CC test signer public key (authority_public == task_public this round)
  4. load the rt01 Evidence private key
  5. construct the Tasks GitTransport
  6. construct the Evidence GitTransport
  7. recompute executor_sha256 locally from the installed bundle
  8. compare it against the registration binding
  9. call poll_once()
 10. bounded sleep, then repeat

Refuses: shell execution, arbitrary action, arbitrary URL, arbitrary path input,
deploy, reboot, Production, HK actions. The only task action accepted is
`RUNTIME_HOST_PROBE_V1`, enforced by channel.py itself (`ACTION`).

Usage:
    agent_service.py            # resident loop
    agent_service.py --once     # single pass, then exit

No path/URL arguments are accepted on purpose: every path and remote comes from
the protected root-owned config file at CONFIG_PATH.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import serialization

from adapter import protected_read
from channel import Reject
from flow import poll_once
from git_transport import GitTransport

CONFIG_PATH = "/etc/go-runtime-host/agent.json"
IMDS_INSTANCE_ID = "http://100.100.100.200/latest/meta-data/instance-id"  # fixed, not configurable
TICK_MIN, TICK_MAX = 1, 3600


def fail(kind, detail=""):
    sys.stderr.write(json.dumps({"status": "REFUSED", "reason": kind, "detail": str(detail)[:200]},
                                sort_keys=True) + "\n")
    sys.stderr.flush()
    return 1


def check_path(value, name):
    """Absolute, no '..'. Shape only -- protected_read enforces ownership/mode."""
    if not isinstance(value, str) or not value.startswith("/") or ".." in value.split("/"):
        raise Reject("config_path:%s" % name)
    return value


def check_remote(value, name):
    """Fixed trusted remote; never a Request input. Reject options/argv injection."""
    if not isinstance(value, str) or value.startswith("-") or "\n" in value or not value.startswith("git@"):
        raise Reject("config_remote:%s" % name)
    return value


def load_config():
    raw = protected_read(CONFIG_PATH)
    cfg = json.loads(raw.decode("utf-8"))
    for k in ("environment", "host_id", "agent_id", "registration_path",
              "authority_public_path", "task_public_path", "evidence_private_path",
              "executor_bundle_dir", "registry_db", "tasks", "evidence", "tick_seconds"):
        if k not in cfg:
            raise Reject("config_missing:%s" % k)
    for k in ("registration_path", "authority_public_path", "task_public_path",
              "evidence_private_path", "executor_bundle_dir", "registry_db"):
        check_path(cfg[k], k)
    for k in ("tasks", "evidence"):
        block = cfg[k]
        for sub in ("remote", "branch", "key", "known_hosts"):
            if sub not in block:
                raise Reject("config_missing:%s.%s" % (k, sub))
        check_remote(block["remote"], k + ".remote")
        check_path(block["key"], k + ".key")
        check_path(block["known_hosts"], k + ".known_hosts")
    if not isinstance(cfg["tick_seconds"], int) or not TICK_MIN <= cfg["tick_seconds"] <= TICK_MAX:
        raise Reject("config_tick")
    return cfg


def load_public(path):
    data = protected_read(path)
    try:
        return serialization.load_pem_public_key(data)
    except Exception:  # noqa: BLE001 -- fall back to the OpenSSH one-line form
        return serialization.load_ssh_public_key(data)


def load_private(path):
    return serialization.load_pem_private_key(protected_read(path), password=None)


def observe_live_host_id():
    """Locally observed cloud instance identity. Fixed link-local metadata endpoint,
    never a URL supplied by a caller or by a task."""
    req = urllib.request.Request(IMDS_INSTANCE_ID, headers={"User-Agent": "go-runtime-host-agent"})
    with urllib.request.urlopen(req, timeout=5) as r:  # no redirects expected
        value = r.read(128).decode("ascii", "strict").strip()
    if not value or len(value) > 64 or "/" in value:
        raise Reject("imds_shape")
    return value


def compute_executor_sha256(bundle_dir):
    """executor_sha256 = SHA256(canonical installed Management Agent manifest).

    manifest line: <sha256><two spaces><relative_path>\\n  (UTF-8, LF, no BOM)
    paths sorted by byte order; covers every *.py installed directly in bundle_dir.
    """
    import hashlib
    names = []
    with os.scandir(bundle_dir) as it:
        for entry in it:
            if entry.is_file(follow_symlinks=False) and entry.name.endswith(".py"):
                names.append(entry.name)
    if not names:
        raise Reject("bundle_empty")
    names.sort(key=lambda s: s.encode("utf-8"))
    parts = []
    for name in names:
        with open(os.path.join(bundle_dir, name), "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        parts.append("%s  %s\n" % (digest, name))
    manifest = "".join(parts).encode("utf-8")
    return hashlib.sha256(manifest).hexdigest(), names


def build_git_env(key_path, known_hosts):
    return {
        "GIT_SSH_COMMAND": "ssh -i %s -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
                           "-o UserKnownHostsFile=%s -o BatchMode=yes" % (key_path, known_hosts),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def one_pass(cfg, registry_holder):
    from channel import Registry

    registration_raw = protected_read(cfg["registration_path"])
    authority_public = load_public(cfg["authority_public_path"])
    task_public = load_public(cfg["task_public_path"])
    evidence_signer = load_private(cfg["evidence_private_path"])

    live_host_id = observe_live_host_id()
    executor_sha256, files = compute_executor_sha256(cfg["executor_bundle_dir"])

    tasks = GitTransport(cfg["tasks"]["remote"], cfg["tasks"]["branch"], "tasks",
                         git_env=build_git_env(cfg["tasks"]["key"], cfg["tasks"]["known_hosts"]))
    evidence = GitTransport(cfg["evidence"]["remote"], cfg["evidence"]["branch"], "evidence",
                            git_env=build_git_env(cfg["evidence"]["key"], cfg["evidence"]["known_hosts"]))

    if registry_holder[0] is None:
        os.makedirs(os.path.dirname(cfg["registry_db"]), mode=0o700, exist_ok=True)
        registry_holder[0] = Registry(cfg["registry_db"])

    # Binding check happens inside initialize()/probe(); do an explicit pre-check too so a
    # local mismatch refuses before any network I/O is attempted.
    from channel import digest, registration
    reg = registration(registration_raw, authority_public, clock())
    if reg["environment"] != cfg["environment"] or reg["host_id"] != cfg["host_id"] \
            or reg["agent_id"] != cfg["agent_id"]:
        raise Reject("config_registration_binding")
    if executor_sha256 != reg["executor_sha256"]:
        raise Reject("local_executor_mismatch")
    if live_host_id != cfg["host_id"]:
        raise Reject("local_host_mismatch")

    results = poll_once(registry_holder[0], registration_raw, authority_public, task_public,
                        evidence_signer, live_host_id, executor_sha256, tasks, evidence, clock)

    sys.stderr.write(json.dumps({
        "status": "PASS", "environment": cfg["environment"], "host_id": live_host_id,
        "executor_sha256": executor_sha256, "bundle_files": files,
        "registration_sha256": digest(reg), "results": [list(r) for r in results],
    }, sort_keys=True) + "\n")
    sys.stderr.flush()
    return 0


def clock():
    """Trusted clock, sampled in-process per invocation. Never a caller/Request timestamp."""
    return int(time.time())


def main(argv):
    if len(argv) > 1 and argv[1] not in ("--once",):
        return fail("bad_argument", argv[1])
    once = len(argv) > 1
    try:
        cfg = load_config()
    except Reject as exc:
        return fail("config", exc)
    except Exception as exc:  # noqa: BLE001
        return fail("config_io", type(exc).__name__)

    holder = [None]
    while True:
        try:
            one_pass(cfg, holder)
        except Reject as exc:
            return fail("refused", exc)
        except urllib.error.URLError as exc:
            return fail("imds_unreachable", type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 -- fail closed on anything unexpected
            return fail("error", type(exc).__name__)
        if once:
            return 0
        time.sleep(cfg["tick_seconds"])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
