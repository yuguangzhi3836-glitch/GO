"""The canonical provenance proof, run against a repository that starts no process.

The real adapter (`git_repository.py`) is exercised in `test_git_repository.py`, against real
repositories. This suite is about the *rule*: does each of the six steps of section 7.3
refuse what it should refuse, pass what it should pass, stop when it should stop, and list
what it should list. A rule tested only through a subprocess is a rule entangled with its
environment; here the repository is six dictionaries.

The in-memory repository computes object ids the way git does -- sha1 over
`"<type> <len>\\0" + content` -- so a verdict produced here and one produced by the real
adapter are the same shape and the same identifiers.
"""
import hashlib
import importlib
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import canonical_provenance as P  # noqa: E402

CONTRACT = ROOT / 'contracts' / 'canonical_source_invariant_v1.schema.json'

MAIN = 'a' * 40
OTHER = 'b' * 40
OFF_MAIN = 'c' * 40
UNKNOWN = 'd' * 40

CANDIDATE_SCHEMA = 'go.release-candidate.v1'
ARTIFACT = 'sha256:' + '1' * 64
OTHER_ARTIFACT = 'sha256:' + '2' * 64

MODULE_PREFIX = 'hk-staging/source/executor/runtime'


def object_id(kind, raw):
    return hashlib.sha1(b'%s %d\0' % (kind.encode('ascii'), len(raw)) + raw).hexdigest()


def subtrees(files):
    """The tree ids of a commit: its own, and one per top-level directory."""
    out = {'': object_id('tree', b''.join(
        sorted(('%s\0%s' % (path, object_id('blob', content))).encode('ascii')
               for path, content in files.items())))}
    for prefix in sorted({path.split('/', 1)[0] for path in files if '/' in path}):
        body = b''.join(sorted(
            ('%s\0%s' % (path, object_id('blob', content))).encode('ascii')
            for path, content in files.items() if path.startswith(prefix + '/')))
        out[prefix] = object_id('tree', body)
    return out


class MemoryRepository(P.Repository):
    """A repository the proof can be run against without running anything.

    `disk` is the working tree, which is a different thing from the object database: the
    drift this proof exists to find lives exactly in the gap between the two.
    """

    def __init__(self):
        self.refs = {}
        self.commits = {}
        self.trees = {}
        self.ancestors = {}
        self.disk = {}
        self.asked = []

    def add_commit(self, commit, files, ancestors=()):
        self.commits[commit] = dict(files)
        self.trees[commit] = subtrees(files)
        self.ancestors[commit] = set(ancestors) | {commit}
        return commit

    def set_ref(self, ref, commit):
        self.refs[ref] = commit
        return commit

    def resolve(self, ref):
        self.asked.append(('resolve', ref))
        return self.refs.get(ref)

    def has_commit(self, commit):
        return commit in self.commits

    def is_ancestor(self, commit, ref):
        self.asked.append(('is_ancestor', commit, ref))
        target = self.refs.get(ref)
        return target is not None and commit in self.ancestors.get(target, set())

    def tree_id(self, commit, path):
        if commit not in self.commits:
            return None
        return self.trees[commit].get(path or '')

    def object_at(self, commit, path):
        files = self.commits.get(commit)
        if not files or path not in files:
            return None
        return object_id('blob', files[path]), files[path]

    def disk_object_id(self, repo_path, filename):
        if repo_path not in self.disk:
            raise OSError('file_not_readable')
        return object_id('blob', self.disk[repo_path])


APPLICATION_FILES = {
    'application/main.py': b'print("a")\n',
    'application/Dockerfile': b'FROM python:3.13\n',
    'deploy/hk-staging/docker-compose.business-runtime.yml': b'services: {}\n',
}

MODULE_FILES = {
    MODULE_PREFIX + '/' + name + '.py': (name + ' = 1\n').encode('ascii')
    for name in ('install_fact', 'deploy_runtime', 'rollback_runtime', 'candidate_fact',
                 'candidate_source', 'migration_guard', 'collector_runtime', 'canary_runtime',
                 'artifact_runtime')
}


