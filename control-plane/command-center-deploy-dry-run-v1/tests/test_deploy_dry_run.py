"""Isolated tests for the DEPLOY dry-run rehearsal (CC V1-07 / #102).

Standard library only. No network, no Git, no subprocess, no runtime credential
or state path, no live Control Plane or Hong Kong contact.

The load-bearing tests here are two. First: every request-side refusal this
component can emit is a token the Boss Request Bridge can itself raise, checked
against the Bridge's own sources, so no parallel refusal vocabulary exists.
Second: a TASK_CANDIDATE is not a Task, in every field that could be mistaken
for one.
"""
import datetime as dt
import importlib.machinery
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

loader = importlib.machinery.SourceFileLoader(
    "go_deploy_dry_run", str(ROOT / "command-center" / "go-deploy-dry-run"))
spec = importlib.util.spec_from_loader(loader.name, loader)
D = importlib.util.module_from_spec(spec)
loader.exec_module(D)

CONTRACT = ROOT / D.CONTRACT_FILE
AT = D.parse_time("2026-09-15T01:00:00Z")
COMMIT = "a" * 40

BRIDGE_SOURCES = (
    REPO / "control-plane" / "boss-test-pr-live-integration-v1" / "command-center"
    / "go-boss-request-bridge",
    REPO / "control-plane" / "boss-deploy-request-v1" / "go-boss-request-bridge",
    REPO / "control-plane" / "boss-deploy-request-v1" / "go_deploy_request.py",
)
# Both call shapes, exactly as CC V1-05.1 established.
REJECT_CALL = re.compile(r"Reject\(\s*['\"]([a-z0-9_]+)['\"]")
REASON_ARGUMENT = re.compile(r"(?:exact|match)\([^()]*?['\"]([a-z0-9_]+)['\"]\s*\)")


def bridge_tokens():
    direct, passed = set(), set()
    for path in BRIDGE_SOURCES:
        text = path.read_text(encoding="utf-8")
        direct |= set(REJECT_CALL.findall(text))
        passed |= set(REASON_ARGUMENT.findall(text))
    return direct | passed


def readiness(verdict="YES", gates=None, boundary=None, contract=None):
    base = [("DEPLOYMENT_PLAN", True, {"plan_id": "release-one"}),
            ("APPROVED_CANDIDATE", True, {"source_commit": COMMIT}),
            ("PACKAGE_BINDING", True, {"image_id": "sha256:" + "f" * 64}),
            ("CURRENT_RUNTIME", True, {"image_config_id": "sha256:" + "e" * 64}),
            ("SOURCE_BINDING", True, None), ("TEST_PR", True, None),
            ("VERIFY", True, None), ("HUMAN_APPROVAL", True, None),
            ("LIVE_SWITCH", True, None), ("LIVE_SWITCH_PROVENANCE", True, None),
            ("BRIDGE_ACCEPTANCE", True, None),
            ("CANARY", False, None),
            ("RELEASE_GATES", False, None)]
    document = {
        "schema_version": "1", "contract": D.READINESS_CONTRACT,
        "scope": "READ_ONLY_DEPLOY_READINESS", "authority": "DERIVED_NON_AUTHORITATIVE",
        "generated_at": "2026-09-15T01:00:00Z", "as_of": "2026-09-15T01:00:00Z",
        "verdict": {"deploy_ready": verdict, "reason": "synthetic", "mandatory_gates": 9,
                    "failed": [], "unknown": [], "advisory_failed": []},
        "gates": gates if gates is not None else
        [{"gate": name, "mandatory": mandatory, "state": "PASS", "reason": "synthetic gate",
          **({"observed": observed} if observed else {})}
         for name, mandatory, observed in base],
        "authority_boundary": dict(boundary or D.READINESS_BOUNDARY)}
    if contract:
        document["contract"] = contract
    return document


def request(**over):
    value = {"schema_version": "1", "request_id": "rehearsal-one",
             "action_id": D.DEPLOY_ACTION, "environment": D.ENVIRONMENT,
             "requested_at": "2026-09-15T00:59:30Z", "plan_id": "release-one"}
    value.update(over)
    return value


