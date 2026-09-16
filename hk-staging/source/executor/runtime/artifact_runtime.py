"""Read side of the sealed candidate-artifact store (contract ``go.sealed-artifact.v1``).

The agent seals; this module resolves and materialises.  It is deliberately
separate from the agent's writer because the two ship in different units, and the
constants below are the whole interface between them -- a test re-reads both files
and fails if they ever disagree.

Who owns what, and why the reader is not the author
---------------------------------------------------
The two halves of this contract never run as the same account: the agent writes
the store (systemd ``User=go-hk-agent``) and this module runs inside the Hong Kong
executor, which the agent invokes as ``sudo -n /usr/local/libexec/go-hk-deployctl``
and therefore as root.  Ownership here means "which account is allowed to have
written this evidence", never "who is reading it".  An earlier revision compared
each object's owner with this process's own effective uid, which made a package
written by ``go-hk-agent`` unreadable by root and a package root wrote look
legitimate -- the one arrangement that can actually never happen.  The anchor is
now the fixed account name, resolved from the account database on every check, and
this module never consults its own identity at all.

Why there is no repo digest here
--------------------------------
A registry manifest digest exists only after a push, and it is not equal to an
image's config ID in general.  Identifying a candidate by a digest whose suffix
must equal its own image ID was therefore never satisfiable for a host-built
image; the sealed package's own SHA256 is the delivery identity instead, and the
image identity stays the config ID the build reported.

Everything the caller supplies is validated, and nothing the caller supplies is a
path: the object path is derived from the content address alone.
"""
import hashlib
import json
import os
import re
import stat
import tarfile

SCHEMA = "go.sealed-artifact.v1"
STORE_ROOT = "/var/lib/go-hk-artifacts"
OBJECT_DIR = "objects"
SUFFIX = ".tar"
# The store has exactly one trusted author.  These are account *names*: the ids
# behind them are resolved on the host that applies the rule, never assumed here.
TRUSTED_WRITER_USER = "go-hk-agent"
TRUSTED_WRITER_GROUP = "go-hk-agent"
MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024
FILE_MODE = 0o600
UNTRUSTED_BITS = 0o077
DIRECTORY_MODE = 0o700
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
CONFIG_NAME = "manifest.json"


class Reject(ValueError):
    pass


def _system_identity():
    """``(uid, gid)`` of the trusted writer account, from the account database.

    Nothing is assumed when the account cannot be resolved: the failure is a
    refusal, because every fallback (the current process, root, the file's own
    owner) would move the trust anchor to whatever the caller happens to be.
    """
    try:
        import grp
        import pwd
    except ImportError as exc:
        raise Reject("E_ARTIFACT_ACCOUNT_UNAVAILABLE") from exc
    try:
        uid = pwd.getpwnam(TRUSTED_WRITER_USER).pw_uid
        gid = grp.getgrnam(TRUSTED_WRITER_GROUP).gr_gid
    except KeyError as exc:
        raise Reject("E_ARTIFACT_ACCOUNT_UNAVAILABLE") from exc
    if uid == 0 or gid == 0:
        raise Reject("E_ARTIFACT_ACCOUNT_UNTRUSTED")
    return uid, gid


# Tests replace this to model a store written by one account and read by another;
# production never replaces it.
_IDENTITY_RESOLVER = _system_identity


def trusted_identity():
    """The ``(uid, gid)`` every directory and object in the store must carry."""
    identity = _IDENTITY_RESOLVER()
    if (not isinstance(identity, tuple) or len(identity) != 2
            or not all(isinstance(value, int) and not isinstance(value, bool)
                       and value >= 0 for value in identity)):
        raise Reject("E_ARTIFACT_ACCOUNT_UNTRUSTED")
    return identity


def _trusted_directory(path):
    """A store directory that is exactly the trusted writer's, or a refusal."""
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise Reject("E_ARTIFACT_STORE_UNAVAILABLE") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Reject("E_ARTIFACT_STORE_UNAVAILABLE")
    if (info.st_uid, info.st_gid) != trusted_identity():
        raise Reject("E_ARTIFACT_STORE_UNTRUSTED")
    if stat.S_IMODE(info.st_mode) != DIRECTORY_MODE:
        raise Reject("E_ARTIFACT_STORE_UNTRUSTED")
    return path


