"""Isolated tests for the Bridge Request fact export (CC V1-05 / #100).

Standard library only. No network, no Git, no subprocess, no runtime credential
or state path, no live Control Plane or Hong Kong contact.

The load-bearing test in this file is the vocabulary coverage test: it reads the
Bridge sources as they are in the repository, extracts every refusing token the
Bridge can emit, and asserts that the published contract classifies all of them.
A refusal reason that the contract has never heard of would be reported as
UNCLASSIFIED_REJECT; a token the Bridge can emit but the contract cannot even
name would mean this component ships a blind spot.
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
    "go_request_fact_export", str(ROOT / "command-center" / "go-request-fact-export"))
spec = importlib.util.spec_from_loader(loader.name, loader)
X = importlib.util.module_from_spec(spec)
loader.exec_module(X)

CONTRACT = ROOT / X.CONTRACT_FILE
AT = dt.datetime(2026, 9, 14, 13, 0, tzinfo=dt.timezone.utc)
HEAD = "a" * 40
REQUEST_ID = "synthetic-request-1"

# Every place a Request can be refused, as it exists in this repository.
BRIDGE_SOURCES = (
    REPO / "control-plane" / "boss-test-pr-live-integration-v1" / "command-center"
    / "go-boss-request-bridge",
    REPO / "control-plane" / "boss-deploy-request-v1" / "go-boss-request-bridge",
    REPO / "control-plane" / "boss-deploy-request-v1" / "go_deploy_request.py",
)
# Every refusing token is a literal string at its call site, but there are two
# call shapes and they must both be scanned: ``Reject("token")`` raised directly,
# and the ``reason`` argument of ``exact(...)`` / ``match(...)``, which raise
# ``Reject(reason)`` inside the helper. Scanning only the first shape silently
# under-counts the vocabulary, which is exactly the blind spot this test exists
# to prevent.
REJECT_CALL = re.compile(r"Reject\(\s*['\"]([a-z0-9_]+)['\"]")
REASON_ARGUMENT = re.compile(r"(?:exact|match)\([^()]*?['\"]([a-z0-9_]+)['\"]\s*\)")


def bridge_refusal_tokens():
    """The union of both call shapes. This is the claim the contract must cover."""
    direct, passed = set(), set()
    for path in BRIDGE_SOURCES:
        text = path.read_text(encoding="utf-8")
        direct |= set(REJECT_CALL.findall(text))
        passed |= set(REASON_ARGUMENT.findall(text))
    return direct, passed


def request_body(request_id=REQUEST_ID, **over):
    value = {"schema_version": "1", "request_id": request_id, "action_id": "HK_STAGING_VERIFY",
             "environment": "HK-STAGING-01", "requested_at": "2026-09-14T11:00:00Z"}
    value.update(over)
    return value


def signed_task(request_id=REQUEST_ID):
    return {"schema_version": "1",
            "task_id": "go-boss-request-verify-20260914T110000Z-"
                       + __import__("hashlib").sha256(request_id.encode()).hexdigest()[:12],
            "nonce": "synthetic-nonce", "issued_at": "2026-09-14T11:00:05Z",
            "expires_at": "2026-09-14T11:15:05Z", "authority": "GO-COMMAND-CENTER",
            "environment": "HK-STAGING-01", "action_id": "HK_STAGING_VERIFY",
            "parameters": {"release_id": "synthetic", "candidate_image_id": "sha256:" + "0" * 64,
                           "expected_current_image_id": "sha256:" + "0" * 64},
            "signature": "0" * 128}


def workdir(ledger=None, poll=None, requests=(), journaled_at="2026-09-14T12:00:00Z"):
    root = pathlib.Path(tempfile.mkdtemp(prefix="ccv105-"))
    (root / "requests").mkdir()
    (root / "ledger.json").write_bytes(X.canonical(ledger or {"version": 1, "requests": {}}) + b"\n")
    if poll is not None:
        document = {"schema_version": "1", "bridge_output": poll}
        if journaled_at is not None:
            document["journaled_at"] = journaled_at
        (root / "poll.json").write_bytes(X.canonical(document) + b"\n")
    for name, value in requests:
        (root / "requests" / name).write_bytes(X.canonical(value) + b"\n")
    return root


def collected(request_id=REQUEST_ID, head=HEAD, body=None):
    return (request_id + ".json",
            {"ref": "refs/remotes/origin/boss-request-" + request_id, "head_sha": head,
             "path": "requests/" + request_id + ".json", "request": body or request_body(request_id)})


def poll_output(results, version="synthetic-bridge"):
    return {"bridge_version": version, "channel_mode": "PERSISTENT", "publish_enabled": True,
            "results": results}


def run_export(root, out="out"):
    return X.export([str(root / "ledger.json")],
                    [str(root / "poll.json")] if (root / "poll.json").exists() else [],
                    str(root / "requests"), str(root / out), str(CONTRACT), AT)


def only_fact(root, out="out"):
    folder = root / out / X.FACTS_DIR
    names = sorted(p.name for p in folder.glob("*.json"))
    return [json.loads((folder / name).read_text(encoding="utf-8")) for name in names]


class VocabularyCoverageTests(unittest.TestCase):
    """No refusal reason the Bridge can emit may be unknown to the contract."""

    @classmethod
    def setUpClass(cls):
        cls.vocabulary = X.Vocabulary(CONTRACT)

    def test_the_bridge_sources_are_where_the_contract_says_they_are(self):
        for path in BRIDGE_SOURCES:
            self.assertTrue(path.is_file(), "Bridge source moved or vanished: %s" % path)

    def test_both_refusal_call_shapes_are_scanned(self):
        direct, passed = bridge_refusal_tokens()
        self.assertGreater(len(direct), 50, "the direct extraction found too few tokens")
        self.assertGreater(len(passed), 10, "the reason-argument extraction found too few tokens")
        self.assertTrue(passed - direct, "the two shapes must not be identical")

    def test_every_refusal_token_the_bridge_can_emit_is_classified(self):
        direct, passed = bridge_refusal_tokens()
        tokens = direct | passed
        self.assertGreaterEqual(len(tokens), 96,
                                "the extraction found suspiciously few tokens: %d" % len(tokens))
        unclassified = sorted(t for t in tokens
                              if self.vocabulary.classify(t) == "UNCLASSIFIED_REJECT")
        self.assertEqual(unclassified, [],
                         "the Bridge can emit a refusal the contract never classifies: %s"
                         % unclassified)
        # A token reachable only through the reason argument must be classified
        # too: those are the ones a single-shape scan misses.
        missed = sorted(t for t in (passed - direct)
                        if self.vocabulary.classify(t) == "UNCLASSIFIED_REJECT")
        self.assertEqual(missed, [], "unclassified reason arguments: %s" % missed)

    def test_every_class_maps_to_exactly_one_kind(self):
        schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
        declared = set(schema["x-go-reason-classes"]) - {"note"}
        mapped = set()
        for kind, names in schema["x-go-kind-by-class"].items():
            if kind == "note":
                continue
            for name in names:
                self.assertNotIn(name, mapped, "class %s maps to two kinds" % name)
                mapped.add(name)
        self.assertEqual(mapped, declared)

    def test_the_two_identity_negatives_have_their_own_kinds(self):
        self.assertEqual(self.vocabulary.classify("duplicate_request_id"), "DUPLICATE")
        self.assertEqual(self.vocabulary.classify("already_seen"), "REPLAY")
        self.assertEqual(self.vocabulary.kind_for_class("DUPLICATE"), "REQUEST_DUPLICATE")
        self.assertEqual(self.vocabulary.kind_for_class("REPLAY"), "REQUEST_REPLAY_REJECTED")
        self.assertNotIn("REQUEST_DUPLICATE", ("REQUEST_REJECTED",))
        self.assertNotIn("REQUEST_REPLAY_REJECTED", ("REQUEST_REJECTED",))

    def test_an_unknown_token_is_preserved_rather_than_dropped(self):
        self.assertEqual(self.vocabulary.classify("a_token_from_a_future_bridge"),
                         "UNCLASSIFIED_REJECT")
        self.assertEqual(self.vocabulary.kind_for_class("UNCLASSIFIED_REJECT"), "REQUEST_REJECTED")

    def test_an_incomplete_contract_is_refused_before_anything_is_read(self):
        broken = pathlib.Path(tempfile.mkdtemp(prefix="ccv105-contract-")) / "broken.json"
        broken.write_text(json.dumps({"x-go-reason-classes": {}, "x-go-kind-by-class": {},
                                      "x-go-ledger-derived-reasons": {}}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            X.Vocabulary(str(broken))


class ExportTests(unittest.TestCase):
    def test_accepted_case_projects_as_validated_with_a_binding(self):
        task = signed_task()
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "published", "request_id": REQUEST_ID, "task": task,
                        "task_sha256": X.digest(task), "task_commit": "b" * 40}}},
                       poll=poll_output([{"pr": "7", "head": HEAD, "status": "published",
                                          "task_id": task["task_id"]}]),
                       requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["by_kind"], {"REQUEST_VALIDATED": 1})
        fact = only_fact(root)[0]
        self.assertEqual(fact["kind"], "REQUEST_VALIDATED")
        self.assertEqual(fact["request_id"], REQUEST_ID)
        self.assertEqual(fact["source"]["path"], "requests/" + REQUEST_ID + ".json")
        self.assertEqual(fact["nonce"], task["nonce"])
        self.assertEqual(fact["binding"]["task_id"], task["task_id"])
        self.assertEqual(fact["binding"]["task_sha256"], X.digest(task))
        self.assertEqual(fact["binding"]["task_commit"], "b" * 40)
        self.assertTrue(fact["binding"]["proof_required"])
        self.assertEqual(fact["binding"]["proof"], "TASK_SIGNATURE_AND_DIGEST_PREFIX")
        self.assertEqual(fact["time_source"], "POLL_JOURNAL")

    def test_the_binding_facts_are_checkable_against_the_task_on_the_bus(self):
        """The claimed digest must be the digest of the Task as the bus stores it."""
        task = signed_task()
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "published", "request_id": REQUEST_ID, "task": task,
                        "task_sha256": X.digest(task)}}}, requests=[collected()])
        run_export(root)
        fact = only_fact(root)[0]
        stored = X.canonical(task) + b"\n"
        self.assertEqual(X.digest(json.loads(stored.decode("utf-8"))), fact["binding"]["task_sha256"])

    def test_re_exporting_the_same_bridge_outcome_is_idempotent(self):
        task = signed_task()
        ledger = {"version": 1, "requests": {"7:" + HEAD: {
                  "status": "published", "request_id": REQUEST_ID, "task": task,
                  "task_sha256": X.digest(task)}}}
        root = workdir(ledger=ledger, requests=[collected()])
        first = run_export(root)["facts"][0]["fact_id"]
        second = X.export([str(root / "ledger.json")], [], str(root / "requests"),
                          str(root / "out"), str(CONTRACT), AT + dt.timedelta(hours=1))
        self.assertEqual(second["facts"][0]["fact_id"], first)
        self.assertEqual(len(only_fact(root)), 1)

    def test_the_ledger_is_read_only(self):
        task = signed_task()
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "published", "request_id": REQUEST_ID, "task": task,
                        "task_sha256": X.digest(task)}}}, requests=[collected()])
        before = (root / "ledger.json").read_bytes()
        run_export(root)
        self.assertEqual((root / "ledger.json").read_bytes(), before)

    def test_a_dry_run_is_not_an_acceptance(self):
        """dry_run_consumed derived a preview and published nothing."""
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "dry_run_consumed", "request_id": REQUEST_ID,
                        "task_id": "preview", "publish_enabled": False}}},
                       requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["by_kind"], {"REQUEST_REJECTED": 1})
        fact = only_fact(root)[0]
        self.assertEqual(fact["reason"]["code"], "dry_run_no_task_published")
        self.assertEqual(fact["reason"]["origin"], "BRIDGE_LEDGER_STATE")
        self.assertEqual(fact["reason"]["class"], "NOT_ALLOWED")
        self.assertFalse(fact["binding"]["claimed"])
        self.assertIsNone(fact["binding"]["task_id"])

    def test_a_non_terminal_ledger_state_produces_no_lifecycle_fact(self):
        for status in ("claiming", "prepared", "publishing"):
            root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                            "status": status, "request_id": REQUEST_ID,
                            "task": signed_task()}}}, requests=[collected()])
            index = run_export(root)
            self.assertEqual(index["counts"]["facts"], 0, status)
            self.assertEqual(index["counts"]["submissions_without_fact"], 1, status)
            self.assertIn("SUBMISSION_WITHOUT_REQUEST_FACT", [a["kind"] for a in index["anomalies"]])

    def test_the_ignored_status_is_submission_level_and_keeps_its_reason(self):
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "ignored", "reason": "non_request_or_extra_files"}}},
                       requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["facts"], 0)
        self.assertEqual(index["submissions"][0]["reason"], "non_request_or_extra_files")

    # -- refusals -------------------------------------------------------------
    def test_a_refusal_keeps_the_token_and_gets_a_class(self):
        root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "rejected",
                                          "reason": "pr_head_not_found"}]),
                       requests=[collected()])
        index = run_export(root)
        fact = only_fact(root)[0]
        self.assertEqual(fact["kind"], "REQUEST_REJECTED")
        self.assertEqual(fact["reason"]["code"], "pr_head_not_found")
        self.assertEqual(fact["reason"]["class"], "UNRESOLVABLE")
        self.assertEqual(fact["reason"]["origin"], "BRIDGE_REJECT_TOKEN")
        self.assertTrue(fact["reason"]["preserved_verbatim"])
        self.assertEqual(fact["observed_at"], "2026-09-14T12:00:00Z")
        self.assertEqual(index["counts"]["by_kind"], {"REQUEST_REJECTED": 1})

    def test_every_bridge_token_round_trips_into_a_fact(self):
        direct, passed = bridge_refusal_tokens()
        for token in sorted(direct | passed):
            root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "rejected",
                                              "reason": token}]),
                           requests=[collected()])
            run_export(root)
            fact = only_fact(root)[0]
            self.assertEqual(fact["reason"]["code"], token)
            self.assertTrue(fact["reason"]["class"])
            self.assertIn(fact["kind"], ("REQUEST_REJECTED", "REQUEST_DUPLICATE",
                                         "REQUEST_REPLAY_REJECTED"))

    def test_a_reason_the_contract_does_not_know_is_still_carried(self):
        root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "rejected",
                                          "reason": "a_token_from_a_future_bridge"}]),
                       requests=[collected()])
        run_export(root)
        fact = only_fact(root)[0]
        self.assertEqual(fact["reason"]["code"], "a_token_from_a_future_bridge")
        self.assertEqual(fact["reason"]["class"], "UNCLASSIFIED_REJECT")
        self.assertEqual(fact["kind"], "REQUEST_REJECTED")

    def test_a_rejection_without_a_reason_is_refused_rather_than_invented(self):
        root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "rejected"}]),
                       requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["facts"], 0)
        self.assertEqual(index["counts"]["submissions_without_fact"], 1)

    # -- duplicate and replay -------------------------------------------------
    def test_a_duplicate_is_its_own_kind(self):
        root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "rejected",
                                          "reason": "duplicate_request_id"}]),
                       requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["by_kind"], {"REQUEST_DUPLICATE": 1})
        self.assertEqual(only_fact(root)[0]["reason"]["class"], "DUPLICATE")

    def test_a_replay_is_its_own_kind_and_claims_nothing(self):
        root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "already_seen",
                                          "record": {"status": "published",
                                                     "request_id": REQUEST_ID,
                                                     "task": signed_task()}}]),
                       requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["by_kind"], {"REQUEST_REPLAY_REJECTED": 1})
        fact = only_fact(root)[0]
        self.assertEqual(fact["reason"]["code"], "already_seen")
        self.assertEqual(fact["reason"]["origin"], "BRIDGE_POLL_STATUS")
        self.assertFalse(fact["binding"]["claimed"])
        self.assertIsNone(fact["binding"]["task_id"])
        self.assertFalse(fact["binding"]["proof_required"])

    # -- fail closed ----------------------------------------------------------
    def test_an_undated_journal_is_read_but_produces_no_fact(self):
        root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "rejected",
                                          "reason": "malformed_json"}]),
                       requests=[collected()], journaled_at=None)
        index = run_export(root)
        self.assertEqual(index["counts"]["facts"], 0)
        self.assertEqual(index["submissions"][0]["reason"], "malformed_json")
        self.assertIn("POLL_JOURNAL_UNDATED", [a["kind"] for a in index["anomalies"]])

    def test_an_unidentifiable_submission_produces_no_fact_but_is_listed(self):
        root = workdir(poll=poll_output([{"pr": "8", "head": "c" * 40, "status": "rejected",
                                          "reason": "malformed_json"}]),
                       requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["facts"], 0)
        entry = [s for s in index["submissions"] if s["pr_number"] == "8"][0]
        self.assertEqual(entry["reason"], "malformed_json")
        self.assertFalse(entry["fact_emitted"])
        self.assertIn("request_identity_unresolved", entry["detail"])

    def test_an_action_that_cannot_be_resolved_refuses_the_fact(self):
        bad = {"schema_version": "1", "request_id": REQUEST_ID, "action_id": "NOT_AN_ACTION",
               "environment": "HK-STAGING-01", "requested_at": "2026-09-14T11:00:00Z"}
        root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "rejected",
                                          "reason": "action_not_enabled_in_channel"}]),
                       requests=[(REQUEST_ID + ".json",
                                  {"ref": "refs/x", "head_sha": HEAD,
                                   "path": "requests/" + REQUEST_ID + ".json", "request": bad})])
        index = run_export(root)
        self.assertEqual(index["counts"]["facts"], 0)
        self.assertIn("request_action_unresolved",
                      " ".join(a["detail"] for a in index["anomalies"]))

    def test_a_broken_ledger_is_reported_and_does_not_stop_the_export(self):
        root = workdir(poll=poll_output([{"pr": "7", "head": HEAD, "status": "rejected",
                                          "reason": "pr_head_not_found"}]),
                       requests=[collected()])
        (root / "ledger.json").write_text("{", encoding="utf-8")
        index = run_export(root)
        self.assertEqual(index["counts"]["by_kind"], {"REQUEST_REJECTED": 1})
        self.assertIn("LEDGER_UNREADABLE", [a["kind"] for a in index["anomalies"]])

    def test_a_ledger_with_another_version_is_refused(self):
        root = workdir(ledger={"version": 2, "requests": {}}, requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["facts"], 0)
        self.assertIn("LEDGER_UNREADABLE", [a["kind"] for a in index["anomalies"]])

    # -- the export is never authority ----------------------------------------
    def test_nothing_the_exporter_writes_holds_authority(self):
        task = signed_task()
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "published", "request_id": REQUEST_ID, "task": task,
                        "task_sha256": X.digest(task)}}}, requests=[collected()])
        index = run_export(root)
        self.assertFalse(any(index["authority"].values()))
        for fact in only_fact(root):
            self.assertFalse(any(fact["authority"].values()))
        blob = X.canonical(index) + b"".join(X.canonical(f) for f in only_fact(root))
        for forbidden in (b'"grants_execution":true', b'"signature"', b'"signed_task"',
                          b'"holds_private_key":true'):
            self.assertNotIn(forbidden, blob)

    def test_the_exporter_reads_no_signing_key(self):
        source = (ROOT / "command-center" / "go-request-fact-export").read_text(encoding="utf-8")
        for forbidden in ("load_pem_private_key", "serialization", "cryptography", "sign("):
            self.assertNotIn(forbidden, source.split('"""')[2], forbidden)
        self.assertNotIn("cryptography", source)

    def test_the_index_records_every_submission_it_saw(self):
        task = signed_task()
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "published", "request_id": REQUEST_ID, "task": task,
                        "task_sha256": X.digest(task)}}},
                       poll=poll_output([{"pr": "7", "head": HEAD, "status": "published",
                                          "task_id": task["task_id"]},
                                         {"pr": "9", "head": "d" * 40, "status": "rejected",
                                          "reason": "request_oversized"}]),
                       requests=[collected()])
        index = run_export(root)
        self.assertEqual(index["counts"]["submissions"], 2)
        self.assertEqual(index["counts"]["facts"], 1)
        self.assertEqual(index["counts"]["submissions_without_fact"], 1)
        self.assertEqual(len(index["submissions"]), 2)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_the_lifecycle_set_is_closed_and_matches_the_issue(self):
        kind = self.schema["properties"]["kind"]
        self.assertEqual(set(kind["enum"]), {"REQUEST_CREATED", "REQUEST_VALIDATED",
                                             "REQUEST_REJECTED", "REQUEST_DUPLICATE",
                                             "REQUEST_REPLAY_REJECTED"})

    def test_every_fact_must_bind_an_identity(self):
        for key in ("request_id", "action_id", "submission", "source", "reason", "binding"):
            self.assertIn(key, self.schema["required"], key)

    def test_a_fact_may_not_claim_authority(self):
        authority = self.schema["properties"]["authority"]["properties"]
        for key, value in authority.items():
            self.assertEqual(value["const"], False, key)

    def test_the_contract_says_that_an_acceptance_needs_a_signed_task(self):
        notes = " ".join(self.schema["x-go-binding-proof"])
        self.assertIn("REQUEST_VALIDATED is the only positive fact", notes)
        self.assertIn("sha256(request_id)[:12]", notes)
        self.assertIn("never leaves REQUEST_VALIDATED", notes)

    def test_the_contract_refuses_to_let_a_ledger_event_be_authority(self):
        notes = " ".join(self.schema["x-go-non-authority"])
        self.assertIn("not a permission", notes)
        self.assertIn("never a success", notes)

    def test_the_two_level_observation_model_is_documented(self):
        model = self.schema["x-go-submission-level"]
        self.assertIn("fact must bind a request_id", model["SUBMISSION_OBSERVATION"])
        self.assertIn("REQUEST_FACT", model)

    def test_the_ledger_derived_reason_is_declared(self):
        derived = self.schema["x-go-ledger-derived-reasons"]["dry_run_no_task_published"]
        self.assertEqual(derived["class"], "NOT_ALLOWED")
        self.assertIn("published nothing", derived["meaning"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