class Fixture:
    """A requests/ directory, a readiness document, an optional store and history."""

    def __init__(self, body=None, readiness_document=None, history=None, with_store=True,
                 file_name=None, in_requests_dir=True):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ccv107-"))
        folder = self.root / "requests" if in_requests_dir else self.root
        folder.mkdir(parents=True, exist_ok=True)
        body = body if body is not None else request()
        self.request_path = folder / (file_name or ("%s.json" % body.get("request_id", "x")))
        self.request_path.write_text(json.dumps(body), encoding="utf-8")
        self.readiness_path = self.root / "DEPLOY_READINESS.json"
        self.readiness_path.write_text(
            json.dumps(readiness_document if readiness_document is not None else readiness()),
            encoding="utf-8")
        self.history_path = None
        if history is not None:
            self.history_path = self.root / "history.json"
            self.history_path.write_text(json.dumps(history), encoding="utf-8")
        self.store = (self.root / "store") if with_store else None

    def run(self, **over):
        return D.dry_run(str(over.pop("request_path", self.request_path)),
                         str(over.pop("readiness_path", self.readiness_path)),
                         over.pop("store", self.store),
                         over.pop("history_path", self.history_path), AT, AT,
                         D.Checks(CONTRACT))

    def raw(self, text):
        self.request_path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return self.run()


def check(document, name):
    return [entry for entry in document["checks"] if entry["check"] == name][0]


class VocabularyTests(unittest.TestCase):
    """No new refusal vocabulary: every token here must be the Bridge's own."""

    @classmethod
    def setUpClass(cls):
        cls.checks = D.Checks(CONTRACT)
        cls.schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.bridge = bridge_tokens()

    def test_every_request_check_token_is_a_bridge_token(self):
        self.assertGreaterEqual(len(self.bridge), 96, "the Bridge extraction shrank")
        stray = sorted(entry["token"] for entry in self.checks.request_checks
                       if entry["token"] not in self.bridge)
        self.assertEqual(stray, [], "this component invents refusal vocabulary: %s" % stray)

    def test_the_check_table_is_closed_and_declares_its_stage(self):
        stages = set(self.schema["x-go-stages"]) - {"note"}
        for entry in self.checks.request_checks:
            self.assertIn(entry["stage"], stages, entry)
        self.assertEqual(len({entry["check"] for entry in self.checks.request_checks}),
                         len(self.checks.request_checks))

    def test_every_declared_check_can_actually_be_reached(self):
        """A table entry with no code path would be a documented lie."""
        source = (ROOT / "command-center" / "go-deploy-dry-run").read_text(encoding="utf-8")
        for entry in self.checks.request_checks:
            if entry["check"] == "candidate_identity":
                continue
            self.assertIn('"%s"' % entry["check"], source, entry["check"])

    def test_an_undeclared_check_is_refused(self):
        with self.assertRaises(D.Refuse):
            self.checks.token_for("a_check_that_was_never_declared")


class DecisionTests(unittest.TestCase):
    def test_a_legal_request_produces_a_candidate_and_nothing_else(self):
        document = Fixture(history={"consumed_plan_ids": []}).run()
        self.assertEqual(document["decision"]["outcome"], "TASK_CANDIDATE")
        self.assertFalse(document["decision"]["task_published"])
        self.assertFalse(document["decision"]["signed"])
        self.assertFalse(document["decision"]["deploy_performed"])
        self.assertTrue(document["candidate"])

    def test_a_refusal_outranks_an_unknown(self):
        """One definite refusal decides the outcome whatever else is unproven."""
        document = Fixture(history={"consumed_plan_ids": []},
                           body=request(action_id="HK_STAGING_VERIFY")).run()
        self.assertEqual(document["decision"]["outcome"], "REJECTED")
        self.assertEqual(document["decision"]["refused"], ["action"])

    def test_an_unknown_is_never_a_pass(self):
        document = Fixture(history=None).run()
        self.assertEqual(document["decision"]["outcome"], "UNPROVEN")
        self.assertIsNone(document["candidate"])
        self.assertIn("plan_not_already_consumed", document["decision"]["unproven"])
        self.assertIn("not a pass", document["decision"]["reason"])

    def test_every_fault_is_reported_in_one_run(self):
        document = Fixture(history={"consumed_plan_ids": []},
                           body=request(action_id="HK_STAGING_VERIFY",
                                        environment="PRODUCTION",
                                        requested_at="2026-09-15T00:00:00Z")).run()
        self.assertEqual(set(document["decision"]["refused"]),
                         {"action", "environment", "stale_or_future_request"},
                         document["decision"])

    def test_without_a_store_a_replay_cannot_be_detected(self):
        document = Fixture(history={"consumed_plan_ids": []}, with_store=False).run()
        self.assertEqual(document["decision"]["outcome"], "UNPROVEN")
        self.assertEqual(check(document, "request_not_already_dry_run")["state"], "UNKNOWN")


