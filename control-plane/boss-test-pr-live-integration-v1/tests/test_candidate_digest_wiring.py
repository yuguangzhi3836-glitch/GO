"""CCV1-85 (WP-4A): the candidate digest from the Task to the Evidence, on Hong Kong's side.

What is proven here, in the order the deployment path resolves it:

* the agent refuses a DEPLOY Task whose candidate digest is absent, malformed, or
  accompanied by a field the contract does not define;
* the host loads the candidate fact that digest addresses from a root-owned store,
  under a policy that is exercised rather than assumed;
* the digest is **recomputed** on this host and must agree, so a legacy document cannot
  be promoted into a converged one by being placed at the right filename;
* the migration rule runs before any mutation, and every refusal in that chain leaves
  the runner untouched -- asserted against a recorder, not against an exception type;
* the Evidence the agent writes carries the digest the executor verified.

The store policy is POSIX (uid 0, mode bits, O_NOFOLLOW).  This workstation cannot grant
those, so the reader's syscalls are served by a shim whose stat results are the ones a
correct host would produce; the policy itself is exercised directly with the violating
stat results as well, which is the part a Windows run could otherwise never show.

Standard library only. No network, no Git, no Docker, no live Hong Kong contact.
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
RUNTIME = REPO / "hk-staging" / "source" / "executor" / "runtime"
AGENT_SOURCE = REPO / "hk-staging" / "source" / "agent"
AGENT_INSTALLED = ROOT / "hk-staging"
sys.path.insert(0, str(AGENT_SOURCE))
sys.path.insert(0, str(AGENT_INSTALLED))

from hk_agent import deployment_actions, transport  # noqa: E402

IMAGE = "sha256:" + "1" * 64
OTHER_IMAGE = "sha256:" + "2" * 64
PACKAGE = "3" * 64
HEAD = "0133_flight_change_plan"
OTHER_HEAD = "0135_some_other_head"


def load_runtime(name):
    loader = importlib.machinery.SourceFileLoader("under_test_" + name,
                                                  str(RUNTIME / (name + ".py")))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


candidate_fact = load_runtime("candidate_fact")
candidate_source = load_runtime("candidate_source")
migration_guard = load_runtime("migration_guard")
deploy_runtime = load_runtime("deploy_runtime")


def converged(**over):
    fact = {
        "schema": candidate_fact.SCHEMA,
        "candidate_id": "rc1-wp4a-vector",
        "source_repository": candidate_fact.CANDIDATE_REPOSITORY,
        "source_commit": "b" * 40,
        "application_tree": "c" * 40,
        "source_fingerprint": "d" * 64,
        "migration_head": HEAD,
        "migration_required": False,
        "build_definition": {
            "profile": "go-application-python-v1",
            "dockerfile": "Dockerfile.go-application-python-v2",
            "dockerfile_sha256": "f" * 64,
            "executor_version": "test-pr-v3",
            "builder_image_tag": "go-hotel:depth48-runtime-6d0fd905",
            "builder_image_id": "sha256:" + "4" * 64,
        },
        "artifact_digest": IMAGE,
        "required_services": ["api", "recovery-worker", "outbox-worker",
                              "mobile-push-receipt-worker", "reconciliation-worker",
                              "mobile-push-worker", "mobile-engagement-worker",
                              "judgment-worker"],
        "test_result_identity": {
            "action_id": "HK_STAGING_TEST_PR",
            "task_id": "go-boss-test-pr-99-wp4a",
            "evidence_id": "wp4a-evidence",
            "source_pr_number": "99",
            "source_commit_sha": "b" * 40,
            "artifact_digest": IMAGE,
            "executor_result": "TEST_PR_OK",
        },
        "rollback_relation": {"relation": "REPLACES_CURRENT_KNOWN_GOOD",
                              "previous_known_good_image_id": OTHER_IMAGE},
        "artifact_package": {"durability": "PROVEN", "package_sha256": PACKAGE},
    }
    fact.update(over)
    return fact


def digest_of(fact):
    return candidate_fact.candidate_contract_sha256(fact)


class OsShim:
    """`os`, with `lstat`/`fstat` answering as a correct host would.

    The reader's policy is about uid and mode bits, which this workstation cannot
    express for its own files, so the shim supplies stat results instead of weakening
    the policy.  Everything else -- open, read, close, path -- stays real.
    """

    def __init__(self, dir_mode=stat.S_IFDIR | 0o755, dir_uid=0,
                 file_mode=stat.S_IFREG | 0o400, file_uid=0, file_size=None):
        self.dir_mode, self.dir_uid = dir_mode, dir_uid
        self.file_mode, self.file_uid, self.file_size = file_mode, file_uid, file_size

    def __getattr__(self, name):
        return getattr(os, name)

    def lstat(self, path):
        if os.path.isdir(path):
            return types.SimpleNamespace(st_mode=self.dir_mode, st_uid=self.dir_uid)
        if self.file_size is not None:
            size = self.file_size
        else:
            size = os.path.getsize(path)
        return types.SimpleNamespace(st_mode=self.file_mode, st_uid=self.file_uid,
                                     st_size=size)

    def fstat(self, descriptor):
        size = self.file_size if self.file_size is not None else os.fstat(descriptor).st_size
        return types.SimpleNamespace(st_mode=self.file_mode, st_uid=self.file_uid,
                                     st_size=size)


class StoreCase(unittest.TestCase):
    """A store whose contents and policy the test decides."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = pathlib.Path(self.tmp.name) / "candidates-v1"
        self.store.mkdir()
        self.fact = converged()
        self.digest = digest_of(self.fact)
        self.write_fact(self.fact)

    def write_fact(self, document, name=None):
        path = self.store / ((name or digest_of(document)) + ".json")
        path.write_bytes(json.dumps(document, sort_keys=True).encode("utf-8"))
        return path

    def read(self, digest, shim=None, ):
        with patch.object(candidate_source, "CANDIDATE_DIR", str(self.store)), \
             patch.object(candidate_source, "os", shim or OsShim()):
            return candidate_source.load_candidate_fact(digest)


