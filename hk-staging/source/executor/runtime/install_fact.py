"""The Hong Kong trust root: what this host has installed, and who says so.

CCV1-86 (WP-5). Before this module the launcher answered "are my bytes the ones I was
written against?" by comparing each runtime module against a SHA256 constant compiled
into the launcher itself. That answered the question for five modules and left four
unanswered -- the launcher could not attest its own bytes at all, had no readable version
for anything, and could only be updated by editing and reinstalling the launcher.

Now the answer comes from a single signed document, `/etc/go-hk-deployctl/install-fact-v1.json`,
produced by the installation flow (never by the executor) and signed with an identity that
already exists:

    INSTALL_FACT_SIGNER = HK_EVIDENCE_SIGNER

Why that identity and not the Command Center's task signer:

* an install fact is a statement **this host makes about itself** -- "these are the bytes
  installed here". The HK evidence signer's entire role is to sign facts produced by this
  host's execution layer; evidenced by the same key already verifying at
  `/etc/go-hk-agent/keys/evidence-signing.pub`.
* the private key of the evidence identity is present **only** on this host, which is where
  installation happens. Signing with the task identity would require the Command Center's
  authority private key to live on the machine that authority authorises -- after which the
  authorised host could mint its own authorisations. That is a boundary we do not cross.
* the Command Center's trust store already carries `hk-evidence.pub`, so the Command Center
  can verify an install fact with **no new key material** and no new identity.

The trust root, stated plainly (it is not "the launcher checks itself"):

    root ownership of /usr/local/libexec/go-hk-deployctl*
      + the install fact's signature, verified against a root-owned public key
        whose own fingerprint the fact names
      + the fact's statements about every module and about the launcher's own bytes

The launcher does not attest itself. It *reads an externally signed statement about
itself* and compares that statement with its own bytes. If the two disagree the launcher
refuses; if the statement is missing it refuses. A reader that cannot find its own
warrant does not proceed on the grounds that it seems fine.

`version` on a module is human-readable and advisory, but it is not decorative: it is
the module's own `VERSION` (or `_VERSION`) constant read out of the module's bytes by
`declared_version()`, and verification re-reads the same bytes and requires the two to
agree. A module that declares no version is recorded as `undeclared` -- a true statement
rather than a placeholder that might be mistaken for one.
"""
import ast
import base64
import hashlib
import json
import os
import pathlib
import re
import stat

SCHEMA = 'go.hk-install-fact.v1'
INSTALLED_IDENTITY_SCHEMA = 'go.hk-installed-identity.v1'

INSTALL_FACT = '/etc/go-hk-deployctl/install-fact-v1.json'
INSTALL_FACT_KEY = '/etc/go-hk-deployctl/keys/install-fact-signing.pub'
CANDIDATE_DIR = '/etc/go-hk-deployctl/candidates-v1'
ENVIRONMENT_GRAPH = '/etc/go-hk-deployctl/environment-graph-v1.json'

# The identity that signs, and the form of the name it is recorded under.  The name is
# checked; so is the fingerprint, recomputed from the public key that is actually on
# disk -- so replacing the .pub invalidates every fact signed under the old one.
SIGNER_IDENTITY = 'hk-evidence-signer'
# The fingerprint group keeps its `SHA256:` prefix because `key_id()` returns the
# prefix too. Capturing only the bare digest here and comparing it with the prefixed
# value would make every signature look like it came from another key -- a check that
# fails closed, but for the wrong reason and always.
SIGNATURE_IDENTITY = re.compile(r'^([a-z][a-z0-9-]{0,63}):(SHA256:[A-Za-z0-9+/]{43}=)$')
SIGNATURE = re.compile(r'^[A-Za-z0-9+/]+={0,2}$')

# The complete set of modules the launcher depends on, directly or through one another
# level of dynamic loading.  Exact, not a subset: a fact that omits a module that is on
# disk, or names one that is not, is not a statement about this installation.
RUNTIME_MODULES = (
    'install_fact',
    'collector_runtime',
    'canary_runtime',
    'deploy_runtime',
    'rollback_runtime',
    'artifact_runtime',
    'candidate_source',
    'migration_guard',
    'candidate_fact',
)