def repository_with_main():
    """`main` holds the application tree and the runtime modules; a second commit does not."""
    repository = MemoryRepository()
    repository.add_commit(MAIN, {**APPLICATION_FILES, **MODULE_FILES})
    repository.add_commit(OTHER, {**APPLICATION_FILES, **MODULE_FILES,
                                  'application/extra.py': b'x = 2\n'},
                          ancestors=[MAIN])
    repository.add_commit(OFF_MAIN, {'application/side.py': b'y = 3\n'})
    repository.set_ref('origin/main', OTHER)
    return repository


def canonical_tree(repository, commit=OTHER, path='application'):
    return repository.tree_id(commit, path)


def candidate_fact(commit=OTHER, tree=None, artifact=ARTIFACT):
    return {
        'schema': CANDIDATE_SCHEMA,
        'candidate_id': 'depth48-ordered-repairs',
        'source_repository': P.CANDIDATE_REPOSITORY,
        'source_commit': commit,
        'application_tree': tree,
        'source_fingerprint': '9' * 64,
        'migration_head': '0133_flight_change_plan',
        'migration_required': False,
        'build_definition': {'profile': 'go-application-python-v1',
                             'dockerfile': 'Dockerfile.go-application-python-v2'},
        'artifact_digest': artifact,
        'required_services': ['api'],
        'test_result_identity': {'action_id': 'HK_STAGING_TEST_PR'},
        'rollback_relation': {'relation': 'NO_PREVIOUS_KNOWN_GOOD',
                              'previous_known_good_image_id': None},
    }


def signed_result(built=ARTIFACT):
    return {'action_id': 'HK_STAGING_TEST_PR', 'status': 'SUCCESS', 'built_image_id': built}


def modules_from(repository, commit=OTHER, prefix=MODULE_PREFIX):
    out = []
    for path, content in repository.commits[commit].items():
        if path.startswith(prefix + '/'):
            out.append({'name': path[len(prefix) + 1:-3],
                        'version': 'test',
                        'sha256': hashlib.sha256(content).hexdigest()})
    return sorted(out, key=lambda entry: entry['name'])


def step_of(verdict, name):
    for step in verdict['steps']:
        if step['step'] == name:
            return step
    raise AssertionError('no such step: %s' % name)


class SimulationTests(unittest.TestCase):
    """The simulation itself: if it is wrong, every claim below is wrong with it."""

    def test_the_simulation_computes_git_object_ids(self):
        self.assertEqual(object_id('blob', b'x\n'), P.blob_object_id(b'x\n'))

    def test_the_simulation_gives_the_same_tree_to_the_same_content(self):
        left = MemoryRepository()
        left.add_commit(MAIN, APPLICATION_FILES)
        right = MemoryRepository()
        right.add_commit(OTHER, APPLICATION_FILES)
        self.assertEqual(left.tree_id(MAIN, ''), right.tree_id(OTHER, ''))
        self.assertEqual(left.tree_id(MAIN, 'application'),
                         right.tree_id(OTHER, 'application'))

    def test_the_simulation_gives_a_different_tree_to_different_content(self):
        repository = repository_with_main()
        self.assertNotEqual(repository.tree_id(MAIN, 'application'),
                            repository.tree_id(OTHER, 'application'))
        self.assertNotEqual(repository.tree_id(MAIN, ''), repository.tree_id(OFF_MAIN, ''))

    def test_the_simulation_knows_what_is_on_main(self):
        repository = repository_with_main()
        self.assertTrue(repository.is_ancestor(MAIN, 'origin/main'))
        self.assertTrue(repository.is_ancestor(OTHER, 'origin/main'))
        self.assertFalse(repository.is_ancestor(OFF_MAIN, 'origin/main'))
        self.assertFalse(repository.has_commit(UNKNOWN))