# --------------------------------------------------------------------------- #
# A. the Task contract
# --------------------------------------------------------------------------- #
class TaskParameterTests(unittest.TestCase):
    """The agent's DEPLOY contract, and the other actions' contracts, unchanged."""

    def params(self, **over):
        base = {"release_id": "r-1", "candidate_image_id": IMAGE,
                "candidate_package_sha256": PACKAGE,
                "expected_current_image_id": OTHER_IMAGE,
                "canary_evidence_id": "c-1", "approval_id": "a-1",
                "candidate_contract_sha256": "e" * 64}
        base.update(over)
        return base

    def test_a_well_formed_digest_is_accepted(self):
        validated = deployment_actions.validate("HK_STAGING_DEPLOY", self.params())
        self.assertEqual(validated["candidate_contract_sha256"], "e" * 64)

    def test_an_absent_digest_is_refused(self):
        params = self.params()
        params.pop("candidate_contract_sha256")
        with self.assertRaises(deployment_actions.Reject):
            deployment_actions.validate("HK_STAGING_DEPLOY", params)

    def test_a_malformed_digest_is_refused(self):
        for wrong in ("", "not-a-digest", "E" * 64, "e" * 63, "e" * 65, 0, None, True):
            with self.subTest(digest=wrong):
                with self.assertRaises(deployment_actions.Reject):
                    deployment_actions.validate("HK_STAGING_DEPLOY",
                                                self.params(candidate_contract_sha256=wrong))

    def test_an_unknown_extra_field_is_still_refused(self):
        for extra in ({"migration_required": False}, {"migration_head": HEAD},
                      {"topology": {"version": 2}}, {"candidate_body": {}}):
            with self.subTest(extra=sorted(extra)):
                with self.assertRaises(deployment_actions.Reject):
                    deployment_actions.validate("HK_STAGING_DEPLOY",
                                                self.params(**extra))

    def test_the_other_actions_did_not_grow_the_field(self):
        """The digest belongs to DEPLOY. A canary is not a candidate deployment."""
        self.assertEqual(set(deployment_actions.validate(
            "HK_STAGING_VERIFY", {"release_id": "r-1", "candidate_image_id": IMAGE,
                                  "expected_current_image_id": OTHER_IMAGE})),
            {"release_id", "candidate_image_id", "expected_current_image_id"})
        self.assertEqual(set(deployment_actions.validate(
            "HK_STAGING_CANARY", {"release_id": "r-1", "candidate_image_id": IMAGE,
                                  "candidate_package_sha256": PACKAGE,
                                  "expected_current_image_id": OTHER_IMAGE})),
            {"release_id", "candidate_image_id", "candidate_package_sha256",
             "expected_current_image_id"})
        self.assertEqual(set(deployment_actions.validate(
            "HK_STAGING_ROLLBACK", {"release_id": "r-1",
                                    "source_deploy_task_id": "t-1",
                                    "approval_id": "a-1"})),
            {"release_id", "source_deploy_task_id", "approval_id"})
        for action, params in (("HK_STAGING_VERIFY", {"release_id": "r-1",
                                                      "candidate_image_id": IMAGE,
                                                      "expected_current_image_id": OTHER_IMAGE,
                                                      "candidate_contract_sha256": "e" * 64}),):
            with self.subTest(action=action):
                with self.assertRaises(deployment_actions.Reject):
                    deployment_actions.validate(action, params)

    def test_the_argv_carries_the_digest_in_the_launchers_order(self):
        validated = deployment_actions.validate("HK_STAGING_DEPLOY", self.params())
        b = {"task_id": "t-1", "nonce": "n-1", "authority": "GO-COMMAND-CENTER",
             "canonical_sha256": "f" * 64}
        command = deployment_actions.argv("HK_STAGING_DEPLOY", validated, b)
        self.assertEqual(command[1], "deploy")
        flags = command[2::2]
        self.assertEqual(flags, ["--release-id", "--candidate-image-id",
                                 "--candidate-package-sha256",
                                 "--expected-current-image-id", "--canary-evidence-id",
                                 "--approval-id", "--candidate-contract-sha256",
                                 "--task-id", "--task-nonce", "--task-authority",
                                 "--task-canonical-sha256"])


