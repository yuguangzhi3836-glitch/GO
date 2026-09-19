"""CANONICAL_SOURCE_INVARIANT -- the six-step proof that bytes belong to canonical `main`.

Owner: `control-plane/command-center-canonical-provenance-v1`.

This is the one implementation of the invariant stated in CCV1-82 CONTRACT SPEC section 7:

> Bytes that have not passed CANONICAL_PROVENANCE must not be deployed; and a drift
> discovered after a deployment must be findable by the next Evidence.

The proof has six steps, they are evaluated **in order**, and the first failure stops the
chain -- a later step that consumed the output of a failed one has nothing to consume:

    1  candidate.source_commit is a canonical commit (on the ancestor chain of main)
    2  the declared tree equals tree(commit, path) -- `application/`, or the whole tree
    3  TEST_PR Evidence.built_image_id equals candidate.artifact_digest
    4  installed_identity.source_commit equals the authorised deploy commit
    5  every installed runtime module's sha256 equals the git blob at (commit, path)
    6  (a failure anywhere) refuse, and name the specific files that disagree

Steps 5 and 6 are where the SPEC demands a **complete** difference list rather than a first
offender: an operator told "one of your modules is wrong" has to diff the whole tree; one
told which module disagrees does not.

WHAT THIS MODULE IS NOT
-----------------------
* It is not an authority. It deploys nothing, publishes nothing, signs nothing and
  activates nothing: `AUTHORITY` below is the machine-readable statement of that, and the
  contract schema pins every entry false.
* It does not *fetch*. The repository handle it is given is read through local, read-only
  git plumbing only (see `git_repository.py`). Which `main` was proved against is therefore
  an input rather than an assumption -- and it is recorded in the verdict as
  `canonical_commit`, so a stale reference is an auditable fact rather than a silent one.
* It does not decide policy. Whether a refusal stops a publication or is recorded is the
  caller's decision (SPEC section 12 sequences it as T3); this module decides only whether
  the bytes are canonical, and refuses rather than guessing when they are not.

THE ONE DUPLICATED LINE
-----------------------
Step 3 compares an artifact digest with a signed `built_image_id`, and candidate admission
already refuses that disagreement (`candidate_test_result_evidence_artifact`). The
comparison is repeated here because section 7.3 defines the proof as a sequence of
assertions over the facts, and a proof that delegated one of its steps would not be runnable
on its own. What is *not* duplicated is the candidate digest: `candidate_fact.py` (WP-1)
remains its only implementation, and this module imports it.

A DIVERGENCE WORTH KNOWING ABOUT
--------------------------------
Step 5 compares `sha256(git blob at (commit, path))` with a module's recorded `sha256`. One
side is over the bytes that were installed, the other over the bytes the repository stores.
When the checkout that produced a staged tree and the repository agree, the two numbers are
the same. When a checkout has rewritten line endings (a Windows working tree with
`core.autocrlf=true`), they are not -- and that divergence is exactly what this comparison
exists to surface, not a reason to normalise either side.
"""
import hashlib
import importlib.util
import os
import re

# --------------------------------------------------------------------------- #
# the refusal vocabulary -- stable, and closed at five
# --------------------------------------------------------------------------- #
# CCV1-82 section 7.2 names exactly these five codes. They are stable contract: a Boss reads
# them back and request-visibility classifies them. Nothing here may add a sixth to
# describe a situation one of these five already describes.
E_COMMIT_NOT_CANONICAL = 'E_COMMIT_NOT_CANONICAL'
E_TREE_MISMATCH = 'E_TREE_MISMATCH'
E_ARTIFACT_MISMATCH = 'E_ARTIFACT_MISMATCH'
E_BLOB_DRIFT = 'E_BLOB_DRIFT'
E_INSTALL_DRIFT = 'E_INSTALL_DRIFT'

CODES = (E_COMMIT_NOT_CANONICAL, E_TREE_MISMATCH, E_ARTIFACT_MISMATCH,
         E_BLOB_DRIFT, E_INSTALL_DRIFT)

