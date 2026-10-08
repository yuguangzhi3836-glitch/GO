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
import hashlib
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

# The one Bridge source that still exists in this repository. It is kept because the
# scan below has to be able to fail against something real. The Old Command Center
# Bridge that owned the full six-action channel was retired on 2026-10-08, so the
# vocabulary this scan covers is narrower than it was while that component existed.
BRIDGE_SOURCES = (
    REPO / "control-plane" / "boss-test-pr-live-integration-v1" / "command-center"
    / "go-boss-request-bridge",
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


# A stable refusal code is written once as a module constant and raised by name, so
# neither literal pattern above can see it.  `Reject('literal')` also stays lowercase
# in those patterns, which would hide an ``E_...`` code even when it is a literal.
# Both shapes matter for the same reason: an unclassified refusal is reported to a
# Boss as UNCLASSIFIED_REJECT, and nothing else would catch the gap.
NAMED_CONSTANT = re.compile(r"^([A-Z][A-Z0-9_]*) = '([^']+)'$", re.M)
NAMED_RAISE = re.compile(r"Reject\(\s*([A-Z][A-Z0-9_]*)\s*\)")


def bridge_named_refusal_tokens():
    """Refusal codes the Bridge raises through a named module constant."""
    found = set()
    for path in BRIDGE_SOURCES:
        text = path.read_text(encoding="utf-8")
        values = dict(NAMED_CONSTANT.findall(text))
        for name in NAMED_RAISE.findall(text):
            if name in values:
                found.add(values[name])
    return found


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


def run_export_with_ledger(root, poll_paths, out="out", observations=None):
    """Export against explicit poll documents, optionally recording observations."""
    return X.export([str(root / "ledger.json")], poll_paths, str(root / "requests"),
                    str(root / out), str(CONTRACT), AT,
                    str(root / observations) if observations else None)


def mult_poll(root, instants, status="rejected", reason="pr_head_not_found"):
    """One poll document per instant, in the order given. Returns their paths."""
    return [write_poll(root, "poll-%02d.json" % index, instant, status=status, reason=reason)
            for index, instant in enumerate(instants)]


def write_poll(root, name, instant, status="rejected", reason="pr_head_not_found"):
    """One journalled Bridge poll output at a named path."""
    document = {"schema_version": "1", "journaled_at": instant,
                "bridge_output": poll_output([{"pr": "7", "head": HEAD, "status": status,
                                               "reason": reason}])}
    path = root / name
    path.write_bytes(X.canonical(document) + b"\n")
    return str(path)


def fact_bytes(root, out="out"):
    """Every file in the fact store, by name: the immutable store's exact bytes."""
    folder = root / out / X.FACTS_DIR
    return {path.name: path.read_bytes() for path in sorted(folder.glob("*.json"))}


def only_fact(root, out="out"):
    folder = root / out / X.FACTS_DIR
    names = sorted(p.name for p in folder.glob("*.json"))
    return [json.loads((folder / name).read_text(encoding="utf-8")) for name in names]


class VocabularyCoverageTests(unittest.TestCase):
    """The classification tables must stay closed and self-consistent.

    The scan that proved this component covered the whole Bridge refusal vocabulary
    read the Old Command Center Bridge, which was retired on 2026-10-08 with that
    component's source. Everything here that does not need that external source
    remains.
    """

    @classmethod
    def setUpClass(cls):
        cls.vocabulary = X.Vocabulary(CONTRACT)

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

    def test_a_non_terminal_ledger_state_is_reported_and_never_an_acceptance(self):
        """In flight is an answer; the property this test defends is unchanged.

        A non-terminal ledger state used to produce no fact at all. That made an
        in-flight Request indistinguishable from one the Bridge never mentioned,
        in a component whose whole purpose is to answer "why did my Request not
        become a Task". It is now reported as REQUEST_CREATED -- the weakest kind
        there is -- and the property this test has always existed to defend is
        pinned harder than before: no acceptance, no Task named, no proof needed,
        no reason claimed.
        """
        task = signed_task()
        for status in ("claiming", "prepared", "publishing"):
            root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                            "status": status, "request_id": REQUEST_ID, "task": task}}},
                           poll=poll_output([{"pr": "7", "head": HEAD, "status": "published",
                                              "task_id": task["task_id"]}]),
                           requests=[collected()])
            index = run_export(root)
            self.assertEqual(index["counts"]["by_kind"], {"REQUEST_CREATED": 1}, status)
            fact = only_fact(root)[0]
            self.assertEqual(fact["kind"], "REQUEST_CREATED", status)
            self.assertFalse(fact["binding"]["claimed"], status)
            self.assertFalse(fact["binding"]["proof_required"], status)
            self.assertEqual(fact["binding"]["proof"], "NOT_APPLICABLE", status)
            self.assertIsNone(fact["binding"]["task_id"], status)
            self.assertFalse(fact["reason"]["applicable"], status)
            self.assertIsNone(fact["reason"]["code"], status)
            # And the observation is no longer a gap: the submission is a fact.
            self.assertEqual(index["counts"]["submissions_without_fact"], 0, status)
            self.assertNotIn("SUBMISSION_WITHOUT_REQUEST_FACT",
                             [a["kind"] for a in index["anomalies"]], status)

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
        self.assertEqual(fact["first_observed_at"], "2026-09-14T12:00:00Z")
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


