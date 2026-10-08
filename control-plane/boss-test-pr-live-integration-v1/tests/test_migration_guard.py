"""The executor's last no-migration line of defence (CCV1-84 WP-2).

Three things are proven here:

1. **The check is complete and fail-closed.**  Every shape of candidate migration
   declaration either yields `VERIFIED_NO_MIGRATION` or refuses with one of the two
   stable codes -- never a pass by omission.  `precheck()` is the refusing form and it
   is exercised on all of them.

2. **The check is inert.**  `migration_guard` imports nothing that could run a command,
   open a file or mutate state, so it can be called as the first statement of a deploy.

3. **It is not wired, and that is visible.**  `deploy_runtime.run_deploy()` does not
   call it, and cannot until WP-4 extends the Task and Evidence contract with the
   candidate fact.  The test below fails the day somebody wires it without doing that,
   which is the point: the absence of the check must not be mistaken for the check
   passing, and the presence of a partial wiring must not be mistaken for a complete one.

Standard library only. No network, no Git, no Docker, no live Hong Kong contact.
"""
import importlib.machinery
import importlib.util
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "hk-staging"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

RUNTIME = REPO / "hk-staging" / "source" / "executor" / "runtime"
GUARD_PATH = RUNTIME / "migration_guard.py"
DEPLOY_RUNTIME_PATH = RUNTIME / "deploy_runtime.py"
AGENT_ACTIONS_PATH = ROOT / "hk-staging" / "hk_agent" / "deployment_actions.py"
ADMISSION_FACT_PATH = (REPO / "control-plane" / "command-center-candidate-admission-v1"
                       / "candidate_fact.py")

SUPPORTED_HEAD = "0133_flight_change_plan"