class RejectionTests(unittest.TestCase):
    """One case per declared check: the rehearsal refuses deterministically."""

    def reject(self, name, fixture):
        document = fixture.run()
        entry = check(document, name)
        self.assertEqual(entry["state"], "FAIL", (name, entry))
        self.assertIsNotNone(entry["reason_code"], name)
        self.assertEqual(entry["reason_origin"], "BRIDGE_REQUEST_VOCABULARY", name)
        self.assertEqual(document["decision"]["outcome"], "REJECTED", name)
        return entry

    def test_unreadable_request(self):
        fixture = Fixture(history={"consumed_plan_ids": []})
        document = fixture.run(request_path=fixture.root / "requests" / "absent.json")
        entry = check(document, "request_readable")
        self.assertEqual(entry["state"], "FAIL")
        self.assertEqual(entry["reason_code"], "invalid_json")

    def test_oversized_request(self):
        fixture = Fixture(history={"consumed_plan_ids": []})
        fixture.request_path.write_bytes(b"x" * (D.MAX_REQUEST_BYTES + 1))
        document = fixture.run()
        entry = check(document, "request_readable")
        self.assertEqual(entry["state"], "FAIL")
        self.assertEqual(entry["reason_code"], "request_oversized")

    def test_malformed_json(self):
        fixture = Fixture(history={"consumed_plan_ids": []})
        document = fixture.raw("{not json")
        entry = check(document, "request_json")
        self.assertEqual(entry["state"], "FAIL")
        self.assertEqual(entry["reason_code"], "malformed_json")

    def test_duplicate_json_key(self):
        fixture = Fixture(history={"consumed_plan_ids": []})
        text = json.dumps(request())[:-1] + ', "plan_id": "release-one"}'
        document = fixture.raw(text)
        self.assertEqual(check(document, "request_unique_keys")["reason_code"],
                         "duplicate_json_key")

    def test_wrong_field_set(self):
        fixture = Fixture(history={"consumed_plan_ids": []},
                          body=request(extra="x"))
        self.reject("request_fields", fixture)

    def test_wrong_schema_version(self):
        fixture = Fixture(history={"consumed_plan_ids": []}, body=request(schema_version="2"))
        self.assertEqual(self.reject("request_schema_version", fixture)["reason_code"],
                         "schema_version")

    def test_bad_request_id(self):
        fixture = Fixture(history={"consumed_plan_ids": []}, body=request(request_id="a"),
                          file_name="a.json")
        self.assertEqual(self.reject("request_id_format", fixture)["reason_code"], "request_id")

    def test_wrong_action(self):
        fixture = Fixture(history={"consumed_plan_ids": []},
                          body=request(action_id="HK_STAGING_ROLLBACK"))
        self.assertEqual(self.reject("request_action", fixture)["reason_code"], "action")

    def test_wrong_environment(self):
        fixture = Fixture(history={"consumed_plan_ids": []},
                          body=request(environment="PRODUCTION"))
        self.assertEqual(self.reject("request_environment", fixture)["reason_code"], "environment")

    def test_requested_at_not_a_string(self):
        fixture = Fixture(history={"consumed_plan_ids": []}, body=request(requested_at=1))
        self.assertEqual(self.reject("request_requested_at_type", fixture)["reason_code"],
                         "requested_at_not_string")

    def test_requested_at_unparseable(self):
        fixture = Fixture(history={"consumed_plan_ids": []},
                          body=request(requested_at="yesterday"))
        self.assertEqual(self.reject("request_requested_at_format", fixture)["reason_code"],
                         "invalid_requested_at")

    def test_stale_request(self):
        fixture = Fixture(history={"consumed_plan_ids": []},
                          body=request(requested_at="2026-09-14T00:00:00Z"))
        self.assertEqual(self.reject("request_freshness", fixture)["reason_code"],
                         "stale_or_future_request")

    def test_future_request(self):
        fixture = Fixture(history={"consumed_plan_ids": []},
                          body=request(requested_at="2026-09-15T03:00:00Z"))
        self.assertEqual(self.reject("request_freshness", fixture)["reason_code"],
                         "stale_or_future_request")

    def test_bad_plan_id(self):
        fixture = Fixture(history={"consumed_plan_ids": []}, body=request(plan_id="a"))
        self.assertEqual(self.reject("request_plan_id_format", fixture)["reason_code"], "plan_id")

    def test_filename_not_bound_to_request_id(self):
        fixture = Fixture(history={"consumed_plan_ids": []}, file_name="something-else.json")
        self.assertEqual(self.reject("request_filename_binding", fixture)["reason_code"],
                         "request_filename_binding")

    def test_a_request_outside_a_requests_directory_is_unproven_not_pass(self):
        document = Fixture(history={"consumed_plan_ids": []}, in_requests_dir=False).run()
        self.assertEqual(check(document, "request_filename_binding")["state"], "UNKNOWN")