# --------------------------------------------------------------------------- #
# B. the store, and its policy
# --------------------------------------------------------------------------- #
class StorePolicyTests(unittest.TestCase):
    """The rule is exercised directly, with the stat results a bad host would produce."""

    def info(self, mode, uid=0):
        return types.SimpleNamespace(st_mode=mode, st_uid=uid)

    def test_a_root_owned_read_only_file_is_acceptable(self):
        self.assertIsNone(candidate_source.file_violation(
            self.info(stat.S_IFREG | 0o400)))

    def test_anything_a_non_root_could_replace_is_not(self):
        """The rule is that nobody but root can *write* it.

        Being readable is not a failure: a candidate fact is not a secret, and the value
        it is checked against is already stated by the Task. Being writable by a group or
        by anyone is the failure, because then the document behind the digest can be
        replaced after it was reviewed.
        """
        violations = [self.info(stat.S_IFREG | 0o400, uid=1000),      # not root
                      self.info(stat.S_IFREG | 0o620),               # group writable
                      self.info(stat.S_IFREG | 0o606),               # world writable
                      self.info(stat.S_IFREG | 0o666),               # both
                      self.info(stat.S_IFLNK | 0o400),               # a link, not a file
                      self.info(stat.S_IFDIR | 0o700),               # not a file at all
                      self.info(stat.S_IFIFO | 0o600)]               # not a file at all
        for info in violations:
            with self.subTest(mode=oct(info.st_mode), uid=info.st_uid):
                self.assertEqual(candidate_source.file_violation(info),
                                 "E_CANDIDATE_STORE_UNTRUSTED")

    def test_a_readable_but_unwritable_file_is_acceptable(self):
        for mode in (0o400, 0o440, 0o444, 0o600, 0o644):
            with self.subTest(mode=oct(mode)):
                self.assertIsNone(candidate_source.file_violation(
                    self.info(stat.S_IFREG | mode)))

    def test_every_directory_on_the_way_down_is_held_to_the_rule(self):
        self.assertIsNone(candidate_source.directory_violation(
            self.info(stat.S_IFDIR | 0o755)))
        for info in (self.info(stat.S_IFDIR | 0o755, uid=1000),
                     self.info(stat.S_IFDIR | 0o775),
                     self.info(stat.S_IFDIR | 0o777),
                     self.info(stat.S_IFLNK | 0o755),
                     self.info(stat.S_IFREG | 0o755)):
            with self.subTest(mode=oct(info.st_mode), uid=info.st_uid):
                self.assertEqual(candidate_source.directory_violation(info),
                                 "E_CANDIDATE_STORE_UNTRUSTED")


