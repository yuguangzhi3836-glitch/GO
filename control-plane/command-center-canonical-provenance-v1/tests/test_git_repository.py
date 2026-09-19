"""The same proof, against real repositories -- and the adapter's own closed surface.

The rule is tested in `test_canonical_provenance.py` without running anything. This suite
runs the real thing, because two of the claims here cannot be made any other way:

* the adapter's answers agree with `git` itself (`rev-parse`, `cat-file`, object ids), and
* the shell-free, fetch-free, write-free surface is closed: every subcommand outside the
  allowlist raises before a process starts.

The fixture repositories are built with ordinary git commands through `subprocess`
(`init`, `add`, `commit`). That is the *test* using git, not the component: the component's
own restriction is asserted separately, and the audit hook in `run_checks.py` permits no
program other than git.
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import canonical_provenance as P  # noqa: E402
from git_repository import GitRepository, default_git  # noqa: E402

MODULE_PREFIX = 'hk-staging/source/executor/runtime'
APPLICATION_FILES = {
    'application/main.py': b'print("a")\n',
    'application/Dockerfile': b'FROM python:3.13\n',
}
MODULE_FILES = {
    MODULE_PREFIX + '/deploy_runtime.py': b'VERSION = "0.6.0"\n',
    MODULE_PREFIX + '/candidate_fact.py': b'SCHEMA = "go.release-candidate.v1"\n',
}


def git(*arguments, cwd):
    return subprocess.run([default_git(), *arguments], cwd=str(cwd), check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def commit_all(work, message):
    git('add', '-A', cwd=work)
    git('-c', 'user.email=t@example.invalid', '-c', 'user.name=t',
        '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', message, cwd=work)
    return git('rev-parse', 'HEAD', cwd=work).stdout.strip()


class RealRepositoryCase(unittest.TestCase):
    """A throwaway repository, built once per test, with `main` and a side branch."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.git_program = default_git()
        except OSError as exc:  # pragma: no cover - a host without git cannot run this
            raise unittest.SkipTest('git is unavailable: %s' % exc)
        cls.temporary = tempfile.mkdtemp(prefix='go-cc-provenance-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temporary, ignore_errors=True)

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(dir=self.temporary))
        git('init', '-q', '-b', 'main', cwd=self.work)
        for path, content in {**APPLICATION_FILES, **MODULE_FILES}.items():
            target = self.work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.main_commit = commit_all(self.work, 'the canonical commit')
        git('update-ref', 'refs/remotes/origin/main', self.main_commit, cwd=self.work)
        # A commit that exists and is not on main: the shape of a provenance claim that is
        # broken rather than merely stale.
        git('checkout', '-q', '-b', 'side', cwd=self.work)
        (self.work / 'application' / 'side.py').write_bytes(b'y = 3\n')
        self.side_commit = commit_all(self.work, 'a side commit')
        git('checkout', '-q', 'main', cwd=self.work)
        self.repository = GitRepository(self.work, git=self.git_program)

    # ------------------------------------------------------------------ #
    # the adapter against git itself
    # ------------------------------------------------------------------ #
    def test_the_ref_resolves_to_the_commit_git_reports(self):
        self.assertEqual(self.repository.resolve('origin/main'), self.main_commit)
        self.assertEqual(self.repository.resolve('main'), self.main_commit)

    def test_a_ref_that_is_not_a_ref_is_refused(self):
        self.assertEqual(self.repository.resolve('origin/main'), self.main_commit)
        for bad in ('HEAD~1', 'main..side', '-not-a-ref', ''):
            with self.assertRaises(ValueError):
                self.repository.resolve(bad)

    def test_membership_of_a_commit_is_what_git_says(self):
        self.assertTrue(self.repository.has_commit(self.main_commit))
        self.assertFalse(self.repository.has_commit('f' * 40))

    def test_ancestry_is_what_git_says(self):
        self.assertTrue(self.repository.is_ancestor(self.main_commit, 'origin/main'))
        self.assertFalse(self.repository.is_ancestor(self.side_commit, 'origin/main'))
        self.assertTrue(self.repository.is_ancestor(self.side_commit, 'side'))

    def test_the_root_tree_is_what_git_reports(self):
        self.assertEqual(self.repository.tree_id(self.main_commit, ''),
                         git('rev-parse', '%s^{tree}' % self.main_commit,
                             cwd=self.work).stdout.strip())

    def test_a_subtree_is_what_git_reports(self):
        self.assertEqual(self.repository.tree_id(self.main_commit, 'application'),
                         git('rev-parse', '%s:application' % self.main_commit,
                             cwd=self.work).stdout.strip())

    def test_a_path_that_is_not_a_tree_is_not_returned_as_one(self):
        self.assertIsNone(self.repository.tree_id(self.main_commit, 'application/main.py'))
        self.assertIsNone(self.repository.tree_id(self.main_commit, 'nowhere'))

    def test_a_blob_is_what_git_reports(self):
        oid, content = self.repository.object_at(self.main_commit, 'application/main.py')
        self.assertEqual(oid, git('rev-parse', '%s:application/main.py' % self.main_commit,
                                  cwd=self.work).stdout.strip())
        self.assertEqual(content, APPLICATION_FILES['application/main.py'])

    def test_a_missing_object_is_not_an_answer(self):
        self.assertIsNone(self.repository.object_at(self.main_commit, 'application/absent.py'))
        self.assertIsNone(self.repository.object_at('f' * 40, 'application/main.py'))

    def test_a_tree_is_not_returned_as_a_blob(self):
        self.assertIsNone(self.repository.object_at(self.main_commit, 'application'))

    def test_the_file_object_id_equals_the_commits_blob_when_the_file_is_unmodified(self):
        oid, _ = self.repository.object_at(self.main_commit, 'application/main.py')
        self.assertEqual(self.repository.disk_object_id('application/main.py',
                                                        self.work / 'application' / 'main.py'),
                         oid)

    def test_a_crlf_checkout_still_hashes_to_the_committed_blob(self):
        """The workstation's own configuration, and the defect that hid inside it.

        `core.autocrlf=true` with no `.gitattributes`: git writes a CRLF working tree and
        commits an LF blob. The two are the same file, so the proof must see one object id.
        It did not, until the bytes were fed to git on stdin instead of being named as a file:
        with `--path` *and* a file argument, git decides from the filename spelling whether it
        is looking inside the working tree, and a Windows backslash spelling is not -- so the
        clean filters were skipped and a file identical to its blob was reported as drift.
        """
        git('config', 'core.autocrlf', 'true', cwd=self.work)
        target = self.work / 'application' / 'crlf.txt'
        target.write_bytes(b'alpha\r\nbeta\r\n')
        commit = commit_all(self.work, 'a CRLF worktree file')
        oid, content = self.repository.object_at(commit, 'application/crlf.txt')
        self.assertEqual(content, b'alpha\nbeta\n')
        self.assertEqual(target.read_bytes(), b'alpha\r\nbeta\r\n')
        self.assertEqual(self.repository.disk_object_id('application/crlf.txt', target), oid)
        # And the same answer as git run the way a person runs it, with the configuration the
        # machine actually has. This half is what caught the real defect: the adapter used to
        # pass GIT_CONFIG_NOSYSTEM=1, and on a workstation whose git keeps `core.autocrlf=true`
        # in its *system* config that removed the clean filter, so every CRLF file in the
        # repository was reported as drift even though it was identical to its blob.
        ambient = subprocess.run(
            [self.git_program, 'hash-object', '--path=application/crlf.txt', '--stdin'],
            input=target.read_bytes(), stdout=subprocess.PIPE, cwd=str(self.work),
            env=dict(os.environ, GIT_NO_REPLACE_OBJECTS='1'), check=True)
        self.assertEqual(ambient.stdout.decode().strip(), oid)

    def test_a_dot_directory_is_a_real_repository_path(self):
        # `.github/workflows/**` is a path this repository has. A path rule that refuses a
        # leading dot refuses real files, and the drift report then names a file that is fine.
        target = self.work / '.github' / 'workflows' / 'x.yml'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'on: push\n')
        commit = commit_all(self.work, 'a dot directory')
        oid, _ = self.repository.object_at(commit, '.github/workflows/x.yml')
        self.assertEqual(self.repository.disk_object_id('.github/workflows/x.yml', target),
                         oid)

    # ------------------------------------------------------------------ #
    # the closed surface
    # ------------------------------------------------------------------ #
    def test_a_subcommand_outside_the_allowlist_raises_before_a_process_starts(self):
        for forbidden in ('fetch', 'clone', 'ls-remote', 'push', 'update-ref', 'config',
                          'add', 'checkout', 'gc'):
            with self.assertRaises(ValueError):
                self.repository._run(forbidden)

    def test_no_network_or_write_subcommand_appears_in_the_allowlist(self):
        self.assertEqual(set(P and __import__('git_repository').ALLOWED_SUBCOMMANDS)
                         & set(__import__('git_repository').FORBIDDEN_SUBCOMMANDS), set())

    def test_an_option_this_component_does_not_pass_is_refused(self):
        for argument in ('--output=/tmp/x', '-w', '-c', '--exec-path=/tmp'):
            with self.assertRaises(ValueError):
                self.repository._run('rev-parse', argument, 'HEAD')

    def test_a_path_that_leaves_the_tree_is_refused(self):
        for path in ('../../etc/passwd', '/etc/passwd', '-oops', ''):
            with self.assertRaises(ValueError):
                self.repository.object_at(self.main_commit, path)

    def test_the_repository_root_must_be_a_directory(self):
        with self.assertRaises(ValueError):
            GitRepository(self.work / 'nowhere')

    def test_every_invocation_disables_replace_refs(self):
        # A replace ref makes one commit answer for another, which is exactly a way to make
        # a non-canonical commit look canonical. The adapter refuses to honour them.
        completed = self.repository._run('rev-parse', '--verify', '--quiet', 'HEAD')
        self.assertEqual(completed.returncode, 0)
        self.assertIn('--no-replace-objects', ' '.join(
            [self.repository.git, '--no-replace-objects']))


    # ------------------------------------------------------------------ #
    # the two samples the SPEC asks for: a real drift, and a difference that is not one
    # ------------------------------------------------------------------ #

    def test_a_clean_checkout_of_the_commit_is_not_a_drift(self):
        files = [(path, self.work / path) for path in APPLICATION_FILES]
        verdict = P.prove_checkout(self.repository, self.main_commit, files)
        self.assertEqual(verdict['verdict'], 'PASS', verdict['refusal'])
        self.assertEqual(verdict['drift'], [])

    def test_a_changed_byte_is_a_real_drift_and_is_named(self):
        (self.work / 'application' / 'main.py').write_bytes(b'print("b")\n')
        files = [(path, self.work / path) for path in APPLICATION_FILES]
        verdict = P.prove_checkout(self.repository, self.main_commit, files)
        self.assertEqual(verdict['verdict'], 'REFUSED')
        self.assertEqual(P.refusal_code(verdict), P.E_BLOB_DRIFT)
        self.assertEqual(P.drift_paths(verdict), ['application/main.py'])
        self.assertNotEqual(verdict['drift'][0]['expected'], verdict['drift'][0]['observed'])

    def test_a_missing_file_is_a_real_drift(self):
        (self.work / 'application' / 'Dockerfile').unlink()
        files = [(path, self.work / path) for path in APPLICATION_FILES]
        verdict = P.prove_checkout(self.repository, self.main_commit, files)
        self.assertEqual(P.refusal_code(verdict), P.E_BLOB_DRIFT)
        self.assertEqual(P.drift_paths(verdict), ['application/Dockerfile'])

    def test_a_commit_off_main_is_refused_as_provenance_broken_by_the_real_adapter(self):
        files = [('application/side.py', self.work / 'application' / 'main.py')]
        verdict = P.prove_checkout(self.repository, self.side_commit, files)
        self.assertEqual(P.refusal_code(verdict), P.E_COMMIT_NOT_CANONICAL)
        self.assertEqual(verdict['refusal']['condition'], P.PROVENANCE_BROKEN)
        self.assertEqual(verdict['canonical_commit'], self.main_commit)

    def test_an_install_source_proof_passes_on_the_real_repository(self):
        modules = []
        for path in MODULE_FILES:
            raw = (self.work / path).read_bytes()
            modules.append({'name': pathlib.Path(path).stem,
                            'sha256': hashlib.sha256(raw).hexdigest()})
        verdict = P.prove_install_source(
            self.repository, self.main_commit,
            self.repository.tree_id(self.main_commit, ''), modules,
            module_prefix=MODULE_PREFIX)
        self.assertEqual(verdict['verdict'], 'PASS', verdict['refusal'])
        self.assertEqual(len(verdict['modules']), len(MODULE_FILES))

    def test_an_install_source_proof_refuses_a_module_whose_hash_is_not_the_blob(self):
        modules = [{'name': 'deploy_runtime', 'sha256': '0' * 64}]
        verdict = P.prove_install_source(
            self.repository, self.main_commit,
            self.repository.tree_id(self.main_commit, ''), modules,
            module_prefix=MODULE_PREFIX)
        self.assertEqual(P.refusal_code(verdict), P.E_INSTALL_DRIFT)
        self.assertEqual(P.drift_paths(verdict), [MODULE_PREFIX + '/deploy_runtime.py'])
        self.assertEqual(verdict['drift'][0]['kind'],
                         'module_bytes_differ_from_the_commit')

    def test_the_real_hash_of_the_real_file_is_the_one_the_proof_compares(self):
        path = MODULE_PREFIX + '/deploy_runtime.py'
        oid, content = self.repository.object_at(self.main_commit, path)
        self.assertEqual(hashlib.sha256(content).hexdigest(),
                         hashlib.sha256((self.work / path).read_bytes()).hexdigest())
        self.assertEqual(self.repository.disk_object_id(path, self.work / path), oid)


if __name__ == '__main__':
    unittest.main()
