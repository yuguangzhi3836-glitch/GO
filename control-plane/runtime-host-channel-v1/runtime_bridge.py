"""Local filesystem bridge between the root Management Agent and the C1-C14 Runtime.

Proposed candidate path: control-plane/runtime-host-channel-v1/runtime_bridge.py
Installed on the Runtime Host at:

    /opt/go/runtime-host-agent/runtime_bridge.py

The Management Agent must never open the Runtime database: that database belongs to
the `go-runtime` account and runs in WAL mode. Instead the Agent drops one immutable
request file into a fixed inbox directory and reads one immutable result file from a
fixed outbox directory. The Runtime side of the bridge is `runtime_bridge_service.py`,
which runs as `go-runtime` and is the only process that calls the installed
`Runtime.enqueue()`.

This module holds the request/result schema and the Management-Agent-side producer.
Both files are small, canonical, and closed: exact field sets, no arbitrary payload,
no path, no command, no URL, and no caller-selectable owner or runtime kind.

No socket, no listener, no daemon framework, no network.
"""
import json
import os
import stat
import sys

from channel import (RUNTIME_KIND, RUNTIME_OWNER_C, Reject, canonical, decode, fields,
                     hex_digest, identifier)

SCHEMA_VERSION = 1
REQUEST_KIND = "runtime-c1-probe-request"
RESULT_KIND = "runtime-c1-probe-result"

REQUEST_FIELDS = ("version kind external_task_id external_task_sha256 registration_sha256 "
                  "owner_c runtime_kind")
RESULT_FIELDS = ("version kind external_task_id external_task_sha256 runtime_task_id "
                 "runtime_owner_c runtime_kind runtime_status runtime_event_hash "
                 "runtime_result_sha256")

# Fixed default directories. They are constants, never taken from a task document.
INBOX_DIR = "/var/lib/go-runtime-bridge/inbox"
OUTBOX_DIR = "/var/lib/go-runtime-bridge/outbox"

MAX_BYTES = 4096
INBOX_MODE = 0o640
OUTBOX_MODE = 0o640

# Terminal Runtime task states, mirrored from the frozen Runtime contract. A result is
# only published when the task has actually reached one of these.
TERMINAL_STATUSES = ("SUCCEEDED", "FAILED", "CANCELLED", "ESCALATED")


