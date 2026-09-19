"""The Hong Kong side's root-owned candidate facts, and the graph this host is on.

CCV1-85 (WP-4A). The Command Center now names a candidate by its content -- the digest
of the converged candidate fact -- in the signed DEPLOY Task. That is only a binding if
the host that performs the deployment can produce the fact itself and check the digest,
which is what this module does:

    Task.parameters.candidate_contract_sha256
        -> /etc/go-hk-deployctl/candidates-v1/<digest>.json   (root-owned, read-only)
        -> candidate_fact.validate_converged()
        -> candidate_fact.candidate_contract_sha256()          (recomputed, not trusted)
        -> must equal the Task's digest
        -> must name the same artifact as the Task's candidate image and package

Three properties are deliberate:

* **The digest is recomputed.** A host that only compared the Task's digest with a
  filename would be trusting the Command Center's arithmetic and its own directory
  listing at the same time. The fact is parsed, validated and digested here.

* **The fact is resolved by content, not by name.** The lookup key is the digest, so a
  document cannot be reached through a readable identifier that happens to be
  convenient. `candidate_id` is deliberately not a key: it is a name, not an identity.

* **The path is not a parameter.** The store's location is a constant here and the
  filename is the digest itself, which is validated before it is used. Nothing a Task
  carries can redirect the read.

The host layout belongs to the install flow: `/etc/go-hk-deployctl/**` is root-owned and
written by an installer, never by the executor and never by this module. This module
only reads, and it refuses rather than defaulting.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import stat

CANDIDATE_DIR = '/etc/go-hk-deployctl/candidates-v1'
ENVIRONMENT_GRAPH = '/etc/go-hk-deployctl/environment-graph-v1.json'

# A converged candidate fact is a small document. A ceiling keeps a hostile or corrupt
# store from turning a deployment into a memory event.
MAX_CANDIDATE_BYTES = 64 * 1024
MAX_GRAPH_BYTES = 4 * 1024

TRUSTED_UID = 0
WRITABLE_BY_OTHERS = 0o022

SHA256 = re.compile(r'^[0-9a-f]{64}$')
ENVIRONMENT = 'HK-STAGING-01'

# The two stable migration codes, restated here because this is the code that decides
# what a missing environment graph means. The lineage suite pins every copy equal.
E_DATABASE_MIGRATION_GRAPH_MISMATCH = 'E_DATABASE_MIGRATION_GRAPH_MISMATCH'

# The single implementation of the candidate digest, distributed beside this module.
# It is the same file the Command Center's candidate admission component owns -- not a
# second implementation of the same rule -- and the lineage suite pins the two byte for
# byte, so a divergence is a test failure rather than a silent drift.
CANDIDATE_FACT_SHA256 = 'b378a4724633a963526409ed98dfbfa90a1ab601aa123771edcf4c6567cde0fd'


class Reject(ValueError):
    """A refusal. The message is the observable code."""


def _sibling(name, expected_sha256, module_name):
    """Load one sibling runtime module after validating its bytes.

    The same discipline the launcher uses for its own siblings: a module is loaded only
    from the directory this file is in, only if it is a regular file, and only if its
    bytes are the ones this file was written against.
    """
    directory = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(directory, name + '.py')
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise ValueError('module path')
        with open(path, 'rb') as handle:
            if hashlib.sha256(handle.read()).hexdigest() != expected_sha256:
                raise ValueError('module integrity')
    except (OSError, ValueError) as exc:
        raise Reject('E_CANDIDATE_MODULE_INTEGRITY') from exc
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise Reject('E_CANDIDATE_MODULE_INTEGRITY')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CANDIDATE_FACT = None


def candidate_fact_module():
    """The shared candidate fact implementation, loaded once per process."""
    global _CANDIDATE_FACT
    if _CANDIDATE_FACT is None:
        _CANDIDATE_FACT = _sibling('candidate_fact', CANDIDATE_FACT_SHA256,
                                   '_go_hk_candidate_fact')
    return _CANDIDATE_FACT


# --------------------------------------------------------------------------- #
# root-only reads
# --------------------------------------------------------------------------- #
def directory_violation(info):
    """Why this directory is not acceptable as part of the store, or None.

    A root-owned file inside a directory anyone can replace is not a trusted read, so
    every component of the path is held to the same rule, not only the last one.
    """
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return 'E_CANDIDATE_STORE_UNTRUSTED'
    if info.st_uid != TRUSTED_UID or info.st_mode & WRITABLE_BY_OTHERS:
        return 'E_CANDIDATE_STORE_UNTRUSTED'
    return None


def file_violation(info):
    """Why this file is not acceptable as a candidate fact, or None."""
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return 'E_CANDIDATE_STORE_UNTRUSTED'
    if info.st_uid != TRUSTED_UID or info.st_mode & WRITABLE_BY_OTHERS:
        return 'E_CANDIDATE_STORE_UNTRUSTED'
    return None


def _check_ancestors(path):
    """Walk the whole path: a trusted file under an untrusted directory is not trusted."""
    current = pathlib.Path(path)
    for candidate in [current, *current.parents]:
        try:
            info = os.lstat(str(candidate))
        except OSError as exc:
            raise Reject('E_CANDIDATE_STORE_UNTRUSTED') from exc
        code = directory_violation(info)
        if code:
            raise Reject(code)


def _secure_read(path, limit, absent_code):
    """Read a root-owned regular file without following any link."""
    if not isinstance(path, str) or not os.path.isabs(path):
        raise Reject('E_CANDIDATE_STORE_UNTRUSTED')
    _check_ancestors(os.path.dirname(path))
    flags = os.O_RDONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise Reject(absent_code) from exc
    except OSError as exc:
        raise Reject('E_CANDIDATE_STORE_UNTRUSTED') from exc
    try:
        info = os.fstat(descriptor)
        code = file_violation(info)
        if code:
            raise Reject(code)
        if info.st_size > limit:
            raise Reject('E_CANDIDATE_STORE_UNTRUSTED')
        chunks, remaining = [], limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
    finally:
        os.close(descriptor)
    if len(raw) > limit:
        raise Reject('E_CANDIDATE_STORE_UNTRUSTED')
    return raw


def _parse(raw, code):
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Reject(code) from exc


# --------------------------------------------------------------------------- #
# the facts
# --------------------------------------------------------------------------- #
def load_candidate_fact(candidate_contract_sha256):
    """The converged candidate fact this digest addresses, verified against the digest.

    The document is read from a root-owned store, validated as a converged candidate
    fact, and digested here; the recomputed digest must equal the one the Task carried.
    The filename agrees by construction, because the digest is what the filename is
    built from -- but it is the recomputation, not the filename, that decides.

    A legacy `go.hk-candidate-contract.v*` document is refused by name: its digest is
    computed over a different byte form, so it can never be the fact a converged digest
    addresses. Refusing it here is what stops a legacy document from being promoted into
    a converged one merely by being placed at the right filename.
    """
    if not isinstance(candidate_contract_sha256, str) \
            or SHA256.fullmatch(candidate_contract_sha256) is None:
        # An absent or malformed digest names no candidate this host can look up.
        raise Reject('candidate_digest_absent')
    fact_module = candidate_fact_module()
    raw = _secure_read(os.path.join(CANDIDATE_DIR, candidate_contract_sha256 + '.json'),
                       MAX_CANDIDATE_BYTES, 'E_CANDIDATE_FACT_ABSENT')
    document = _parse(raw, 'E_CANDIDATE_FACT_UNREADABLE')
    try:
        kind = fact_module.classify_document(document)
    except fact_module.CandidateFactError as exc:
        raise Reject(str(exc)) from exc
    if kind != fact_module.CandidateDigestKind.CONVERGED:
        raise Reject('candidate_digest_legacy_not_converged:%s' % kind)
    try:
        fact_module.validate_converged(document)
        recomputed = fact_module.candidate_contract_sha256(document)
    except fact_module.CandidateFactError as exc:
        raise Reject(str(exc)) from exc
    if recomputed != candidate_contract_sha256:
        raise Reject('candidate_digest_mismatch')
    return document


def require_same_artifact(fact, candidate_image_id, candidate_package_sha256):
    """The fact and the Task must be about the same artifact, or nothing is deployed.

    The digest proves the Command Center and this host are talking about one candidate
    document. It does not, on its own, prove that the image this Task told us to run is
    the image that document describes -- so the artifact identity is compared too, and a
    disagreement stops the deployment before anything is replaced.
    """
    if fact.get('artifact_digest') != candidate_image_id:
        raise Reject('E_DEPLOY_CANDIDATE_IMAGE')
    package = fact.get('artifact_package')
    delivered = package.get('package_sha256') if isinstance(package, dict) else None
    if delivered != candidate_package_sha256:
        raise Reject('E_DEPLOY_CANDIDATE_PACKAGE')
    return fact


def environment_migration_head():
    """The migration graph this host is on, from the root-owned environment fact.

    V1 executes no database migration, so "the graph this host is on" is the only graph a
    deployable candidate may declare. A fact that is missing, unreadable, off
    environment or headless is refused in the migration graph code rather than treated
    as an empty agreement: an unestablished environment graph must not let a candidate
    through, which is the same rule the Command Center applies at derivation time.
    """
    raw = _secure_read(ENVIRONMENT_GRAPH, MAX_GRAPH_BYTES,
                       E_DATABASE_MIGRATION_GRAPH_MISMATCH)
    document = _parse(raw, E_DATABASE_MIGRATION_GRAPH_MISMATCH)
    if not isinstance(document, dict) or document.get('environment') != ENVIRONMENT:
        raise Reject(E_DATABASE_MIGRATION_GRAPH_MISMATCH)
    head = document.get('migration_head')
    if not isinstance(head, str) or not head:
        raise Reject(E_DATABASE_MIGRATION_GRAPH_MISMATCH)
    return head
