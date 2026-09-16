"""Sealed candidate-artifact store: the durable half of a TEST_PR build.

Contract ``go.sealed-artifact.v1``
----------------------------------
A TEST_PR builds an image and the build is thrown away: ``test_pr.py`` removes
the image in its ``finally`` block, so what the signed Evidence reported
(``built_image_id``) is a *build identity*, not a deliverable.  Nothing can
later CANARY or DEPLOY it, because no copy of those bytes exists anywhere.

This module is the missing half.  It turns the exact image a TEST_PR just built
into an immutable, content-addressed package in a fixed local store, and it
resolves that package back into the same image on demand.

    seal(runner, image_ref, image_id)   ->  {"package_sha256": ..., "image_id": ...}
    resolve(package_sha256)             ->  verified package path
    load(runner, package_sha256, image_id) -> the image is present in Docker again

Why the package identity is a SHA256 and not a registry digest
-------------------------------------------------------------
A registry manifest digest only exists after a push, and it is not equal to the
image's config ID in general.  A build that is never pushed has neither.  The
store therefore identifies the package by the SHA256 of the package bytes
itself, and the image by the config ID the build already reported.  Both
identities are recorded; neither is invented.

The unpacked package identity is checked three independent ways before the
image is allowed back into Docker:

* the file's own SHA256 equals the name it is stored under,
* the archive's config blob hashes to ``image_id`` (the bytes ARE that image),
* ``docker load`` then reports ``.Id == image_id``.

What is fixed, and what a caller can never choose
-------------------------------------------------
Store root, object directory names, file names, ``docker`` argv, tags, file
modes and the size bound are all constants of this module.  The only value any
caller supplies is a validated 64-hex content address and an image ID that must
match the package — never a path, never an argv, never a tag.

Failure modes are refusals, never repairs: symlinked or group-writable objects,
absent packages, over-sized packages, a name that does not match the content, a
config blob that is not the claimed image, and a loaded image that differs from
the candidate are all rejected.
"""
import hashlib
import os
import re
import secrets
import stat
import tarfile

SCHEMA = "go.sealed-artifact.v1"
STORE_ROOT = "/var/lib/go-hk-artifacts"
OBJECT_DIR = "objects"
SUFFIX = ".tar"
# A candidate application image of this repository is a few hundred MiB; 4 GiB
# is generous and still bounds what the store will ever read back.
MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024
# The sealed package is a build artifact, not a public file.
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700
# Any group or other access to a sealed object means a process other than the
# agent's own user could have written it, so it is not evidence any more.
UNTRUSTED_BITS = 0o077
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
CONFIG_NAME = "manifest.json"
# Tags an image may carry.  Recorded for audit only; never used as authority and
# never passed to Docker by this module.
TAG = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class Reject(Exception):
    """A sealed-artifact operation refused.  Nothing is written and nothing is loaded."""


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def _effective_uid(fallback=None):
    """The uid this process runs as, or ``fallback`` where the platform has no notion of it.

    The production target is Linux, where the store is root-owned.  On a platform
    without an effective uid the comparison is skipped rather than guessed, the
    same way the TEST_PR builder resolves it.
    """
    getter = getattr(os, "geteuid", None) or getattr(os, "getuid", None)
    return getter() if getter is not None else fallback


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def store_root(path=None):
    """The fixed store root, or the one a test supplied.

    The directory must already exist, must not be a symlink, must be owned by the
    effective user and must not be writable by anyone else, so a package can
    never be resolved out of a directory an unprivileged process could plant.
    """
    root = path if path is not None else STORE_ROOT
    try:
        info = os.lstat(root)
    except OSError as exc:
        raise Reject("SEALED_ARTIFACT_STORE_UNAVAILABLE") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Reject("SEALED_ARTIFACT_STORE_UNAVAILABLE")
    owner = _effective_uid(info.st_uid)
    if info.st_uid != owner or stat.S_IMODE(info.st_mode) != DIRECTORY_MODE:
        raise Reject("SEALED_ARTIFACT_STORE_UNTRUSTED")
    if not os.access(root, os.W_OK | os.X_OK):
        raise Reject("SEALED_ARTIFACT_STORE_UNAVAILABLE")
    return root