def read_bounded(path, maximum=MAX_BYTES):
    """Regular file only, no symlink, bounded size. Never a shell or a path input."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Reject("bridge_not_regular")
        raw = b""
        while True:
            try:
                chunk = os.read(fd, maximum + 1)
            except OSError as exc:
                raise Reject("bridge_read") from exc
            if not chunk:
                break
            raw += chunk
            if len(raw) > maximum:
                raise Reject("bridge_size")
        return raw
    finally:
        os.close(fd)


def read_optional(path, maximum=MAX_BYTES):
    """A missing file reads as None. Anything unsafe or unreadable is a refusal:
    a symlink or a replaced object must never be treated as an absent one."""
    try:
        return read_bounded(path, maximum)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Reject("bridge_unreadable") from exc


def atomic_write(path, raw, uid, gid, mode):
    """Durable, byte-exact replace: write, fsync, adjust owner/mode, then rename."""
    directory = os.path.dirname(path)
    temporary = os.path.join(directory, ".bridge.%d.tmp" % os.getpid())
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        try:
            os.chown(temporary, uid, gid)
        except OSError:
            # Group ownership is best effort for an unprivileged producer; the
            # directory's set-group-id bit already fixes the group in practice.
            pass
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def bridge_path(directory, external_task_id):
    """One file per external task identity. The identifier shape excludes separators."""
    identifier(external_task_id)
    return os.path.join(directory, external_task_id + ".json")


def encode_request(external_task_id, external_task_sha256, registration_sha256):
    identifier(external_task_id)
    hex_digest(external_task_sha256)
    hex_digest(registration_sha256)
    return canonical({"version": SCHEMA_VERSION, "kind": REQUEST_KIND,
                      "external_task_id": external_task_id,
                      "external_task_sha256": external_task_sha256,
                      "registration_sha256": registration_sha256,
                      "owner_c": RUNTIME_OWNER_C, "runtime_kind": RUNTIME_KIND})


def parse_request(raw):
    """Closed request schema. owner_c and runtime_kind are fixed; there is no payload."""
    value = decode(raw)
    fields(value, REQUEST_FIELDS)
    if type(value["version"]) is not int or value["version"] != SCHEMA_VERSION \
            or value["kind"] != REQUEST_KIND:
        raise Reject("bridge_version_or_kind")
    identifier(value["external_task_id"])
    hex_digest(value["external_task_sha256"])
    hex_digest(value["registration_sha256"])
    if value["owner_c"] != RUNTIME_OWNER_C or value["runtime_kind"] != RUNTIME_KIND:
        raise Reject("bridge_target")
    return value


def parse_result(raw):
    """Closed result schema; the Runtime task id shape is fixed by the Runtime."""
    value = decode(raw)
    fields(value, RESULT_FIELDS)
    if type(value["version"]) is not int or value["version"] != SCHEMA_VERSION \
            or value["kind"] != RESULT_KIND:
        raise Reject("bridge_version_or_kind")
    identifier(value["external_task_id"])
    hex_digest(value["external_task_sha256"])
    hex_digest(value["runtime_event_hash"])
    hex_digest(value["runtime_result_sha256"])
    if value["runtime_owner_c"] != RUNTIME_OWNER_C or value["runtime_kind"] != RUNTIME_KIND:
        raise Reject("bridge_target")
    if value["runtime_status"] not in TERMINAL_STATUSES:
        raise Reject("bridge_status")
    return value


def encode_result(external_task_id, external_task_sha256, runtime_task_id,
                  runtime_status, runtime_event_hash, runtime_result_sha256):
    return canonical({"version": SCHEMA_VERSION, "kind": RESULT_KIND,
                      "external_task_id": external_task_id,
                      "external_task_sha256": external_task_sha256,
                      "runtime_task_id": runtime_task_id,
                      "runtime_owner_c": RUNTIME_OWNER_C, "runtime_kind": RUNTIME_KIND,
                      "runtime_status": runtime_status,
                      "runtime_event_hash": runtime_event_hash,
                      "runtime_result_sha256": runtime_result_sha256})


def runtime_result_sha256(result):
    """Canonical digest of the observed Runtime worker result object."""
    import hashlib
    return hashlib.sha256(canonical(result if result is not None else {})).hexdigest()


class LocalBridge:
    """Management-Agent side of the bridge.

    Writes at most one immutable request per external task and reads the Runtime
    result back. It never opens the Runtime database, never signs anything, never
    executes anything and never touches the network.
    """

    def __init__(self, inbox_dir=INBOX_DIR, outbox_dir=OUTBOX_DIR, gid=None):
        for path in (inbox_dir, outbox_dir):
            if not isinstance(path, str) or not path.startswith("/") or ".." in path.split("/"):
                raise Reject("bridge_config_path")
        self.inbox_dir = inbox_dir
        self.outbox_dir = outbox_dir
        self.gid = gid

    def request(self, external_task_id, external_task_sha256, registration_sha256):
        raw = encode_request(external_task_id, external_task_sha256, registration_sha256)
        path = bridge_path(self.inbox_dir, external_task_id)
        existing = read_optional(path)
        if existing is not None:
            # Same external task and same bytes: reuse. Anything else is refused,
            # and a different request under the same identity is never overwritten.
            if existing != raw:
                raise Reject("bridge_request_conflict")
            return parse_request(existing)
        os.makedirs(self.inbox_dir, mode=0o750, exist_ok=True)
        atomic_write(path, raw, 0, self.gid if self.gid is not None else -1, INBOX_MODE)
        back = read_optional(path)
        if back != raw:
            raise Reject("bridge_request_readback")
        return parse_request(back)

    def result(self, external_task_id):
        raw = read_optional(bridge_path(self.outbox_dir, external_task_id))
        if raw is None:
            return None
        return parse_result(raw)


def main(argv):
    """Manual inspection only: no arguments, prints the fixed directory constants."""
    if len(argv) != 1:
        sys.stderr.write(json.dumps({"status": "REFUSED", "reason": "usage"}) + "\n")
        return 1
    sys.stdout.write(json.dumps({"inbox": INBOX_DIR, "outbox": OUTBOX_DIR,
                                 "request_kind": REQUEST_KIND, "result_kind": RESULT_KIND,
                                 "schema_version": SCHEMA_VERSION}, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
