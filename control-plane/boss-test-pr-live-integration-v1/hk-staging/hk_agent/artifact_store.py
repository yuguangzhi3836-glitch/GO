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

Who owns the store, and why it is not the reader
------------------------------------------------
The two halves of this contract never run as the same account: the agent writes
the store (systemd ``User=go-hk-agent``) and the Hong Kong executor reads it
through ``sudo`` as root.  Ownership is therefore a property of the *evidence* —
"which account is allowed to have written this" — and not of whoever is reading
it.  Comparing an object's owner with the reader's own uid, as both halves of
this contract used to do, made one operation unsatisfiable by construction: a
package written by ``go-hk-agent`` could never be read by root, and a package
root owned could never have been written by the agent.

The trust anchor is consequently a fixed account name, resolved from the system
account database on every check.  No numeric uid is written down anywhere: a uid
is machine state, and a hard-coded one would silently become the anchor on a host
where that number means something else.  A resolver that cannot find the account
is a refusal, and never falls back to the current process, to root, or to
"whatever owns the file".

What is fixed, and what a caller can never choose
-------------------------------------------------
Store root, object directory names, file names, ``docker`` argv, tags, file
modes, the trusted writer account and the size bound are all constants of this
module.  The only value any caller supplies is a validated 64-hex content address
and an image ID that must match the package — never a path, never an argv, never
a tag, never an owner.

Failure modes are refusals, never repairs: symlinked or wrongly-owned objects,
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
# The store has exactly one trusted author.  These are account *names*: the ids
# behind them are resolved on the host that applies the rule, never assumed here.
TRUSTED_WRITER_USER = "go-hk-agent"
TRUSTED_WRITER_GROUP = "go-hk-agent"
# A candidate application image of this repository is a few hundred MiB; 4 GiB
# is generous and still bounds what the store will ever read back.
MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024
# The sealed package is a build artifact, not a public file.
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700
# Any group or other access to a sealed object means a process other than the
# trusted writer could have written it, so it is not evidence any more.  The
# exact-mode comparison above already excludes every such combination; this mask
# is kept as a second, independent refusal so a future relaxation of the mode
# comparison cannot quietly widen the contract.
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
# the trust anchor
# --------------------------------------------------------------------------- #
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
        raise Reject("SEALED_ARTIFACT_ACCOUNT_UNAVAILABLE") from exc
    try:
        uid = pwd.getpwnam(TRUSTED_WRITER_USER).pw_uid
        gid = grp.getgrnam(TRUSTED_WRITER_GROUP).gr_gid
    except KeyError as exc:
        raise Reject("SEALED_ARTIFACT_ACCOUNT_UNAVAILABLE") from exc
    if uid == 0 or gid == 0:
        raise Reject("SEALED_ARTIFACT_ACCOUNT_UNTRUSTED")
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
        raise Reject("SEALED_ARTIFACT_ACCOUNT_UNTRUSTED")
    return identity


def _process_identity():
    """``(euid, egid)`` of this process, or ``None`` where the platform has none."""
    uid = getattr(os, "geteuid", None) or getattr(os, "getuid", None)
    gid = getattr(os, "getegid", None) or getattr(os, "getgid", None)
    if uid is None or gid is None:
        return None
    return uid(), gid()


def require_writer_identity():
    """Refuse to *write* the store from any account but the trusted writer.

    Only the writing half is gated this way.  The reader is deliberately exempt:
    root consumes the store as a privileged consumer, and consuming an artifact
    does not make root its author.  Where a platform has no effective identity the
    check is skipped rather than guessed, exactly as the TEST_PR builder does.
    """
    current = _process_identity()
    if current is None:
        return None
    if current != trusted_identity():
        raise Reject("SEALED_ARTIFACT_WRITER_IDENTITY")
    return current


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def _trusted_directory(path):
    """A store directory that is exactly the trusted writer's, or a refusal."""
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise Reject("SEALED_ARTIFACT_STORE_UNAVAILABLE") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Reject("SEALED_ARTIFACT_STORE_UNAVAILABLE")
    if (info.st_uid, info.st_gid) != trusted_identity():
        raise Reject("SEALED_ARTIFACT_STORE_UNTRUSTED")
    if stat.S_IMODE(info.st_mode) != DIRECTORY_MODE:
        raise Reject("SEALED_ARTIFACT_STORE_UNTRUSTED")
    return path


