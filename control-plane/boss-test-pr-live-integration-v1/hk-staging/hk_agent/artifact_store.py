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
itself.  Both identities are recorded; neither is invented.

The image's own identity is subtler, and an earlier revision of this contract got
it wrong: it required the archive's config blob to hash to the id that
``docker image inspect`` reports.  On a host using the **containerd image store**
-- Hong Kong runs server 29.7.2 on ``io.containerd.snapshotter.v1`` -- the id
Docker reports is the digest of the descriptor ``index.json`` names, which is an
*index* digest, and the config digest is a different value (measured: ``1c9598d6…``
reported, config ``57beafa2…``).  The two are separate identities and are never
compared with each other; ``image_identity`` accepts either, says which role
matched, and requires the bytes behind whichever it accepted to be in the archive.

The unpacked package identity is checked three independent ways before the
image is allowed back into Docker:

* the file's own SHA256 equals the name it is stored under,
* the archive proves an identity equal to ``image_id``, in a named role, with the
  config blob itself present and hashed,
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
import json
import os
import posixpath
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

# --- the two ``docker save`` formats --------------------------------------- #
# An OCI image layout.  The blob path is *derived* from a content address and
# never taken from JSON, so no descriptor can name a path of its own choosing.
LAYOUT_NAME = "oci-layout"
INDEX_NAME = "index.json"
BLOB_DIR = "blobs/sha256"
OCI_LAYOUT_VERSION = "1.0.0"
# Media types this contract may follow, listed explicitly.  A type outside these
# lists is refused rather than followed: an unknown descriptor must never become
# the authority for which image the candidate is.
INDEX_MEDIA_TYPES = ("application/vnd.oci.image.index.v1+json",
                     "application/vnd.docker.distribution.manifest.list.v2+json")
MANIFEST_MEDIA_TYPES = ("application/vnd.oci.image.manifest.v1+json",
                        "application/vnd.docker.distribution.manifest.v2+json")
CONFIG_MEDIA_TYPES = ("application/vnd.oci.image.config.v1+json",
                      "application/vnd.docker.container.image.v1+json")
# Docker writes attestation manifests beside an image and marks them in two
# different ways depending on how the archive was produced: the manifest body
# carries an ``artifactType`` when the image was built with attestations, and the
# descriptor that names it carries this annotation when the image was *pulled*.
# Measured: a pulled reference's attestation has the annotation and no artifactType,
# and its config blob is a normal-looking image config.  Without both signals the
# attestation's config would enter the set of identities that can name the candidate.
REFERENCE_TYPE_ANNOTATION = "vnd.docker.reference.type"
ATTESTATION_REFERENCE_TYPE = "attestation-manifest"
# A bounded traversal: real archives nest at most one index inside another and
# carry a handful of descriptors.  A hostile archive must not be able to make the
# reader walk without limit, so both the depth and the descriptor count are
# capped, and the same caps are declared by the reader.
MAX_DESCRIPTOR_DEPTH = 4
MAX_DESCRIPTOR_COUNT = 256
MAX_ARCHIVE_MEMBERS = 65536
# The largest document read whole out of an archive: an image manifest, a
# descriptor index, a ``docker save`` index.  Layer and config *blobs* are hashed
# in place and are only buffered when they have to be parsed as JSON.
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024

# The archive-format refusals, shared verbatim with the reader: a writer that
# accepts a graph must never be paired with a reader that refuses it.  Each side
# prefixes them with its own namespace, and a test compares both vocabularies.
ARCHIVE_REFUSALS = ("ARCHIVE_INVALID",          # unreadable, truncated, or no layout at all
                    "MEMBER_UNSAFE",            # absolute, traversing, or a non-regular authority
                    "MEMBER_DUPLICATE",         # one authoritative name, twice
                    "BLOB_AMBIGUOUS",           # one identity, two canonical locations
                    "LAYOUT_AMBIGUOUS",         # two layouts naming different images
                    "OCI_INVALID",              # malformed layout marker, index or manifest
                    "DESCRIPTOR_INVALID",       # a descriptor that contradicts itself
                    "DESCRIPTOR_LIMIT",         # traversal budget exhausted
                    "MEDIA_TYPE_UNSUPPORTED",   # unknown type would have to be image authority
                    "BLOB_MISSING",             # a blob this contract must read is not in the archive
                    "BLOB_MISMATCH",            # a blob does not size or hash to its descriptor
                    "IMAGE_IDENTITY_MISMATCH")  # the archive proves no identity equal to the candidate