# The *condition* says which kind of disagreement it is, so one stable code can describe
# several situations without any of them becoming invisible. A code answers "may this
# proceed"; a condition answers "what exactly is wrong". Keeping them apart is what lets
# the code set stay at five while section 7.1's two named conditions (DRIFT /
# PROVENANCE_BROKEN) stay distinguishable in the report.
UNRESOLVABLE = 'UNRESOLVABLE'
PROVENANCE_BROKEN = 'PROVENANCE_BROKEN'
DRIFT = 'DRIFT'
NOT_THE_AUTHORIZED_COMMIT = 'NOT_THE_AUTHORIZED_COMMIT'

CONDITIONS = (UNRESOLVABLE, PROVENANCE_BROKEN, DRIFT, NOT_THE_AUTHORIZED_COMMIT)

# The six steps of section 7.3, in the order the SPEC fixes. The names are stable: a verdict
# is read step by step, and a report that renumbered them would stop being comparable with
# an earlier one.
STEP_COMMIT_IS_CANONICAL = 'commit_is_canonical'
STEP_APPLICATION_TREE_MATCHES = 'application_tree_matches'
STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT = 'artifact_matches_the_signed_result'
STEP_INSTALLED_IDENTITY_IS_THE_AUTHORIZED_COMMIT = 'installed_identity_is_the_authorized_commit'
STEP_MODULES_ARE_THE_COMMIT_BLOBS = 'installed_modules_are_the_commit_blobs'
STEP_DISK_BLOBS_MATCH_THE_COMMIT = 'disk_blobs_match_the_commit'

STEPS = (STEP_COMMIT_IS_CANONICAL,
         STEP_APPLICATION_TREE_MATCHES,
         STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT,
         STEP_INSTALLED_IDENTITY_IS_THE_AUTHORIZED_COMMIT,
         STEP_MODULES_ARE_THE_COMMIT_BLOBS,
         STEP_DISK_BLOBS_MATCH_THE_COMMIT)

# The four phases a caller can ask for. They are named after what the caller *has*, not
# after what it hopes to conclude: a proof composed from the wrong inputs cannot be asked
# for by accident.
PHASE_PRE_DEPLOY = 'PRE_DEPLOY'
PHASE_INSTALL_SOURCE = 'INSTALL_SOURCE'
PHASE_POST_DEPLOY = 'POST_DEPLOY'
PHASE_CHECKOUT = 'CHECKOUT'

PASS = 'PASS'
FAIL = 'FAIL'
NOT_EVALUATED = 'NOT_EVALUATED'

# The reason a step carries when the composition it belongs to does not contain it at all.
# It is a different fact from "the input this step needed was missing": a missing input
# raises (`ProvenanceError`), because a proof asked a question it cannot answer is a
# programming error, while a step outside the composition was never asked. Without that
# split, a verdict could report PASS while one of its steps was never evaluated.
NOT_PART = 'not_part_of_this_proof'

SCHEMA = 'go.canonical-source-invariant.v1'
CONTRACT_NAME = 'CANONICAL_SOURCE_INVARIANT'

DEFAULT_CANONICAL_REF = 'origin/main'
DEFAULT_APPLICATION_PATH = 'application'

CANDIDATE_REPOSITORY = 'yuguangzhi3836-glitch/GO'

# Repository paths and refs are repo-relative, forward-slashed strings that never leave the
# tree. A path this component cannot address is refused rather than handed to a program, and
# the rule is ONE rule with two instantiations rather than two spellings of the same idea --
# the adapter imports these, so "what a repository path may look like" has a single
# implementation for the whole component.
#
# A leading dot is allowed: `.github/workflows/**` is a path this repository really has, and
# a rule that refuses it refuses real files. `.` and `..` as *components* are not, because a
# path that can name a place outside the tree is not a repository path. Backslashes are
# refused for the same reason a range is not a ref: on Windows a backslash spelling reaches
# git as a different string, and `git hash-object --path` silently stops applying the
# repository's clean filters. That is not a theory -- it produced a false drift on a file
# that matched its blob exactly (CCV1-88).
COMPONENT = re.compile(r'^[A-Za-z0-9._-]{1,255}$')


class AddressableName:
    """A `fullmatch`-shaped rule for the strings that may address something in a repository.

    `fullmatch` returns True rather than a match object: every call site asks "may I address
    this", and none of them asks what matched.
    """

    def __init__(self, ranges_forbidden):
        self.ranges_forbidden = ranges_forbidden

    def fullmatch(self, value):
        if not isinstance(value, str) or not value or value.startswith('/') \
                or value.startswith('-') or '\\' in value:
            return None
        if self.ranges_forbidden and '..' in value:
            # A range is not a ref: `main..side` names a set of commits, and a question about
            # a set is a different question from the one this proof answers.
            return None
        for component in value.split('/'):
            if component in ('', '.', '..') or COMPONENT.fullmatch(component) is None:
                return None
        return True