# --------------------------------------------------------------------------- #
# Semantic identity: aggregate first, then mint
#
# The rule under test is that a fact's identity is its semantics -- the Request,
# the normalized outcome, the normalized reason and the normalized binding
# result -- and that the instant it carries is the earliest instant any
# observation of those semantics was placed at, never the newest. Before this,
# the identity included the observation instant, so a submission that sat in one
# state while the Bridge was polled repeatedly minted one immutable fact per
# poll: 36 fact files for 18 submissions, and a Git history that grew with
# observations rather than with outcomes.
# --------------------------------------------------------------------------- #
class SemanticDedupTests(unittest.TestCase):
    T1, T2, T3 = ("2026-09-14T12:00:00Z", "2026-09-14T12:05:00Z", "2026-09-14T12:10:00Z")

    def test_one_outcome_observed_three_times_is_one_fact_at_the_first_instant(self):
        root = workdir(requests=[collected()])
        index = run_export_with_ledger(root, mult_poll(root, [self.T1, self.T2, self.T3]),
                                       observations="observations.json")
        self.assertEqual(index["counts"]["facts"], 1, index["counts"])
        fact = only_fact(root)[0]
        self.assertEqual(fact["first_observed_at"], self.T1)
        self.assertEqual(fact["kind"], "REQUEST_REJECTED")
        # The moving parts live in the local ledger, and nowhere else.
        ledger = json.loads((root / "observations.json").read_text(encoding="utf-8"))
        entry = ledger["facts"][fact["semantic_id"]]
        self.assertEqual(entry["semantic_fact_id"], fact["fact_id"])
        self.assertEqual(entry["first_seen_at"], self.T1)
        self.assertEqual(entry["last_seen_at"], self.T3)
        self.assertEqual(entry["observation_count"], 3)
        self.assertEqual(entry["observed_instants"], [self.T1, self.T2, self.T3])
        # And the fact itself must not carry any of them.
        self.assertNotIn("last_seen_at", fact)
        self.assertNotIn("observation_count", fact)

    def test_the_first_seen_instant_never_moves_to_a_later_observation(self):
        root = workdir(requests=[collected()])
        run_export_with_ledger(root, mult_poll(root, [self.T1]), observations="observations.json")
        before = only_fact(root)[0]
        run_export_with_ledger(root, mult_poll(root, [self.T1, self.T2, self.T3]),
                               observations="observations.json")
        after = only_fact(root)[0]
        self.assertEqual(before["fact_id"], after["fact_id"])
        self.assertEqual(after["first_observed_at"], self.T1)

    def test_reversing_the_input_order_changes_not_one_byte(self):
        forward_root = workdir(requests=[collected()])
        forward = mult_poll(forward_root, [self.T1, self.T2, self.T3])
        run_export_with_ledger(forward_root, forward, observations="observations.json")

        reverse_root = workdir(requests=[collected()])
        same = mult_poll(reverse_root, [self.T1, self.T2, self.T3])
        run_export_with_ledger(reverse_root, list(reversed(same)), observations="observations.json")

        self.assertEqual(fact_bytes(forward_root), fact_bytes(reverse_root))
        self.assertEqual(only_fact(forward_root)[0]["fact_id"], only_fact(reverse_root)[0]["fact_id"])

    def test_a_new_observation_of_the_same_outcome_mints_nothing(self):
        root = workdir(requests=[collected()])
        first = run_export_with_ledger(root, mult_poll(root, [self.T1]),
                                       observations="observations.json")
        before = fact_bytes(root)
        self.assertEqual(first["counts"]["facts"], 1)
        # The same outcome, seen again later: a newer instant and nothing else.
        again = run_export_with_ledger(root, mult_poll(root, [self.T1, self.T2]),
                                       observations="observations.json")
        self.assertEqual(again["counts"]["facts"], 1, again["counts"])
        self.assertEqual(before, fact_bytes(root), "the immutable store moved")
        third = run_export_with_ledger(root, mult_poll(root, [self.T1, self.T2, self.T3]),
                                       observations="observations.json")
        self.assertEqual(third["counts"]["facts"], 1, third["counts"])
        self.assertEqual(before, fact_bytes(root), "the immutable store moved")

    def test_a_changed_outcome_is_exactly_one_new_semantic_fact(self):
        """A real state change adds one fact, and the earlier one stays.

        The exporter has no REQUEST_CREATED kind -- that state is the projection's
        "no fact was observed", not something the Bridge reports -- so the pair is
        expressed with two refusal semantics for the same Request: the reason it
        was refused changed between observations. What is pinned is the rule, not
        the spelling of the pair: unchanged semantics mint nothing, changed
        semantics mint exactly one.
        """
        root = workdir(requests=[collected()])
        first_poll = write_poll(root, "a.json", self.T1, reason="pr_head_not_found")
        first = run_export_with_ledger(root, [first_poll], observations="observations.json")
        self.assertEqual(first["counts"]["facts"], 1, first["counts"])
        before = only_fact(root)[0]

        second_poll = write_poll(root, "b.json", self.T2, reason="duplicate_request_id")
        index = run_export_with_ledger(root, [first_poll, second_poll],
                                       observations="observations.json")
        after = only_fact(root)
        self.assertEqual(index["counts"]["facts"], 2, index["counts"])
        self.assertEqual(len(after), 2)
        ids = {fact["fact_id"] for fact in after}
        self.assertIn(before["fact_id"], ids, "the earlier fact was rewritten away")
        self.assertEqual({fact["reason"]["code"] for fact in after},
                         {"pr_head_not_found", "duplicate_request_id"})
        self.assertEqual({fact["kind"] for fact in after},
                         {"REQUEST_REJECTED", "REQUEST_DUPLICATE"})
        # Only the new semantics was minted, at its own first instant.
        fresh = [fact for fact in after if fact["fact_id"] != before["fact_id"]][0]
        self.assertEqual(fresh["first_observed_at"], self.T2)

    def test_created_then_validated_is_exactly_two_semantic_facts(self):
        """A lifecycle transition is a real change, and it is never deduplicated.

        The Bridge speaks twice about one Request: first that it is publishing,
        then that it published. Two different outcomes of one Request identity, so
        two facts -- and the earlier one survives the later one, because the store
        is append-only and the identity of a fact does not move.

        REQUEST_CREATED is the interesting half. It is the state in which a Request
        has neither become a Task nor been refused, so the semantic identity has to
        treat it as an outcome of its own rather than as an absence of one.
        """
        root = workdir(requests=[collected()])
        task = signed_task()
        ledger = root / "ledger.json"

        # T1: the Bridge is publishing. Its own poll output carries the instant.
        ledger.write_bytes(X.canonical({"version": 1, "requests": {"7:" + HEAD: {
            "status": "publishing", "request_id": REQUEST_ID, "task": task}}}) + b"\n")
        in_flight = write_poll(root, "in-flight.json", self.T1, status="published")
        first = run_export_with_ledger(root, [in_flight], observations="observations.json")
        self.assertEqual(first["counts"]["by_kind"], {"REQUEST_CREATED": 1}, first["counts"])
        created_bytes = fact_bytes(root)

        # T2: the Bridge published. A different outcome, so a second fact.
        ledger.write_bytes(X.canonical({"version": 1, "requests": {"7:" + HEAD: {
            "status": "published", "request_id": REQUEST_ID, "task": task,
            "task_sha256": X.digest(task), "task_commit": "b" * 40}}}) + b"\n")
        published = write_poll(root, "published.json", self.T2, status="published")
        second = run_export_with_ledger(root, [in_flight, published],
                                        observations="observations.json")
        self.assertEqual(second["counts"]["by_kind"], {"REQUEST_VALIDATED": 1},
                         second["counts"])

        facts = {fact["kind"]: fact for fact in only_fact(root)}
        self.assertEqual(sorted(facts), ["REQUEST_CREATED", "REQUEST_VALIDATED"],
                         "a lifecycle transition was deduplicated away")
        self.assertEqual(facts["REQUEST_CREATED"]["first_observed_at"], self.T1)
        self.assertEqual(facts["REQUEST_VALIDATED"]["first_observed_at"], self.T2)
        self.assertNotEqual(facts["REQUEST_CREATED"]["semantic_id"],
                            facts["REQUEST_VALIDATED"]["semantic_id"])
        # The created fact asserts nothing; the validated one makes the claim.
        self.assertFalse(facts["REQUEST_CREATED"]["binding"]["claimed"])
        self.assertIsNone(facts["REQUEST_CREATED"]["binding"]["task_id"])
        self.assertFalse(facts["REQUEST_CREATED"]["binding"]["proof_required"])
        self.assertTrue(facts["REQUEST_VALIDATED"]["binding"]["claimed"])
        # And the earlier fact was neither rewritten nor removed by the later one.
        for name, body in created_bytes.items():
            self.assertEqual(fact_bytes(root)[name], body, "an immutable fact moved")
        self.assertEqual(len(fact_bytes(root)), 2)

    def test_the_same_id_with_different_bytes_is_refused_not_overwritten(self):
        root = workdir(requests=[collected()])
        run_export_with_ledger(root, mult_poll(root, [self.T1]), observations="observations.json")
        fact = only_fact(root)[0]
        path = root / "out" / X.FACTS_DIR / (fact["fact_id"] + ".json")
        # Same id, different body: the one thing an immutable store must never do
        # is quietly accept this.
        forged = dict(fact, binding=dict(fact["binding"], proof="TASK_SIGNATURE_AND_DIGEST_PREFIX"))
        path.write_bytes(X.canonical(forged) + b"\n")
        with self.assertRaises(X.Refuse) as caught:
            run_export_with_ledger(root, mult_poll(root, [self.T1]),
                                   observations="observations.json")
        self.assertIn("fact_id_collision", str(caught.exception))
        self.assertEqual(path.read_bytes(), X.canonical(forged) + b"\n")

    def test_a_historical_timestamp_based_fact_is_preserved_untouched(self):
        """The store is append-only across the change of identity rule."""
        root = workdir(requests=[collected()])
        folder = root / "out" / X.FACTS_DIR
        folder.mkdir(parents=True)
        historical_name = "request-fact-" + "0" * 32 + ".json"
        historical = X.canonical({
            "schema_version": "1", "kind": "REQUEST_VALIDATED",
            "request_id": "an-earlier-request", "action_id": "HK_STAGING_VERIFY",
            "environment": "HK-STAGING-01", "nonce": None,
            "observed_at": "2026-09-01T00:00:00Z", "time_source": "POLL_JOURNAL",
            "submission": {"pr_number": "1", "head_sha": "b" * 40,
                           "submission_key": "1:" + "b" * 40},
            "source": None,
            "reason": {"applicable": False, "code": None, "class": None, "origin": None,
                       "preserved_verbatim": True},
            "binding": {"claimed": True, "task_id": None, "task_sha256": None,
                        "task_commit": None, "proof_required": True, "proof": "X"},
            "authority": {"is_execution_authority": False}}) + b"\n"
        (folder / historical_name).write_bytes(historical)

        index = run_export_with_ledger(root, mult_poll(root, [self.T1]),
                                       observations="observations.json")
        self.assertEqual((folder / historical_name).read_bytes(), historical,
                         "the exporter rewrote a historical fact")
        self.assertEqual(index["counts"]["facts"], 1, "only this run's facts are counted")
        names = sorted(fact_bytes(root))
        self.assertEqual(len(names), 2, names)
        self.assertIn(historical_name, names)
        minted = [name for name in names if name != historical_name][0]
        self.assertEqual(json.loads((folder / minted).read_text(encoding="utf-8"))["kind"],
                         "REQUEST_REJECTED")

    def test_the_observation_ledger_is_never_written_inside_the_export_root(self):
        root = workdir(requests=[collected()])
        run_export_with_ledger(root, mult_poll(root, [self.T1]), observations="observations.json")
        self.assertTrue((root / "observations.json").is_file())
        self.assertFalse((root / "out" / X.OBSERVATION_LEDGER_NAME).exists())
        self.assertFalse((root / "out" / X.FACTS_DIR / X.OBSERVATION_LEDGER_NAME).exists())

    def test_the_identity_excludes_every_time_field_and_the_submission(self):
        self.assertNotIn("first_observed_at", X.SEMANTIC_IDENTITY_KEYS)
        self.assertNotIn("time_source", X.SEMANTIC_IDENTITY_KEYS)
        self.assertNotIn("submission", X.SEMANTIC_IDENTITY_KEYS)
        self.assertIn("request_id", X.SEMANTIC_IDENTITY_KEYS)
        self.assertIn("reason", X.SEMANTIC_IDENTITY_KEYS)
        self.assertIn("binding", X.SEMANTIC_IDENTITY_KEYS)
        self.assertEqual(set(X.FACT_ID_EXCLUDED),
                         {"fact_id", "first_observed_at", "time_source"})
        # semantic_id is covered by the id digest, so it cannot be edited freely.
        self.assertNotIn("semantic_id", X.FACT_ID_EXCLUDED)


