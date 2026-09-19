"""The one way this component talks to a repository: local, read-only git plumbing.

CCV1-88 (WP-6). `canonical_provenance.py` states the proof; this module is the only place
that runs a program to answer it. Everything about *how* it runs is chosen so that the
verifier's inputs can be stated exactly:

* **One program, and a closed list of subcommands.** `ALLOWED_SUBCOMMANDS` is the complete
  set. Anything else -- `fetch`, `clone`, `ls-remote`, `push`, `update-ref`, `config`, any
  porcelain that can write -- raises `ProvenanceError` before a process is started. A
  verifier that could fetch would be a verifier that can choose its own reference, and one
  that could write would be a thing that changes the evidence it is examining.

* **No shell.** argv is a list built here; a repository path or a ref never reaches a shell.

* **No replace refs.** `--no-replace-objects` is passed to every invocation. A replace ref
  is a local alias that makes one commit answer for another; with it in play, "this commit
  is on main" could be true of a commit that is not.

* **No terminal, no optional locks, no locale.** `GIT_TERMINAL_PROMPT=0`,
  `GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C`: the answer does not depend on who asked it.

* **Argument injection is refused, not escaped.** A ref or a path beginning with `-` is
  refused here (`_checked`), because `git rev-parse --verify --quiet -- <something>` is
  still a way to reach an option this module did not intend to offer.

Nothing here writes: no `-w`, no index change, no ref update. `hash-object` is called
without `-w` on purpose -- the object id of a file is computable without storing it.
"""
import os
import re
import shutil
import subprocess

# The complete set of subcommands this component may run. Read-only plumbing only.
ALLOWED_SUBCOMMANDS = (
    'rev-parse',    # resolve a ref, a commit's tree, or commit:path
    'cat-file',     # object type, existence and content
    'merge-base',   # --is-ancestor, the canonality question itself
    'hash-object',  # the object id git would record for a file (never with -w)
    'symbolic-ref', # which branch HEAD is on, for reporting
    'show-ref',     # which refs exist, for reporting
)

# The complete set of option arguments this component passes. `--path=` is validated
# separately because it carries a value. A flag that is not here is not passed, and a caller
# cannot introduce one: `--output`, `-w` and friends are exactly the options that would turn
# a read into a write. The list is exactly what the call sites use -- an unused permission is
# a permission nobody is watching.
ALLOWED_FLAGS = (
    '-e',            # cat-file: does the object exist
    '-t',            # cat-file: what type is it
    '--batch',       # cat-file: id, type and content in one answer
    '--is-ancestor', # merge-base: the canonality question
    '--quiet',       # no output, answer by exit code
    '--stdin',       # hash-object: hash bytes handed to it, with --path applying the filters
    '--verify',      # rev-parse: refuse anything that is not one object
)

# Named so that the reason is auditable and so a test can assert none of these is ever
# reachable. The list is documentation as much as policy: it is what "this verifier cannot
# reach the network or move a ref" means, spelled out.
FORBIDDEN_SUBCOMMANDS = (
    'fetch', 'clone', 'pull', 'push', 'ls-remote', 'archive', 'submodule',
    'remote', 'config', 'gc', 'fsck', 'repack', 'prune', 'update-ref', 'update-index',
    'commit', 'reset', 'checkout', 'switch', 'restore', 'clean', 'stash', 'merge',
    'rebase', 'cherry-pick', 'revert', 'apply', 'am', 'add', 'rm', 'mv', 'worktree',
    'init', 'filter-branch', 'replace', 'notes', 'tag', 'branch', 'send-pack',
    'receive-pack', 'upload-pack', 'daemon',
)

OBJECT_ID = re.compile(r'^[0-9a-f]{40}$')
COMMIT = re.compile(r'^[0-9a-f]{40}$')

# The path and ref rules belong to the proof, not to this adapter: two implementations of
# "what a repository path may look like" would be two things to keep in step, and this
# component exists because that kind of copy drifts. They are imported under the names this
# module's call sites use.
from canonical_provenance import REPO_PATH as PATHSPEC, REF  # noqa: E402

DEFAULT_TIMEOUT = 60


class _GitError(RuntimeError):
    """git failed in a way that is not an answer to the question asked."""


