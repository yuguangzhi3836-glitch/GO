"""C14-only adapters for the existing private Task and Evidence Git repositories.

No signing, reviewer identity creation, task execution or installation. Bind only
inside the corresponding trusted CC/HK host; Git credentials remain host-owned.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from acceptance_gate import C14_ACTION, C14_ENVIRONMENT, Refusal
from c13_attestation import CANDIDATE, TREE, SCOPE
from house_bridge import canonical, digest, TASK_FIELDS, EVIDENCE_FIELDS

REPOSITORIES = {
    "tasks": "git@github.com:chenzhenxi1-sudo/go-control-tasks.git",
    "evidence": "git@github.com:chenzhenxi1-sudo/go-control-evidence.git",
}
LIMITS = {"junit": 8_000_000, "stdout": 2_000_000, "manifest": 64_000}
ZERO = "0" * 40


def identity(task_id, nonce=None):
    if type(task_id) is not str or not re.fullmatch(r"go-c14-acceptance-[0-9a-f]{32}", task_id):
        raise Refusal("bus_task_identity")
    if nonce is not None and (type(nonce) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", nonce)):
        raise Refusal("bus_nonce")
    return task_id + ("-" + nonce if nonce is not None else "")


def envelope(raw, task_id, nonce=None):
    limit = 256_000 if nonce is not None else 32_000
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= limit:
            raise ValueError("size")
        data = json.loads(raw)
        fields = EVIDENCE_FIELDS if nonce is not None else TASK_FIELDS
        source = data["executor_result"] if nonce is not None else data["parameters"]
        if (type(data) is not dict or set(data) != fields or raw != canonical(data) + b"\n" or
                data["schema_version"] != "1" or data["task_id"] != task_id or
                data["action_id"] != C14_ACTION or data["environment"] != C14_ENVIRONMENT or
                (source["candidate_sha"], source["application_tree"], source["test_scope_sha256"]) !=
                (CANDIDATE, TREE, SCOPE) or (nonce is not None and data["nonce"] != nonce)):
            raise ValueError("scope")
        identity(task_id, data["nonce"])
        return data
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise Refusal("bus_envelope") from exc


class GitAcceptanceBus:
    """One private persistent clone per role; no working-tree/index mutations.

    CC: tasks write-enabled, evidence read-only. HK: tasks read-only, evidence
    write-enabled. Repository permissions must independently enforce that split.
    The installer provisions the clone and SSH trust; this class never clones,
    reads key files, opens an interactive credential prompt or changes config.
    """

    def __init__(self, repository, kind, *, write_enabled=False):
        if kind not in REPOSITORIES or type(write_enabled) is not bool:
            raise Refusal("bus_configuration")
        self.repository, self.kind, self.write_enabled = Path(repository), kind, write_enabled
        if not self.repository.is_absolute():
            raise Refusal("bus_repository")
        self.env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "SSH_AUTH_SOCK"}}
        self.env.update(LC_ALL="C", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
                        GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
                        GIT_AUTHOR_NAME="GO C14 Bus", GIT_AUTHOR_EMAIL="go-c14-bus@localhost",
                        GIT_COMMITTER_NAME="GO C14 Bus", GIT_COMMITTER_EMAIL="go-c14-bus@localhost")
        self.pending = {}
        self.snapshots = {}

    def _git(self, args, *, data=None, index=None, optional=False):
        env = dict(self.env)
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        try:
            result = subprocess.run(["git", "-C", str(self.repository),
                "-c", "core.hooksPath=/dev/null", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                "-c", "push.followTags=false", "-c", "push.recurseSubmodules=no",
                "-c", "core.fsync=committed,reference", "-c", "core.fsyncMethod=fsync",
                "-c", "commit.gpgSign=false", *args], input=data, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Refusal("bus_git_unavailable") from exc
        if result.returncode:
            if optional and result.returncode == 1:
                return None
            raise Refusal("bus_git_operation")
        return result.stdout

    @contextmanager
    def _locked(self):
        fd = None
        try:
            info = self.repository.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise Refusal("bus_repository_permissions")
            fd = os.open(self.repository / ".c14-bus.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            lock_info = os.fstat(fd)
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid() or stat.S_IMODE(lock_info.st_mode) != 0o600:
                raise Refusal("bus_lock_permissions")
            fcntl.flock(fd, fcntl.LOCK_EX)
            version = re.match(rb"git version (\d+)\.(\d+)", self._git(["version"]))
            if version is None or tuple(map(int, version.groups())) < (2, 38):
                raise Refusal("bus_git_durability_version")
            origins = self._git(["remote", "get-url", "--all", "origin"]).decode().splitlines()
            if origins != [REPOSITORIES[self.kind]]:
                raise Refusal("bus_remote_binding")
            yield
        except OSError as exc:
            raise Refusal("bus_repository_unavailable") from exc
        finally:
            if fd is not None:
                os.close(fd)

    def _snapshot(self):
        # Explicit URL avoids an independently configured pushurl/refspec/mirror.
        self._git(["fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                   REPOSITORIES[self.kind], "+refs/heads/main:refs/c14/latest"])
        return self._git(["rev-parse", "--verify", "refs/c14/latest^{commit}"]).decode().strip()

    def _read(self, commit, path, limit):
        entry = self._git(["ls-tree", "-z", commit, "--", path])
        if not entry:
            return None
        try:
            metadata, name = entry.rstrip(b"\0").split(b"\t")
            mode, kind, oid = metadata.split()
            if mode != b"100644" or kind != b"blob" or name.decode() != path:
                raise ValueError("type")
            size = int(self._git(["cat-file", "-s", oid.decode()]))
            if size > limit:
                raise ValueError("size")
            raw = self._git(["cat-file", "blob", oid.decode()])
            if len(raw) != size:
                raise ValueError("size")
            return raw
        except (ValueError, UnicodeError) as exc:
            raise Refusal("bus_blob") from exc

    def _require(self, kind, write=False):
        if self.kind != kind or (write and not self.write_enabled):
            raise Refusal("bus_role")

    def _ref(self, key):
        return "refs/c14/outbox/" + self.kind + "/" + key

    def _ref_value(self, ref):
        found = self._git(["show-ref", "--verify", "--quiet", ref], optional=True)
        if found is None:
            return None
        return self._git(["rev-parse", "--verify", ref + "^{commit}"]).decode().strip()

    def _state(self, snapshot, files):
        existing = {path: self._read(snapshot, path, len(raw)) for path, raw in files.items()}
        if all(raw is None for raw in existing.values()):
            return "absent"
        if existing == files:
            return "exact"
        raise Refusal("bus_remote_conflict")

    def _commit(self, parent, files, key):
        with tempfile.TemporaryDirectory(prefix="c14-index-") as tmp:
            index = Path(tmp) / "index"
            self._git(["read-tree", parent], index=index)
            for path, raw in sorted(files.items()):
                oid = self._git(["hash-object", "-w", "--stdin"], data=raw).decode().strip()
                self._git(["update-index", "--add", "--cacheinfo", "100644," + oid + "," + path], index=index)
            tree = self._git(["write-tree"], index=index).decode().strip()
        return self._git(["commit-tree", tree, "-p", parent], data=("C14 bus publication: " + key + "\n").encode()).decode().strip()

    def _send(self, commit, files):
        try:
            self._git(["push", "--porcelain", REPOSITORIES[self.kind], commit + ":refs/heads/main"])
        except Refusal:
            # A disconnected client cannot tell whether the server accepted the
            # push. Re-read exact bytes; never create another Task or signature.
            snapshot = self._snapshot()
            if self._state(snapshot, files) == "exact":
                return snapshot
            raise Refusal("bus_publication_pending")
        snapshot = self._snapshot()
        if self._state(snapshot, files) != "exact":
            raise Refusal("bus_publication_readback")
        return snapshot

    def _publish(self, key, files):
        with self._locked():
            ref = self._ref(key)
            if self._ref_value(ref) is not None:
                raise Refusal("bus_outbox_exists_use_recovery")
            parent = self._snapshot()
            if self._state(parent, files) != "absent":
                raise Refusal("bus_already_published")
            commit = self._commit(parent, files, key)
            # Atomic create, durable objects/ref BEFORE the network mutation.
            self._git(["update-ref", ref, commit, ZERO])
            return self._send(commit, files)

    def publish_house_task(self, task_id, raw):
        self._require("tasks", write=True)
        key = identity(task_id)
        envelope(raw, task_id)
        return self._publish(key, {"tasks/" + task_id + ".json": raw})

    def read_house_task(self, task_id):
        self._require("tasks")
        identity(task_id)
        with self._locked():
            return self._read(self._snapshot(), "tasks/" + task_id + ".json", 32_000)

    def publish_house_artifact(self, task_id, nonce, name, raw):
        self._require("evidence", write=True)
        key = identity(task_id, nonce)
        if name not in LIMITS or type(raw) is not bytes or len(raw) > LIMITS[name]:
            raise Refusal("bus_artifact")
        blobs = self.pending.setdefault(key, {})
        if name in blobs and blobs[name] != raw:
            raise Refusal("bus_artifact_conflict")
        blobs[name] = raw

    def _bundle(self, task_id, nonce, raw, blobs):
        data = envelope(raw, task_id, nonce)
        if set(blobs) != set(LIMITS) or any(type(b) is not bytes or len(b) > LIMITS[n] or
                digest(b) != data["executor_result"].get(n + "_sha256") for n, b in blobs.items()):
            raise Refusal("bus_artifact_binding")
        key = identity(task_id, nonce)
        return {"evidence/" + key + ".json": raw,
                **{"artifacts/c14/" + key + "/" + name: blob for name, blob in blobs.items()}}

    def publish_house_evidence(self, task_id, nonce, raw):
        self._require("evidence", write=True)
        key = identity(task_id, nonce)
        files = self._bundle(task_id, nonce, raw, self.pending.get(key, {}))
        result = self._publish(key, files)
        self.pending.pop(key, None)
        return result

    def read_house_evidence(self, task_id, nonce):
        self._require("evidence")
        key = identity(task_id, nonce)
        with self._locked():
            snapshot = self._snapshot()
            self.snapshots[key] = snapshot
            self._git(["update-ref", "refs/c14/readback/" + key, snapshot])
            return self._read(snapshot, "evidence/" + key + ".json", 256_000)

    def read_house_artifact(self, task_id, nonce, name):
        self._require("evidence")
        key = identity(task_id, nonce)
        if name not in LIMITS or key not in self.snapshots:
            raise Refusal("bus_evidence_snapshot_required")
        with self._locked():
            return self._read(self.snapshots[key], "artifacts/c14/" + key + "/" + name, LIMITS[name])

    def recover_publication(self, task_id, nonce=None):
        """Publish only previously persisted bytes; no signing, execution or TTL refresh."""
        self._require("tasks" if nonce is None else "evidence", write=True)
        key = identity(task_id, nonce)
        with self._locked():
            ref = self._ref(key)
            commit = self._ref_value(ref)
            if commit is None:
                raise Refusal("bus_no_pending_publication")
            if nonce is None:
                path = "tasks/" + key + ".json"
                raw = self._read(commit, path, 32_000)
                envelope(raw, task_id)
                files = {path: raw}
            else:
                raw = self._read(commit, "evidence/" + key + ".json", 256_000)
                blobs = {n: self._read(commit, "artifacts/c14/" + key + "/" + n, limit) for n, limit in LIMITS.items()}
                files = self._bundle(task_id, nonce, raw, blobs)
            changed = self._git(["diff-tree", "--no-commit-id", "--name-only", "-r", commit]).decode().splitlines()
            if set(changed) != set(files):
                raise Refusal("bus_outbox_scope")
            parent = self._snapshot()
            if self._state(parent, files) == "exact":
                return parent
            # Health traffic may have advanced main. Re-parent the same exact
            # file bytes once under explicit recovery; no force push or loop.
            replacement = self._commit(parent, files, key)
            self._git(["update-ref", ref, replacement, commit])
            return self._send(replacement, files)
