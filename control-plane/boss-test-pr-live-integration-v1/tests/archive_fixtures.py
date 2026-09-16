"""Archive fixtures: the two shapes ``docker save`` really produces.

One source of truth on purpose.  The defect this whole change exists to close was
a *fixture* problem: every fixture wrote a legacy docker-archive, so the parser
agreed with the suite and refused the host, which writes an OCI image layout.
A second copy of these builders in another suite would rebuild exactly that blind
spot, so they live here and every suite imports them.

Nothing here is hand-written data: digests and sizes are computed from the bytes
actually written, so a parser cannot agree with a fixture by accident.
"""
import hashlib
import io
import json
import tarfile

# The OCI media types Docker writes, and the layout marker's content.
OCI_LAYOUT = json.dumps({"imageLayoutVersion": "1.0.0"}).encode()
OCI_INDEX_TYPE = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG_TYPE = "application/vnd.oci.image.config.v1+json"
OCI_LAYER_TYPE = "application/vnd.oci.image.layer.v1.tar"


def write_tar(path, entries):
    """Write ``{name: bytes}`` as an archive, in order."""
    with tarfile.open(path, "w") as tar:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


def read_tar(path):
    """Every regular member of an archive, as ``{name: bytes}``."""
    with tarfile.open(path, "r:") as tar:
        return {member.name: tar.extractfile(member).read()
                for member in tar.getmembers() if member.isfile()}


def synthetic_save(path, config_bytes, repo_tags=("go-hk-test-pr:" + "a" * 40,)):
    """A legacy docker-archive: ``manifest.json`` naming a flat config member."""
    digest = hashlib.sha256(config_bytes).hexdigest()
    index = json.dumps([{"Config": digest, "RepoTags": list(repo_tags), "Layers": []}]).encode()
    write_tar(path, {digest: config_bytes, "manifest.json": index})
    return "sha256:" + digest


def oci_save(path, config_bytes, *, nesting=1, attestation=False, layers=(b"layer-bytes",)):
    """The OCI image layout a containerd-backed Docker actually writes.

    HK-STAGING runs server 29.7.2 on ``io.containerd.snapshotter.v1``: ``oci-layout``,
    an ``index.json`` pointing at a *nested* index, that index pointing at the image
    manifest, and every blob filed under ``blobs/sha256/<digest>``.  ``nesting``
    adds index levels, ``attestation`` adds the artifact manifest Docker writes
    beside the image.
    """
    blobs = {}

    def store(payload):
        digest = hashlib.sha256(payload).hexdigest()
        blobs[digest] = payload
        return digest

    def descriptor(media_type, payload_digest, payload):
        return {"mediaType": media_type, "digest": "sha256:" + payload_digest,
                "size": len(payload)}

    config_digest = store(config_bytes)
    manifest = {"schemaVersion": 2, "mediaType": OCI_MANIFEST_TYPE,
                "config": descriptor(OCI_CONFIG_TYPE, config_digest, config_bytes),
                "layers": [descriptor(OCI_LAYER_TYPE, store(payload), payload)
                           for payload in layers]}
    manifest_bytes = json.dumps(manifest).encode()
    descriptors = [descriptor(OCI_MANIFEST_TYPE, store(manifest_bytes), manifest_bytes)]
    if attestation:
        attestation_config = b'{"architecture":"unknown","os":"unknown"}'
        attestation_manifest = {"schemaVersion": 2, "mediaType": OCI_MANIFEST_TYPE,
                                "artifactType": "application/vnd.in-toto+json",
                                "config": descriptor(OCI_CONFIG_TYPE,
                                                     store(attestation_config),
                                                     attestation_config),
                                "layers": []}
        payload = json.dumps(attestation_manifest).encode()
        descriptors.append(descriptor(OCI_MANIFEST_TYPE, store(payload), payload))
    node = {"schemaVersion": 2, "mediaType": OCI_INDEX_TYPE, "manifests": descriptors}
    for _ in range(nesting):
        payload = json.dumps(node).encode()
        node = {"schemaVersion": 2, "mediaType": OCI_INDEX_TYPE,
                "manifests": [descriptor(OCI_INDEX_TYPE, store(payload), payload)]}
    entries = {"oci-layout": OCI_LAYOUT, "index.json": json.dumps(node).encode()}
    for digest, payload in blobs.items():
        entries["blobs/sha256/" + digest] = payload
    write_tar(path, entries)
    return "sha256:" + config_digest


