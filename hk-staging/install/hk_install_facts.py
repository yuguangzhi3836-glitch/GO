#!/usr/bin/env python3
"""The controlled installation of the Hong Kong executor's facts (CCV1-86 / WP-5).

This is the **producer** side of `go.hk-install-fact.v1`. It is run by an operator, as
root, on the HK host, from a staged tree -- never by the executor and never by anything
the Command Center publishes. It answers three questions and writes three kinds of file:

1. **Which candidate facts may this host deploy?** Each approved converged candidate is
   read, validated, digested, and filed under its own digest in
   `<state>/candidates-v1/<candidate_contract_sha256>.json`.
2. **Which migration graph is this host on?** The canonical runtime pointer's
   `database.alembic_head` is turned into a root-owned local fact,
   `<state>/environment-graph-v1.json`. The executor never reaches the network, so this
   conversion happens here, once, under review -- not per deployment.
3. **Which bytes are installed?** The launcher, the nine runtime modules, the candidate
   facts and the environment graph are hashed, assembled into an install fact, signed with
   the HK evidence identity, and written atomically.

Three disciplines are inherited rather than invented:

* **Durable writes.** `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW` on a temporary name in the
  destination directory, `fsync` the file, `fsync` the directory, then `rename`. A
  half-written fact never becomes the fact, and a reader that arrives mid-install sees the
  previous installation rather than a torn one.
* **Nothing is edited in place.** A new installation is a new `installation_id`; the
  previous fact is archived as `install-fact-v1.<old_id>.json`. Which bytes were installed
  last Tuesday stays answerable.
* **Legacy documents are never installed.** A `go.hk-candidate-contract.v*` document is
  refused by name. They remain readable history; they do not become candidate facts by
  being copied into the right directory.

Every rule this program applies is taken from the runtime's own modules --
`candidate_fact.py` for what a candidate is, `install_fact.py` for the module set, the
canonical byte form and the runtime digest. The installer carries no second copy of any of
them, because two implementations of one rule is the drift this work exists to remove.

What this program deliberately does **not** do: it does not prove that a candidate's
`source_commit` is on canonical `main`. That proof needs the repository and belongs to
WP-6 (`verify_canonical_provenance`). What it does here is require the operator to declare
the lineage it is installing (`--allow-candidate-commit`, defaulting to `--source-commit`)
and refuse anything outside it, so the association is explicit and recorded rather than
assumed.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import secrets
import stat
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

STATE_DIR = '/etc/go-hk-deployctl'
DEFAULT_RUNTIME = REPO_ROOT / 'hk-staging' / 'source' / 'executor' / 'runtime'
DEFAULT_LAUNCHER = REPO_ROOT / 'hk-staging' / 'source' / 'executor' / 'go-hk-deployctl'
DEFAULT_RUNTIME_POINTER = REPO_ROOT / 'docs' / 'canonical-baseline' / 'CURRENT_HK_RUNTIME.json'

ENVIRONMENT_GRAPH_SCHEMA = 'go.hk-environment-graph.v1'
ENVIRONMENT = 'HK-STAGING-01'
REPOSITORY = 'yuguangzhi3836-glitch/GO'

SOURCE_COMMIT = re.compile(r'^[0-9a-f]{40}$')
MIGRATION_HEAD = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
INSTALLER_IDENTITY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
LAUNCHER_VERSION = re.compile(r'^VERSION *= *"([^"]+)"', re.M)

CANDIDATE_FILE_MODE = 0o400
GRAPH_FILE_MODE = 0o400
FACT_FILE_MODE = 0o400
KEY_FILE_MODE = 0o444


class InstallError(ValueError):
    """A refusal. The message is the observable code."""


# --------------------------------------------------------------------------- #
# the runtime's own implementations, so there is never a second copy of a rule
# --------------------------------------------------------------------------- #
def _load(runtime_dir, name, module_name):
    path = pathlib.Path(runtime_dir) / (name + '.py')
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise InstallError('E_INSTALL_RUNTIME_UNAVAILABLE:' + name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runtime(runtime_dir):
    """`candidate_fact` (what a candidate is) and `install_fact` (the fact's own rules)."""
    return (_load(runtime_dir, 'candidate_fact', '_hk_install_candidate_fact'),
            _load(runtime_dir, 'install_fact', '_hk_install_install_fact'))


# --------------------------------------------------------------------------- #
# durable writes
# --------------------------------------------------------------------------- #
def fsync_directory(path, fsync=os.fsync):
    """Push the rename itself to disk, not just the bytes it points at."""
    if os.name != 'posix':
        return False
    descriptor = os.open(path, os.O_RDONLY)
    try:
        fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def atomic_write(path, payload, mode=CANDIDATE_FILE_MODE, write=None, fsync=os.fsync):
    """Write `payload` to `path` so that no reader ever sees a partial file.

    Temporary name in the destination directory (`rename` is only atomic within one
    filesystem), created with `O_EXCL` so it cannot adopt an existing file, and
    `O_NOFOLLOW` so it cannot be directed through a link. If anything fails the temporary
    is removed: a failed install leaves the previous state intact, not a `.tmp` that a
    later run might mistake for progress.
    """
    path = str(path)
    directory = os.path.dirname(path)
    temporary = '%s.tmp.%s' % (path, secrets.token_hex(8))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    if write is None:
        def write(handle, data):
            handle.write(data)
    try:
        write(os.fdopen(descriptor, 'wb', closefd=False), payload)
        os.fchmod(descriptor, mode)
        fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    os.close(descriptor)
    # `os.replace`, not `os.rename`: an installation replaces the previous fact, and on
    # POSIX both are the same atomic rename while on Windows only this one will replace an
    # existing destination rather than refusing it.
    os.replace(temporary, path)
    fsync_directory(directory, fsync)
    return path


def ensure_directory(path, mode=0o700):
    """Create a root-owned directory chain with no write bit for anyone else."""
    path = str(path)
    if not os.path.isdir(path):
        os.makedirs(path, mode=mode, exist_ok=True)
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise InstallError('E_INSTALL_STATE_UNTRUSTED')
    if hasattr(os, 'geteuid') and info.st_uid != 0:
        raise InstallError('E_INSTALL_STATE_UNTRUSTED')
    if info.st_mode & 0o022:
        raise InstallError('E_INSTALL_STATE_UNTRUSTED')
    return path


# --------------------------------------------------------------------------- #
# the controlled facts
# --------------------------------------------------------------------------- #
def build_environment_graph(pointer, environment=ENVIRONMENT):
    """Turn the canonical runtime pointer into the root-owned local fact.

    `database.alembic_head` is the only authority for the graph this host supports. The
    value is copied, not recomputed and not guessed; a pointer that does not state it
    stops the install, because an environment whose graph cannot be established must not
    be handed a fact that claims it can.
    """
    if not isinstance(pointer, dict):
        raise InstallError('E_INSTALL_POINTER_INVALID')
    database = pointer.get('database')
    head = database.get('alembic_head') if isinstance(database, dict) else None
    if not isinstance(head, str) or MIGRATION_HEAD.fullmatch(head) is None:
        raise InstallError('E_INSTALL_POINTER_MIGRATION_HEAD_MISSING')
    if environment != ENVIRONMENT:
        raise InstallError('E_INSTALL_ENVIRONMENT_UNSUPPORTED')
    candidate = pointer.get('release_candidate_v1')
    commit = pointer.get('candidate_commit') or pointer.get('source_commit')
    if commit is None and isinstance(candidate, dict):
        commit = candidate.get('source_commit')
    return {
        'schema': ENVIRONMENT_GRAPH_SCHEMA,
        'environment': environment,
        'migration_head': head,
        'source_identity': 'docs/canonical-baseline/CURRENT_HK_RUNTIME.json',
        'source_commit': commit if isinstance(commit, str) else '',
    }


def stage_candidate_facts(sources, fact_module, allowed_commits):
    """Validate the approved candidates and describe them for the install fact.

    Returns `(digests, bodies)`. Nothing is written until every candidate has passed, so
    one bad candidate cannot leave a half-installed store behind.
    """
    digests, bodies = [], {}
    for source in sources:
        source = pathlib.Path(source)
        try:
            document = json.loads(source.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise InstallError('E_INSTALL_CANDIDATE_UNREADABLE:' + source.name) from exc
        try:
            kind = fact_module.classify_document(document)
        except fact_module.CandidateFactError as exc:
            raise InstallError('E_INSTALL_CANDIDATE_INVALID:' + str(exc)) from exc
        if kind != fact_module.CandidateDigestKind.CONVERGED:
            # `LEGACY_READ ONLY` is not a slogan: a legacy contract is refused here, so it
            # cannot enter the store and be handed to a deployment as a candidate.
            raise InstallError('E_INSTALL_CANDIDATE_NOT_CONVERGED:%s' % kind)
        try:
            fact_module.validate_converged(document)
            digest = fact_module.candidate_contract_sha256(document)
        except fact_module.CandidateFactError as exc:
            raise InstallError('E_INSTALL_CANDIDATE_INVALID:' + str(exc)) from exc
        if source.stem != digest:
            # The filename is the content address. A file whose name is not its digest
            # would install under a name no Task could ask for -- or, worse, under the name
            # of a different candidate.
            raise InstallError('E_INSTALL_CANDIDATE_FILENAME_MISMATCH:' + source.name)
        if document['source_commit'] not in allowed_commits:
            raise InstallError('E_INSTALL_CANDIDATE_NOT_IN_LINEAGE:' + source.name)
        if digest in bodies:
            raise InstallError('E_INSTALL_CANDIDATE_DUPLICATE:' + source.name)
        bodies[digest] = json.dumps(document, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8') + b'\n'
        digests.append(digest)
    if not digests:
        raise InstallError('E_INSTALL_NO_CANDIDATE')
    return sorted(digests), bodies


def build_install_fact(*, install_module, installation_id, source_commit, source_tree,
                       installed_at, installer_identity, launcher_path, runtime_dir,
                       candidate_digests, candidate_bodies, environment_graph_path,
                       compose_overlays=(), state_dir=STATE_DIR):
    """Assemble the fact from what is actually on disk. No digest here is supplied by hand."""
    if SOURCE_COMMIT.fullmatch(source_commit or '') is None:
        raise InstallError('E_INSTALL_SOURCE_COMMIT')
    if SOURCE_COMMIT.fullmatch(source_tree or '') is None:
        raise InstallError('E_INSTALL_SOURCE_TREE')
    if INSTALLER_IDENTITY.fullmatch(installer_identity or '') is None:
        raise InstallError('E_INSTALL_INSTALLER_IDENTITY')

    launcher_bytes = pathlib.Path(launcher_path).read_bytes()
    version = LAUNCHER_VERSION.search(launcher_bytes.decode('utf-8', 'replace'))
    if version is None:
        raise InstallError('E_INSTALL_LAUNCHER_VERSION')

    modules = []
    for name in install_module.RUNTIME_MODULES:
        raw = (pathlib.Path(runtime_dir) / (name + '.py')).read_bytes()
        modules.append({'name': name,
                        'version': install_module.declared_version(raw),
                        'sha256': hashlib.sha256(raw).hexdigest()})

    facts = [{'candidate_contract_sha256': digest,
              'path': os.path.join(state_dir, 'candidates-v1', digest + '.json'),
              'sha256': hashlib.sha256(candidate_bodies[digest]).hexdigest()}
             for digest in candidate_digests]

    return {
        'schema': install_module.SCHEMA,
        'installation_id': installation_id,
        'source_repository': REPOSITORY,
        'source_commit': source_commit,
        'source_tree': source_tree,
        'installed_at': installed_at,
        'installer_identity': installer_identity,
        'launcher_version': version.group(1),
        'launcher_sha256': hashlib.sha256(launcher_bytes).hexdigest(),
        'runtime_digest': install_module.runtime_digest(modules),
        'runtime_modules': modules,
        'compose_overlays': [dict(row) for row in compose_overlays],
        'candidate_fact_set': facts,
        'environment_graph_identity': {
            'path': environment_graph_path,
            'sha256': hashlib.sha256(
                pathlib.Path(environment_graph_path).read_bytes()).hexdigest(),
        },
    }


def _load_signer(private_key_path):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:  # pragma: no cover - environment, not input
        raise InstallError('E_INSTALL_CRYPTO_UNAVAILABLE') from exc
    raw = pathlib.Path(private_key_path).read_bytes()
    try:
        if raw.lstrip().startswith(b'-----'):
            key = serialization.load_pem_private_key(raw, password=None)
        else:
            key = serialization.load_ssh_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError('key type')
    except ValueError as exc:
        raise InstallError('E_INSTALL_SIGNER_KEY_INVALID') from exc
    return key


def installed_public_key(signing_key):
    """The public half of the signing key, in the form the launcher reads."""
    from cryptography.hazmat.primitives import serialization
    return _load_signer(signing_key).public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)


def sign_fact(document, private_key_path, install_module):
    """Sign with the HK evidence identity, and record which key did it.

    `signature_identity` carries a fingerprint of the public key so that replacing the
    `.pub` file invalidates every fact signed under the old one: the verifier recomputes
    the fingerprint from the key it loads and compares the two.
    """
    key = _load_signer(private_key_path)
    signed = dict(document)
    signed['signature_identity'] = '%s:%s' % (install_module.SIGNER_IDENTITY,
                                             install_module.key_id(key.public_key()))
    signed['signature'] = base64.b64encode(
        key.sign(install_module.canonical(install_module.unsigned(signed)))).decode('ascii')
    return signed


# --------------------------------------------------------------------------- #
# the canonical provenance proof (CCV1-88 / WP-6)
# --------------------------------------------------------------------------- #
# This file records a `source_commit` and a `source_tree` and says, in its own header, that
# proving the commit is on canonical `main` "needs the repository and belongs to WP-6". The
# repository is not on this host, so the proof is made where the repository is -- by
# `control-plane/command-center-canonical-provenance-v1` -- and this installer consumes it.
#
# What this installer can and cannot establish, stated plainly rather than implied:
#
#   * it CAN establish that the proof is about the commit, the tree **and the module bytes**
#     this installation is about to record. Every module hash is recomputed from the files
#     themselves and compared with the proof's own list, so a proof carrying wrong bytes
#     cannot install anything.
#   * it CANNOT re-derive the ancestry claim; that needs the repository. So a proof is trusted
#     for exactly one thing -- "this commit is on `main`" -- and for nothing else. That
#     residual is the operator's, and the operator is the one root identity on this host.
#   * a proof that is absent, unreadable, refused, about a different commit or tree, or silent
#     about a module being installed, is a refusal (`E_INSTALL_CANONICAL_PROOF`) and nothing is
#     written.
#
# No new key and no new signature are involved. The fact keeps the one signer it had; the
# proof is an input to the install action, not a second attestation of it.
CANONICAL_PROOF_SCHEMA = 'go.canonical-source-invariant.v1'
CANONICAL_PROOF_PHASE = 'INSTALL_SOURCE'
CANONICAL_PROOF_CODES = ('E_COMMIT_NOT_CANONICAL', 'E_TREE_MISMATCH',
                         'E_ARTIFACT_MISMATCH', 'E_BLOB_DRIFT', 'E_INSTALL_DRIFT')
# The fields this consumer binds. The verdict contract is larger -- steps, drift, authority --
# and that is the producer's business; what an installer must be able to read is the claim and
# the module list it is a claim about.
CANONICAL_PROOF_FIELDS = ('schema', 'verdict', 'phase', 'canonical_ref', 'canonical_commit',
                          'authorized_deploy_commit', 'source_tree', 'modules', 'refusal',
                          'codes')


def check_canonical_proof(document, source_commit, source_tree, module_hashes):
    """Refuse the installation unless the proof is a PASS about exactly these bytes.

    Called before anything is written. A refusal here leaves the state directory exactly as it
    was, so a failed install is not a half-install that the launcher would then refuse.
    """
    if not isinstance(document, dict) or not set(CANONICAL_PROOF_FIELDS) <= set(document):
        raise InstallError('E_INSTALL_CANONICAL_PROOF')
    if document['schema'] != CANONICAL_PROOF_SCHEMA \
            or document['verdict'] != 'PASS' \
            or document['phase'] != CANONICAL_PROOF_PHASE \
            or document['refusal'] is not None:
        raise InstallError('E_INSTALL_CANONICAL_PROOF')
    if tuple(document['codes']) != CANONICAL_PROOF_CODES:
        raise InstallError('E_INSTALL_CANONICAL_PROOF')
    if SOURCE_COMMIT.fullmatch(document['canonical_commit'] or '') is None:
        raise InstallError('E_INSTALL_CANONICAL_PROOF')
    if not isinstance(document['canonical_ref'], str) or not document['canonical_ref']:
        raise InstallError('E_INSTALL_CANONICAL_PROOF')
    if document['authorized_deploy_commit'] != source_commit:
        raise InstallError('E_INSTALL_CANONICAL_PROOF')
    if document['source_tree'] != source_tree:
        raise InstallError('E_INSTALL_CANONICAL_PROOF')
    if not isinstance(document['modules'], list):
        raise InstallError('E_INSTALL_CANONICAL_PROOF')
    proven = {}
    for entry in document['modules']:
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) \
                or not isinstance(entry.get('sha256'), str):
            raise InstallError('E_INSTALL_CANONICAL_PROOF')
        proven[entry['name']] = entry['sha256']
    for name, digest in module_hashes.items():
        if proven.get(name) != digest:
            # A module this installation will record that the proof never checked, or checked
            # to a different value. Either way the proof is about another set of bytes.
            raise InstallError('E_INSTALL_CANONICAL_PROOF')
    return document


# --------------------------------------------------------------------------- #
# the installation
# --------------------------------------------------------------------------- #
def installation_id(now=None, token=None):
    """Sortable, unique per installation, never reused."""
    stamp = time.strftime('%Y%m%dT%H%M%SZ',
                          time.gmtime(now if now is not None else time.time()))
    return '%s-%s' % (stamp, token or secrets.token_hex(4))


def previous_installation_id(fact_path):
    """The id of the fact currently installed, or None."""
    try:
        document = json.loads(pathlib.Path(fact_path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    value = document.get('installation_id')
    return value if isinstance(value, str) else None


def install(*, state_dir, runtime_dir, launcher_path, candidate_sources, runtime_pointer,
            source_commit, source_tree, installer_identity, signing_key,
            canonical_proof=None, allowed_commits=None, environment=ENVIRONMENT,
            compose_overlays=(), now=None, token=None, atomic=atomic_write):
    """Write the store, the graph and the fact. Returns a summary of what was written.

    Order matters, in two ways.

    The controlled files the fact describes are written **before** the fact that describes
    them. A reader that arrives in between sees the previous fact, which describes the
    previous files -- still a consistent installation. The reverse order would publish a fact
    whose modules are not yet on disk.

    And the canonical provenance proof is checked **before the first write**, against the
    module hashes of exactly the fact that is about to be written. An install that cannot show
    its bytes are canonical leaves nothing behind to clean up.
    """
    fact_module, install_module = load_runtime(runtime_dir)
    candidate_dir = os.path.join(state_dir, 'candidates-v1')
    fact_path = os.path.join(state_dir, 'install-fact-v1.json')
    graph_path = os.path.join(state_dir, 'environment-graph-v1.json')
    key_path = os.path.join(state_dir, 'keys', 'install-fact-signing.pub')

    lineage = set(allowed_commits) if allowed_commits else {source_commit}
    graph = build_environment_graph(runtime_pointer, environment)
    graph_bytes = json.dumps(graph, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode('utf-8') + b'\n'

    digests, bodies = stage_candidate_facts(candidate_sources, fact_module, lineage)

    # The gate, before the first write of any kind -- including the directories the writes
    # need. The module hashes are computed the way `build_install_fact` computes them, from the
    # files in this runtime directory, so the proof is checked against exactly the hashes the
    # fact is about to record.
    check_canonical_proof(canonical_proof, source_commit, source_tree,
                          {name: hashlib.sha256(
                              (pathlib.Path(runtime_dir) / (name + '.py')).read_bytes()
                           ).hexdigest()
                           for name in install_module.RUNTIME_MODULES})

    ensure_directory(state_dir, 0o700)
    ensure_directory(candidate_dir, 0o755)
    ensure_directory(os.path.dirname(key_path), 0o755)

    for digest in digests:
        atomic(os.path.join(candidate_dir, digest + '.json'), bodies[digest],
               mode=CANDIDATE_FILE_MODE)
    atomic(graph_path, graph_bytes, mode=GRAPH_FILE_MODE)
    atomic(key_path, installed_public_key(signing_key), mode=KEY_FILE_MODE)

    moment = now if now is not None else time.time()
    document = build_install_fact(
        install_module=install_module, installation_id=installation_id(moment, token),
        source_commit=source_commit, source_tree=source_tree,
        installed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(moment)),
        installer_identity=installer_identity, launcher_path=launcher_path,
        runtime_dir=runtime_dir, candidate_digests=digests, candidate_bodies=bodies,
        environment_graph_path=graph_path, compose_overlays=compose_overlays,
        state_dir=state_dir)

    signed = sign_fact(document, signing_key, install_module)

    previous = previous_installation_id(fact_path)
    archived = None
    if previous and previous != signed['installation_id']:
        archived = os.path.join(state_dir, 'install-fact-v1.%s.json' % previous)
        if not os.path.exists(archived):
            atomic(archived, pathlib.Path(fact_path).read_bytes(), mode=FACT_FILE_MODE)
    atomic(fact_path,
           json.dumps(signed, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8') + b'\n',
           mode=FACT_FILE_MODE)

    # Read it back the way the launcher will. An installation that does not verify is not
    # an installation, and learning that here is cheaper than learning it at 03:00.
    verified = install_module.load_installation(launcher_path, runtime_dir, fact_path,
                                                key_path, candidate_dir, graph_path)
    return {
        'installation_id': verified['installation_id'],
        'fact_path': fact_path,
        'runtime_digest': verified['runtime_digest'],
        'module_count': len(verified['runtime_modules']),
        'candidates': sorted(row['candidate_contract_sha256']
                             for row in verified['candidate_fact_set']),
        'previous_installation_id': previous,
        'archived_fact': archived,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--state-dir', default=STATE_DIR)
    parser.add_argument('--runtime-dir', default=str(DEFAULT_RUNTIME))
    parser.add_argument('--launcher', default=str(DEFAULT_LAUNCHER))
    parser.add_argument('--candidate', action='append', default=[],
                        help='an approved converged candidate fact JSON (repeatable)')
    parser.add_argument('--candidate-dir', default=None,
                        help='or a directory of them')
    parser.add_argument('--runtime-pointer', default=str(DEFAULT_RUNTIME_POINTER))
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--source-tree', required=True)
    parser.add_argument('--canonical-proof', required=True,
                        help='the CANONICAL_SOURCE_INVARIANT verdict that proves the source '
                             'identity, from command-center-canonical-provenance-v1')
    parser.add_argument('--installer-identity', required=True)
    parser.add_argument('--signing-key', required=True,
                        help='the HK evidence signing private key')
    parser.add_argument('--allow-candidate-commit', action='append', default=[],
                        help='a commit a candidate may come from (defaults to --source-commit)')
    parser.add_argument('--environment', default=ENVIRONMENT)
    parser.add_argument('--installation-token', default=None)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if hasattr(os, 'geteuid') and os.geteuid() != 0:
        # The state directory is root-owned by contract; installing into it as anyone else
        # would produce a fact the launcher then refuses. Say so instead of half-doing it.
        print('E_INSTALL_NOT_ROOT', file=sys.stderr)
        return 2
    candidates = list(args.candidate)
    if args.candidate_dir:
        candidates += sorted(str(p) for p in pathlib.Path(args.candidate_dir).glob('*.json'))
    pointer = json.loads(pathlib.Path(args.runtime_pointer).read_text(encoding='utf-8'))
    try:
        proof = json.loads(pathlib.Path(args.canonical_proof).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        # Absent or unreadable is not a proof. Nothing is written.
        print('E_INSTALL_CANONICAL_PROOF', file=sys.stderr)
        return 2
    try:
        summary = install(state_dir=args.state_dir, runtime_dir=args.runtime_dir,
                          launcher_path=args.launcher, candidate_sources=candidates,
                          runtime_pointer=pointer, source_commit=args.source_commit,
                          source_tree=args.source_tree,
                          installer_identity=args.installer_identity,
                          signing_key=args.signing_key, canonical_proof=proof,
                          allowed_commits=args.allow_candidate_commit,
                          environment=args.environment, token=args.installation_token)
    except InstallError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