_REFUSAL_PREFIX = "SEALED_ARTIFACT_"
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


def _refuse(code):
    """One archive-format refusal, named from the vocabulary both sides declare."""
    raise Reject(_REFUSAL_PREFIX + code)


def _authoritative(name):
    """A member name that can decide what image an archive is."""
    return name in (LAYOUT_NAME, INDEX_NAME, CONFIG_NAME) or name.startswith(BLOB_DIR + "/")


def _member_index(tar):
    """Every regular member by name, with anything unsafe refused.

    A tar member name is data, so it is not trusted: nothing absolute, nothing
    that traverses and nothing that is not already normalised is accepted.  An
    *authoritative* name -- the layout markers and every blob path -- must be a
    plain regular file and must appear exactly once; a symlink, a hard link, a
    device or a FIFO under such a name is refused rather than followed.  Members
    outside that namespace are ignored, because an archive may carry anything else
    and none of it can change which image the archive is.
    """
    regular = {}
    count = 0
    for member in tar.getmembers():
        count += 1
        if count > MAX_ARCHIVE_MEMBERS:
            _refuse("DESCRIPTOR_LIMIT")
        name = member.name
        if not isinstance(name, str) or not name or "\x00" in name or name.startswith("/"):
            _refuse("MEMBER_UNSAFE")
        normal = name[2:] if name.startswith("./") else name
        if (not normal or normal == ".." or normal.startswith("../")
                or posixpath.normpath(normal) != normal):
            _refuse("MEMBER_UNSAFE")
        if member.isdir():
            continue
        if not member.isfile():
            if _authoritative(normal):
                _refuse("MEMBER_UNSAFE")
            continue
        if normal in regular:
            if _authoritative(normal):
                _refuse("MEMBER_DUPLICATE")
            continue
        regular[normal] = member
    return regular


def _read_member(tar, member, limit=MAX_DOCUMENT_BYTES):
    """One small member read whole.  Only a document we mean to parse is read."""
    if member.size is None or member.size < 0 or member.size > limit:
        _refuse("ARCHIVE_INVALID")
    stream = tar.extractfile(member)
    if stream is None:
        _refuse("ARCHIVE_INVALID")
    data = stream.read(limit + 1)
    if len(data) != member.size:
        _refuse("ARCHIVE_INVALID")
    return data


def _document(data, code):
    """A JSON object, or a refusal.  A document is never half-read."""
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        _refuse(code)
    if not isinstance(value, dict):
        _refuse(code)
    return value


def _blob(tar, regular, digest, size, paths, document=False):
    """The one verified member a content address names.

    Exactly one of ``paths`` must hold it; an identity present at two locations is
    refused rather than preferred.  The bytes are hashed in place -- a layer blob
    is never buffered whole -- and must both match the declared size and hash to
    the digest they are filed under.  ``document`` returns the bytes for the
    caller to parse, which is only ever asked for by the small blobs that *are*
    descriptors.
    """
    found = [path for path in paths if path in regular]
    if not found:
        _refuse("BLOB_MISSING")
    if len(found) > 1:
        _refuse("BLOB_AMBIGUOUS")
    member = regular[found[0]]
    if member.size is None or member.size < 0 or member.size > MAX_PACKAGE_BYTES:
        _refuse("ARCHIVE_INVALID")
    if size is not None and member.size != size:
        _refuse("BLOB_MISMATCH")
    if document and member.size > MAX_DOCUMENT_BYTES:
        _refuse("ARCHIVE_INVALID")
    stream = tar.extractfile(member)
    if stream is None:
        _refuse("ARCHIVE_INVALID")
    hasher = hashlib.sha256()
    total = 0
    buffer = bytearray() if document else None
    while True:
        part = stream.read(1024 * 1024)
        if not part:
            break
        total += len(part)
        if total > MAX_PACKAGE_BYTES:
            _refuse("ARCHIVE_INVALID")
        hasher.update(part)
        if buffer is not None:
            buffer += part
    if total != member.size:
        _refuse("ARCHIVE_INVALID")
    if hasher.hexdigest() != digest:
        _refuse("BLOB_MISMATCH")
    return bytes(buffer) if buffer is not None else None