def object_dir(root):
    directory = os.path.join(root, OBJECT_DIR)
    try:
        info = os.lstat(directory)
    except OSError as exc:
        raise Reject("SEALED_ARTIFACT_STORE_UNAVAILABLE") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Reject("SEALED_ARTIFACT_STORE_UNAVAILABLE")
    owner = _effective_uid(info.st_uid)
    if info.st_uid != owner or stat.S_IMODE(info.st_mode) != DIRECTORY_MODE:
        raise Reject("SEALED_ARTIFACT_STORE_UNTRUSTED")
    return directory


def package_path(package_sha256, root=None):
    """The one path a content address can name.

    A caller supplies a 64-hex identity and nothing else: no directory, no
    extension, no traversal.  Anything else is refused before a path exists.
    """
    if not isinstance(package_sha256, str) or SHA256.fullmatch(package_sha256) is None:
        raise Reject("SEALED_ARTIFACT_PACKAGE_IDENTITY")
    return os.path.join(object_dir(store_root(root)), package_sha256 + SUFFIX)


def _config_digest(archive):
    """The digest of the config blob inside a ``docker save`` archive.

    ``image_id`` is the SHA256 of exactly these bytes, so this is the check that
    says "the archive is that image" without trusting the archive's own index.
    """
    try:
        with tarfile.open(archive, "r:") as tar:
            members = tar.getmembers()
            config = None
            for member in members:
                if member.name.lstrip("./") != CONFIG_NAME or not member.isfile():
                    continue
                if config is not None:
                    raise Reject("SEALED_ARTIFACT_ARCHIVE_INVALID")
                config = member
            if config is None:
                raise Reject("SEALED_ARTIFACT_ARCHIVE_INVALID")
            # The config path inside a save archive is its own member name.
            import json
            index = json.loads(tar.extractfile(config).read().decode("utf-8"))
            if not isinstance(index, list) or len(index) != 1 or not isinstance(index[0], dict):
                raise Reject("SEALED_ARTIFACT_ARCHIVE_INVALID")
            digest = index[0].get("Config")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise Reject("SEALED_ARTIFACT_ARCHIVE_INVALID")
            names = [m for m in members if m.isfile() and m.name.lstrip("./") == digest]
            if len(names) != 1:
                raise Reject("SEALED_ARTIFACT_ARCHIVE_INVALID")
            hasher = hashlib.sha256()
            stream = tar.extractfile(names[0])
            for part in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(part)
            return hasher.hexdigest()
    except Reject:
        raise
    except (OSError, tarfile.TarError, ValueError, KeyError, UnicodeDecodeError) as exc:
        raise Reject("SEALED_ARTIFACT_ARCHIVE_INVALID") from exc