class StepOneTests(unittest.TestCase):
    """A commit is canonical, or it is something else -- and which something else matters."""

    def setUp(self):
        self.repository = repository_with_main()

    def test_a_commit_on_main_passes(self):
        result = P.step_commit_is_canonical(self.repository, OTHER)
        self.assertEqual(result['state'], P.PASS)
        self.assertEqual(result['observed']['canonical_commit'], OTHER)

    def test_a_commit_off_main_is_provenance_broken_not_unresolvable(self):
        result = P.step_commit_is_canonical(self.repository, OFF_MAIN)
        self.assertEqual(result['state'], P.FAIL)
        self.assertEqual(result['code'], P.E_COMMIT_NOT_CANONICAL)
        self.assertEqual(result['condition'], P.PROVENANCE_BROKEN)

    def test_a_commit_that_does_not_exist_is_unresolvable(self):
        result = P.step_commit_is_canonical(self.repository, UNKNOWN)
        self.assertEqual(result['code'], P.E_COMMIT_NOT_CANONICAL)
        self.assertEqual(result['condition'], P.UNRESOLVABLE)

    def test_a_missing_canonical_ref_refuses_rather_than_passing(self):
        repository = MemoryRepository()
        repository.add_commit(MAIN, APPLICATION_FILES)
        result = P.step_commit_is_canonical(repository, MAIN, 'origin/main')
        self.assertEqual(result['state'], P.FAIL)
        self.assertEqual(result['condition'], P.UNRESOLVABLE)

    def test_a_malformed_commit_is_refused_before_any_lookup(self):
        result = P.step_commit_is_canonical(self.repository, 'main')
        self.assertEqual(result['code'], P.E_COMMIT_NOT_CANONICAL)
        self.assertEqual(result['condition'], P.UNRESOLVABLE)

    def test_the_ref_this_component_is_asked_about_is_the_ref_it_records(self):
        result = P.step_commit_is_canonical(self.repository, MAIN, 'origin/main')
        self.assertEqual(result['observed']['canonical_commit'],
                         self.repository.resolve('origin/main'))


class StepTwoTests(unittest.TestCase):
    """A real commit with someone else's tree is the shape a false revision claim takes."""

    def setUp(self):
        self.repository = repository_with_main()

    def test_the_commits_own_tree_passes(self):
        result = P.step_tree_matches(self.repository, OTHER,
                                     canonical_tree(self.repository), 'application')
        self.assertEqual(result['state'], P.PASS)

    def test_another_commits_tree_is_drift(self):
        result = P.step_tree_matches(self.repository, OTHER,
                                     canonical_tree(self.repository, OFF_MAIN, ''),
                                     'application')
        self.assertEqual(result['code'], P.E_TREE_MISMATCH)
        self.assertEqual(result['condition'], P.DRIFT)
        self.assertEqual(result['expected'], {'declared_tree':
                                              canonical_tree(self.repository)})

    def test_a_tree_that_is_not_an_object_id_is_unresolvable(self):
        result = P.step_tree_matches(self.repository, OTHER, 'not-a-tree', 'application')
        self.assertEqual(result['code'], P.E_TREE_MISMATCH)
        self.assertEqual(result['condition'], P.UNRESOLVABLE)

    def test_a_path_the_commit_does_not_have_is_unresolvable(self):
        result = P.step_tree_matches(self.repository, OTHER, 'e' * 40, 'nowhere')
        self.assertEqual(result['code'], P.E_TREE_MISMATCH)
        self.assertEqual(result['condition'], P.UNRESOLVABLE)

    def test_the_whole_tree_is_what_no_path_means(self):
        whole = self.repository.tree_id(OTHER, '')
        self.assertEqual(P.step_tree_matches(self.repository, OTHER, whole, None)['state'],
                         P.PASS)
        self.assertEqual(P.step_tree_matches(self.repository, OTHER, whole,
                                            'application')['state'], P.FAIL)

    def test_a_path_that_cannot_be_addressed_is_a_programming_error(self):
        with self.assertRaises(P.ProvenanceError):
            P.step_tree_matches(self.repository, OTHER, 'e' * 40, '../../etc')