def _descriptor(value):
    """A descriptor reduced to the three fields that can actually be checked."""
    if not isinstance(value, dict):
        _refuse("DESCRIPTOR_INVALID")
    media_type, digest, size = value.get("mediaType"), value.get("digest"), value.get("size")
    if (not isinstance(media_type, str) or not isinstance(digest, str)
            or IMAGE_ID.match(digest) is None):
        _refuse("DESCRIPTOR_INVALID")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
        _refuse("DESCRIPTOR_INVALID")
    return media_type, digest[7:], size


def _is_attestation(annotations):
    """Whether the descriptor that named a manifest said it is an attestation."""
    return (isinstance(annotations, dict)
            and annotations.get(REFERENCE_TYPE_ANNOTATION) == ATTESTATION_REFERENCE_TYPE)


def _image_config(tar, regular, manifest, configs, named_by=None):
    """Bind one image manifest's own content into the graph and record its config.

    A manifest this contract follows is claiming to be the image, so its config and
    every layer it names are the image's own content: they must be in the archive
    and must hash to the descriptor that named them.  An attestation manifest is
    hashed like everything else, but its config is not an image, so it never becomes
    candidate authority -- and Docker marks attestations either in the manifest body
    or in the descriptor that names it, so both are checked.
    """
    if manifest.get("schemaVersion") != 2:
        _refuse("OCI_INVALID")
    if (manifest.get("mediaType") is not None
            and manifest["mediaType"] not in MANIFEST_MEDIA_TYPES):
        _refuse("DESCRIPTOR_INVALID")
    if manifest.get("artifactType") or _is_attestation(named_by):
        return
    config_type, config_digest, config_size = _descriptor(manifest.get("config"))
    if config_type not in CONFIG_MEDIA_TYPES:
        _refuse("MEDIA_TYPE_UNSUPPORTED")
    _blob(tar, regular, config_digest, config_size,
          [BLOB_DIR + "/" + config_digest], document=True)
    layers = manifest.get("layers")
    if not isinstance(layers, list):
        _refuse("OCI_INVALID")
    for layer in layers:
        layer_type, layer_digest, layer_size = _descriptor(layer)
        _blob(tar, regular, layer_digest, layer_size, [BLOB_DIR + "/" + layer_digest])
    configs.add(config_digest)