def _read_package_bytes(path, expected_sha256):
    """Open a stored object exactly once, without following a symlink."""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
    except OSError as exc:
        raise Reject("SEALED_ARTIFACT_PACKAGE_UNAVAILABLE") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != _effective_uid(info.st_uid):
            raise Reject("SEALED_ARTIFACT_PACKAGE_UNTRUSTED")
        if info.st_mode & UNTRUSTED_BITS:
            raise Reject("SEALED_ARTIFACT_PACKAGE_UNTRUSTED")
        if info.st_size == 0 or info.st_size > MAX_PACKAGE_BYTES:
            raise Reject("SEALED_ARTIFACT_PACKAGE_OVERSIZED")
        hasher = hashlib.sha256()
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(part)
    if hasher.hexdigest() != expected_sha256:
        raise Reject("SEALED_ARTIFACT_PACKAGE_TAMPERED")
    return path


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #
def seal(runner, image_ref, image_id, root=None, tags=None):
    """Publish the image that is currently tagged ``image_ref`` as an immutable package.

    The build has already happened; this only preserves its exact bytes.  The
    image the caller names must be the image Docker reports, so a package can
    never be sealed under an identity the caller chose.
    """
    if not isinstance(image_ref, str) or TAG.fullmatch(image_ref) is None:
        raise Reject("SEALED_ARTIFACT_IMAGE_REFERENCE")
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise Reject("SEALED_ARTIFACT_IMAGE_IDENTITY")
    reported = runner(["/usr/bin/docker", "image", "inspect", image_ref, "--format", "{{.Id}}"])
    if getattr(reported, "returncode", 0) or (reported.stdout or "").strip() != image_id:
        raise Reject("SEALED_ARTIFACT_BUILT_IMAGE_MISMATCH")

    directory = object_dir(store_root(root))
    temporary = os.path.join(directory, "." + secrets.token_hex(16) + ".tmp")
    try:
        runner(["/usr/bin/docker", "save", "--output", temporary, image_ref], timeout=900)
        os.chmod(temporary, FILE_MODE)
        config_digest = _config_digest(temporary)
        if config_digest != image_id.split(":", 1)[1]:
            raise Reject("SEALED_ARTIFACT_CONFIG_MISMATCH")
        size = os.stat(temporary).st_size
        if size == 0 or size > MAX_PACKAGE_BYTES:
            raise Reject("SEALED_ARTIFACT_PACKAGE_OVERSIZED")
        package_sha256 = _sha256_file(temporary)
        destination = os.path.join(directory, package_sha256 + SUFFIX)
        if os.path.exists(destination):
            # Same content address must mean the same bytes.  A differing object
            # under this name is tampering, and is refused rather than replaced.
            if _sha256_file(destination) != package_sha256:
                raise Reject("SEALED_ARTIFACT_COLLISION")
        else:
            os.replace(temporary, destination)
            temporary = None
            os.chmod(destination, FILE_MODE)
        _fsync_directory(directory)
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass
    return {
        "schema": SCHEMA,
        "image_id": image_id,
        "package_sha256": package_sha256,
        "package_bytes": size,
        "store": os.path.basename(store_root(root)),
        "image_reference": image_ref,
        "image_tags": sorted(tags or ()),
    }


def _fsync_directory(path):
    """Make a rename durable.  Where the platform cannot open a directory, skip it."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def resolve(package_sha256, root=None):
    """Return the verified path of a package, or refuse.

    Verification is byte-level and identity-based: the object is opened without
    following symlinks, must be a regular root-owned 0600 file inside the fixed
    store, and its SHA256 must equal the address it was asked for.
    """
    return _read_package_bytes(package_path(package_sha256, root), package_sha256)


def load(runner, package_sha256, image_id, root=None):
    """Materialise the sealed package back into Docker and prove it is the candidate.

    A ``docker load`` that brings in a different image, or a package whose
    archive is not the claimed image, is refused; the candidate is only allowed
    to exist once the loaded ID equals the one the package seals.
    """
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise Reject("SEALED_ARTIFACT_IMAGE_IDENTITY")
    path = resolve(package_sha256, root)
    if _config_digest(path) != image_id.split(":", 1)[1]:
        raise Reject("SEALED_ARTIFACT_CONFIG_MISMATCH")
    loaded = runner(["/usr/bin/docker", "load", "--input", path], timeout=600)
    if getattr(loaded, "returncode", 0):
        raise Reject("SEALED_ARTIFACT_LOAD_FAILED")
    reported = runner(["/usr/bin/docker", "image", "inspect", image_id, "--format", "{{.Id}}"])
    if getattr(reported, "returncode", 0) or (reported.stdout or "").strip() != image_id:
        raise Reject("SEALED_ARTIFACT_LOADED_IMAGE_MISMATCH")
    return {"schema": SCHEMA, "image_id": image_id, "package_sha256": package_sha256,
            "load": "PASS", "image_present": "PASS"}