class CandidateLookupTests(StoreCase):
    """B and C: the fact is found by content, and the digest is recomputed."""

    def test_the_digest_finds_its_fact_and_the_digest_is_recomputed(self):
        fact = self.read(self.digest)
        self.assertEqual(fact, self.fact)
        self.assertEqual(digest_of(fact), self.digest)

    def test_a_missing_file_refuses(self):
        with self.assertRaises(candidate_source.Reject) as caught:
            self.read("a" * 64)
        self.assertEqual(str(caught.exception), "E_CANDIDATE_FACT_ABSENT")

    def test_an_absent_or_malformed_digest_refuses_before_any_read(self):
        for wrong in (None, "", "not-a-digest", "E" * 64, 7, True):
            with self.subTest(digest=wrong):
                with self.assertRaises(candidate_source.Reject) as caught:
                    self.read(wrong)
                self.assertEqual(str(caught.exception), "candidate_digest_absent")

    def test_a_file_whose_contents_do_not_match_its_name_refuses(self):
        """The filename is not the check; the recomputation is."""
        other = converged(candidate_id="rc1-wp4a-other")
        path = self.write_fact(other, name=self.digest)
        self.assertEqual(path.stem, self.digest)
        with self.assertRaises(candidate_source.Reject) as caught:
            self.read(self.digest)
        self.assertEqual(str(caught.exception), "candidate_digest_mismatch")

    def test_a_legacy_document_at_a_converged_digest_is_refused_by_name(self):
        """The confusion this exists to stop: a legacy document is not a converged fact.

        Its digest is computed over a different byte form, so no converged digest can
        address it -- and placing one at the right filename does not change that.
        """
        for schema in sorted(candidate_fact.LEGACY_SCHEMA_TO_KIND):
            with self.subTest(schema=schema):
                legacy = {"schema": schema, "candidate": {"repository": "r"}}
                self.write_fact(legacy, name=self.digest)
                with self.assertRaises(candidate_source.Reject) as caught:
                    self.read(self.digest)
                self.assertTrue(
                    str(caught.exception).startswith("candidate_digest_legacy_not_converged:"),
                    str(caught.exception))

    def test_a_prohibited_condition_document_is_refused(self):
        broken = converged(migration_required=True)
        self.write_fact(broken, name=self.digest)
        with self.assertRaises(candidate_source.Reject) as caught:
            self.read(self.digest)
        self.assertEqual(str(caught.exception),
                         candidate_fact.E_DATABASE_MIGRATION_REQUIRED)

    def test_an_unreadable_store_refuses_rather_than_defaulting(self):
        for shim in (OsShim(dir_mode=stat.S_IFDIR | 0o777),
                     OsShim(dir_uid=1000),
                     OsShim(file_mode=stat.S_IFREG | 0o620),
                     OsShim(file_uid=1000),
                     OsShim(file_mode=stat.S_IFLNK | 0o400)):
            with self.subTest(shim=shim.dir_mode, uid=shim.dir_uid):
                with self.assertRaises(candidate_source.Reject) as caught:
                    self.read(self.digest, shim=shim)
                self.assertEqual(str(caught.exception), "E_CANDIDATE_STORE_UNTRUSTED")

    def test_an_oversized_document_is_refused(self):
        with self.assertRaises(candidate_source.Reject) as caught:
            self.read(self.digest, shim=OsShim(file_size=candidate_source.MAX_CANDIDATE_BYTES + 1))
        self.assertEqual(str(caught.exception), "E_CANDIDATE_STORE_UNTRUSTED")

    def test_the_module_it_uses_is_pinned_by_bytes(self):
        self.assertEqual(
            hashlib.sha256((RUNTIME / "candidate_fact.py").read_bytes()).hexdigest(),
            candidate_source.CANDIDATE_FACT_SHA256)

    def test_the_fact_must_agree_with_the_task_about_the_artifact(self):
        fact = self.read(self.digest)
        self.assertIs(candidate_source.require_same_artifact(fact, IMAGE, PACKAGE), fact)
        for image, package in ((OTHER_IMAGE, PACKAGE), (IMAGE, "9" * 64),
                               (OTHER_IMAGE, "9" * 64)):
            with self.subTest(image=image[:14], package=package[:6]):
                with self.assertRaises(candidate_source.Reject):
                    candidate_source.require_same_artifact(fact, image, package)