def _oci_identity(tar, regular):
    """``(root descriptor digest, config digests)`` an OCI image layout proves.

    ``index.json`` is followed as a graph rather than as ``manifests[0]``: it names
    one descriptor and that descriptor may be another index before the graph reaches
    an image manifest, which is exactly the shape Docker writes.  The descriptor
    ``index.json`` names is the identity Docker reports *as the image id* on a host
    using the containerd image store, so it is returned separately -- and its bytes
    are required to be in the archive, because an identity nobody can hash is not an
    identity.

    Below that descriptor an index is a *catalogue*, not a statement of content.
    Docker writes the complete multi-platform list while shipping only the platform
    it was asked for -- measured: sixteen descriptors, two blobs present -- so an
    entry whose blob is absent is skipped rather than refused.  Skipping promotes
    nothing: a descriptor only becomes authority once its bytes have been hashed in
    place, and a graph that ends up proving no image at all is refused.
    """
    if LAYOUT_NAME not in regular:
        _refuse("OCI_INVALID")
    layout = _document(_read_member(tar, regular[LAYOUT_NAME]), "OCI_INVALID")
    if layout.get("imageLayoutVersion") != OCI_LAYOUT_VERSION:
        _refuse("OCI_INVALID")
    root = _document(_read_member(tar, regular[INDEX_NAME]), "OCI_INVALID")
    if root.get("mediaType") not in INDEX_MEDIA_TYPES:
        _refuse("MEDIA_TYPE_UNSUPPORTED")
    entries = root.get("manifests")
    if root.get("schemaVersion") != 2 or not isinstance(entries, list) or not entries:
        _refuse("OCI_INVALID")
    # An archive names one image.  Several roots would make "the identity Docker
    # reports" a choice, and this contract never chooses.
    if len(entries) != 1:
        _refuse("OCI_INVALID")
    target_type, target, target_size = _descriptor(entries[0])
    if target_type not in INDEX_MEDIA_TYPES and target_type not in MANIFEST_MEDIA_TYPES:
        _refuse("MEDIA_TYPE_UNSUPPORTED")
    target_document = _document(
        _blob(tar, regular, target, target_size, [BLOB_DIR + "/" + target], document=True),
        "OCI_INVALID")
    configs, seen, count = set(), {target: target_type}, 0
    # ``index.json`` is level 0, so the descriptor it names is level 1 and the bound
    # is the depth of the index graph below the archive's own index.
    pending = [(target_type, target_document, entries[0].get("annotations"), 1)]
    while pending:
        media_type, document, named_by, depth = pending.pop()
        if depth > MAX_DESCRIPTOR_DEPTH:
            _refuse("DESCRIPTOR_LIMIT")
        if media_type in MANIFEST_MEDIA_TYPES:
            _image_config(tar, regular, document, configs, named_by)
            continue
        if document.get("schemaVersion") != 2:
            _refuse("OCI_INVALID")
        if (document.get("mediaType") is not None
                and document["mediaType"] not in INDEX_MEDIA_TYPES):
            _refuse("DESCRIPTOR_INVALID")
        manifests = document.get("manifests")
        if not isinstance(manifests, list) or not manifests:
            _refuse("OCI_INVALID")
        for entry in manifests:
            child_type, child, child_size = _descriptor(entry)
            count += 1
            if count > MAX_DESCRIPTOR_COUNT:
                _refuse("DESCRIPTOR_LIMIT")
            if child_type not in INDEX_MEDIA_TYPES and child_type not in MANIFEST_MEDIA_TYPES:
                _refuse("MEDIA_TYPE_UNSUPPORTED")
            if child in seen:
                # One blob may be reached by several paths, but it may not be
                # described as two different things.
                if seen[child] != child_type:
                    _refuse("DESCRIPTOR_INVALID")
                continue
            seen[child] = child_type
            if BLOB_DIR + "/" + child not in regular:
                # A catalogue entry this archive did not export.
                continue
            child_document = _document(
                _blob(tar, regular, child, child_size, [BLOB_DIR + "/" + child],
                      document=True), "OCI_INVALID")
            if child_type in INDEX_MEDIA_TYPES:
                pending.append((child_type, child_document, entry.get("annotations"),
                                depth + 1))
                continue
            _image_config(tar, regular, child_document, configs, entry.get("annotations"))
    if not configs:
        # An index that ends up naming no image at all is not an image archive.
        _refuse("OCI_INVALID")
    return target, configs


