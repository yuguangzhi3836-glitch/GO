"""WP-4's remaining item: the installation identity, host -> Evidence -> proof.

CCV1-82 CONTRACT SPEC 5.3 defines one block, `go.hk-installed-identity.v1`, and gives it
one producer: the host, reading the installation fact it has already verified.  Section
7.3 step 4 consumes it as the answer to "is this host running the authorised commit?".

Three ends are checked together here, because each end on its own is satisfied by a
different implementation:

* the executor (`go-hk-deployctl`) derives the block from the document
  `_verify_installation()` returned, so it cannot be produced without the verification;
* the agent checks the block's shape and carries it onto the signed Evidence, refusing a
  document whose block is missing or malformed;
* the Command Center's `CANONICAL_SOURCE_INVARIANT` step 4 reads it back, and refuses a
  host running a different commit -- including a canonical one it was not authorised for.

Nothing here re-implements the block: `install_fact.installed_identity()` is the only
implementation, and the middle of the chain is asserted to carry *its* output.

The executor is loaded from the repository as the extensionless file it is, the same way
the host loads it.  Standard library only.  No network, no Git, no Docker, no live contact.
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
EXECUTOR = REPO / "hk-staging" / "source" / "executor" / "go-hk-deployctl"
INSTALL_FACT = REPO / "hk-staging" / "source" / "executor" / "runtime" / "install_fact.py"

sys.path.insert(0, str(ROOT / "hk-staging"))
sys.path.insert(0, str(REPO / "control-plane" / "command-center-canonical-provenance-v1"))

from hk_agent import deployment_actions, transport  # noqa: E402
import canonical_provenance as P  # noqa: E402

IMAGE = "sha256:" + "1" * 64
INSTALLED_COMMIT = "9b932745" + "0" * 32
AUTHORIZED_COMMIT = INSTALLED_COMMIT
OTHER_CANONICAL_COMMIT = "d" * 40

IDENTITY = {"schema": "go.hk-installed-identity.v1", "installation_id": "install-20260919",
            "source_commit": INSTALLED_COMMIT, "launcher_version": "0.7.0-environment-lock",
            "launcher_sha256": "e" * 64, "runtime_digest": "d" * 64}

# A fact of the shape `install-hk-executor-facts.sh` writes.  Only six of these fields are
# the identity, which is the point: the block is a projection of a verified document, not a
# second document that could disagree with it.
FACT = {"schema": "go.hk-install-fact.v1", "installation_id": IDENTITY["installation_id"],
        "source_repository": "yuguangzhi3836-glitch/GO", "source_commit": INSTALLED_COMMIT,
        "source_tree": "a" * 40, "installed_at": "2026-09-19T00:00:00Z",
        "installer_identity": "chenzhenxi1-sudo",
        "launcher_version": IDENTITY["launcher_version"],
        "launcher_sha256": IDENTITY["launcher_sha256"],
        "runtime_digest": IDENTITY["runtime_digest"],
        "runtime_modules": [{"name": "deploy_runtime", "version": "1", "sha256": "b" * 64}],
        "compose_overlays": [], "candidate_fact_set": [], "environment_graph_identity": {},
        "signature_identity": "hk-evidence-signer:SHA256:" + "A" * 43 + "=", "signature": "AA=="}


def load_module(name, path):
    """Load a file that is not importable by name -- the executor has no extension."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TheBlockTests(unittest.TestCase):
    """The block itself, and the one implementation of it."""

    def test_the_fixture_is_the_block_the_one_implementation_produces(self):
        """The rest of this suite is only meaningful if the fixture is that projection."""
        install_fact = load_module("go_hk_install_fact_fixture", INSTALL_FACT)
        self.assertEqual(install_fact.installed_identity(FACT), IDENTITY)

    def test_the_block_is_the_five_fields_the_spec_lists(self):
        self.assertEqual(sorted(IDENTITY),
                         ["installation_id", "launcher_sha256", "launcher_version",
                          "runtime_digest", "schema", "source_commit"])