# --------------------------------------------------------------------------- #
# C. the environment graph
# --------------------------------------------------------------------------- #
class EnvironmentGraphTests(StoreCase):
    """D: what the host is on, and what happens when that cannot be established."""

    def _with_graph(self, document, shim=None, path=None):
        target = pathlib.Path(self.tmp.name) / "environment-graph-v1.json"
        if document is not None:
            target.write_bytes(json.dumps(document).encode("utf-8"))
        with patch.object(candidate_source, "ENVIRONMENT_GRAPH", str(target)), \
             patch.object(candidate_source, "os", shim or OsShim()):
            return candidate_source.environment_migration_head()

    def test_the_host_head_is_read(self):
        self.assertEqual(self._with_graph({"environment": "HK-STAGING-01",
                                           "migration_head": HEAD}), HEAD)

    def test_a_missing_unreadable_or_off_environment_graph_refuses_in_the_graph_code(self):
        for document in (None,
                         {},
                         {"environment": "HK-STAGING-02", "migration_head": HEAD},
                         {"environment": "HK-STAGING-01"},
                         {"environment": "HK-STAGING-01", "migration_head": ""},
                         {"environment": "HK-STAGING-01", "migration_head": 7}):
            with self.subTest(document=document):
                with self.assertRaises(candidate_source.Reject) as caught:
                    self._with_graph(document)
                self.assertEqual(str(caught.exception),
                                 candidate_source.E_DATABASE_MIGRATION_GRAPH_MISMATCH)


# --------------------------------------------------------------------------- #
# D + E. the guard, and the order it runs in
# --------------------------------------------------------------------------- #
class Recorder:
    """A runner that records any attempt to reach the host, and refuses nothing."""

    def __init__(self):
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        raise AssertionError("the deployment path reached the host: %r" % (argv,))