class ReplayTests(unittest.TestCase):
    def test_a_second_rehearsal_of_the_same_request_is_refused(self):
        fixture = Fixture(history={"consumed_plan_ids": []})
        first = fixture.run()
        self.assertEqual(first["decision"]["outcome"], "TASK_CANDIDATE")
        self.assertTrue(first["record"]["written"])
        second = fixture.run()
        self.assertEqual(second["decision"]["outcome"], "REJECTED")
        self.assertEqual(second["decision"]["refused"], ["duplicate_request_id"])
        self.assertTrue(second["record"]["replayed"])
        self.assertFalse(second["record"]["written"])

    def test_the_record_is_only_written_once_per_request_identity(self):
        fixture = Fixture(history={"consumed_plan_ids": []})
        fixture.run()
        fixture.run()
        records = sorted(p.name for p in fixture.store.glob("*.json"))
        self.assertEqual(len(records), 1, records)
        record = json.loads((fixture.store / records[0]).read_text(encoding="utf-8"))
        self.assertTrue(record["consumes_nothing"])
        self.assertIn("consumes no plan", record["note"])

    def test_a_consumed_plan_is_refused(self):
        fixture = Fixture(history={"consumed_plan_ids": ["release-one"]})
        document = fixture.run()
        self.assertEqual(document["decision"]["refused"],
                         ["deployment_plan_or_approval_already_consumed"])

    def test_a_consumed_request_id_is_refused(self):
        fixture = Fixture(history={"consumed_request_ids": ["rehearsal-one"]})
        document = fixture.run()
        self.assertEqual(document["decision"]["refused"],
                         ["deployment_plan_or_approval_already_consumed"])

    def test_a_clean_history_passes_the_consumption_check(self):
        document = Fixture(history={"consumed_plan_ids": ["another-plan"]}).run()
        self.assertEqual(check(document, "plan_not_already_consumed")["state"], "PASS")

    def test_a_refusing_run_still_writes_its_record(self):
        """The audit trail must include the refusals, not only the legal runs."""
        fixture = Fixture(history={"consumed_plan_ids": []},
                          body=request(action_id="HK_STAGING_VERIFY"))
        document = fixture.run()
        self.assertEqual(document["decision"]["outcome"], "REJECTED")
        self.assertTrue(document["record"]["written"])
        records = sorted(fixture.store.glob("*.json"))
        record = json.loads((records[0]).read_text(encoding="utf-8"))
        self.assertEqual(record["refused"], ["action"])
        self.assertEqual(record["outcome"], "REJECTED")


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.document = Fixture(history={"consumed_plan_ids": []}).run()
        self.candidate = self.document["candidate"]

    def test_a_candidate_is_not_a_task(self):
        for field, value in (("executable", False), ("signed", False),
                             ("publish_authorized", False), ("signature", None)):
            self.assertEqual(self.candidate[field], value, field)
        self.assertEqual(self.candidate["kind"], "TASK_CANDIDATE")
        self.assertFalse(self.document["authority_boundary"]["candidate_is_a_task"])

    def test_a_candidate_carries_no_nonce_or_validity_window(self):
        blob = D.canonical(self.document)
        for forbidden in (b'"nonce"', b'"expires_at"', b'"issued_at"'):
            self.assertNotIn(forbidden, blob, forbidden)

    def test_every_candidate_value_comes_from_the_approved_plan(self):
        self.assertEqual(self.candidate["parameters_source"], "APPROVED_PLAN_BUNDLE")
        self.assertEqual(self.candidate["plan_id"], "release-one")
        self.assertEqual(self.candidate["source_commit"], COMMIT)
        self.assertEqual(self.candidate["candidate_image_id"], "sha256:" + "f" * 64)
        self.assertEqual(self.candidate["expected_current_image_id"], "sha256:" + "e" * 64)

    def test_a_yes_without_the_approved_identity_is_refused_not_invented(self):
        gates = readiness()["gates"]
        for gate in gates:
            if gate["gate"] == "PACKAGE_BINDING":
                gate["observed"] = {}
        document = Fixture(history={"consumed_plan_ids": []},
                           readiness_document=readiness(gates=gates)).run()
        self.assertEqual(document["decision"]["outcome"], "REJECTED")
        self.assertIsNone(document["candidate"])
        self.assertEqual(document["decision"]["refused"], ["candidate_fields"])

    def test_a_candidate_holds_no_authority(self):
        for key, value in self.document["authority_boundary"].items():
            self.assertFalse(value, key)