class GitRepository:
    """`canonical_provenance.Repository` over a local clone, via read-only git plumbing.

    The repository is never fetched, never written and never asked a question whose answer
    could change: `resolve` on a stale `origin/main` returns the stale commit, and the
    verdict records it, so a stale reference is visible in the result rather than hidden
    inside it.
    """

    def __init__(self, root, git=None, timeout=DEFAULT_TIMEOUT):
        self.root = os.path.abspath(os.fspath(root))
        if not os.path.isdir(self.root):
            raise ValueError('repository_not_a_directory')
        self.timeout = timeout
        self.git = git or default_git()

    # ------------------------------------------------------------------ #
    # the single program boundary
    # ------------------------------------------------------------------ #
    def _checked(self, *values):
        for value in values:
            if not isinstance(value, str) or not value or value.startswith('-'):
                raise ValueError('unsafe_git_argument')
        return values

    def _run(self, subcommand, *arguments, stdin=None, check=False):
        if subcommand not in ALLOWED_SUBCOMMANDS:
            raise ValueError('subcommand_not_allowed:%s' % subcommand)
        for argument in arguments:
            if not isinstance(argument, str) or not argument:
                raise ValueError('unsafe_git_argument')
            if argument.startswith('-') and argument not in ALLOWED_FLAGS \
                    and not argument.startswith('--path='):
                # `--` is in ALLOWED_FLAGS and everything else that looks like an option is
                # refused: an option this module did not plan to pass is a question it did
                # not plan to ask.
                raise ValueError('unsafe_git_argument')
        # The environment is narrowed, but not to the point of changing the answer.
        #
        # WHAT IS PASSED: PATH, so the same git is found; the home variables, so the global
        # configuration is read; the four hardening variables below.
        #
        # WHAT IS NOT PASSED: GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY,
        # GIT_ALTERNATE_OBJECT_DIRECTORIES and the GIT_CONFIG_* redirects. Those do not
        # describe a repository, they *choose* one -- and "the rules of the repository I was
        # pointed at" is the whole question this adapter answers.
        #
        # WHAT IS NOT DISABLED: the system configuration. `GIT_CONFIG_NOSYSTEM=1` was tried
        # here as hardening and removed the `core.autocrlf=true` that PortableGit sets in its
        # system gitconfig -- so the clean filter stopped running, a CRLF working tree stopped
        # being the LF blob it actually is, and every file in the repository was reported as
        # drift. Changing which configuration is read does not make a proof stricter, it makes
        # it a proof of something else. (CCV1-88, found by the false-drift sample.)
        #
        # The consequence is stated rather than hidden: git applies the clean filters this
        # repository's configuration and attributes define, and a filter is a program. A
        # caller that points this component at a hostile clone gives that clone's filters the
        # same footing they already have for `git status`.
        environment = {
            'PATH': os.environ.get('PATH', ''),
            'GIT_TERMINAL_PROMPT': '0',
            'GIT_OPTIONAL_LOCKS': '0',
            'GIT_NO_REPLACE_OBJECTS': '1',
            'LC_ALL': 'C',
        }
        for name in ('HOME', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH'):
            if name in os.environ:
                environment[name] = os.environ[name]
        argv = [self.git, '--no-replace-objects', '-C', self.root, subcommand, *arguments]
        completed = subprocess.run(argv, input=stdin, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment,
                                   timeout=self.timeout)
        if check and completed.returncode != 0:
            raise _GitError('git %s failed: %s' % (subcommand,
                                                   completed.stderr.decode('utf-8', 'replace')[:200]))
        return completed

    def _text(self, subcommand, *arguments):
        completed = self._run(subcommand, *arguments)
        if completed.returncode != 0:
            return None
        return completed.stdout.decode('utf-8', 'replace').strip()

    # ------------------------------------------------------------------ #
    # the port
    # ------------------------------------------------------------------ #
    def resolve(self, ref):
        """The commit a ref names, or None.

        Only a ref this component may name. Pebbles like `HEAD~3` and ranges are refused:
        the point of a canonical ref is that it is one, fixed, nameable thing.
        """
        if not isinstance(ref, str) or not REF.fullmatch(ref):
            raise ValueError('ref_not_addressable')
        value = self._text('rev-parse', '--verify', '--quiet', '%s^{commit}' % ref)
        return value if value and COMMIT.fullmatch(value) else None

    def has_commit(self, commit):
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            raise ValueError('commit_not_addressable')
        # `cat-file -e` asks only whether the object is present, and answers by exit code.
        return self._run('cat-file', '-e', '%s^{commit}' % commit).returncode == 0

    def is_ancestor(self, commit, ref):
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            raise ValueError('commit_not_addressable')
        if not isinstance(ref, str) or not REF.fullmatch(ref):
            raise ValueError('ref_not_addressable')
        completed = self._run('merge-base', '--is-ancestor', commit, ref)
        if completed.returncode == 0:
            return True
        if completed.returncode == 1:
            return False
        raise _GitError('merge-base --is-ancestor could not be answered')

    def tree_id(self, commit, path):
        """The tree object at `path`; `path` of '' is the commit's own tree."""
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            raise ValueError('commit_not_addressable')
        if path == '':
            value = self._text('rev-parse', '--verify', '--quiet', '%s^{tree}' % commit)
            return value if value and OBJECT_ID.fullmatch(value) else None
        if not PATHSPEC.fullmatch(path):
            raise ValueError('path_not_addressable')
        kind = self._text('cat-file', '-t', '%s:%s' % (commit, path))
        if kind != 'tree':
            return None
        value = self._text('rev-parse', '--verify', '--quiet', '%s:%s' % (commit, path))
        return value if value and OBJECT_ID.fullmatch(value) else None

    def object_at(self, commit, path):
        """(object_id, content) for the blob at `path`, or None.

        One `cat-file --batch` process for one object: the batch protocol returns the object
        id, the type and the bytes together, so "what is at this path" is answered once
        rather than assembled from three calls that could disagree with each other.
        """
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            raise ValueError('commit_not_addressable')
        if not PATHSPEC.fullmatch(path or ''):
            raise ValueError('path_not_addressable')
        spec = '%s:%s' % (commit, path)
        completed = self._run('cat-file', '--batch', stdin=(spec + '\n').encode('utf-8'))
        if completed.returncode != 0:
            return None
        return _parse_batch(completed.stdout)

    def disk_object_id(self, repo_path, filename):
        """The object id git records for `filename` as if it lived at `repo_path`.

        The bytes are **fed to git on stdin**, not named as a file, and that is deliberate.
        `--path` is what applies the repository's clean filters, and with both `--path` and a
        file argument git decides from the filename whether it is looking at a file inside the
        working tree. On Windows a backslash spelling of an absolute path is not recognised as
        inside the tree, the clean filters are silently skipped, and a file that matches its
        blob exactly is reported as drift. Measured, not theorised: that is exactly what
        happened to `docs/canonical-baseline/CURRENT_CANDIDATE.json` against
        `origin/main:docs/canonical-baseline/CURRENT_CANDIDATE.json` (CCV1-88).

        Reading the bytes here and piping them removes the filename spelling from the answer
        entirely, which is the only version of this function that gives the same object id on
        both hosts. `-w` is deliberately absent: computing an object id must not store an
        object.
        """
        if not PATHSPEC.fullmatch(repo_path):
            raise ValueError('path_not_addressable')
        filename = os.fspath(filename)
        try:
            with open(filename, 'rb') as handle:
                raw = handle.read()
        except OSError as exc:
            raise OSError('file_not_readable:%s' % filename) from exc
        # `stdin` here is the *content*, which `_run` hands to `subprocess.run(input=...)` so
        # the child reads it from a pipe and then sees EOF. Passing a file object instead
        # leaves git waiting for a writer that never closes and the suite hanging -- measured,
        # not assumed (CCV1-88).
        completed = self._run('hash-object', '--path=%s' % repo_path, '--stdin', stdin=raw)
        if completed.returncode != 0:
            raise OSError('hash_object_failed')
        value = completed.stdout.decode('ascii', 'replace').strip()
        if not OBJECT_ID.fullmatch(value):
            raise OSError('hash_object_not_an_object_id')
        return value

    # ------------------------------------------------------------------ #
    # reporting
    # ------------------------------------------------------------------ #
    def head_ref(self):
        return self._text('symbolic-ref', '--quiet', 'HEAD')


def _parse_batch(raw):
    """Parse one `cat-file --batch` record: `<oid> <type> <size>\\n<content>\\n`.

    A missing object comes back as `<spec> missing`; anything that is not a blob is not an
    answer to the question `object_at` asks, so both return None.
    """
    header, _, body = raw.partition(b'\n')
    fields = header.decode('utf-8', 'replace').split(' ')
    if len(fields) != 3 or not OBJECT_ID.fullmatch(fields[0]):
        return None
    if fields[1] != 'blob':
        return None
    try:
        size = int(fields[2])
    except ValueError:
        return None
    if size < 0 or size > len(body) + 1:
        return None
    content = body[:size]
    if len(body) > size and body[size:size + 1] != b'\n':
        return None
    return fields[0], content


def default_git():
    """The git program to use: an explicit override, then PATH, then the usual absolute path.

    `GO_GIT` exists so a host with an unusual layout can say so without editing this file;
    the fallback is the absolute path the Command Center's own bridge uses.
    """
    candidate = os.environ.get('GO_GIT')
    if candidate:
        if not os.path.isfile(candidate):
            raise OSError('GO_GIT_does_not_exist')
        return candidate
    found = shutil.which('git')
    if found:
        return found
    if os.path.isfile('/usr/bin/git'):
        return '/usr/bin/git'
    raise OSError('git_not_found')