# --------------------------------------------------------------------------- #
# The action registry, pinned against the contract this component publishes
# --------------------------------------------------------------------------- #
def health_task(request_id=REQUEST_ID):
    """A read-only CONTROL_PLANE_HEALTH Task, as the Bridge signs one.

    `parameters` is empty, which is the whole point of the action: there is no
    image, service, path, environment file, command or plan for a caller to steer.
    """
    return {"schema_version": "1",
            "task_id": "go-boss-health-20260915T153628Z-"
                       + hashlib.sha256(request_id.encode()).hexdigest()[:12],
            "nonce": "synthetic-health-nonce", "issued_at": "2026-09-14T11:00:05Z",
            "expires_at": "2026-09-14T11:15:05Z", "authority": "GO-COMMAND-CENTER",
            "environment": "HK-STAGING-01", "action_id": "CONTROL_PLANE_HEALTH",
            "parameters": {}, "signature": "0" * 128}


class ActionRegistryTests(unittest.TestCase):
    """The exporter's action list is the enum of the contract it publishes."""

    def test_the_registry_is_exactly_the_published_contract_enum(self):
        """Pinned to the contract this component publishes, not to a copy of this tuple.

        Comparing this constant with a fixture built from this constant cannot fail,
        so it protects nothing. The published fact contract is a separate artifact
        this component owns and a consumer validates against, so that is what the
        exporter's list has to equal. The Bridge config this used to be pinned to
        was retired on 2026-10-08 with the Old Command Center.
        """
        schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(sorted(X.ACTION_IDS),
                         sorted(schema["properties"]["action_id"]["enum"]))

    def test_a_published_health_request_mints_a_validated_fact(self):
        """The live defect, pinned. Measured on the Command Center host:

            export_facts            19
            submissions_without_fact 5   (three of them liveness probes)
            anomaly per probe        SUBMISSION_WITHOUT_REQUEST_FACT
                                     detail LEDGER:request_action_unresolved
            projection               lifecycle REQUEST_CREATED, fate
                                     NO_BRIDGE_FACT_OBSERVED, facts 0

        The Bridge had settled and executed each probe and the agent had published
        signed Evidence for it; the fact store said nothing had been observed, and
        every probe added one more permanent anomaly -- growth on a timer, which is
        the thing this whole line of work exists to prevent.
        """
        task = health_task()
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "published", "request_id": REQUEST_ID, "task": task,
                        "task_sha256": X.digest(task), "task_commit": "b" * 40}}},
                       poll=poll_output([{"pr": "7", "head": HEAD, "status": "published",
                                          "task_id": task["task_id"]}]),
                       requests=[collected(body=request_body(
                           action_id="CONTROL_PLANE_HEALTH"))])
        index = run_export(root)
        self.assertEqual(index["counts"]["by_kind"], {"REQUEST_VALIDATED": 1},
                         index["anomalies"])
        self.assertEqual(index["counts"]["submissions_without_fact"], 0)
        self.assertEqual([a["kind"] for a in index["anomalies"]], [])
        fact = only_fact(root)[0]
        self.assertEqual(fact["action_id"], "CONTROL_PLANE_HEALTH")
        self.assertEqual(fact["kind"], "REQUEST_VALIDATED")
        self.assertEqual(fact["binding"]["task_id"], task["task_id"])

    def test_an_action_outside_the_registry_is_still_refused(self):
        """Widening the registry must not turn it into a membership-free pass.

        An action the Bridge would refuse is one nothing may be built on, so a
        submission claiming it yields no fact and keeps saying so.

        HK_STAGING_CANARY was this test's example until it joined the registry,
        and HK_STAGING_ROLLBACK was the next one until it joined too. Because the
        property has to survive every widening, it is asserted against a name one
        revision ahead of the registry, which is never the one that moves.
        """
        task = dict(health_task(), action_id="HK_STAGING_ROLLBACK_V2")
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "published", "request_id": REQUEST_ID, "task": task,
                        "task_sha256": X.digest(task)}}},
                       requests=[collected(body=request_body(
                           action_id="HK_STAGING_ROLLBACK_V2"))])
        index = run_export(root)
        self.assertEqual(index["counts"]["facts"], 0)
        self.assertEqual([a["kind"] for a in index["anomalies"]],
                         ["SUBMISSION_WITHOUT_REQUEST_FACT"])
        self.assertIn("request_action_unresolved", index["anomalies"][0]["detail"])

    def test_a_rollback_submission_inside_the_registry_does_mint_a_fact(self):
        """Joining the registry is not a pass either: it is the same judgement.

        ROLLBACK resolves only because the ledger carries a published Task the
        Bridge signed under that action, which is the same evidence every other
        action has to produce. The fact must name the action the Bridge signed.
        """
        task = dict(health_task(), action_id="HK_STAGING_ROLLBACK",
                    task_id="go-boss-hk-staging-rollback-20260915T153628Z-"
                            + hashlib.sha256(REQUEST_ID.encode()).hexdigest()[:12],
                    parameters={"release_id": "boss-rollback-1",
                                "source_deploy_task_id": "go-boss-hk-staging-deploy-1",
                                "approval_id": "approval-rollback-1"})
        root = workdir(ledger={"version": 1, "requests": {"7:" + HEAD: {
                        "status": "published", "request_id": REQUEST_ID, "task": task,
                        "task_sha256": X.digest(task)}}},
                       requests=[collected(body=request_body(
                           action_id="HK_STAGING_ROLLBACK"))])
        index = run_export(root)
        self.assertEqual(index["counts"]["by_kind"], {"REQUEST_VALIDATED": 1},
                         index["anomalies"])
        self.assertEqual(index["counts"]["submissions_without_fact"], 0)
        self.assertEqual([a["kind"] for a in index["anomalies"]], [])
        fact = only_fact(root)[0]
        self.assertEqual(fact["action_id"], "HK_STAGING_ROLLBACK")
        self.assertEqual(fact["kind"], "REQUEST_VALIDATED")
        self.assertEqual(fact["binding"]["task_id"], task["task_id"])


