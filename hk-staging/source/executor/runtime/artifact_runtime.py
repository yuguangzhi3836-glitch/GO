"""Read side of the sealed candidate-artifact store (contract ``go.sealed-artifact.v1``).

The agent seals; this module resolves and materialises.  It is deliberately
separate from the agent's writer because the two ship in different units, and the
constants below are the whole interface between them -- a test re-reads both files
and fails if they ever disagree.

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
MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024
UNTRUSTED_BITS = 0o077
DIRECTORY_MODE = 0o700
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
CONFIG_NAME = "manifest.json"


class Reject(ValueError):
    pass


def _effective_uid(fallback=None):
    getter = getattr(os, "geteuid", None) or getattr(os, "getuid", None)
    return getter() if getter is not None else fallback


def _object_dir(root=STORE_ROOT):
    root = root if root is not None else STORE_ROOT
    for path in (root, os.path.join(root, OBJECT_DIR)):
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise Reject("E_ARTIFACT_STORE_UNAVAILABLE") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Reject("E_ARTIFACT_STORE_UNAVAILABLE")
        if info.st_uid != _effective_uid(info.st_uid) or stat.S_IMODE(info.st_mode) != DIRECTORY_MODE:
            raise Reject("E_ARTIFACT_STORE_UNTRUSTED")
    return os.path.join(root, OBJECT_DIR)


def resolve(package_sha256, root=STORE_ROOT):
    """The verified path of a sealed package, or a refusal."""
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
        if not stat.S_ISREG(info.st_mode) or info.st_uid != _effective_uid(info.st_uid):
            raise Reject("E_ARTIFACT_PACKAGE_UNTRUSTED")
        if info.st_mode & UNTRUSTED_BITS:
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