class StepThreeTests(unittest.TestCase):
    """Tested A, deploying B: the one thing a signed result is for."""

    def test_the_artifact_the_result_names_passes(self):
        result = P.step_artifact_matches_the_signed_result(candidate_fact(), signed_result())
        self.assertEqual(result['state'], P.PASS)

    def test_an_artifact_the_result_did_not_build_is_refused(self):
        result = P.step_artifact_matches_the_signed_result(
            candidate_fact(), signed_result(OTHER_ARTIFACT))
        self.assertEqual(result['code'], P.E_ARTIFACT_MISMATCH)
        self.assertEqual(result['condition'], P.DRIFT)
        self.assertEqual(result['observed']['built_image_id'], OTHER_ARTIFACT)

    def test_a_result_that_names_no_image_is_unresolvable(self):
        result = P.step_artifact_matches_the_signed_result(candidate_fact(), {})
        self.assertEqual(result['code'], P.E_ARTIFACT_MISMATCH)
        self.assertEqual(result['condition'], P.UNRESOLVABLE)

    def test_a_candidate_that_names_no_image_is_unresolvable(self):
        result = P.step_artifact_matches_the_signed_result(
            candidate_fact(artifact='latest'), signed_result())
        self.assertEqual(result['condition'], P.UNRESOLVABLE)


class StepFourTests(unittest.TestCase):
    """Running a canonical commit that is not the authorised one is its own condition."""

    def test_the_authorized_commit_passes(self):
        result = P.step_installed_identity_is_the_authorized_commit(
            {'source_commit': MAIN}, MAIN)
        self.assertEqual(result['state'], P.PASS)

    def test_another_canonical_commit_is_not_the_authorized_one(self):
        result = P.step_installed_identity_is_the_authorized_commit(
            {'source_commit': OTHER}, MAIN)
        self.assertEqual(result['code'], P.E_INSTALL_DRIFT)
        self.assertEqual(result['condition'], P.NOT_THE_AUTHORIZED_COMMIT)

    def test_an_identity_without_a_commit_is_unresolvable(self):
        result = P.step_installed_identity_is_the_authorized_commit({}, MAIN)
        self.assertEqual(result['code'], P.E_INSTALL_DRIFT)
        self.assertEqual(result['condition'], P.UNRESOLVABLE)

    def test_an_authorization_that_is_not_a_commit_is_a_programming_error(self):
        with self.assertRaises(P.ProvenanceError):
            P.step_installed_identity_is_the_authorized_commit({'source_commit': MAIN}, 'x')