class MutationOrderTests(StoreCase):
    """E: every refusal in this chain ends before the runner is ever consulted.

    Asserting the exception type would not show that; asserting the recorder is empty
    does.  `run_deploy` is the function that mutates, so these tests call the real one
    with its two module loaders pointed at the modules under test.
    """

    def setUp(self):
        super().setUp()
        self.graph = pathlib.Path(self.tmp.name) / "environment-graph-v1.json"
        self.graph.write_bytes(json.dumps({"environment": "HK-STAGING-01",
                                           "migration_head": HEAD}).encode("utf-8"))
        self.runner = Recorder()

    def _run(self, digest, fact=None, graph_head=HEAD, image=IMAGE, package=PACKAGE):
        if fact is not None:
            self.write_fact(fact)
        self.graph.write_bytes(json.dumps({"environment": "HK-STAGING-01",
                                           "migration_head": graph_head}).encode("utf-8"))
        with patch.object(candidate_source, "CANDIDATE_DIR", str(self.store)), \
             patch.object(candidate_source, "ENVIRONMENT_GRAPH", str(self.graph)), \
             patch.object(candidate_source, "os", OsShim()), \
             patch.object(deploy_runtime, "_load_candidate_source",
                          lambda: candidate_source), \
             patch.object(deploy_runtime, "_load_migration_guard",
                          lambda: migration_guard):
            return deploy_runtime.run_deploy(
                "release-1", image, package, OTHER_IMAGE,
                {"task_id": "t-1", "nonce": "n-1", "authority": "GO-COMMAND-CENTER",
                 "canonical_sha256": "f" * 64},
                self.runner, None, None, digest)

    def test_a_well_formed_candidate_gets_past_both_gates(self):
        """The counterpart: these gates are not a blanket refusal.

        A valid candidate is loaded, bound to the artifact and admitted by the migration
        rule, so the refusal that follows comes from the *pre-existing* deploy precheck
        reading a host path this workstation does not have. That the refusal moved past
        both new gates is the finding; naming the later code would only be naming this
        workstation.
        """
        gate_codes = {candidate_source.E_DATABASE_MIGRATION_GRAPH_MISMATCH,
                      migration_guard.E_DATABASE_MIGRATION_REQUIRED,
                      migration_guard.E_DATABASE_MIGRATION_GRAPH_MISMATCH,
                      "candidate_digest_absent", "candidate_digest_mismatch",
                      "E_CANDIDATE_FACT_ABSENT", "E_CANDIDATE_STORE_UNTRUSTED",
                      "E_CANDIDATE_FACT_UNREADABLE", "E_DEPLOY_CANDIDATE_IMAGE",
                      "E_DEPLOY_CANDIDATE_PACKAGE"}
        with self.assertRaises(Exception) as caught:
            self._run(self.digest)
        failure = caught.exception
        self.assertNotIn(str(failure), gate_codes,
                         "a candidate that satisfies both gates was refused by one of "
                         "them: %s" % failure)
        # Past both gates the path continues into the pre-existing precheck, which on
        # this workstation stops at a host path that does not exist (an OSError on the
        # real host's compose file). Either way the failure is downstream of the gates,
        # which is what this test is about.
        self.assertIsInstance(failure, (OSError, deploy_runtime.Reject))
        self.assertEqual(self.runner.calls, [],
                         "the precheck reached the host on this platform after all")

    def _store(self, document, name):
        (self.store / (name + ".json")).write_bytes(
            json.dumps(document, sort_keys=True).encode("utf-8"))
        return name

    def refusals(self):
        """(label, digest, document or None, graph head, image, package, expected code).

        Each row is one way a deployment can be refused before it is a deployment. The
        document, when given, is filed under the digest the row passes, so the reader is
        reached rather than short-circuited by a missing file.
        """
        valid = converged()
        name = digest_of(valid)
        return [
            ("digest absent", None, None, HEAD, IMAGE, PACKAGE, "candidate_digest_absent"),
            ("digest malformed", "not-a-digest", None, HEAD, IMAGE, PACKAGE,
             "candidate_digest_absent"),
            ("fact missing", "a" * 64, None, HEAD, IMAGE, PACKAGE,
             "E_CANDIDATE_FACT_ABSENT"),
            ("fact digest mismatch", name, converged(candidate_id="rc1-other"), HEAD,
             IMAGE, PACKAGE, "candidate_digest_mismatch"),
            ("legacy document", name, {"schema": "go.hk-candidate-contract.v3"}, HEAD,
             IMAGE, PACKAGE, "candidate_digest_legacy_not_converged:LEGACY_V3"),
            ("migration required", name, converged(migration_required=True), HEAD,
             IMAGE, PACKAGE, "E_DATABASE_MIGRATION_REQUIRED"),
            ("graph mismatch", name, valid, OTHER_HEAD, IMAGE, PACKAGE,
             "E_DATABASE_MIGRATION_GRAPH_MISMATCH"),
            ("artifact disagreement", name, valid, HEAD, OTHER_IMAGE, PACKAGE,
             "E_DEPLOY_CANDIDATE_IMAGE"),
            ("package disagreement", name, valid, HEAD, IMAGE, "9" * 64,
             "E_DEPLOY_CANDIDATE_PACKAGE"),
        ]

    def test_every_refusal_happens_before_any_mutation(self):
        for label, digest, document, graph_head, image, package, expected in self.refusals():
            with self.subTest(case=label):
                self.runner.calls.clear()
                if document is not None:
                    self._store(document, digest)
                with self.assertRaises((candidate_source.Reject, migration_guard.Reject,
                                        deploy_runtime.Reject)) as caught:
                    self._run(digest, graph_head=graph_head, image=image, package=package)
                self.assertEqual(str(caught.exception), expected)
                self.assertEqual(self.runner.calls, [],
                                 "%s reached the host before it was refused" % label)

    def test_timeout_and_subprocess_failures_are_still_the_runtimes(self):
        """The two gates were inserted above the existing ones, not instead of them."""
        source = (RUNTIME / "deploy_runtime.py").read_text(encoding="utf-8")
        body = source[source.index("def run_deploy("):]
        self.assertIn("_precheck(runner", body)
        self.assertLess(body.index("guard.precheck("), body.index("_precheck(runner"))