def store_root(path=None):
    """The fixed store root, or the one a test supplied.

    The directory must already exist, must not be a symlink, must be owned by the
    trusted writer account and must not be writable by anyone else, so a package
    can never be resolved out of a directory an unprivileged process could plant.
    """
    root = path if path is not None else STORE_ROOT
    _trusted_directory(root)
    if not os.access(root, os.W_OK | os.X_OK):
        raise Reject("SEALED_ARTIFACT_STORE_UNAVAILABLE")
    return root


def object_dir(root):
    return _trusted_directory(os.path.join(root, OBJECT_DIR))


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


def verify_object(path, expected_sha256):
    """The single place a sealed object's bytes are accepted.

    Everything the store promises about a readable object is decided here, so the
    writer can never report a package as sealed under rules the reader would
    later disagree with: the object is opened without following a symlink, must be
    a regular file owned by the trusted writer account, must carry exactly the
    sealed file mode, must be within the size bound, and its SHA256 must equal the
    address it is stored under.

    The owner is compared against the *trusted writer account*, not against this
    process.  That is what lets root read a package the agent wrote -- and what
    stops a package root wrote from ever counting as agent evidence.
    """
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
    except OSError as exc:
        raise Reject("SEALED_ARTIFACT_PACKAGE_UNAVAILABLE") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise Reject("SEALED_ARTIFACT_PACKAGE_UNTRUSTED")
        if (info.st_uid, info.st_gid) != trusted_identity():
            raise Reject("SEALED_ARTIFACT_PACKAGE_UNTRUSTED")
        if stat.S_IMODE(info.st_mode) != FILE_MODE or info.st_mode & UNTRUSTED_BITS:
            raise Reject("SEALED_ARTIFACT_PACKAGE_UNTRUSTED")
        if info.st_size == 0 or info.st_size > MAX_PACKAGE_BYTES:
            raise Reject("SEALED_ARTIFACT_PACKAGE_OVERSIZED")
        hasher = hashlib.sha256()
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(part)
    if hasher.hexdigest() != expected_sha256:
        raise Reject("SEALED_ARTIFACT_PACKAGE_TAMPERED")
    return path


def _publish_no_overwrite(source, destination):
    """Publish ``source`` under ``destination`` without ever replacing an object.

    A hard link gives exactly the semantics a content-addressed store needs: the
    name appears only if it did not exist, and it is either fully visible with its
    final bytes or not there at all.  Where hard links are unavailable the fallback
    is a rename guarded by a fresh existence check, which keeps the same
    no-overwrite promise on a filesystem that cannot express the stronger one.
    """
    try:
        os.link(source, destination)
    except FileExistsError:
        return False
    except OSError:
        if os.path.lexists(destination):
            return False
        os.replace(source, destination)
        return True
    try:
        os.unlink(source)
    except OSError:
        pass
    return True


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #
def seal(runner, image_ref, image_id, root=None, tags=None):
    """Publish the image that is currently tagged ``image_ref`` as an immutable package.

    The build has already happened; this only preserves its exact bytes.  The
    image the caller names must be the image Docker reports, so a package can
    never be sealed under an identity the caller chose.  Sealing is a write, so it
    also requires this process to be the trusted writer account.

    The object is verified once more before this function reports the package as
    sealed, under exactly the rules ``resolve`` will apply later.  Reporting
    ``PROVEN`` for an object that a reader would then refuse is the failure this
    store exists to prevent, so the final check is not optional.
    """
    if not isinstance(image_ref, str) or TAG.fullmatch(image_ref) is None:
        raise Reject("SEALED_ARTIFACT_IMAGE_REFERENCE")
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise Reject("SEALED_ARTIFACT_IMAGE_IDENTITY")
    require_writer_identity()
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
        if _publish_no_overwrite(temporary, destination):
            temporary = None
            os.chmod(destination, FILE_MODE)
        else:
            # The address already resolved.  Same address must mean the same bytes,
            # and the object already there must itself satisfy the trust contract:
            # otherwise a planted or re-owned object would be reported sealed here
            # and only refused later, as a CANARY or DEPLOY refusal.
            if _sha256_file(destination) != package_sha256:
                raise Reject("SEALED_ARTIFACT_COLLISION")
        verify_object(destination, package_sha256)
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
    following symlinks, must be a regular 0600 file owned by the trusted writer
    account inside the fixed store, and its SHA256 must equal the address it was
    asked for.
    """
    return verify_object(package_path(package_sha256, root), package_sha256)


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