class TheExecutorTests(unittest.TestCase):
    """End one: the host derives the block, and only from a verification it just made."""

    def setUp(self):
        self.executor = load_module("go_hk_deployctl_under_test", EXECUTOR)
        self.install_fact = load_module("go_hk_install_fact_under_test", INSTALL_FACT)

    def test_the_block_is_derived_from_the_document_the_verification_returned(self):
        calls = []
        self.executor._verify_installation = lambda: (calls.append("verified"), dict(FACT))[1]
        self.executor._load_install_fact = lambda: self.install_fact
        self.assertEqual(self.executor._installed_identity(),
                         self.install_fact.installed_identity(FACT))
        self.assertEqual(calls, ["verified"])

    def test_a_document_carries_the_block_when_it_is_given_one(self):
        document = self.executor._document("SUCCESS", "r-1", IMAGE, IMAGE,
                                           {"all": "PASS"}, "VERIFY_OK", IDENTITY)
        self.assertEqual(document["installed_identity"], IDENTITY)
        self.assertEqual(document["result"], "VERIFY_OK")

    def test_a_refusal_document_does_not_claim_one(self):
        """A refusal did not necessarily get far enough to know what it was installed as."""
        document = self.executor._document("REJECTED", "r-1", "", "", {}, "VERIFY_REJECTED")
        self.assertNotIn("installed_identity", document)

    def test_every_action_the_executor_runs_carries_the_block_to_its_document(self):
        """The SPEC qualifies the candidate digest by action and leaves this one unqualified.

        The ordering -- the verification runs before the runtime is loaded -- is asserted
        where the launcher's wiring is already read, in `test_hk_install_fact`.  What is
        unique here is that all four actions hand the block to the document they return,
        and that none of them reaches `_verify_installation()` on its own.
        """
        source = EXECUTOR.read_text(encoding="utf-8")
        for action, carried in (("_deploy", '"DEPLOY_OK",identity)'),
                                ("_rollback", '"ROLLBACK_OK",identity)'),
                                ("_canary", '"CANARY_OK",identity)'),
                                ("_verify", '"VERIFY_OK",\n                         identity)')):
            with self.subTest(action=action):
                body = source.split("def %s(" % action, 1)[1].split("\ndef ", 1)[0]
                self.assertIn(carried, body,
                              "%s verified the installation but did not carry the block" % action)
                self.assertNotIn("_verify_installation()", body,
                                 "%s reaches the verification without deriving the block" % action)
        self.assertEqual(source.count("def _verify_installation():"), 1)