# --------------------------------------------------------------------------- #
# F. the Evidence, and the two agent copies
# --------------------------------------------------------------------------- #
class EvidenceTests(unittest.TestCase):
    """F: what the agent writes, and that the installed agent is the reviewed agent."""

    def task(self, **over):
        task = {"schema_version": "1", "task_id": "go-boss-deploy-1", "nonce": "n-1",
                "issued_at": "2026-09-18T00:00:00Z", "expires_at": "2026-09-18T01:00:00Z",
                "authority": "GO-COMMAND-CENTER", "environment": "HK-STAGING-01",
                "action_id": "HK_STAGING_DEPLOY",
                "parameters": {"release_id": "r-1", "candidate_image_id": IMAGE,
                               "candidate_package_sha256": PACKAGE,
                               "expected_current_image_id": OTHER_IMAGE,
                               "canary_evidence_id": "c-1", "approval_id": "a-1",
                               "candidate_contract_sha256": "e" * 64},
                "signature": "0" * 32}
        task.update(over)
        return task

    def result(self, digest="e" * 64):
        return {"schema_version": "1", "executor_version": "0.5.0-candidate-digest",
                "action_id": "HK_STAGING_DEPLOY", "status": "SUCCESS",
                "release_id": "r-1", "candidate_image_id": IMAGE,
                "expected_current_image_id": OTHER_IMAGE, "result": "DEPLOY_OK",
                "gate_results": {"all": "PASS"}, "deploy_record_schema_version": "2",
                "deploy_record_id": "a" * 64, "deploy_record_sha256": "b" * 64,
                "candidate_contract_sha256": digest}

    def test_new_deploy_evidence_carries_the_digest_the_task_carried(self):
        record = transport.evidence(self.task(), self.result())
        self.assertEqual(record["candidate_contract_sha256"], "e" * 64)

    def test_pending_is_forbidden_scope_and_the_rest_are_untouched(self):
        for name in ("time_authorization", "installed_identity", "execution_window"):
            self.assertNotIn(name, transport.evidence(self.task(), self.result()))

    def test_an_executor_that_omits_the_digest_is_refused(self):
        broken = self.result()
        broken.pop("candidate_contract_sha256")
        with self.assertRaises(transport.Reject):
            transport.evidence(self.task(), broken)

    def test_an_executor_result_naming_another_candidate_is_refused(self):
        with self.assertRaises(deployment_actions.Reject):
            deployment_actions.parse_executor_output(
                json.dumps(self.result(digest="9" * 64), separators=(",", ":")),
                "HK_STAGING_DEPLOY",
                deployment_actions.validate("HK_STAGING_DEPLOY", self.task()["parameters"]))

    def test_both_agent_copies_agree_on_the_contract_this_round_changed(self):
        """Two copies of the agent exist; they are not the same file, and must not drift.

        `install/install-hk-agent.sh` deploys
        `control-plane/boss-test-pr-live-integration-v1/hk-staging/hk_agent/**` -- that is
        the canonical, complete agent, and the one the Hong Kong suite exercises.  The
        Command Center's own tests import `hk-staging/source/agent/hk_agent/**`, which is
        the same code for `core.py` and `deployment_actions.py` but a *much smaller*
        `transport.py`: the failure-evidence capability lives only in the canonical copy.

        So byte equality is not the property, and asserting it would be wrong.  The
        property that matters is that whatever this round changed is the same in both:
        the agent version, and the DEPLOY requirement and record field.  Editing one copy
        and not the other is a silent no-op on the host, and this is the test that says so.
        """
        facts = (
            'VERSION = "0.5.8-candidate-digest"',
            '"deploy_record_schema_version","deploy_record_id","deploy_record_sha256","candidate_contract_sha256"',
            '"candidate_contract_sha256":result["candidate_contract_sha256"]',
        )
        copies = {"installed (canonical)": ROOT / "hk-staging" / "hk_agent" / "transport.py",
                  "reviewed (hk-staging/source)": REPO / "hk-staging" / "source" / "agent"
                  / "hk_agent" / "transport.py"}
        for label, path in copies.items():
            text = path.read_text(encoding="utf-8")
            for fact in facts:
                with self.subTest(copy=label, fact=fact[:40]):
                    self.assertIn(fact, text, "%s drifted from the contract" % label)

    def test_the_two_agent_copies_are_otherwise_the_modules_they_claim_to_be(self):
        """The parts that *are* shared stay shared, so a divergence is visible."""
        for name in ("core.py", "deployment_actions.py"):
            with self.subTest(module=name):
                a = (REPO / "hk-staging" / "source" / "agent" / "hk_agent" / name).read_bytes()
                b = (ROOT / "hk-staging" / "hk_agent" / name).read_bytes()
                self.assertEqual(a.replace(b"\r\n", b"\n"), b.replace(b"\r\n", b"\n"),
                                 "%s differs between the two agent trees" % name)


if __name__ == "__main__":
    unittest.main()