def _legacy_config_digest(tar, regular):
    """The image config digest a legacy ``docker save`` index names.

    ``manifest.json`` is a list with exactly one entry and its ``Config`` is the
    identity of the config blob.  Docker's hybrid archive -- an OCI layout with
    that same list beside it -- files the blob under the OCI path, so the
    reference may be either the flat name or ``blobs/sha256/<digest>``.  Only
    those two locations are ever read and the digest is taken from the reference's
    own last component, so nothing here can name a path of its choosing.
    """
    try:
        index = json.loads(_read_member(tar, regular[CONFIG_NAME]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        _refuse("ARCHIVE_INVALID")
    if not isinstance(index, list) or len(index) != 1 or not isinstance(index[0], dict):
        _refuse("ARCHIVE_INVALID")
    reference = index[0].get("Config")
    if (not isinstance(reference, str) or not reference or "\x00" in reference
            or reference.startswith("/")):
        _refuse("MEMBER_UNSAFE")
    parts = reference.split("/")
    if any(part in ("", ".", "..") for part in parts):
        _refuse("MEMBER_UNSAFE")
    if len(parts) > 1 and "/".join(parts[:-1]) != BLOB_DIR:
        _refuse("MEMBER_UNSAFE")
    name = parts[-1][:-5] if parts[-1].endswith(".json") else parts[-1]
    if SHA256.fullmatch(name) is None:
        _refuse("ARCHIVE_INVALID")
    _blob(tar, regular, name, None, [name, BLOB_DIR + "/" + name], document=True)
    return name


def archive_identity(archive):
    """Every identity this archive proves about the image it carries.

    ``root``    the digest ``index.json`` itself names -- the identity Docker
                reports as the image id on a host using the containerd image store
                (measured on HK-STAGING, server 29.7.2) -- or ``None`` when the
                archive carries no OCI layout;
    ``configs`` every image config digest the archive proves;
    ``legacy``  the config digest ``manifest.json`` names, or ``None``.

    Three roles, three fields.  An index digest, a config digest and a layout
    marker are different things and are never compared with one another: a rule
    that requires the first to equal the second is a rule no host using the
    containerd image store can ever satisfy.
    """
    try:
        with tarfile.open(archive, "r:") as tar:
            regular = _member_index(tar)
            oci, legacy = None, None
            root = None
            if INDEX_NAME in regular:
                root, oci = _oci_identity(tar, regular)
            if CONFIG_NAME in regular:
                legacy = _legacy_config_digest(tar, regular)
                # Two layouts in one archive are acceptable only while they name
                # the same image; an archive that contradicts itself is refused
                # rather than resolved by preferring one of them.
                if oci is not None and legacy not in oci:
                    _refuse("LAYOUT_AMBIGUOUS")
            if oci is None and legacy is None:
                _refuse("ARCHIVE_INVALID")
            configs = set(oci or ())
            if legacy is not None:
                configs.add(legacy)
            return {"root": root, "configs": configs, "legacy": legacy}
    except Reject:
        raise
    except (OSError, tarfile.TarError, ValueError, KeyError, UnicodeDecodeError) as exc:
        raise Reject(_REFUSAL_PREFIX + "ARCHIVE_INVALID") from exc


def image_identity(archive, image_id):
    """Prove ``image_id`` is the image this archive carries, and say in which role.

    Docker reports an image's id as one of two different things depending on how the
    host stores images: the digest of the descriptor ``index.json`` names (the
    containerd image store -- measured on HK-STAGING, server 29.7.2, where the
    reported id was an *index* digest and the image's config digest was a different
    value), or the image config's own digest (Docker's legacy image store, and
    GitHub's runners).  Both are identities this archive can prove, so both are
    accepted -- each only after the bytes behind it have been hashed in place -- and
    the role that matched is reported rather than assumed.  The two identities are
    never compared with each other.

    An archive that names no image, carries a descriptor type this contract does not
    know, contradicts itself across two layouts, or proves no identity equal to the
    candidate, is refused.
    """
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise Reject("SEALED_ARTIFACT_IMAGE_IDENTITY")
    expected = image_id.split(":", 1)[1]
    identity = archive_identity(archive)
    if identity["root"] == expected:
        role = "root_descriptor"
    elif expected in identity["configs"]:
        role = "config"
    else:
        _refuse("IMAGE_IDENTITY_MISMATCH")
    return {"image_id": image_id,
            "image_identity_role": role,
            "root_descriptor_digest": identity["root"],
            "config_digests": sorted(identity["configs"])}


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
        # The archive is this image only if it proves an identity equal to the one
        # the build reported.  Which role that identity played is recorded rather
        # than assumed; whatever the archive's own index claims about itself is not
        # authority, the bytes are.
        identity = image_identity(temporary, image_id)
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
        # Which of the archive's own identities the reported image id turned out to
        # be, and both of them.  Docker names an image by the descriptor its
        # index.json points at on a containerd host, and by the config digest on a
        # legacy host; recording the role is what stops a later reader from having
        # to guess which one it is holding.
        "image_identity_role": identity["image_identity_role"],
        "root_descriptor_digest": identity["root_descriptor_digest"],
        "config_digests": identity["config_digests"],
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
    image_identity(path, image_id)
    loaded = runner(["/usr/bin/docker", "load", "--input", path], timeout=600)
    if getattr(loaded, "returncode", 0):
        raise Reject("SEALED_ARTIFACT_LOAD_FAILED")
    reported = runner(["/usr/bin/docker", "image", "inspect", image_id, "--format", "{{.Id}}"])
    if getattr(reported, "returncode", 0) or (reported.stdout or "").strip() != image_id:
        raise Reject("SEALED_ARTIFACT_LOADED_IMAGE_MISMATCH")
    return {"schema": SCHEMA, "image_id": image_id, "package_sha256": package_sha256,
            "load": "PASS", "image_present": "PASS"}