def load_guard():
    loader = importlib.machinery.SourceFileLoader("migration_guard_under_test",
                                                  str(GUARD_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


g = load_guard()


def declaration(**over):
    value = {"migration_required": False, "migration_head": SUPPORTED_HEAD}
    value.update(over)
    return value


class VerdictTests(unittest.TestCase):
    """What a declaration means, in the two stable codes and nothing else."""

    def test_a_declaration_on_the_environment_graph_verifies(self):
        self.assertEqual(g.verdict(declaration(), SUPPORTED_HEAD),
                         g.VERIFIED_NO_MIGRATION)

    def test_the_prohibited_condition_is_refused_in_its_own_code(self):
        for wrong in (True, 0, 1, "", "false", None, [], {}):
            with self.subTest(migration_required=wrong):
                self.assertEqual(g.verdict(declaration(migration_required=wrong),
                                           SUPPORTED_HEAD),
                                 g.REFUSED_MIGRATION_REQUIRED)

    def test_another_graph_is_refused_in_the_graph_code(self):
        self.assertEqual(
            g.verdict(declaration(migration_head="0135_some_other_head"), SUPPORTED_HEAD),
            g.REFUSED_MIGRATION_GRAPH_MISMATCH)

    def test_a_missing_declaration_is_never_a_pass(self):
        for absent in ("migration_head", "migration_required"):
            with self.subTest(absent=absent):
                part = declaration()
                part.pop(absent)
                self.assertEqual(g.verdict(part, SUPPORTED_HEAD),
                                 g.REFUSED_MIGRATION_GRAPH_MISMATCH)

    def test_no_fact_at_all_is_its_own_answer_not_a_pass(self):
        outcome = g.verdict(None, SUPPORTED_HEAD)
        self.assertEqual(outcome, g.FACT_NOT_SUPPLIED)
        self.assertNotEqual(outcome, g.VERIFIED_NO_MIGRATION)
        self.assertNotEqual(outcome, g.VERIFIED_NO_MIGRATION)

    def test_an_unestablishable_environment_graph_refuses(self):
        for head in (None, ""):
            with self.subTest(supported=head):
                self.assertEqual(g.verdict(declaration(), head),
                                 g.REFUSED_MIGRATION_GRAPH_MISMATCH)

    def test_a_malformed_declaration_is_refused_not_guessed_at(self):
        for wrong in ("a string", 7, [], ("migration_required", False)):
            with self.subTest(fact=wrong):
                self.assertEqual(g.verdict(wrong, SUPPORTED_HEAD),
                                 g.REFUSED_MIGRATION_GRAPH_MISMATCH)

    def test_the_two_codes_are_the_whole_vocabulary(self):
        codes = {g.E_DATABASE_MIGRATION_REQUIRED, g.E_DATABASE_MIGRATION_GRAPH_MISMATCH}
        self.assertEqual(codes, {"E_DATABASE_MIGRATION_REQUIRED",
                                 "E_DATABASE_MIGRATION_GRAPH_MISMATCH"})
        outcomes = {g.VERIFIED_NO_MIGRATION, g.REFUSED_MIGRATION_REQUIRED,
                    g.REFUSED_MIGRATION_GRAPH_MISMATCH, g.FACT_NOT_SUPPLIED}
        self.assertEqual(len(outcomes), 4, "two outcomes collapsed into one")


class PrecheckTests(unittest.TestCase):
    """The refusing form, which is what a wired deploy path calls."""

    def test_it_passes_only_a_verified_no_migration_declaration(self):
        self.assertEqual(g.precheck(declaration(), SUPPORTED_HEAD),
                         g.VERIFIED_NO_MIGRATION)

    def test_the_prohibited_condition_raises_before_anything_could_happen(self):
        with self.assertRaises(g.Reject) as caught:
            g.precheck(declaration(migration_required=True), SUPPORTED_HEAD)
        self.assertEqual(str(caught.exception), g.E_DATABASE_MIGRATION_REQUIRED)

    def test_a_different_graph_raises_in_the_graph_code(self):
        with self.assertRaises(g.Reject) as caught:
            g.precheck(declaration(migration_head="0135_some_other_head"), SUPPORTED_HEAD)
        self.assertEqual(str(caught.exception), g.E_DATABASE_MIGRATION_GRAPH_MISMATCH)

    def test_an_unsupplied_fact_refuses_rather_than_proceeding(self):
        """The one that matters most: an unwired caller must not look like a pass.

        If WP-4 ever wires this with the fact left unsupplied -- a Task field that
        nobody filled in, a store the executor cannot read -- the deployment stops.
        """
        with self.assertRaises(g.Reject) as caught:
            g.precheck(None, SUPPORTED_HEAD)
        self.assertEqual(str(caught.exception), g.E_DATABASE_MIGRATION_GRAPH_MISMATCH)

    def test_it_refuses_before_the_runner_is_ever_consulted(self):
        """`precheck` must not be able to run anything, so it cannot be late."""
        calls = []

        class Recorder:
            def __getattr__(self, name):
                calls.append(name)
                raise AssertionError("the guard reached for %s" % name)

        for fact, head in ((declaration(migration_required=True), SUPPORTED_HEAD),
                           (declaration(migration_head="other"), SUPPORTED_HEAD),
                           (None, SUPPORTED_HEAD)):
            with self.subTest(fact=fact):
                with self.assertRaises(g.Reject):
                    g.precheck(fact, head)
        self.assertEqual(calls, [], "the guard touched something outside itself")


class InertnessTests(unittest.TestCase):
    """It decides and refuses; it cannot do anything else."""

    def test_it_imports_nothing_that_could_act(self):
        for forbidden in ("subprocess", "socket", "shutil", "urllib", "requests",
                          "tempfile", "sqlite3"):
            self.assertFalse(hasattr(g, forbidden),
                             "migration_guard must not be able to use %s" % forbidden)
        source = GUARD_PATH.read_text(encoding="utf-8")
        for forbidden in ("import os", "import subprocess", "import socket",
                          "open(", "pathlib", "os."):
            self.assertNotIn(forbidden, source,
                             "migration_guard names %s" % forbidden)

    def test_it_holds_no_authority_of_its_own(self):
        source = GUARD_PATH.read_text(encoding="utf-8")
        self.assertNotIn("sign", source)
        self.assertNotIn("write", source.replace("writes nothing", "")
                         .replace("write nothing", ""), "the guard writes something")


class WiringStatusTests(unittest.TestCase):
    """CCV1-85 (WP-4A): the check is connected, and the connection is asserted.

    WP-2 shipped this class as three *reverse* assertions -- the executor does not call
    the guard, the DEPLOY parameters carry no candidate fact, the seam is only named --
    precisely so that wiring it would have to be a deliberate act. This is that act.
    The tests are rewritten rather than deleted, so the property they were guarding (that
    nothing gets wired by accident) is now guarded in the other direction: the wiring
    cannot be *removed* by accident either.
    """

    def test_the_executor_calls_the_guard_before_it_mutates(self):
        """The seam WP-2 declared is the call path now, in the right order.

        Order is asserted by position inside `run_deploy` itself rather than by
        assertion on a mock, because the property that matters is that the guard is
        unreachable-late: any mutation in that function is below these lines.
        """
        source = DEPLOY_RUNTIME_PATH.read_text(encoding="utf-8")
        body = source[source.index("def run_deploy("):]
        load_at = body.index("source.load_candidate_fact(")
        artifact_at = body.index("source.require_same_artifact(")
        guard_at = body.index("guard.precheck(")
        precheck_at = body.index("_precheck(runner")
        self.assertLess(load_at, artifact_at,
                        "the fact is bound to the artifact after it is loaded")
        self.assertLess(artifact_at, guard_at,
                        "the artifact binding must precede the migration gate")
        self.assertLess(guard_at, precheck_at,
                        "the guard must run before the deploy precheck")
        self.assertIn('_MIGRATION_GUARD_SHA256', source,
                      "the guard is loaded without a byte pin")

    def test_the_deploy_parameters_carry_the_candidate_and_no_migration_fact(self):
        """The candidate digest is now part of the contract, and nothing else is.

        The digest is the candidate's *identity*; a migration declaration is not, and it
        stays inside the candidate fact rather than becoming a Task parameter a caller
        could be tempted to set.
        """
        source = AGENT_ACTIONS_PATH.read_text(encoding="utf-8")
        deploy = re.search(r'action == "HK_STAGING_DEPLOY":\s*\n\s*p=_exact\(params,\(([^)]*)\)',
                           source)
        self.assertIsNotNone(deploy, "the DEPLOY parameter set was not found")
        declared = {name.strip().strip('"') for name in deploy.group(1).split(",")}
        self.assertEqual(declared, {"release_id", "candidate_image_id",
                                    "candidate_package_sha256", "expected_current_image_id",
                                    "canary_evidence_id", "approval_id",
                                    "candidate_contract_sha256"})
        for name in ("migration_required", "migration_head", "topology",
                     "candidate_contract", "candidate_body", "candidate_path"):
            self.assertNotIn(name, declared,
                             "%s must not be a Task parameter" % name)

    def test_the_launcher_pin_was_updated_and_the_rest_were_not(self):
        """`PIN_UPDATED_FOR_LOCAL_SOURCE=YES`, and exactly one pin moved.

        WP-4A is allowed to update the launcher's pin for the module it changed. It is
        not allowed to disturb the other four, and this is the assertion that says so.
        """
        import hashlib

        def lf_sha256(path):
            """The pinned value is over the committed blob, which is LF.

            This repository checks out CRLF outside a component `.gitattributes`, so
            hashing the worktree bytes directly compares the file to something no pin was
            ever computed over. Normalising first is what makes the comparison meaningful
            on this workstation as well as on the runner.
            """
            return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()

        launcher = (REPO / "hk-staging" / "source" / "executor" / "go-hk-deployctl").read_text(
            encoding="utf-8")
        pins = dict(re.findall(r'_(\w+)_SHA256 = "([0-9a-f]{64})"', launcher))
        self.assertEqual(sorted(pins), ["ARTIFACT", "CANARY", "COLLECTOR", "DEPLOY",
                                        "ROLLBACK"])
        for name, filename in (("COLLECTOR", "collector_runtime"), ("CANARY", "canary_runtime"),
                               ("ROLLBACK", "rollback_runtime"), ("ARTIFACT", "artifact_runtime")):
            self.assertEqual(pins[name], lf_sha256(RUNTIME / (filename + ".py")),
                             "%s pin no longer matches its module" % name)
        self.assertEqual(pins["DEPLOY"], lf_sha256(DEPLOY_RUNTIME_PATH),
                         "the DEPLOY pin was not updated with its module")
        # and the chain below the launcher is pinned the same way, one level at a time
        deploy_source = DEPLOY_RUNTIME_PATH.read_text(encoding="utf-8")
        for constant, module in (("_CANDIDATE_SOURCE_SHA256", "candidate_source"),
                                 ("_MIGRATION_GUARD_SHA256", "migration_guard")):
            pinned = re.search(constant + r' = "([0-9a-f]{64})"', deploy_source).group(1)
            self.assertEqual(pinned, lf_sha256(RUNTIME / (module + ".py")),
                             "%s pin no longer matches %s.py" % (constant, module))
        guard_source = (RUNTIME / "candidate_source.py").read_text(encoding="utf-8")
        pinned = re.search(r"CANDIDATE_FACT_SHA256 = .([0-9a-f]{64}).",
                           guard_source).group(1)
        self.assertEqual(pinned, lf_sha256(RUNTIME / "candidate_fact.py"),
                         "the candidate fact pin no longer matches its module")

    def test_the_seam_is_named(self):
        self.assertIn("WP4_SEAM", dir(g))
        self.assertIn("run_deploy", g.WP4_SEAM)


class CrossLayerAgreementTests(unittest.TestCase):
    """One vocabulary, two components, no imports between them.

    The third layer this pinned was the Old Command Center plan derivation, retired
    on 2026-10-08 with `control-plane/boss-deploy-request-v1`. The two that remain
    are the ones the live TEST_PR path actually runs.
    """

    def _constants(self, path, names):
        source = path.read_text(encoding="utf-8")
        found = {}
        for name in names:
            match = re.search(r"^%s = ['\"]([^'\"]+)['\"]" % name, source, re.M)
            if match:
                found[name] = match.group(1)
        return found

    def test_the_two_layers_declare_the_same_two_codes(self):
        names = ("E_DATABASE_MIGRATION_REQUIRED", "E_DATABASE_MIGRATION_GRAPH_MISMATCH")
        layers = {
            "executor": self._constants(GUARD_PATH, names),
            "admission": self._constants(ADMISSION_FACT_PATH, names),
        }
        for layer, found in layers.items():
            self.assertEqual(sorted(found), sorted(names),
                             "%s does not declare both codes" % layer)
            self.assertEqual(found["E_DATABASE_MIGRATION_REQUIRED"],
                             "E_DATABASE_MIGRATION_REQUIRED", layer)
            self.assertEqual(found["E_DATABASE_MIGRATION_GRAPH_MISMATCH"],
                             "E_DATABASE_MIGRATION_GRAPH_MISMATCH", layer)

    def test_the_executor_layer_agrees_with_the_module_it_loaded(self):
        self.assertEqual(g.E_DATABASE_MIGRATION_REQUIRED, "E_DATABASE_MIGRATION_REQUIRED")
        self.assertEqual(g.E_DATABASE_MIGRATION_GRAPH_MISMATCH,
                         "E_DATABASE_MIGRATION_GRAPH_MISMATCH")


if __name__ == "__main__":
    unittest.main()