class StepFiveTests(unittest.TestCase):
    """The complete list, not the first offender."""

    def setUp(self):
        self.repository = repository_with_main()

    def test_every_module_of_the_commit_passes(self):
        result = P.step_modules_are_the_commit_blobs(
            self.repository, OTHER, modules_from(self.repository), MODULE_PREFIX)
        self.assertEqual(result['state'], P.PASS)
        self.assertEqual(len(result['modules']), len(MODULE_FILES))

    def test_every_disagreeing_module_is_named(self):
        modules = modules_from(self.repository)
        modules[0] = dict(modules[0], sha256='0' * 64)
        modules[1] = dict(modules[1], sha256='0' * 64)
        result = P.step_modules_are_the_commit_blobs(self.repository, OTHER, modules,
                                                     MODULE_PREFIX)
        self.assertEqual(result['state'], P.FAIL)
        self.assertEqual(result['code'], P.E_INSTALL_DRIFT)
        self.assertEqual(len(result['drift']), 2)
        self.assertEqual(sorted(entry['name'] for entry in result['drift']),
                         sorted([modules[0]['name'], modules[1]['name']]))

    def test_a_module_the_commit_does_not_hold_is_named_and_has_no_expected_side(self):
        result = P.step_modules_are_the_commit_blobs(
            self.repository, OTHER, [{'name': 'not_a_runtime_module', 'sha256': '0' * 64}],
            MODULE_PREFIX)
        self.assertEqual(result['drift'][0]['kind'], 'module_absent_from_the_commit')
        self.assertIsNone(result['drift'][0]['observed'])
        self.assertEqual(result['drift'][0]['path'],
                         MODULE_PREFIX + '/not_a_runtime_module.py')

    def test_a_module_the_commit_holds_without_a_declared_hash_is_drift(self):
        result = P.step_modules_are_the_commit_blobs(
            self.repository, OTHER, [{'name': 'deploy_runtime'}], MODULE_PREFIX)
        self.assertEqual(result['state'], P.FAIL)
        self.assertEqual(result['drift'][0]['kind'], 'module_bytes_differ_from_the_commit')

    def test_the_module_path_is_derived_from_the_name_and_nothing_else(self):
        # A record that also carries a `path` cannot redirect the read: the path compared is
        # the one derived from the module's name under the prefix the caller declared.
        honest = modules_from(self.repository)[0]
        result = P.step_modules_are_the_commit_blobs(
            self.repository, OTHER,
            [dict(honest, path='/etc/passwd', file='../../etc/shadow')], MODULE_PREFIX)
        self.assertEqual(result['state'], P.PASS)
        self.assertEqual(result['modules'][0]['path'],
                         MODULE_PREFIX + '/' + honest['name'] + '.py')

    def test_a_module_name_that_cannot_be_addressed_is_a_programming_error(self):
        with self.assertRaises(P.ProvenanceError):
            P.step_modules_are_the_commit_blobs(self.repository, OTHER,
                                                [{'name': '../x', 'sha256': '0' * 64}],
                                                MODULE_PREFIX)


class BlobRowTests(unittest.TestCase):
    """A checkout, against the commit -- the drift a `sha256sum` never sees."""

    def setUp(self):
        self.repository = repository_with_main()

    def test_a_checkout_that_is_the_commit_passes(self):
        self.repository.disk = dict(self.repository.commits[OTHER])
        files = [(path, 'local:' + path) for path in self.repository.commits[OTHER]]
        result = P.step_disk_blobs_match_the_commit(self.repository, OTHER, files)
        self.assertEqual(result['state'], P.PASS)
        self.assertEqual(result['observed']['files'], len(files))

    def test_one_changed_byte_is_drift_and_is_named(self):
        self.repository.disk = dict(self.repository.commits[OTHER])
        self.repository.disk['application/main.py'] = b'print("b")\n'
        files = [('application/main.py', 'local:main'),
                 ('application/Dockerfile', 'local:dockerfile')]
        result = P.step_disk_blobs_match_the_commit(self.repository, OTHER, files)
        self.assertEqual(result['code'], P.E_BLOB_DRIFT)
        self.assertEqual([entry['path'] for entry in result['drift']],
                         ['application/main.py'])
        self.assertNotEqual(result['drift'][0]['expected'], result['drift'][0]['observed'])

    def test_a_file_the_checkout_does_not_have_is_drift_with_no_observed_side(self):
        self.repository.disk = {}
        result = P.step_disk_blobs_match_the_commit(
            self.repository, OTHER, [('application/main.py', 'local:missing')])
        self.assertEqual(result['code'], P.E_BLOB_DRIFT)
        self.assertIsNone(result['drift'][0]['observed'])

    def test_a_file_the_commit_does_not_hold_is_drift_with_no_expected_side(self):
        self.repository.disk = {'application/new.py': b'z = 4\n'}
        result = P.step_disk_blobs_match_the_commit(
            self.repository, OTHER, [('application/new.py', 'local:new')])
        self.assertIsNone(result['drift'][0]['expected'])
        self.assertIsNotNone(result['drift'][0]['observed'])