def _object_dir(root=STORE_ROOT):
    root = root if root is not None else STORE_ROOT
    _trusted_directory(root)
    return _trusted_directory(os.path.join(root, OBJECT_DIR))


def resolve(package_sha256, root=STORE_ROOT):
    """The verified path of a sealed package, or a refusal.

    The object is opened without following a symlink and must be a regular file
    owned by the trusted writer account, carrying exactly the sealed file mode,
    within the size bound, with a SHA256 equal to the address asked for.  Root
    reading a package it does not own is the normal case, not an exception.
    """
    if not isinstance(package_sha256, str) or SHA256.fullmatch(package_sha256) is None:
        raise Reject("E_ARTIFACT_PACKAGE_IDENTITY")
    path = os.path.join(_object_dir(root), package_sha256 + SUFFIX)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
    except OSError as exc:
        raise Reject("E_ARTIFACT_PACKAGE_UNAVAILABLE") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise Reject("E_ARTIFACT_PACKAGE_UNTRUSTED")
        if (info.st_uid, info.st_gid) != trusted_identity():
            raise Reject("E_ARTIFACT_PACKAGE_UNTRUSTED")
        if stat.S_IMODE(info.st_mode) != FILE_MODE or info.st_mode & UNTRUSTED_BITS:
            raise Reject("E_ARTIFACT_PACKAGE_UNTRUSTED")
        if info.st_size == 0 or info.st_size > MAX_PACKAGE_BYTES:
            raise Reject("E_ARTIFACT_PACKAGE_OVERSIZED")
        hasher = hashlib.sha256()
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(part)
    if hasher.hexdigest() != package_sha256:
        raise Reject("E_ARTIFACT_PACKAGE_TAMPERED")
    return path


def config_digest(path):
    """The digest of the config blob inside a ``docker save`` archive."""
    try:
        with tarfile.open(path, "r:") as tar:
            members = tar.getmembers()
            index = None
            for member in members:
                if member.name.lstrip("./") == CONFIG_NAME and member.isfile():
                    if index is not None:
                        raise Reject("E_ARTIFACT_ARCHIVE_INVALID")
                    index = json.loads(tar.extractfile(member).read().decode("utf-8"))
            if not isinstance(index, list) or len(index) != 1 or not isinstance(index[0], dict):
                raise Reject("E_ARTIFACT_ARCHIVE_INVALID")
            digest = index[0].get("Config")
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise Reject("E_ARTIFACT_ARCHIVE_INVALID")
            blobs = [m for m in members if m.isfile() and m.name.lstrip("./") == digest]
            if len(blobs) != 1:
                raise Reject("E_ARTIFACT_ARCHIVE_INVALID")
            hasher = hashlib.sha256()
            stream = tar.extractfile(blobs[0])
            for part in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(part)
            return hasher.hexdigest()
    except Reject:
        raise
    except (OSError, tarfile.TarError, ValueError, KeyError, UnicodeDecodeError) as exc:
        raise Reject("E_ARTIFACT_ARCHIVE_INVALID") from exc


def materialise(runner, package_sha256, image_id, root=STORE_ROOT):
    """Make the sealed candidate image present in Docker, and prove it is that image.

    The image is only allowed to exist once the package's own bytes hash to the
    address asked for, the archive's config blob hashes to the candidate image ID,
    and Docker reports the loaded image as that same ID.
    """
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise Reject("E_ARTIFACT_IMAGE_IDENTITY")
    path = resolve(package_sha256, root)
    if config_digest(path) != image_id.split(":", 1)[1]:
        raise Reject("E_ARTIFACT_CONFIG_MISMATCH")
    loaded = runner(["/usr/bin/docker", "load", "--input", path], 600)
    if getattr(loaded, "returncode", 0):
        raise Reject("E_ARTIFACT_LOAD_FAILED")
    reported = runner(["/usr/bin/docker", "image", "inspect", image_id, "--format", "{{.Id}}"], 30)
    if getattr(reported, "returncode", 0) or (reported.stdout or "").strip() != image_id:
        raise Reject("E_ARTIFACT_LOADED_IMAGE_MISMATCH")
    return {"artifact_package": "PASS", "artifact_materialised": "PASS", "candidate_image": "PASS"}