class ReadinessCompositionTests(unittest.TestCase):
    def test_a_failing_gate_refuses_with_the_gate_name(self):
        for name in ("HUMAN_APPROVAL", "TEST_PR", "VERIFY", "CURRENT_RUNTIME", "LIVE_SWITCH",
                     "DEPLOYMENT_PLAN", "SOURCE_BINDING", "APPROVED_CANDIDATE"):
            gates = readiness()["gates"]
            for gate in gates:
                if gate["gate"] == name:
                    gate["state"] = "FAIL"
            document = Fixture(history={"consumed_plan_ids": []},
                               readiness_document=readiness(gates=gates)).run()
            self.assertEqual(document["decision"]["outcome"], "REJECTED", name)
            self.assertEqual(document["decision"]["refused"], [name], name)
            entry = check(document, "readiness:%s" % name)
            self.assertEqual(entry["reason_origin"], "DEPLOY_READINESS_GATE")

    def test_an_unknown_gate_leaves_the_outcome_unproven(self):
        gates = readiness()["gates"]
        for gate in gates:
            if gate["gate"] == "PACKAGE_BINDING":
                gate["state"] = "UNKNOWN"
        document = Fixture(history={"consumed_plan_ids": []},
                           readiness_document=readiness(gates=gates)).run()
        self.assertEqual(document["decision"]["outcome"], "UNPROVEN")
        self.assertIsNone(document["candidate"])

    def test_an_advisory_gate_never_blocks(self):
        for name in ("CANARY", "RELEASE_GATES"):
            gates = readiness()["gates"]
            for gate in gates:
                if gate["gate"] == name:
                    gate["state"] = "FAIL"
            document = Fixture(history={"consumed_plan_ids": []},
                               readiness_document=readiness(gates=gates)).run()
            self.assertEqual(document["decision"]["outcome"], "TASK_CANDIDATE", name)
            self.assertTrue(check(document, "readiness:%s" % name)["advisory"], name)
            self.assertNotIn(name, document["decision"]["refused"], name)

    def test_a_readiness_document_of_another_contract_is_refused(self):
        with self.assertRaises(D.Refuse):
            Fixture(history={"consumed_plan_ids": []},
                    readiness_document=readiness(contract="SOMETHING_ELSE")).run()

    def test_a_readiness_document_claiming_authority_is_refused(self):
        boundary = dict(D.READINESS_BOUNDARY)
        boundary["can_create_task"] = True
        with self.assertRaises(D.Refuse):
            Fixture(history={"consumed_plan_ids": []},
                    readiness_document=readiness(boundary=boundary)).run()

    def test_a_readiness_document_without_a_gate_is_refused(self):
        gates = [g for g in readiness()["gates"] if g["gate"] != "DEPLOYMENT_PLAN"]
        with self.assertRaises(D.Refuse):
            Fixture(history={"consumed_plan_ids": []},
                    readiness_document=readiness(gates=gates)).run()

    def test_the_rehearsal_reports_every_gate_it_was_given(self):
        document = Fixture(history={"consumed_plan_ids": []}).run()
        reported = {entry["check"] for entry in document["checks"]
                    if entry["stage"] == "READINESS"}
        self.assertEqual(reported, {"readiness:%s" % name for name in
                                    ("DEPLOYMENT_PLAN", "APPROVED_CANDIDATE", "PACKAGE_BINDING",
                                     "CURRENT_RUNTIME", "SOURCE_BINDING", "TEST_PR", "VERIFY",
                                     "HUMAN_APPROVAL", "LIVE_SWITCH", "LIVE_SWITCH_PROVENANCE",
                                     "CANARY", "RELEASE_GATES", "BRIDGE_ACCEPTANCE")})


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.document = Fixture(history={"consumed_plan_ids": []}).run()

    def test_the_boundary_block_is_all_false(self):
        self.assertTrue(all(value is False
                            for value in self.document["authority_boundary"].values()))

    def test_the_run_never_reports_a_publication_or_a_deployment(self):
        self.assertFalse(self.document["decision"]["task_published"])
        self.assertFalse(self.document["decision"]["signed"])
        self.assertFalse(self.document["decision"]["deploy_performed"])

    def test_the_source_holds_no_key_and_spawns_nothing(self):
        source = (ROOT / "command-center" / "go-deploy-dry-run").read_text(encoding="utf-8")
        for forbidden in ("cryptography", "load_pem_private_key", "import socket", "subprocess",
                          "PRODUCTION"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_no_caller_supplied_parameter_is_accepted(self):
        for option in ("--image", "--service", "--path", "--env", "--command"):
            self.assertNotIn(option, (ROOT / "command-center" / "go-deploy-dry-run")
                             .read_text(encoding="utf-8"), option)

    def test_the_candidate_is_the_only_thing_that_could_be_mistaken_for_work(self):
        self.assertIn("not a Task", " ".join(self.document["notes"]))
        blob = D.canonical(self.document)
        self.assertNotIn(b'"signed_task"', blob)
        self.assertNotIn(b'"grants_execution"', blob)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_the_outcome_set_is_closed(self):
        outcome = self.schema["properties"]["decision"]["properties"]["outcome"]
        self.assertEqual(set(outcome["enum"]), {"TASK_CANDIDATE", "REJECTED", "UNPROVEN"})

    def test_the_stage_set_is_closed(self):
        stage = self.schema["properties"]["checks"]["items"]["properties"]["stage"]
        self.assertEqual(set(stage["enum"]),
                         {"REQUEST_SHAPE", "REQUEST_IDENTITY", "PLAN_CONSUMPTION", "READINESS"})

    def test_the_reason_origins_are_closed(self):
        origin = self.schema["properties"]["checks"]["items"]["properties"]["reason_origin"]
        self.assertEqual(set(origin["enum"]),
                         {None, "BRIDGE_REQUEST_VOCABULARY", "DEPLOY_READINESS_GATE"})

    def test_the_candidate_can_never_be_executable_or_signed(self):
        candidate = self.schema["properties"]["candidate"]["properties"]
        self.assertEqual(candidate["executable"]["const"], False)
        self.assertEqual(candidate["signed"]["const"], False)
        self.assertEqual(candidate["publish_authorized"]["const"], False)
        self.assertEqual(candidate["parameters_source"]["const"], "APPROVED_PLAN_BUNDLE")
        self.assertEqual(candidate["signature"]["type"], "null")

    def test_the_contract_pins_the_three_impossible_things(self):
        forbidden = " ".join(self.schema["x-go-forbidden"])
        for phrase in ("Publishing, creating or signing a real DEPLOY Task",
                       "Touching the live deploy enable switch",
                       "Executing a deployment, contacting Hong Kong, or touching Production",
                       "Treating a dry-run record as a consumption"):
            self.assertIn(phrase, forbidden)

    def test_the_contract_states_the_acceptance_rules(self):
        acceptance = self.schema["x-go-acceptance"]
        self.assertIn("TASK_CANDIDATE", acceptance["legal dry run"])
        self.assertIn("deterministic REJECTED", acceptance["each illegal or missing gate"])
        self.assertIn("duplicate_request_id", acceptance["replay or duplicate"])
        self.assertIn("DEPLOY_PERFORMED=NO", acceptance["always"])

    def test_the_decision_always_declares_what_did_not_happen(self):
        decision = self.schema["properties"]["decision"]
        for key, const in (("task_published", False), ("signed", False),
                           ("deploy_performed", False)):
            self.assertEqual(decision["properties"][key]["const"], const, key)
            self.assertIn(key, decision["required"], key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
