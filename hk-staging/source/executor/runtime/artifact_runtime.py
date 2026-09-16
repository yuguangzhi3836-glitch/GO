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

Why there is no repo digest here, and which image identity there is
-------------------------------------------------------------------
A registry manifest digest exists only after a push, and it is not equal to an
image's config ID in general.  The sealed package's own SHA256 is the delivery
identity instead.

The image identity is subtler, and an earlier revision of this contract got it
wrong: it required the archive's config blob to hash to the id that
``docker image inspect`` reports.  On a host using the **containerd image store**
-- Hong Kong runs server 29.7.2 on ``io.containerd.snapshotter.v1`` -- the id
Docker reports is the digest of the descriptor ``index.json`` names, which is an
*index* digest, and the config digest is a different value (measured on this host:
``1c9598d6…`` reported, config ``57beafa2…``).  This module therefore accepts
either identity, proves the bytes behind whichever matched, and reports which role
it was; it never compares the two with each other.

Two archive formats, one candidate identity
-------------------------------------------
The package this module reads was written by the agent's ``docker save``, so it
carries whatever format that host produces.  A host using Docker's own image store
writes a *legacy docker-archive*; the Hong Kong host uses the containerd image
store (server 29.7.2, ``driver-type io.containerd.snapshotter.v1``) and writes an
*OCI image layout* -- ``oci-layout``, ``index.json``, ``blobs/sha256/<digest>`` --
where the index may point at a nested index before the image manifest.  An earlier
revision of this contract understood only the legacy shape, which is why the first
real TEST_PR sealed nothing.

Both are read here, by the same grammar the writer applies, and neither is guessed
at: the OCI side is followed as a bounded descriptor graph in which the descriptor
``index.json`` names must be present as a regular member and hash to the digest
that named it, an index entry whose blob the archive did not export is skipped,
and everything a manifest we do follow names must be present and hash to what
named it.  If both layouts are present they must name the same image.  Whatever
the layout, the decision is unchanged: the archive must prove an identity equal to
the candidate image id, in one of the two named roles, with the bytes behind it
present and hashed.

Everything the caller supplies is validated, and nothing the caller supplies is a
path: the object path is derived from the content address alone.
"""
import hashlib
import json
import posixpath
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
_REFUSAL_PREFIX = "E_ARTIFACT_"


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


def _image_config(tar, regular, manifest, configs):
    """Bind one image manifest's own content into the graph and record its config.

    A manifest this contract follows is claiming to be the image, so its config and
    every layer it names are the image's own content: they must be in the archive
    and must hash to the descriptor that named them.  An attestation manifest is
    hashed like everything else, but its config is not an image, so it never becomes
    candidate authority.
    """
    if manifest.get("schemaVersion") != 2:
        _refuse("OCI_INVALID")
    if (manifest.get("mediaType") is not None
            and manifest["mediaType"] not in MANIFEST_MEDIA_TYPES):
        _refuse("DESCRIPTOR_INVALID")
    if manifest.get("artifactType"):
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
    pending = [(target_type, target_document, 1)]
    while pending:
        media_type, document, depth = pending.pop()
        if depth > MAX_DESCRIPTOR_DEPTH:
            _refuse("DESCRIPTOR_LIMIT")
        if media_type in MANIFEST_MEDIA_TYPES:
            _image_config(tar, regular, document, configs)
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
                pending.append((child_type, child_document, depth + 1))
                continue
            _image_config(tar, regular, child_document, configs)
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
        raise Reject("E_ARTIFACT_IMAGE_IDENTITY")
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


def materialise(runner, package_sha256, image_id, root=STORE_ROOT):
    """Make the sealed candidate image present in Docker, and prove it is that image.

    The image is only allowed to exist once the package's own bytes hash to the
    address asked for, the archive proves an identity equal to the candidate image
    ID (in a named role, with the bytes behind it present and hashed), and Docker
    reports the loaded image as that same ID.
    """
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise Reject("E_ARTIFACT_IMAGE_IDENTITY")
    path = resolve(package_sha256, root)
    image_identity(path, image_id)
    loaded = runner(["/usr/bin/docker", "load", "--input", path], 600)
    if getattr(loaded, "returncode", 0):
        raise Reject("E_ARTIFACT_LOAD_FAILED")
    reported = runner(["/usr/bin/docker", "image", "inspect", image_id, "--format", "{{.Id}}"], 30)
    if getattr(reported, "returncode", 0) or (reported.stdout or "").strip() != image_id:
        raise Reject("E_ARTIFACT_LOADED_IMAGE_MISMATCH")
    return {"artifact_package": "PASS", "artifact_materialised": "PASS", "candidate_image": "PASS"}