class CompositionTests(unittest.TestCase):
    """The compositions: ordering, stopping, and never claiming more than was proved."""

    def setUp(self):
        self.repository = repository_with_main()

    def test_a_canonical_candidate_with_its_signed_result_passes(self):
        candidate = candidate_fact(tree=canonical_tree(self.repository))
        verdict = P.prove_candidate(self.repository, candidate, signed_result())
        self.assertEqual(verdict['verdict'], P.PASS, verdict['refusal'])
        self.assertIsNone(verdict['refusal'])
        self.assertEqual(verdict['phase'], P.PHASE_PRE_DEPLOY)
        self.assertEqual(verdict['candidate_contract_sha256'],
                         P.candidate_contract_sha256(candidate))
        self.assertEqual(verdict['canonical_commit'], OTHER)

    def test_a_candidate_that_is_not_on_main_is_refused_at_step_one(self):
        candidate = candidate_fact(commit=OFF_MAIN, tree=canonical_tree(self.repository,
                                                                       OFF_MAIN, ''))
        verdict = P.prove_candidate(self.repository, candidate, signed_result())
        self.assertEqual(verdict['verdict'], 'REFUSED')
        self.assertEqual(P.refusal_code(verdict), P.E_COMMIT_NOT_CANONICAL)
        self.assertEqual(verdict['refusal']['condition'], P.PROVENANCE_BROKEN)

    def test_the_chain_stops_at_the_first_failure(self):
        candidate = candidate_fact(commit=OFF_MAIN, tree='e' * 40)
        verdict = P.prove_candidate(self.repository, candidate, signed_result(OTHER_ARTIFACT))
        self.assertEqual(verdict['refusal']['step'], P.STEP_COMMIT_IS_CANONICAL)
        self.assertEqual(step_of(verdict, P.STEP_APPLICATION_TREE_MATCHES)['state'],
                         P.NOT_EVALUATED)
        self.assertEqual(step_of(verdict, P.STEP_APPLICATION_TREE_MATCHES)['observed']
                         ['reason'], 'commit_not_canonical')
        # Step 3 does not consume step 1 or 2, so it is still evaluated and still reported:
        # the artifact disagreement must not be hidden behind the commit refusal.
        self.assertEqual(step_of(verdict, P.STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT)['state'],
                         P.FAIL)
        self.assertEqual([entry['code'] for entry in [verdict['refusal']]],
                         [P.E_COMMIT_NOT_CANONICAL])

    def test_every_step_of_a_verdict_is_present_and_in_order(self):
        verdict = P.prove_candidate(self.repository, candidate_fact(
            tree=canonical_tree(self.repository)), signed_result())
        self.assertEqual([step['step'] for step in verdict['steps']], list(P.STEPS))

    def test_a_pass_never_carries_a_step_that_was_not_evaluated_for_a_missing_input(self):
        verdict = P.prove_candidate(self.repository, candidate_fact(
            tree=canonical_tree(self.repository)), signed_result())
        self.assertEqual(verdict['verdict'], P.PASS)
        self.assertEqual({reason for _, reason in P.not_evaluated_steps(verdict)}, {P.NOT_PART})

    def test_an_absent_signed_result_is_a_programming_error_not_a_pass(self):
        with self.assertRaises(P.ProvenanceError):
            P.prove_candidate(self.repository, candidate_fact(
                tree=canonical_tree(self.repository)), None)

    def test_a_candidate_that_is_not_converged_has_no_verdict(self):
        broken = candidate_fact(tree=canonical_tree(self.repository))
        broken['migration_required'] = True
        with self.assertRaises(P.candidate_fact_module().CandidateFactError):
            P.prove_candidate(self.repository, broken, signed_result())

    def test_an_install_source_proof_covers_the_commit_the_tree_and_the_modules(self):
        verdict = P.prove_install_source(self.repository, OTHER,
                                         self.repository.tree_id(OTHER, ''),
                                         modules_from(self.repository),
                                         module_prefix=MODULE_PREFIX)
        self.assertEqual(verdict['verdict'], P.PASS, verdict['refusal'])
        self.assertEqual(verdict['phase'], P.PHASE_INSTALL_SOURCE)
        self.assertEqual(verdict['source_tree'], self.repository.tree_id(OTHER, ''))
        self.assertEqual(
            step_of(verdict, P.STEP_ARTIFACT_MATCHES_THE_SIGNED_RESULT)['observed']['reason'],
            P.NOT_PART)

    def test_an_install_source_proof_refuses_a_module_that_drifted(self):
        modules = modules_from(self.repository)
        modules[0] = dict(modules[0], sha256='0' * 64)
        verdict = P.prove_install_source(self.repository, OTHER,
                                         self.repository.tree_id(OTHER, ''),
                                         modules, module_prefix=MODULE_PREFIX)
        self.assertEqual(verdict['verdict'], 'REFUSED')
        self.assertEqual(P.refusal_code(verdict), P.E_INSTALL_DRIFT)
        self.assertEqual(len(verdict['drift']), 1)

    def test_an_install_source_proof_refuses_a_tree_that_is_not_the_commits(self):
        verdict = P.prove_install_source(self.repository, OTHER, 'f' * 40,
                                         modules_from(self.repository),
                                         module_prefix=MODULE_PREFIX)
        self.assertEqual(P.refusal_code(verdict), P.E_TREE_MISMATCH)
        self.assertEqual(verdict['refusal']['step'], P.STEP_APPLICATION_TREE_MATCHES)
        # The module comparison does not consume the declared tree -- it compares the
        # modules against the commit's blobs -- so it is still evaluated and still reported.
        self.assertEqual(step_of(verdict, P.STEP_MODULES_ARE_THE_COMMIT_BLOBS)['state'], P.PASS)

    def test_an_installation_proof_names_the_host_that_is_not_the_authorized_one(self):
        verdict = P.prove_installation(self.repository, MAIN, {'source_commit': OTHER},
                                       self.repository.tree_id(OTHER, ''),
                                       modules_from(self.repository),
                                       module_prefix=MODULE_PREFIX)
        self.assertEqual(P.refusal_code(verdict), P.E_INSTALL_DRIFT)
        self.assertEqual(verdict['refusal']['condition'], P.NOT_THE_AUTHORIZED_COMMIT)
        self.assertEqual(verdict['phase'], P.PHASE_POST_DEPLOY)

    def test_an_installation_proof_passes_and_carries_the_modules_it_checked(self):
        verdict = P.prove_installation(self.repository, OTHER, {'source_commit': OTHER},
                                       self.repository.tree_id(OTHER, ''),
                                       modules_from(self.repository),
                                       module_prefix=MODULE_PREFIX)
        self.assertEqual(verdict['verdict'], P.PASS, verdict['refusal'])
        self.assertEqual(len(verdict['modules']), len(MODULE_FILES))
        self.assertEqual(verdict['authorized_deploy_commit'], OTHER)

    def test_a_checkout_proof_reports_the_tree_it_was_checked_against(self):
        self.repository.disk = dict(self.repository.commits[OTHER])
        files = [('application/main.py', 'local:main')]
        verdict = P.prove_checkout(self.repository, OTHER, files)
        self.assertEqual(verdict['verdict'], P.PASS)
        self.assertEqual(verdict['source_tree'], self.repository.tree_id(OTHER, ''))
        self.assertEqual(verdict['phase'], P.PHASE_CHECKOUT)

    def test_a_checkout_proof_refuses_a_missing_file_list(self):
        with self.assertRaises(P.ProvenanceError):
            P.prove_checkout(self.repository, OTHER, [])

    def test_the_refusal_helpers_agree_with_the_verdict(self):
        verdict = P.prove_candidate(self.repository, candidate_fact(commit=OFF_MAIN,
                                                                   tree='e' * 40),
                                    signed_result(OTHER_ARTIFACT))
        self.assertTrue(P.refused(verdict))
        self.assertEqual(P.refusal_code(verdict), P.E_COMMIT_NOT_CANONICAL)
        self.assertEqual(P.drift_paths(verdict), [])
        passing = P.prove_candidate(self.repository, candidate_fact(
            tree=canonical_tree(self.repository)), signed_result())
        self.assertFalse(P.refused(passing))
        self.assertIsNone(P.refusal_code(passing))


