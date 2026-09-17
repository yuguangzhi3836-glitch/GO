#!/usr/bin/env python3
"""Fail-closed, source-bound HK Agent maintenance upgrade.

This is an installer for shared control-plane bytes only.  It never invokes a
business executor and it has no database, image, CANARY, VERIFY or DEPLOY path.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time

SCHEMA = "go.hk-agent-upgrade-before.v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FILES = {
    "transport.py": ("hk-staging/hk_agent/transport.py", "/opt/go-hk-agent-rebuilt/hk_agent/transport.py", 0o644),
    "test_pr.py": ("hk-staging/hk_agent/test_pr.py", "/opt/go-hk-agent-rebuilt/hk_agent/test_pr.py", 0o644),
    "artifact_store.py": ("hk-staging/hk_agent/artifact_store.py", "/opt/go-hk-agent-rebuilt/hk_agent/artifact_store.py", 0o644),
    "Dockerfile.go-application-python-v2": ("hk-staging/Dockerfile.go-application-python-v2", "/usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2", 0o644),
    "install-hk-agent.sh": ("install/install-hk-agent.sh", "/usr/local/libexec/go-hk-test-pr/install-hk-agent.sh", 0o755),
    "preflight.sh": ("install/preflight.sh", "/usr/local/libexec/go-hk-test-pr/preflight.sh", 0o755),
    "upgrade_hk_agent.py": ("install/upgrade_hk_agent.py", "/usr/local/libexec/go-hk-test-pr/upgrade_hk_agent.py", 0o755),
    "SHA256SUMS": ("SHA256SUMS", "/usr/local/libexec/go-hk-test-pr/SHA256SUMS", 0o644),
}
PROTECTED = {
    "agent.json": "/etc/go-hk-agent/agent.json",
    "go-hk-agent.service": "/etc/systemd/system/go-hk-agent.service",
    "go-hk-agent.timer": "/etc/systemd/system/go-hk-agent.timer",
    "docker-access.conf": "/etc/systemd/system/go-hk-agent.service.d/30-test-pr-docker-access.conf",
}
DIRECTORIES = {
    "store": "/var/lib/go-hk-artifacts",
    "objects": "/var/lib/go-hk-artifacts/objects",
    "failures": "/var/lib/go-hk-artifacts/failures",
}
ALL_FILE_KEYS = frozenset(FILES) | frozenset(PROTECTED)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rooted(path, prefix):
    return prefix / path.lstrip("/") if prefix else Path(path)


def snapshot(path):
    if not path.exists():
        return {"state": "absent"}
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"UNSAFE_FILE:{path}")
    st = path.stat()
    return {"state": "present", "sha256": digest(path), "uid": st.st_uid,
            "gid": st.st_gid, "mode": stat.S_IMODE(st.st_mode)}


def directory_snapshot(path):
    if not path.exists():
        return {"state": "absent"}
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"UNSAFE_DIRECTORY:{path}")
    st = path.stat()
    return {"state": "present", "uid": st.st_uid, "gid": st.st_gid,
            "mode": stat.S_IMODE(st.st_mode)}


def load_before(path, candidate_sha):
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("BEFORE_UNSAFE")
    raw = source.read_bytes()
    value = json.loads(raw)
    if set(value) != {"schema", "candidate_sha", "observed_at", "files", "directories", "service"}:
        raise RuntimeError("BEFORE_SCHEMA")
    if value["schema"] != SCHEMA or value["candidate_sha"] != candidate_sha:
        raise RuntimeError("BEFORE_BINDING")
    if set(value["files"]) != ALL_FILE_KEYS or set(value["directories"]) != set(DIRECTORIES):
        raise RuntimeError("BEFORE_SCOPE")
    service = value["service"]
    if service != {"timer_active": True, "timer_enabled": True, "service_active": False}:
        raise RuntimeError("BEFORE_SERVICE_STATE")
    return value, hashlib.sha256(raw).hexdigest(), raw


def verify_manifest(root):
    manifest = root / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError("CANDIDATE_MANIFEST_UNSAFE")
    seen = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        checksum, name = line.split("  ", 1)
        if not SHA256.fullmatch(checksum) or name.startswith("/") or ".." in Path(name).parts:
            raise RuntimeError("CANDIDATE_MANIFEST_SCHEMA")
        candidate = root / name
        if name in seen or not candidate.is_file() or candidate.is_symlink():
            raise RuntimeError("CANDIDATE_MANIFEST_SCOPE")
        if digest(candidate) != checksum:
            raise RuntimeError("CANDIDATE_MANIFEST_MISMATCH")
        seen.add(name)
    required = {item[0] for item in FILES.values() if item[0] != "SHA256SUMS"}
    if not required <= seen:
        raise RuntimeError("CANDIDATE_MANIFEST_INCOMPLETE")


def check_observed(before, prefix):
    for name, expected in before["files"].items():
        canonical = FILES[name][1] if name in FILES else PROTECTED[name]
        if snapshot(rooted(canonical, prefix)) != expected:
            raise RuntimeError(f"OBSERVED_BEFORE_FILE_DRIFT:{name}")
    for name, expected in before["directories"].items():
        if directory_snapshot(rooted(DIRECTORIES[name], prefix)) != expected:
            raise RuntimeError(f"OBSERVED_BEFORE_DIRECTORY_DRIFT:{name}")


def systemctl(command, *args, check=True):
    result = subprocess.run([command, *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if check and result.returncode:
        raise RuntimeError(f"SYSTEMCTL_{args[0].upper()}:{result.returncode}")
    return result


def service_is_active(command, unit):
    return systemctl(command, "is-active", "--quiet", unit, check=False).returncode == 0


def service_is_enabled(command, unit):
    return systemctl(command, "is-enabled", "--quiet", unit, check=False).returncode == 0


def restore_timer(command, receipt, phase, attempts=3):
    """Start the timer and prove both active and enabled state.

    A successful ``systemctl start`` is not proof that the timer is usable.  The
    caller must keep its restoration-pending state until this function returns.
    Every failed observation is retained in the durable receipt, including an
    unexpected readback return code or an exception while invoking systemctl.
    """
    history = receipt.setdefault("timer_restore_attempts", [])
    last_error = "TIMER_RESTORE_NOT_ATTEMPTED"
    for attempt in range(1, attempts + 1):
        record = {"phase": phase, "attempt": attempt}
        history.append(record)
        try:
            started = systemctl(command, "start", "go-hk-agent.timer", check=False)
            record["start_rc"] = started.returncode
            if started.returncode:
                raise RuntimeError(f"TIMER_START_RC:{started.returncode}")

            active = systemctl(command, "is-active", "--quiet",
                               "go-hk-agent.timer", check=False)
            enabled = systemctl(command, "is-enabled", "--quiet",
                                "go-hk-agent.timer", check=False)
            record["active_rc"] = active.returncode
            record["enabled_rc"] = enabled.returncode
            if active.returncode == 0 and enabled.returncode == 0:
                record["result"] = "PASS"
                if "timer_restore_error" in receipt:
                    receipt["timer_restore_recovered"] = True
                return
            if active.returncode not in (0, 3):
                raise RuntimeError(f"TIMER_ACTIVE_READBACK_RC:{active.returncode}")
            if enabled.returncode not in (0, 1):
                raise RuntimeError(f"TIMER_ENABLED_READBACK_RC:{enabled.returncode}")
            if active.returncode != 0:
                raise RuntimeError("TIMER_INACTIVE_AFTER_START")
            raise RuntimeError("TIMER_DISABLED_AFTER_START")
        except Exception as exc:
            last_error = type(exc).__name__ + ":" + str(exc)
            record["result"] = "FAILED"
            record["error"] = last_error
            receipt["timer_restore_error"] = last_error
    raise RuntimeError("TIMER_RESTORE_UNRECOVERED:" + last_error)


def copy_for_backup(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if snapshot(source) != snapshot(target):
        raise RuntimeError(f"BACKUP_VERIFY:{source}")


def atomic_install(source, target, mode, uid, gid):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pr188-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, open(source, "rb") as candidate:
            shutil.copyfileobj(candidate, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.chown(temporary, uid, gid)
        if digest(temporary) != digest(source):
            raise RuntimeError(f"STAGED_HASH:{target}")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def frozen_preflight(root, prefix, protected_before, artifact_uid, artifact_gid,
                     systemctl_command):
    for name, (source, canonical, mode) in FILES.items():
        installed = rooted(canonical, prefix)
        candidate = root / source
        if digest(installed) != digest(candidate):
            raise RuntimeError(f"POSTINSTALL_HASH:{name}")
        if stat.S_IMODE(installed.stat().st_mode) != mode:
            raise RuntimeError(f"POSTINSTALL_MODE:{name}")
    for name, canonical in PROTECTED.items():
        if snapshot(rooted(canonical, prefix)) != protected_before[name]:
            raise RuntimeError(f"PROTECTED_DRIFT:{name}")
    for name, canonical in DIRECTORIES.items():
        path = rooted(canonical, prefix)
        current = directory_snapshot(path)
        if current != {"state": "present", "uid": artifact_uid,
                       "gid": artifact_gid, "mode": 0o700}:
            raise RuntimeError(f"STORE_READBACK:{name}")
    if service_is_active(systemctl_command, "go-hk-agent.service"):
        raise RuntimeError("SERVICE_NOT_QUIESCENT")


def restore(changed, backup, prefix, before):
    errors = []
    for name in reversed(changed):
        _, canonical, _ = FILES[name]
        target = rooted(canonical, prefix)
        try:
            if before["files"][name]["state"] == "present":
                atomic_install(backup / (name + ".before"), target,
                               before["files"][name]["mode"],
                               before["files"][name]["uid"],
                               before["files"][name]["gid"])
            elif target.exists():
                target.unlink()
        except Exception as exc:
            errors.append(f"{name}:{exc}")
    failure_path = rooted(DIRECTORIES["failures"], prefix)
    if before["directories"]["failures"]["state"] == "absent" and failure_path.exists():
        try:
            failure_path.rmdir()
        except Exception as exc:
            errors.append(f"failures:{exc}")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--observed-before", required=True)
    parser.add_argument("--candidate-sha", required=True)
    args = parser.parse_args(argv)
    if not SHA40.fullmatch(args.candidate_sha):
        raise RuntimeError("CANDIDATE_SHA")
    if os.geteuid() != 0 and os.environ.get("GO_HK_UPGRADE_TEST_MODE") != "1":
        raise RuntimeError("ROOT_REQUIRED")
    prefix_raw = os.environ.get("GO_HK_UPGRADE_TEST_ROOT", "")
    prefix = Path(prefix_raw).resolve() if prefix_raw else None
    if prefix and os.environ.get("GO_HK_UPGRADE_TEST_MODE") != "1":
        raise RuntimeError("TEST_ROOT_FORBIDDEN")
    root = Path(args.root).resolve()
    verify_manifest(root)
    before, before_sha, before_raw = load_before(args.observed_before, args.candidate_sha)
    check_observed(before, prefix)

    systemctl_command = os.environ.get("GO_SYSTEMCTL", "systemctl")
    if (not service_is_active(systemctl_command, "go-hk-agent.timer")
            or not service_is_enabled(systemctl_command, "go-hk-agent.timer")
            or service_is_active(systemctl_command, "go-hk-agent.service")):
        raise RuntimeError("LIVE_SERVICE_DRIFT")
    backup_parent = rooted("/var/backups", prefix)
    backup_parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(tempfile.mkdtemp(prefix=f"HK-CHANGE-{stamp}-pr188-",
                                  dir=backup_parent))
    backup.chmod(0o700)
    protected_before = {name: before["files"][name] for name in PROTECTED}
    changed = []
    receipt = {"schema": "go.hk-agent-upgrade-receipt.v1",
               "candidate_sha": args.candidate_sha,
               "observed_before_sha256": before_sha,
               "backup": str(backup), "result": "STARTED"}
    (backup / "observed-before.json").write_bytes(before_raw)
    artifact_uid = (os.getuid() if prefix else int(subprocess.check_output(
        ["id", "-u", "go-hk-agent"], text=True).strip()))
    artifact_gid = (os.getgid() if prefix else int(subprocess.check_output(
        ["id", "-g", "go-hk-agent"], text=True).strip()))
    timer_stopped = False
    restoration_pending = False
    try:
        systemctl(systemctl_command, "stop", "go-hk-agent.timer")
        timer_stopped = True
        restoration_pending = True
        receipt["timer_restoration_pending"] = True
        for _ in range(30):
            if not service_is_active(systemctl_command, "go-hk-agent.service"):
                break
            time.sleep(1)
        else:
            raise RuntimeError("SERVICE_QUIESCE_TIMEOUT")
        check_observed(before, prefix)
        for name in FILES:
            canonical = FILES[name][1]
            target = rooted(canonical, prefix)
            if before["files"][name]["state"] == "present":
                copy_for_backup(target, backup / (name + ".before"))
        for name, (source, canonical, mode) in FILES.items():
            target = rooted(canonical, prefix)
            atomic_install(root / source, target, mode, 0 if not prefix else os.getuid(),
                           0 if not prefix else os.getgid())
            changed.append(name)
        for name, canonical in DIRECTORIES.items():
            path = rooted(canonical, prefix)
            if path.exists():
                if directory_snapshot(path) != {"state": "present", "uid": artifact_uid,
                                                "gid": artifact_gid, "mode": 0o700}:
                    raise RuntimeError(f"STORE_DRIFT:{name}")
            else:
                path.mkdir()
                os.chown(path, artifact_uid, artifact_gid)
                path.chmod(0o700)
        frozen_preflight(root, prefix, protected_before, artifact_uid, artifact_gid,
                         systemctl_command)
        restore_timer(systemctl_command, receipt, "commit")
        timer_stopped = False
        restoration_pending = False
        receipt["timer_restoration_pending"] = False
        receipt["result"] = "PASS"
        receipt["installed"] = {name: snapshot(rooted(spec[1], prefix))
                                for name, spec in FILES.items()}
        receipt["protected"] = protected_before
        receipt["directories"] = {name: directory_snapshot(rooted(path, prefix))
                                  for name, path in DIRECTORIES.items()}

    except Exception as exc:
        receipt["result"] = "FAILED"
        receipt["error"] = type(exc).__name__ + ":" + str(exc)
        receipt["rollback_errors"] = restore(changed, backup, prefix, before)
        if restoration_pending:
            try:
                restore_timer(systemctl_command, receipt, "rollback")
                timer_stopped = False
                restoration_pending = False
            except Exception as timer_exc:
                receipt["timer_restore_error"] = (type(timer_exc).__name__ + ":"
                                                  + str(timer_exc))
        receipt["timer_restoration_pending"] = restoration_pending
        (backup / "receipt.json").write_text(json.dumps(receipt, sort_keys=True,
                                                        separators=(",", ":")) + "\n")
        raise
    (backup / "receipt.json").write_text(json.dumps(receipt, sort_keys=True,
                                                    separators=(",", ":")) + "\n")
    print(json.dumps({"result": "PASS", "candidate_sha": args.candidate_sha,
                      "backup": str(backup), "receipt": str(backup / "receipt.json")},
                     sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