REPO_PATH = AddressableName(ranges_forbidden=False)
REF = AddressableName(ranges_forbidden=True)
COMMIT = re.compile(r'^[0-9a-f]{40}$')
OBJECT_ID = re.compile(r'^[0-9a-f]{40}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
IMAGE_ID = re.compile(r'^sha256:[0-9a-f]{64}$')

AUTHORITY = {
    'may_read_the_repository': True,
    'may_read_the_candidate_and_its_evidence': True,
    'deploys': False,
    'publishes': False,
    'signs': False,
    'activates': False,
    'authorises': False,
    'writes_to_the_repository': False,
    'calls_the_network': False,
    'note': 'The proof answers one question -- are these bytes canonical. It grants nothing.',
}

# --------------------------------------------------------------------------- #
# the candidate identity implementation (WP-1) -- imported, never reimplemented
# --------------------------------------------------------------------------- #
_HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATE_COMPONENT = os.path.join(os.path.dirname(_HERE),
                                   'command-center-candidate-admission-v1')
CANDIDATE_FACT_PATH = os.path.join(CANDIDATE_COMPONENT, 'candidate_fact.py')

_CANDIDATE_FACT = None


class ProvenanceError(ValueError):
    """The proof could not be evaluated as asked. A programming error, not a verdict."""


def candidate_fact_module():
    """The single candidate digest implementation, loaded once per process.

    Imported from its owner component rather than copied: two implementations of
    `candidate_contract_sha256` would be two things to keep in step, and the whole point of
    the converged candidate identity is that there is exactly one.
    """
    global _CANDIDATE_FACT
    if _CANDIDATE_FACT is None:
        if not os.path.isfile(CANDIDATE_FACT_PATH):
            raise ProvenanceError('candidate_component_unavailable')
        spec = importlib.util.spec_from_file_location('_go_canonical_candidate_fact',
                                                      CANDIDATE_FACT_PATH)
        if spec is None or spec.loader is None:
            raise ProvenanceError('candidate_component_unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CANDIDATE_FACT = module
    return _CANDIDATE_FACT


def candidate_contract_sha256(candidate):
    """The converged candidate digest, from its one implementation."""
    return candidate_fact_module().candidate_contract_sha256(candidate)


# --------------------------------------------------------------------------- #
# git object ids -- the one arithmetic a real and a simulated repository share
# --------------------------------------------------------------------------- #
def blob_object_id(content):
    """The git object id of a byte sequence, in the repository's object format.

    `GO` is a sha1-object repository (`git rev-parse --show-object-format` = sha1), so the
    object id is the sha1 of `"blob <len>\\0" + content`. This is exported because the
    in-memory repository the unit tests use must produce the same identifiers as the real
    one: an identifier scheme only one side implements is a difference the tests could not
    see.
    """
    if not isinstance(content, (bytes, bytearray)):
        raise ProvenanceError('blob_content_not_bytes')
    raw = bytes(content)
    return hashlib.sha1(b'blob %d\0' % len(raw) + raw).hexdigest()


def sha256_of(content):
    return hashlib.sha256(bytes(content)).hexdigest()


def module_path(module_prefix, name):
    """The repository path an installed runtime module came from."""
    return '%s/%s.py' % (module_prefix, name)


# --------------------------------------------------------------------------- #
# the repository port
# --------------------------------------------------------------------------- #
class Repository:
    """What the proof needs from a repository -- and nothing more.

    Five reads, all local and read-only. A verifier that could also fetch, write or run an
    arbitrary program would be a verifier whose inputs cannot be stated, so the port is
    deliberately narrower than git.

    `resolve`, `is_ancestor`, `tree_id`, `object_at` and `has_commit` answer questions about
    the object database; `disk_object_id` is the one method that touches a working tree, and
    it exists because a checkout can only be compared with a blob through the repository's
    own clean filters.
    """

    def resolve(self, ref):
        """The commit a ref names, or None if it names no commit."""
        raise NotImplementedError

    def has_commit(self, commit):
        """True when this repository holds the commit object."""
        raise NotImplementedError

    def is_ancestor(self, commit, ref):
        """True when `commit` is an ancestor of (or equal to) the commit `ref` names."""
        raise NotImplementedError

    def tree_id(self, commit, path):
        """The tree object at `path` in `commit`; a `path` of '' is the commit's root tree."""
        raise NotImplementedError

    def object_at(self, commit, path):
        """(object_id, content) for the blob at `path` in `commit`, or None."""
        raise NotImplementedError

    def disk_object_id(self, repo_path, filename):
        """The object id git records for the file `filename` at repository path `repo_path`."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# steps 1 and 2 -- the commit, and the tree it declares
# --------------------------------------------------------------------------- #
def step_commit_is_canonical(repository, commit, canonical_ref=DEFAULT_CANONICAL_REF):
    """Section 7.3 step 1. Is this the kind of commit a deployment may name?

    Three ways to fail, and they are not interchangeable:

    * the ref the proof was asked to use does not resolve -- there is no `main` to be
      canonical *relative to*, so nothing can be proved (`UNRESOLVABLE`);
    * the commit does not exist in this repository (`UNRESOLVABLE`);
    * the commit exists but is not on that chain (`PROVENANCE_BROKEN`) -- which is the
      condition section 7.1 defines, and the one that matters: the bytes are real, they are
      just not main's.
    """
    canonical = repository.resolve(canonical_ref)
    if canonical is None or not COMMIT.fullmatch(canonical):
        return _failed(STEP_COMMIT_IS_CANONICAL, E_COMMIT_NOT_CANONICAL, UNRESOLVABLE,
                       observed={'canonical_ref': canonical_ref},
                       expected={'canonical_ref_resolves_to_a_commit': True})
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit) \
            or not repository.has_commit(commit):
        return _failed(STEP_COMMIT_IS_CANONICAL, E_COMMIT_NOT_CANONICAL, UNRESOLVABLE,
                       observed={'source_commit': commit, 'canonical_commit': canonical},
                       expected={'source_commit_is_a_commit_in_this_repository': True})
    if not repository.is_ancestor(commit, canonical_ref):
        return _failed(STEP_COMMIT_IS_CANONICAL, E_COMMIT_NOT_CANONICAL, PROVENANCE_BROKEN,
                       observed={'source_commit': commit, 'canonical_ref': canonical_ref,
                                 'canonical_commit': canonical},
                       expected={'source_commit_on_the_canonical_chain': canonical})
    return _passed(STEP_COMMIT_IS_CANONICAL,
                   observed={'source_commit': commit, 'canonical_commit': canonical})


def step_tree_matches(repository, commit, declared_tree, tree_path):
    """Section 7.3 step 2. Is the declared tree the tree that commit actually has?

    A commit and a tree are different identity claims, and a document can carry a real
    commit with a tree from somewhere else -- which is the shape a "same revision" claim
    takes when it is not true. A `tree_path` of None means the commit's whole tree, which is
    what the Hong Kong install fact records as its `source_tree`.
    """
    path = '' if tree_path is None else tree_path
    if path and not REPO_PATH.fullmatch(path):
        raise ProvenanceError('tree_path_not_addressable')
    actual = repository.tree_id(commit, path)
    if actual is None:
        return _failed(STEP_APPLICATION_TREE_MATCHES, E_TREE_MISMATCH, UNRESOLVABLE,
                       observed={'source_commit': commit, 'tree_path': path or '.'},
                       expected={'a_tree_at_this_path': True})
    declared = declared_tree
    if not isinstance(declared, str) or not OBJECT_ID.fullmatch(declared):
        return _failed(STEP_APPLICATION_TREE_MATCHES, E_TREE_MISMATCH, UNRESOLVABLE,
                       observed={'declared_tree': declared},
                       expected={'declared_tree_is_a_tree_object_id': True})
    if declared != actual:
        return _failed(STEP_APPLICATION_TREE_MATCHES, E_TREE_MISMATCH, DRIFT,
                       observed={'declared_tree': declared, 'actual_tree': actual,
                                 'tree_path': path or '.', 'source_commit': commit},
                       expected={'declared_tree': actual})
    return _passed(STEP_APPLICATION_TREE_MATCHES,
                   observed={'declared_tree': declared, 'tree_path': path or '.'})


# --------------------------------------------------------------------------- #
# step 3 -- the artifact the signed result actually built
# --------------------------------------------------------------------------- #
def step_artifact_matches_the_signed_result(candidate, evidence):
    """Section 7.3 step 3. Is this artifact the one the signed TEST_PR produced?

    The candidate carries an artifact digest and a signed result carries a built image id.
    When they differ, one of the two documents is about a different build, and no reading of
    "deploy this" survives it.
    """
    digest = candidate.get('artifact_digest')
    built = evidence.get('built_image_id') if isinstance(evidence, dict) else None
    if not isinstance(digest, str) or IMAGE_ID.fullmatch(digest) is None:
        return _failed(STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT, E_ARTIFACT_MISMATCH,
                       UNRESOLVABLE, observed={'artifact_digest': digest},
                       expected={'artifact_digest_names_an_image': True})
    if not isinstance(built, str) or IMAGE_ID.fullmatch(built) is None:
        return _failed(STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT, E_ARTIFACT_MISMATCH,
                       UNRESOLVABLE, observed={'built_image_id': built},
                       expected={'the_signed_result_names_an_image': True})
    if digest != built:
        return _failed(STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT, E_ARTIFACT_MISMATCH, DRIFT,
                       observed={'candidate_artifact_digest': digest, 'built_image_id': built},
                       expected={'built_image_id': digest})
    return _passed(STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT, observed={'built_image_id': built})


# --------------------------------------------------------------------------- #
# step 4 -- what the host says it is running
# --------------------------------------------------------------------------- #
def step_installed_identity_is_the_authorized_commit(installed_identity, authorized_commit):
    """Section 7.3 step 4. Is the installation the authorised one -- not merely canonical?

    A host running a *different* canonical commit is neither drift nor broken provenance:
    its bytes correspond to main, they are simply not the deployment that was authorised.
    That is its own condition, named so an operator does not go looking for a tampered file
    that does not exist.
    """
    installed = (installed_identity or {}).get('source_commit')
    if not isinstance(installed, str) or not COMMIT.fullmatch(installed):
        return _failed(STEP_INSTALLED_IDENTITY_IS_THE_AUTHORIZED_COMMIT, E_INSTALL_DRIFT,
                       UNRESOLVABLE, observed={'installed_source_commit': installed},
                       expected={'installed_source_commit_is_a_commit': True})
    if not isinstance(authorized_commit, str) or not COMMIT.fullmatch(authorized_commit):
        raise ProvenanceError('authorized_commit_not_a_commit')
    if installed != authorized_commit:
        return _failed(STEP_INSTALLED_IDENTITY_IS_THE_AUTHORIZED_COMMIT, E_INSTALL_DRIFT,
                       NOT_THE_AUTHORIZED_COMMIT,
                       observed={'installed_source_commit': installed},
                       expected={'installed_source_commit': authorized_commit})
    return _passed(STEP_INSTALLED_IDENTITY_IS_THE_AUTHORIZED_COMMIT,
                   observed={'installed_source_commit': installed})


# --------------------------------------------------------------------------- #
# step 5 -- the modules, blob by blob
# --------------------------------------------------------------------------- #
def step_modules_are_the_commit_blobs(repository, commit, modules, module_prefix):
    """Section 7.3 step 5. Every installed module against the blob that commit holds.

    `modules` is what an installation recorded (`runtime_modules`: name, version, sha256);
    each name is joined to its repository path, that path is read out of the commit, and the
    hashes are compared. **Every** module is compared and the verdict carries a difference
    line per module: the SPEC asks for the file list, and a list of one is not a list.
    """
    drift = []
    checked = []
    modules = list(modules)
    for module in modules:
        if not isinstance(module, dict):
            raise ProvenanceError('module_not_an_object')
        name = module.get('name')
        declared = module.get('sha256')
        if not isinstance(name, str) or not REPO_PATH.fullmatch(name):
            raise ProvenanceError('module_name_not_addressable')
        path = module_path(module_prefix, name)
        if not REPO_PATH.fullmatch(path):
            raise ProvenanceError('module_path_not_addressable')
        actual = repository.object_at(commit, path)
        if actual is None:
            drift.append({'kind': 'module_absent_from_the_commit', 'name': name,
                          'path': path, 'expected': declared, 'observed': None})
            continue
        expected = sha256_of(actual[1])
        if not isinstance(declared, str) or not SHA256.fullmatch(declared) \
                or declared != expected:
            drift.append({'kind': 'module_bytes_differ_from_the_commit', 'name': name,
                          'path': path, 'expected': expected, 'observed': declared})
            continue
        checked.append({'name': name, 'path': path, 'sha256': expected, 'blob': actual[0]})
    if drift:
        return _failed(STEP_MODULES_ARE_THE_COMMIT_BLOBS, E_INSTALL_DRIFT, DRIFT,
                       observed={'modules': len(modules), 'disagreeing': len(drift)},
                       expected={'every_installed_module_is_the_commit_blob': True},
                       drift=drift, extra={'modules': checked})
    return _passed(STEP_MODULES_ARE_THE_COMMIT_BLOBS,
                   observed={'modules': len(modules)}, extra={'modules': checked})


# --------------------------------------------------------------------------- #
# step 6 -- local bytes against the commit's blobs
# --------------------------------------------------------------------------- #
def step_disk_blobs_match_the_commit(repository, commit, files):
    """The blob row of section 7.2: a checkout's bytes against the commit's objects.

    `files` is an iterable of `(repo_path, filename)` -- the path the repository knows the
    file by, and where those bytes are on this host. The comparison is between two *object
    ids*, not two digests: `git hash-object` of the file (with the repository's clean
    filters applied, which is the only way a checkout can be compared with a blob at all)
    against `git rev-parse <commit>:<path>`.

    A file that is not in the commit is drift with no expected side; a file the commit holds
    that the checkout does not have is drift with no observed side. Both are named, because
    "the tree differs" is not actionable.
    """
    files = [(repo_path, filename) for repo_path, filename in files]
    drift = []
    for repo_path, filename in files:
        if not REPO_PATH.fullmatch(repo_path or ''):
            raise ProvenanceError('repo_path_not_addressable')
        wanted = repository.object_at(commit, repo_path)
        try:
            got = repository.disk_object_id(repo_path, filename)
        except OSError:
            got = None
        if wanted is None or got is None or wanted[0] != got:
            drift.append({'kind': 'file_bytes_differ_from_the_commit', 'path': repo_path,
                          'file': str(filename),
                          'expected': wanted[0] if wanted else None, 'observed': got})
    if drift:
        return _failed(STEP_DISK_BLOBS_MATCH_THE_COMMIT, E_BLOB_DRIFT, DRIFT,
                       observed={'files': len(files), 'disagreeing': len(drift)},
                       expected={'every_file_is_the_commit_blob': True}, drift=drift)
    return _passed(STEP_DISK_BLOBS_MATCH_THE_COMMIT, observed={'files': len(files)})


# --------------------------------------------------------------------------- #
# step results and the verdict
# --------------------------------------------------------------------------- #
def _passed(step, observed=None, extra=None):
    result = {'step': step, 'state': PASS, 'code': None, 'condition': None,
              'observed': observed or {}, 'drift': []}
    result.update(extra or {})
    return result


def _failed(step, code, condition, observed, expected, drift=None, extra=None):
    result = {'step': step, 'state': FAIL, 'code': code, 'condition': condition,
              'observed': observed, 'expected': expected, 'drift': drift or []}
    result.update(extra or {})
    return result


def _not_evaluated(step, reason):
    return {'step': step, 'state': NOT_EVALUATED, 'code': None, 'condition': None,
            'observed': {'reason': reason}, 'drift': []}


def _assemble(phase, canonical_ref, canonical_commit, authorized_commit, application_path,
              candidate_contract, source_tree, results):
    """Assemble the public verdict. The first failure decides; every failure is reported."""
    refusal = None
    for result in results:
        if result['state'] == FAIL and refusal is None:
            refusal = {'step': result['step'], 'code': result['code'],
                       'condition': result['condition'], 'observed': result['observed'],
                       'expected': result['expected']}
    drift = [entry for result in results for entry in result['drift']]
    modules = [entry for result in results for entry in result.get('modules', [])]
    return {
        'schema': SCHEMA,
        'contract': CONTRACT_NAME,
        'phase': phase,
        'verdict': 'REFUSED' if refusal else 'PASS',
        'canonical_ref': canonical_ref,
        'canonical_commit': canonical_commit,
        'authorized_deploy_commit': authorized_commit,
        'application_path': application_path,
        'candidate_contract_sha256': candidate_contract,
        'source_tree': source_tree,
        'steps': results,
        'refusal': refusal,
        'drift': drift,
        'modules': modules,
        'codes': list(CODES),
        'conditions': list(CONDITIONS),
        'authority': dict(AUTHORITY),
    }


def _tail(steps):
    """The steps a composition does not contain, as NOT_EVALUATED rather than omitted.

    A verdict always carries all six steps. An omitted step and a step that passed look the
    same to a reader scanning for gaps, so nothing is omitted.
    """
    return [_not_evaluated(step, NOT_PART) for step in steps]


def _require(value, name):
    """A composition's inputs are required. Absent is a programming error, not a verdict.

    This is what keeps `PASS` honest. If an absent input produced NOT_EVALUATED instead of
    raising, a proof could report PASS while one of its steps was never evaluated -- and a
    deployment gated on an unevaluated proof is a deployment gated on nothing.

    Empty counts as absent. An empty module list or an empty file list is not a proof about
    nothing, it is a caller that has not said what to prove.
    """
    if value is None or (isinstance(value, (str, bytes, list, tuple, dict)) and not value):
        raise ProvenanceError('input_absent:%s' % name)
    return value


# --------------------------------------------------------------------------- #
# the four compositions section 7.3 is actually used as
# --------------------------------------------------------------------------- #
def prove_candidate(repository, candidate, evidence, *,
                    canonical_ref=DEFAULT_CANONICAL_REF,
                    application_path=DEFAULT_APPLICATION_PATH):
    """Steps 1-3 for a converged candidate fact: may this candidate be deployed?

    This is the pre-deployment proof. Whether a refusal stops a publication or is recorded
    is the caller's decision -- the SPEC's transition plan (section 12, T3) sequences that
    decision, and this verifier does not make it.
    """
    _require(evidence, 'test_pr_evidence')
    fact = candidate_fact_module()
    fact.validate_converged(candidate)
    digest = fact.candidate_contract_sha256(candidate)
    commit = candidate['source_commit']

    results = [step_commit_is_canonical(repository, commit, canonical_ref)]
    if results[0]['state'] == PASS:
        results.append(step_tree_matches(repository, commit, candidate['application_tree'],
                                         application_path))
    else:
        results.append(_not_evaluated(STEP_APPLICATION_TREE_MATCHES, 'commit_not_canonical'))
    results.append(step_artifact_matches_the_signed_result(candidate, evidence))
    results.extend(_tail(STEPS[3:]))
    return _assemble(PHASE_PRE_DEPLOY, canonical_ref, repository.resolve(canonical_ref),
                     commit, application_path, digest, None, results)


def prove_install_source(repository, source_commit, source_tree, modules, *,
                         module_prefix, canonical_ref=DEFAULT_CANONICAL_REF):
    """Steps 1, 2 and 5 for the source identity an installation is about to record.

    This is the proof WP-5 left a named seam for: `hk-staging/install/hk_install_facts.py`
    records a `source_commit` and a `source_tree`, and states that proving the commit is on
    `main` "needs the repository and belongs to WP-6". The repository is here, so the proof
    is here: the commit is canonical, the declared tree is that commit's **whole** tree, and
    every runtime module about to be installed hashes to the blob that commit holds.

    The proof does not read the installed host. It answers "are the bytes I am about to
    record canonical", which is the question an installer can act on before it writes
    anything.
    """
    _require(source_commit, 'source_commit')
    _require(source_tree, 'source_tree')
    _require(modules, 'modules')
    results = [step_commit_is_canonical(repository, source_commit, canonical_ref)]
    if results[0]['state'] == PASS:
        results.append(step_tree_matches(repository, source_commit, source_tree, None))
    else:
        results.append(_not_evaluated(STEP_APPLICATION_TREE_MATCHES, 'commit_not_canonical'))
    results.append(_not_evaluated(STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT, NOT_PART))
    results.append(_not_evaluated(STEP_INSTALLED_IDENTITY_IS_THE_AUTHORIZED_COMMIT, NOT_PART))
    if results[0]['state'] == PASS:
        results.append(step_modules_are_the_commit_blobs(repository, source_commit, modules,
                                                         module_prefix))
    else:
        results.append(_not_evaluated(STEP_MODULES_ARE_THE_COMMIT_BLOBS,
                                      'commit_not_canonical'))
    results.append(_not_evaluated(STEP_DISK_BLOBS_MATCH_THE_COMMIT, NOT_PART))
    return _assemble(PHASE_INSTALL_SOURCE, canonical_ref, repository.resolve(canonical_ref),
                     source_commit, None, None, source_tree, results)


def prove_installation(repository, authorized_commit, installed_identity, source_tree,
                       modules, *, module_prefix, canonical_ref=DEFAULT_CANONICAL_REF,
                       application_path=None, authorized_candidate=None):
    """Steps 1, 2, 4 and 5 for an installation: is the host running the authorised bytes?

    `installed_identity` is the block an Evidence carries and `modules` and `source_tree` are
    what the install fact recorded, so this proof needs three documents rather than one and
    says so. The authorised deploy commit is an argument, not a discovery: this proof can
    establish whether a host matches an authorisation, not which authorisation was granted.
    """
    _require(installed_identity, 'installed_identity')
    _require(source_tree, 'source_tree')
    _require(modules, 'modules')
    installed_commit = (installed_identity or {}).get('source_commit')

    results = [step_commit_is_canonical(repository, installed_commit, canonical_ref)]
    if results[0]['state'] == PASS:
        results.append(step_tree_matches(repository, installed_commit, source_tree,
                                         application_path))
    else:
        results.append(_not_evaluated(STEP_APPLICATION_TREE_MATCHES,
                                      'installed_commit_not_canonical'))
    results.append(_not_evaluated(STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT, NOT_PART))
    results.append(step_installed_identity_is_the_authorized_commit(installed_identity,
                                                                   authorized_commit))
    if results[-1]['state'] == PASS:
        results.append(step_modules_are_the_commit_blobs(repository, authorized_commit,
                                                         modules, module_prefix))
    else:
        results.append(_not_evaluated(STEP_MODULES_ARE_THE_COMMIT_BLOBS,
                                      'the_installation_is_not_the_authorized_one'))
    results.append(_not_evaluated(STEP_DISK_BLOBS_MATCH_THE_COMMIT, NOT_PART))
    digest = None
    if isinstance(authorized_candidate, dict):
        digest = candidate_contract_sha256(authorized_candidate)
    return _assemble(PHASE_POST_DEPLOY, canonical_ref, repository.resolve(canonical_ref),
                     authorized_commit, application_path, digest, source_tree, results)


def prove_checkout(repository, commit, files, *, canonical_ref=DEFAULT_CANONICAL_REF):
    """Step 1 and the blob row: is this checkout the commit it claims to be?

    The proof a build or a staging step makes about its own tree, with neither an
    installation nor a candidate document to hand.
    """
    _require(commit, 'commit')
    files = [(repo_path, filename) for repo_path, filename in files]
    _require(files, 'files')
    results = [step_commit_is_canonical(repository, commit, canonical_ref)]
    if results[0]['state'] == PASS:
        results.append(step_disk_blobs_match_the_commit(repository, commit, files))
    else:
        results.append(_not_evaluated(STEP_DISK_BLOBS_MATCH_THE_COMMIT,
                                      'commit_not_canonical'))
    results.extend(_tail(STEPS[2:5]))
    return _assemble(PHASE_CHECKOUT, canonical_ref, repository.resolve(canonical_ref), commit,
                     None, None, repository.tree_id(commit, ''), results)


# --------------------------------------------------------------------------- #
# the decision, as a pure function of a verdict
# --------------------------------------------------------------------------- #
def refused(verdict):
    """True when the proof did not pass. The one place a verdict's meaning is decided."""
    return verdict.get('verdict') != 'PASS'


def refusal_code(verdict):
    """The stable code a caller classifies on, or None when the proof passed."""
    refusal = verdict.get('refusal')
    return refusal.get('code') if isinstance(refusal, dict) else None


def drift_paths(verdict):
    """The repository paths a refusal named, in verdict order."""
    return [entry.get('path') for entry in verdict.get('drift', [])]


def not_evaluated_steps(verdict):
    """The steps this verdict did not evaluate, with their reasons.

    Read by the report and by the suite: a PASS that carries a step not evaluated for any
    reason other than NOT_PART would be a proof claiming more than it did.
    """
    return [(step['step'], (step.get('observed') or {}).get('reason'))
            for step in verdict.get('steps', []) if step['state'] == NOT_EVALUATED]