class ContractTests(unittest.TestCase):
    """The document the component ships must be the one it implements."""

    def setUp(self):
        self.contract = json.loads(CONTRACT.read_text(encoding='utf-8'))

    def test_the_contract_declares_the_fields_a_verdict_carries(self):
        self.assertEqual(set(self.contract['required']), set(P._assemble(
            P.PHASE_CHECKOUT, 'origin/main', None, None, None, None, None,
            [P._not_evaluated(step, P.NOT_PART) for step in P.STEPS])))
        self.assertEqual(self.contract['$id'], P.SCHEMA)

    def test_the_contract_declares_exactly_the_implemented_codes(self):
        self.assertEqual(tuple(self.contract['x-go-refusals']['source']), P.CODES)
        self.assertEqual(tuple(self.contract['x-go-refusals']['conditions']), P.CONDITIONS)

    def test_the_contract_declares_exactly_the_implemented_steps(self):
        self.assertEqual(tuple(self.contract['x-go-steps']['order']), P.STEPS)

    def test_the_contract_grants_nothing(self):
        authority = self.contract['x-go-authority']
        self.assertEqual(sorted(key for key, value in authority.items() if value is True),
                         ['may_read_the_candidate_and_its_evidence',
                          'may_read_the_repository'])

    def test_the_verdict_set_is_closed(self):
        self.assertEqual(self.contract['properties']['verdict']['enum'], ['PASS', 'REFUSED'])

    def test_a_step_code_must_be_one_of_the_five(self):
        declared = self.contract['properties']['steps']['items']['properties']['code']['enum']
        self.assertEqual([code for code in declared if code], list(P.CODES))


