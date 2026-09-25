"""CC-only immutable receipt storage and house_bridge host method composition.

Install a private persistent directory under the Command Center service UID;
HK must have neither this filesystem identity nor the injected KMS credential.
The directory's ancestor chain is a trusted installer responsibility.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from acceptance_gate import Refusal
from house_bridge import canonical
from kms_receipts import receipt_payload


class ReceiptStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        if not self.root.is_absolute():
            raise Refusal("receipt_store_path")

    @contextmanager
    def _directory(self):
        fd = None
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise Refusal("receipt_store_permissions")
            yield fd
        except OSError as exc:
            raise Refusal("receipt_store_io") from exc
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _name(task_id, nonce):
        if any(type(x) is not str or not 0 < len(x) <= 200 for x in (task_id, nonce)):
            raise Refusal("receipt_store_identity")
        return hashlib.sha256(canonical([task_id, nonce])).hexdigest() + ".json"

    @staticmethod
    def _read(directory, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                    stat.S_IMODE(info.st_mode) != 0o600):
                raise Refusal("receipt_file_permissions")
            raw = stream.read(32001)
        if not 0 < len(raw) <= 32000:
            raise Refusal("receipt_store_bytes")
        return raw

    def read(self, task_id, nonce):
        name = self._name(task_id, nonce)
        with self._directory() as directory:
            return self._read(directory, name)

    def publish(self, task_id, nonce, raw):
        if type(raw) is not bytes or not 0 < len(raw) <= 32000:
            raise Refusal("receipt_store_bytes")
        name = self._name(task_id, nonce)
        with self._directory() as directory:
            temp = ".pending-" + secrets.token_hex(16)
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    # Atomic no-overwrite publication on the same local filesystem.
                    os.link(temp, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                except FileExistsError:
                    if self._read(directory, name) != raw:
                        raise Refusal("receipt_store_conflict")
                os.fsync(directory)
                if self._read(directory, name) != raw:
                    raise Refusal("receipt_store_readback")
            finally:
                os.unlink(temp, dir_fd=directory)
                os.fsync(directory)


class ControlReceiptRoute:
    """Bind these four methods on the CC host passed to receive_evidence()."""

    def __init__(self, signer, store: ReceiptStore):
        self.signer, self.store = signer, store

    def sign_control_receipt(self, raw):
        return self.signer.sign_control_receipt(raw)

    def verify_control_receipt(self, raw, signature):
        return self.signer.verify_control_receipt(raw, signature)

    def read_control_receipt(self, task_id, nonce):
        return self.store.read(task_id, nonce)

    def publish_control_receipt(self, task_id, nonce, raw):
        if type(raw) is not bytes or not 0 < len(raw) <= 32000:
            raise Refusal("receipt_route_bytes")
        try:
            record = json.loads(raw)
            if type(record) is not dict or canonical(record) + b"\n" != raw:
                raise Refusal("receipt_route_schema")
            signature = record.pop("signature")
        except (ValueError, UnicodeError, KeyError) as exc:
            raise Refusal("receipt_route_schema") from exc
        unsigned = canonical(record)
        receipt_payload(unsigned)
        if record["task_id"] != task_id or record["nonce"] != nonce:
            raise Refusal("receipt_route_binding")
        if self.verify_control_receipt(unsigned, signature) is not True:
            raise Refusal("receipt_route_signature")
        self.store.publish(task_id, nonce, raw)