class TheAgentTests(unittest.TestCase):
    """End two: the block's shape is checked, and the Evidence carries it."""

    PARAMS = {"release_id": "r-1", "candidate_image_id": IMAGE,
              "expected_current_image_id": IMAGE}
    TASK = {"task_id": "installed-identity-1", "nonce": "nonce-1",
            "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01"}

    def document(self, identity=IDENTITY, **over):
        executor = load_module("go_hk_deployctl_for_agent_tests", EXECUTOR)
        document = executor._document("SUCCESS", "r-1", IMAGE, IMAGE, {"all": "PASS"},
                                      "VERIFY_OK", identity)
        document.update(over)
        return document

    def parse(self, document):
        return deployment_actions.parse_executor_output(
            json.dumps(document, separators=(",", ":")), "HK_STAGING_VERIFY", self.PARAMS)

    def test_a_missing_block_is_refused(self):
        """An action that ran must say what it was installed as, or it is not Evidence."""
        document = self.document()
        document.pop("installed_identity")
        with self.assertRaises(deployment_actions.Reject) as caught:
            self.parse(document)
        self.assertIn("schema rejected", str(caught.exception))
        self.assertEqual(caught.exception.stage, "parser")

    def test_a_refusal_is_a_refusal_and_not_a_malformed_document(self):
        """The block is required of an action that ran, not of one that refused.

        A refusal carries no block, because an action that failed may never have got as far
        as knowing what it was installed as.  The two findings stay distinct, so a real
        executor refusal is never filed as "your output was the wrong shape".
        """
        refusal = self.document()
        refusal.pop("installed_identity")
        refusal.update(status="REJECTED", result="VERIFY_REJECTED")
        with self.assertRaises(deployment_actions.Reject) as caught:
            self.parse(refusal)
        self.assertIn("executor result rejected", str(caught.exception))
        self.assertNotIn("schema rejected", str(caught.exception))
        self.assertEqual(caught.exception.stage, "parser")

    def test_a_malformed_block_is_refused_rather_than_relayed(self):
        for name, broken in (("empty", {}),
                             ("unknown-schema", {**IDENTITY, "schema": "go.other.v1"}),
                             ("short-commit", {**IDENTITY, "source_commit": "9b932745"}),
                             ("extra-field", {**IDENTITY, "media_topology": "x"}),
                             ("missing-field", {k: v for k, v in IDENTITY.items()
                                                if k != "runtime_digest"}),
                             ("not-a-digest", {**IDENTITY, "launcher_sha256": "e" * 63})):
            with self.subTest(case=name):
                with self.assertRaises(deployment_actions.Reject):
                    self.parse(self.document(identity=broken))

    def test_the_evidence_carries_the_block_the_executor_returned(self):
        record = transport.evidence(self.TASK, self.parse(self.document()))
        self.assertEqual(record["installed_identity"], IDENTITY)
        self.assertEqual(record["status"], "SUCCESS")
        self.assertEqual(record["executor_result"], "VERIFY_OK")

    def test_the_two_agent_copies_are_unchanged_in_this_respect(self):
        """`deployment_actions.py` is byte-shared; `transport.py` is not, so both are read."""
        for label, directory in (("installed", ROOT / "hk-staging" / "hk_agent"),
                                 ("reviewed", REPO / "hk-staging" / "source" / "agent"
                                  / "hk_agent")):
            with self.subTest(copy=label):
                text = (directory / "transport.py").read_text(encoding="utf-8")
                self.assertIn('"installed_identity":result["installed_identity"]', text)


class TheProverTests(unittest.TestCase):
    """End three: the proof reads the block back and decides."""

    def block(self):
        """The block exactly as it reaches the proof: out of an Evidence the agent signed."""
        executor = load_module("go_hk_deployctl_for_prover_tests", EXECUTOR)
        document = executor._document("SUCCESS", "r-1", IMAGE, IMAGE, {"all": "PASS"},
                                      "VERIFY_OK", IDENTITY)
        parsed = deployment_actions.parse_executor_output(
            json.dumps(document, separators=(",", ":")), "HK_STAGING_VERIFY",
            TheAgentTests.PARAMS)
        return transport.evidence(TheAgentTests.TASK, parsed)["installed_identity"]

    def test_the_host_that_runs_the_authorised_commit_passes_step_four(self):
        result = P.step_installed_identity_is_the_authorized_commit(self.block(),
                                                                    AUTHORIZED_COMMIT)
        self.assertEqual(result["state"], P.PASS)
        self.assertEqual(result["observed"], {"installed_source_commit": INSTALLED_COMMIT})

    def test_a_different_canonical_commit_is_its_own_condition_not_drift(self):
        result = P.step_installed_identity_is_the_authorized_commit(self.block(),
                                                                    OTHER_CANONICAL_COMMIT)
        self.assertEqual(result["state"], P.FAIL)
        self.assertEqual(result["code"], P.E_INSTALL_DRIFT)
        self.assertEqual(result["condition"], P.NOT_THE_AUTHORIZED_COMMIT)

    def test_an_unusable_block_is_unresolvable_rather_than_a_mismatch(self):
        for name, block in (("absent", {}), ("not-a-commit", {**IDENTITY, "source_commit": "x"})):
            with self.subTest(case=name):
                result = P.step_installed_identity_is_the_authorized_commit(block,
                                                                            AUTHORIZED_COMMIT)
                self.assertEqual(result["state"], P.FAIL)
                self.assertEqual(result["condition"], P.UNRESOLVABLE)


if __name__ == "__main__":
    unittest.main()