class SingleImplementationTests(unittest.TestCase):
    """One candidate digest, one implementation, and not here."""

    def test_the_candidate_digest_is_imported_from_its_owner_component(self):
        self.assertTrue(P.CANDIDATE_FACT_PATH.endswith(
            os.path.join('control-plane', 'command-center-candidate-admission-v1',
                         'candidate_fact.py')))
        self.assertEqual(P.candidate_fact_module().CONTRACT_NAME,
                         'RELEASE_CANDIDATE_V1_CONVERGED')

    def test_the_digest_rule_is_not_reimplemented_in_this_component(self):
        source = (ROOT / 'canonical_provenance.py').read_text(encoding='utf-8')
        # The canonical byte form is `json.dumps(..., sort_keys=True, ...)`. A module that
        # never calls `json.dumps` cannot be a second implementation of it.
        self.assertNotIn('json.dumps', source)
        self.assertIn('candidate_contract_sha256', source)

    def test_the_digest_is_the_owner_components_value(self):
        candidate = candidate_fact(tree='f' * 40)
        self.assertEqual(P.candidate_contract_sha256(candidate),
                         P.candidate_fact_module().candidate_contract_sha256(candidate))

    def test_the_digest_does_not_depend_on_key_order(self):
        candidate = candidate_fact(tree='f' * 40)
        shuffled = dict(reversed(list(candidate.items())))
        self.assertEqual(P.candidate_contract_sha256(candidate),
                         P.candidate_contract_sha256(shuffled))

    def test_the_proof_module_loads_no_second_copy_of_anything(self):
        module = importlib.import_module('canonical_provenance')
        self.assertEqual(module.__file__, str(ROOT / 'canonical_provenance.py'))


if __name__ == '__main__':
    unittest.main()