class InjectedSourceTests(unittest.TestCase):
    """The scan must be able to fail, or its all-clear means nothing.

    A scan that read the wrong files, or matched the wrong shape, reports exactly the same
    green as a repository that really has a token nobody classified. The only way to tell
    those two apart is to put a token in front of it that is certainly unclassified and
    require it to be seen -- once per call shape.

    The sources are copied, not edited: this is a claim about the scan, and it must not
    change the repository the scan is about.
    """

    LITERAL = "a_refusal_the_contract_never_classified"
    CODE = "E_A_CODE_NOBODY_CLASSIFIED"

    @classmethod
    def setUpClass(cls):
        cls.vocabulary = X.Vocabulary(CONTRACT)

    def _injected(self, extra):
        """Point the scan at copies of the Bridge sources, with `extra` appended."""
        scratch = tempfile.TemporaryDirectory(prefix="go-cc-visibility-")
        self.addCleanup(scratch.cleanup)
        root = pathlib.Path(scratch.name)
        original = BRIDGE_SOURCES
        self.addCleanup(lambda: globals().__setitem__("BRIDGE_SOURCES", original))
        copies = []
        for path in BRIDGE_SOURCES:
            target = root / path.name
            target.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
            copies.append(target)
        globals()["BRIDGE_SOURCES"] = tuple(copies)

    def test_the_scan_sees_an_injected_reject_literal(self):
        self._injected("\nraise Reject('%s')\n" % self.LITERAL)
        direct, _ = bridge_refusal_tokens()
        self.assertIn(self.LITERAL, direct)
        self.assertEqual(self.vocabulary.classify(self.LITERAL), "UNCLASSIFIED_REJECT")

    def test_the_scan_sees_an_injected_reason_argument(self):
        self._injected("\ndef check(plan, fields):\n    exact(plan, fields, '%s')\n"
                       % self.LITERAL)
        _, passed = bridge_refusal_tokens()
        self.assertIn(self.LITERAL, passed)
        self.assertEqual(self.vocabulary.classify(self.LITERAL), "UNCLASSIFIED_REJECT")

    def test_the_scan_sees_an_injected_named_constant(self):
        self._injected("\n%s = '%s'\nraise Reject(%s)\n" % (self.CODE, self.CODE, self.CODE))
        named = bridge_named_refusal_tokens()
        self.assertIn(self.CODE, named)
        self.assertEqual(self.vocabulary.classify(self.CODE), "UNCLASSIFIED_REJECT")

    def test_the_probe_does_not_touch_the_repository(self):
        # Copies, not edits: the files the scan is about must be exactly as they were.
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in BRIDGE_SOURCES}
        self._injected("\nraise Reject('%s')\n" % self.LITERAL)
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before}
        self.assertEqual(before, after)

    def test_the_scan_still_points_at_the_repository(self):
        # If a probe's cleanup leaked, this test would be reading a temporary directory --
        # and so would every test after it, while still reporting green.
        for path in BRIDGE_SOURCES:
            self.assertTrue(str(path).startswith(str(REPO)), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