FACT_FIELDS = (
    'schema',
    'installation_id',
    'source_repository',
    'source_commit',
    'source_tree',
    'installed_at',
    'installer_identity',
    'launcher_version',
    'launcher_sha256',
    'runtime_digest',
    'runtime_modules',
    'compose_overlays',
    'candidate_fact_set',
    'environment_graph_identity',
    'signature_identity',
    'signature',
)
MODULE_FIELDS = ('name', 'version', 'sha256')
OVERLAY_FIELDS = ('path', 'version', 'sha256')
CANDIDATE_FACT_FIELDS = ('candidate_contract_sha256', 'path', 'sha256')
ENVIRONMENT_GRAPH_FIELDS = ('path', 'sha256')

REPOSITORY = 'yuguangzhi3836-glitch/GO'
SOURCE_COMMIT = re.compile(r'^[0-9a-f]{40}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
INSTALLATION_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
LAUNCHER_VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$')
INSTALLED_AT = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$')
INSTALLER_IDENTITY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
UNDECLARED_VERSION = 'undeclared'

MAX_FACT_BYTES = 64 * 1024
MAX_KEY_BYTES = 4 * 1024
MAX_DOCUMENT_BYTES = 256 * 1024

TRUSTED_UID = 0
WRITABLE_BY_OTHERS = 0o022


class Reject(ValueError):
    """A refusal. The message is the observable code."""


# --------------------------------------------------------------------------- #
# canonical form
# --------------------------------------------------------------------------- #
def canonical(value):
    """The byte form a signature is computed over, and nothing else.

    Sorted keys, no insignificant whitespace, no NaN: two spellings of the same document
    produce the same bytes, and a document that cannot round-trip is refused rather than
    signed into something a verifier would read differently.
    """
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def unsigned(document):
    return {key: value for key, value in document.items() if key != 'signature'}


def runtime_digest(modules):
    """One value for the whole batch: sha256 over the canonical sorted module list.

    Sorted by name, so the order the fact happens to list them in is not part of the
    identity; over `{name, sha256}` only, because `version` is a human-readable label
    that must not be able to change what a module *is*.
    """
    if not isinstance(modules, (list, tuple)):
        raise Reject('E_INSTALL_FACT_MODULES')
    rows = []
    for module in modules:
        if not isinstance(module, dict):
            raise Reject('E_INSTALL_FACT_MODULES')
        name, digest = module.get('name'), module.get('sha256')
        if not isinstance(name, str) or not isinstance(digest, str):
            raise Reject('E_INSTALL_FACT_MODULES')
        rows.append({'name': name, 'sha256': digest})
    rows.sort(key=lambda row: row['name'])
    return hashlib.sha256(canonical(rows)).hexdigest()


def file_sha256(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def declared_version(source_bytes):
    """A module's own version constant, read out of its bytes without executing it.

    Parsing rather than importing is deliberate: this runs while deciding whether the
    bytes may be loaded at all, so it must not be the thing that loads them.
    """
    try:
        tree = ast.parse(source_bytes.decode('utf-8'))
    except (UnicodeDecodeError, SyntaxError):
        return UNDECLARED_VERSION
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id not in ('VERSION', '_VERSION'):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return UNDECLARED_VERSION


# --------------------------------------------------------------------------- #
# root-only reads (the discipline the Command Center's trust store and #201 use)
# --------------------------------------------------------------------------- #
def directory_violation(info):
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return 'E_INSTALL_FACT_UNTRUSTED'
    if info.st_uid != TRUSTED_UID or info.st_mode & WRITABLE_BY_OTHERS:
        return 'E_INSTALL_FACT_UNTRUSTED'
    return None


def file_violation(info):
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return 'E_INSTALL_FACT_UNTRUSTED'
    if info.st_uid != TRUSTED_UID or info.st_mode & WRITABLE_BY_OTHERS:
        return 'E_INSTALL_FACT_UNTRUSTED'
    return None


def _check_ancestors(path):
    current = pathlib.Path(path)
    for candidate in [current, *current.parents]:
        try:
            info = os.lstat(str(candidate))
        except OSError as exc:
            raise Reject('E_INSTALL_FACT_UNTRUSTED') from exc
        code = directory_violation(info)
        if code:
            raise Reject(code)


def secure_read(path, limit, absent_code):
    """Read a root-owned regular file without following any link."""
    if not isinstance(path, str) or not os.path.isabs(path):
        raise Reject('E_INSTALL_FACT_UNTRUSTED')
    _check_ancestors(os.path.dirname(path))
    flags = os.O_RDONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise Reject(absent_code) from exc
    except OSError as exc:
        raise Reject('E_INSTALL_FACT_UNTRUSTED') from exc
    try:
        info = os.fstat(descriptor)
        code = file_violation(info)
        if code:
            raise Reject(code)
        if info.st_size > limit:
            raise Reject('E_INSTALL_FACT_UNTRUSTED')
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
        raise Reject('E_INSTALL_FACT_UNTRUSTED')
    return raw


# --------------------------------------------------------------------------- #
# signature
# --------------------------------------------------------------------------- #
def key_id(key):
    """A fingerprint of the key material: `SHA256:` over the raw public key bytes."""
    from cryptography.hazmat.primitives import serialization
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode('ascii')


def load_public_key(path):
    """The install fact's verification key, read the secure way."""
    raw = secure_read(path, MAX_KEY_BYTES, 'E_INSTALL_FACT_KEY_ABSENT')
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - environment, not input
        raise Reject('E_INSTALL_FACT_CRYPTO_UNAVAILABLE') from exc
    try:
        if raw.lstrip().startswith(b'ssh-'):
            key = serialization.load_ssh_public_key(raw)
        else:
            key = serialization.load_pem_public_key(raw)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError('key type')
    except ValueError as exc:
        raise Reject('E_INSTALL_FACT_KEY_INVALID') from exc
    return key


def verify_signature(document, key):
    """The fact is signed by the identity it names, or it is not a fact."""
    signature = document.get('signature')
    identity = document.get('signature_identity')
    if not isinstance(signature, str) or SIGNATURE.fullmatch(signature) is None:
        raise Reject('E_INSTALL_FACT_SIGNATURE')
    match = SIGNATURE_IDENTITY.fullmatch(identity) if isinstance(identity, str) else None
    if match is None or match.group(1) != SIGNER_IDENTITY:
        raise Reject('E_INSTALL_FACT_SIGNER_UNKNOWN')
    if match.group(2) != key_id(key):
        # The fact names a fingerprint that is not the installed key's. Either the fact
        # belongs to another key, or the key file has been replaced. Both are refusals.
        raise Reject('E_INSTALL_FACT_SIGNER_MISMATCH')
    try:
        key.verify(base64.b64decode(signature.encode('ascii'), validate=True),
                   canonical(unsigned(document)))
    except Exception as exc:
        raise Reject('E_INSTALL_FACT_SIGNATURE') from exc
    return document


# --------------------------------------------------------------------------- #
# shape
# --------------------------------------------------------------------------- #
def _exact_names(value, names, code):
    if not isinstance(value, dict) or set(value) != set(names):
        raise Reject(code)
    return value


def _sha(value, code):
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise Reject(code)
    return value


def validate_fact(document):
    """The declared shape of an install fact, before any byte is compared."""
    _exact_names(document, FACT_FIELDS, 'E_INSTALL_FACT_FIELDS')
    if document['schema'] != SCHEMA:
        raise Reject('E_INSTALL_FACT_SCHEMA')
    if not isinstance(document['installation_id'], str) \
            or INSTALLATION_ID.fullmatch(document['installation_id']) is None:
        raise Reject('E_INSTALL_FACT_FIELDS')
    if document['source_repository'] != REPOSITORY:
        raise Reject('E_INSTALL_FACT_FIELDS')
    for field in ('source_commit', 'source_tree'):
        if not isinstance(document[field], str) or SOURCE_COMMIT.fullmatch(document[field]) is None:
            raise Reject('E_INSTALL_FACT_FIELDS')
    if not isinstance(document['installed_at'], str) \
            or INSTALLED_AT.fullmatch(document['installed_at']) is None:
        raise Reject('E_INSTALL_FACT_FIELDS')
    if not isinstance(document['installer_identity'], str) \
            or INSTALLER_IDENTITY.fullmatch(document['installer_identity']) is None:
        raise Reject('E_INSTALL_FACT_FIELDS')
    if not isinstance(document['launcher_version'], str) \
            or LAUNCHER_VERSION.fullmatch(document['launcher_version']) is None:
        raise Reject('E_INSTALL_FACT_FIELDS')
    _sha(document['launcher_sha256'], 'E_INSTALL_FACT_FIELDS')
    _sha(document['runtime_digest'], 'E_INSTALL_FACT_FIELDS')

    modules = document['runtime_modules']
    if not isinstance(modules, list) or not modules:
        raise Reject('E_INSTALL_FACT_MODULES')
    for module in modules:
        _exact_names(module, MODULE_FIELDS, 'E_INSTALL_FACT_MODULES')
        if not isinstance(module['name'], str) or module['name'] not in RUNTIME_MODULES:
            raise Reject('E_INSTALL_FACT_MODULES')
        if not isinstance(module['version'], str) or not module['version']:
            raise Reject('E_INSTALL_FACT_MODULES')
        _sha(module['sha256'], 'E_INSTALL_FACT_MODULES')
    names = [module['name'] for module in modules]
    if sorted(names) != sorted(RUNTIME_MODULES):
        raise Reject('E_INSTALL_FACT_MODULES')
    if len(set(names)) != len(names):
        raise Reject('E_INSTALL_FACT_MODULES')

    overlays = document['compose_overlays']
    if not isinstance(overlays, list):
        raise Reject('E_INSTALL_FACT_FIELDS')
    for overlay in overlays:
        _exact_names(overlay, OVERLAY_FIELDS, 'E_INSTALL_FACT_FIELDS')
        if not isinstance(overlay['path'], str) or not os.path.isabs(overlay['path']):
            raise Reject('E_INSTALL_FACT_FIELDS')
        if not isinstance(overlay['version'], str) or not overlay['version']:
            raise Reject('E_INSTALL_FACT_FIELDS')
        _sha(overlay['sha256'], 'E_INSTALL_FACT_FIELDS')

    facts = document['candidate_fact_set']
    if not isinstance(facts, list) or not facts:
        raise Reject('E_INSTALL_FACT_CANDIDATE_SET')
    for fact in facts:
        _exact_names(fact, CANDIDATE_FACT_FIELDS, 'E_INSTALL_FACT_CANDIDATE_SET')
        _sha(fact['candidate_contract_sha256'], 'E_INSTALL_FACT_CANDIDATE_SET')
        if not isinstance(fact['path'], str) or not os.path.isabs(fact['path']):
            raise Reject('E_INSTALL_FACT_CANDIDATE_SET')
        _sha(fact['sha256'], 'E_INSTALL_FACT_CANDIDATE_SET')

    identity = _exact_names(document['environment_graph_identity'], ENVIRONMENT_GRAPH_FIELDS,
                            'E_INSTALL_FACT_ENVIRONMENT_GRAPH')
    if not isinstance(identity['path'], str) or not os.path.isabs(identity['path']):
        raise Reject('E_INSTALL_FACT_ENVIRONMENT_GRAPH')
    _sha(identity['sha256'], 'E_INSTALL_FACT_ENVIRONMENT_GRAPH')
    return document


# --------------------------------------------------------------------------- #
# the fact against the disk
# --------------------------------------------------------------------------- #
def verify_launcher(document, launcher_path):
    """The fact's statement about the launcher, against the launcher's own bytes.

    This is not self-attestation: the number came from outside, signed; the launcher
    only confirms that the file it read is the file the signature describes.
    """
    try:
        actual = file_sha256(launcher_path)
    except OSError as exc:
        raise Reject('E_INSTALL_FACT_LAUNCHER') from exc
    if actual != document['launcher_sha256']:
        raise Reject('E_INSTALL_FACT_LAUNCHER')
    return actual


def verify_runtime_modules(document, runtime_dir):
    """Every module's bytes, and every module's declared version, or a refusal.

    The failure names the module: an operator who is told "the install is wrong" has to
    go and diff the whole tree; one who is told which module disagrees does not.
    """
    declared = {module['name']: module for module in document['runtime_modules']}
    if runtime_digest(document['runtime_modules']) != document['runtime_digest']:
        raise Reject('E_INSTALL_FACT_RUNTIME_DIGEST')
    for name in RUNTIME_MODULES:
        path = os.path.join(runtime_dir, name + '.py')
        try:
            raw = pathlib.Path(path).read_bytes()
        except OSError as exc:
            raise Reject('E_INSTALL_FACT_MODULE_MISSING:' + name) from exc
        if hashlib.sha256(raw).hexdigest() != declared[name]['sha256']:
            raise Reject('E_INSTALL_FACT_MODULE_DRIFT:' + name)
        if declared_version(raw) != declared[name]['version']:
            raise Reject('E_INSTALL_FACT_MODULE_VERSION:' + name)
    return declared


def verify_installed_files(document, candidate_dir=None, environment_graph=None):
    """The controlled facts the fact names must be the files that are actually there.

    Otherwise the install fact and the candidate store are two unrelated documents that
    happen to sit in the same directory, and "which installation does this candidate
    belong to" has no answer.
    """
    directory = candidate_dir or CANDIDATE_DIR
    for entry in document['candidate_fact_set']:
        expected = os.path.join(directory, entry['candidate_contract_sha256'] + '.json')
        if entry['path'] != expected:
            raise Reject('E_INSTALL_FACT_CANDIDATE_SET')
        try:
            actual = file_sha256(entry['path'])
        except OSError as exc:
            raise Reject('E_INSTALL_FACT_CANDIDATE_SET_MISSING:' + entry['candidate_contract_sha256']) from exc
        if actual != entry['sha256']:
            raise Reject('E_INSTALL_FACT_CANDIDATE_SET_DRIFT:' + entry['candidate_contract_sha256'])
    identity = document['environment_graph_identity']
    path = environment_graph or ENVIRONMENT_GRAPH
    if identity['path'] != path:
        raise Reject('E_INSTALL_FACT_ENVIRONMENT_GRAPH')
    try:
        actual = file_sha256(path)
    except OSError as exc:
        raise Reject('E_INSTALL_FACT_ENVIRONMENT_GRAPH_MISSING') from exc
    if actual != identity['sha256']:
        raise Reject('E_INSTALL_FACT_ENVIRONMENT_GRAPH_DRIFT')
    return document


def load_installation(launcher_path, runtime_dir,
                      fact_path=INSTALL_FACT, key_path=INSTALL_FACT_KEY,
                      candidate_dir=None, environment_graph=None):
    """Read, verify and return the installation this launcher is running under.

    Fail-closed at every step, and in this order: the fact is read from a root-owned
    path without following links, its shape is checked, its signature is checked against
    a key whose fingerprint the fact itself names, and only then are bytes compared --
    the launcher's, every module's, the candidate facts' and the environment graph's.
    """
    raw = secure_read(fact_path, MAX_FACT_BYTES, 'E_INSTALL_FACT_ABSENT')
    try:
        document = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Reject('E_INSTALL_FACT_UNREADABLE') from exc
    validate_fact(document)
    verify_signature(document, load_public_key(key_path))
    verify_launcher(document, launcher_path)
    verify_runtime_modules(document, runtime_dir)
    verify_installed_files(document, candidate_dir, environment_graph)
    return document


def installed_identity(document):
    """The minimum a verifier needs in order to answer "what was installed when this ran".

    Derived from a fact that has already been verified, never assembled from parts: an
    identity that could be produced from unverified input would be a claim, not a record.
    """
    return {
        'schema': INSTALLED_IDENTITY_SCHEMA,
        'installation_id': document['installation_id'],
        'source_commit': document['source_commit'],
        'launcher_version': document['launcher_version'],
        'launcher_sha256': document['launcher_sha256'],
        'runtime_digest': document['runtime_digest'],
    }


def read_installed_identity(launcher_path, runtime_dir, fact_path=INSTALL_FACT,
                            key_path=INSTALL_FACT_KEY, candidate_dir=None,
                            environment_graph=None):
    """`installed_identity` for a fully verified installation, or a refusal."""
    return installed_identity(load_installation(
        launcher_path, runtime_dir, fact_path, key_path, candidate_dir, environment_graph))