def hybrid_save(path, config_bytes, *, reference=None):
    """The hybrid Docker writes when both markers are present.

    The first real TEST_PR failed on this shape: ``manifest.json`` was there, was a
    one-element list, and its ``Config`` was *not* a bare digest -- the line the
    traceback pointed at.  The reference may therefore be the flat name or the OCI
    blob path, and the blob is filed under the OCI path either way.
    """
    digest = hashlib.sha256(config_bytes).hexdigest()
    reference = reference or ("blobs/sha256/" + digest)
    index = json.dumps([{"Config": reference, "RepoTags": [], "Layers": []}]).encode()
    entries = {"oci-layout": OCI_LAYOUT, "manifest.json": index,
               "blobs/sha256/" + digest: config_bytes}
    manifest = {"schemaVersion": 2, "mediaType": OCI_MANIFEST_TYPE,
                "config": {"mediaType": OCI_CONFIG_TYPE, "digest": "sha256:" + digest,
                           "size": len(config_bytes)},
                "layers": []}
    manifest_bytes = json.dumps(manifest).encode()
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    entries["blobs/sha256/" + manifest_digest] = manifest_bytes
    entries["index.json"] = json.dumps(
        {"schemaVersion": 2, "mediaType": OCI_INDEX_TYPE,
         "manifests": [{"mediaType": OCI_MANIFEST_TYPE, "digest": "sha256:" + manifest_digest,
                        "size": len(manifest_bytes)}]}).encode()
    write_tar(path, entries)
    return "sha256:" + digest


def mutated(writer, transform):
    """A save writer whose archive is altered after it is written."""

    def save_writer(path, config_bytes):
        writer(path, config_bytes)
        entries = read_tar(path)
        transform(entries)
        write_tar(path, entries)

    return save_writer


def append_member(path, name, payload=b"", *, kind=tarfile.REGTYPE, linkname=""):
    """Add one member of any tar type to an existing archive."""
    with tarfile.open(path, "a") as tar:
        info = tarfile.TarInfo(name)
        info.type = kind
        if kind == tarfile.REGTYPE:
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        else:
            info.linkname = linkname
            tar.addfile(info)


def appended(archive_writer, name, payload=b"", **kwargs):
    """A save writer whose archive gains one extra member, of any type."""

    def save_writer(path, config_bytes):
        archive_writer(path, config_bytes)
        append_member(path, name, payload, **kwargs)

    return save_writer


def refile(entries, mutate_manifest):
    """Rewrite the image manifest descriptor graph, and re-file every node above it.

    Every blob in an OCI layout is named by its own digest, so editing a manifest
    means storing it under a new name and re-pointing whatever named it, all the way
    up to ``index.json``.  Doing that is what lets a test make one *descriptor*
    wrong while the archive as a whole stays well formed -- the case the contract
    has to refuse, and the case a hand-broken archive would never reach.
    """

    def store(payload):
        digest = hashlib.sha256(payload).hexdigest()
        entries["blobs/sha256/" + digest] = payload
        return digest, len(payload)

    def walk(node):
        for descriptor in node["manifests"]:
            digest = descriptor["digest"].split(":", 1)[1]
            child = json.loads(entries.pop("blobs/sha256/" + digest))
            if descriptor["mediaType"] == OCI_INDEX_TYPE:
                walk(child)
            else:
                mutate_manifest(child)
            new, size = store(json.dumps(child).encode())
            descriptor["digest"] = "sha256:" + new
            descriptor["size"] = size

    root = json.loads(entries["index.json"])
    walk(root)
    entries["index.json"] = json.dumps(root).encode()
