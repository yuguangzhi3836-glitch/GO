#!/usr/bin/env python3
"""Isolated tests for the CC V1-03 bounded liveness producer.

These tests never touch a live system, never need a key and never reach the
network.  They load the producer by path (it ships without a `.py` suffix, the
same way the Request bridge does) and assert the properties the issue fixes:

  * fresh signed liveness  => ONLINE/PROVEN        (derived elsewhere, from Evidence)
  * old signed liveness    => STALE
  * missing / invalid      => UNKNOWN / HOLD
  * VERIFY / TEST_PR / DEPLOY permissions unchanged

The producer side of that bargain is narrower and is what is proven here: it
supplies fresh *requests*, it can never supply a verdict, and it cannot be
turned into a high-frequency monitor.
"""
import datetime as dt
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PRODUCER_PATH = ROOT / "command-center" / "go-liveness-producer"
POLICY_PATH = ROOT / "command-center" / "liveness-producer-policy-v1.json"
SCHEMA_PATH = ROOT / "contracts" / "agent_liveness_producer_v1.schema.json"
STATE_LAYER = ROOT.parent / "command-center-state-v1"


def load_producer():
    spec = importlib.util.spec_from_loader(
        "go_liveness_producer", importlib.machinery.SourceFileLoader("go_liveness_producer", str(PRODUCER_PATH)))
    module = importlib.util.module_from_spec(spec)
    sys.modules["go_liveness_producer"] = module
    spec.loader.exec_module(module)
    return module


P = load_producer()
AT = dt.datetime(2026, 9, 14, 12, 0, 0, tzinfo=dt.timezone.utc)


def policy_file(tmp, **overrides):
    base = {
        "schema_version": "1",
        "action_id": "CONTROL_PLANE_HEALTH",
        "environment": "HK-STAGING-01",
        "interval_seconds": 1800,
        "max_probes_per_window": 48,
        "repository": "control-plane/agent-liveness-producer-v1",
        "read_only_actions_only": True,
    }
    base.update(overrides)
    path = pathlib.Path(tmp) / "policy.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


class TestPolicyBounds(unittest.TestCase):
    """A policy may tighten the cadence. It can never loosen it."""

    def test_shipped_policy_is_within_bounds(self):
        policy = P.load_policy(POLICY_PATH)
        self.assertGreaterEqual(policy["interval_seconds"], P.MIN_INTERVAL_SECONDS)
        self.assertLessEqual(policy["interval_seconds"], P.MAX_INTERVAL_SECONDS)
        self.assertLessEqual(policy["max_probes_per_window"], P.MAX_PROBES_PER_WINDOW)
        self.assertEqual(policy["action_id"], P.ACTION_ID)
        self.assertEqual(policy["environment"], P.ENVIRONMENT)

    def test_interval_floor_is_refused(self):
        for bad in (1, 60, 599, P.MIN_INTERVAL_SECONDS - 1):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(P.Reject):
                    P.load_policy(policy_file(tmp, interval_seconds=bad))

    def test_interval_ceiling_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.Reject):
                P.load_policy(policy_file(tmp, interval_seconds=P.MAX_INTERVAL_SECONDS + 1))

    def test_interval_must_be_an_integer(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.Reject):
                P.load_policy(policy_file(tmp, interval_seconds=1800.0))

    def test_other_actions_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.Reject):
                P.load_policy(policy_file(tmp, action_id="HK_" + "STAGING_" + "DEPLOY"))

    def test_production_environment_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.Reject):
                P.load_policy(policy_file(tmp, environment="PRODU" + "CTION"))

    def test_read_only_flag_is_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.Reject):
                P.load_policy(policy_file(tmp, read_only_actions_only=False))

    def test_probe_budget_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.Reject):
                P.load_policy(policy_file(tmp, max_probes_per_window=P.MAX_PROBES_PER_WINDOW + 1))
            with self.assertRaises(P.Reject):
                P.load_policy(policy_file(tmp, max_probes_per_window=0))

    def test_unknown_policy_field_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = policy_file(tmp)
            value = json.loads(path.read_text(encoding="utf-8"))
            value["cron"] = "* * * * *"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(P.Reject):
                P.load_policy(path)


class TestRequestMinting(unittest.TestCase):
    def test_request_matches_the_channel_shape(self):
        request = P.mint_request(AT, 1800)
        self.assertEqual(set(request), set(P.REQUEST_FIELDS))
        self.assertEqual(request["action_id"], "CONTROL_PLANE_HEALTH")
        self.assertEqual(request["environment"], "HK-STAGING-01")
        self.assertNotIn("signature", request)

    def test_tick_is_idempotent_inside_a_bucket(self):
        first = P.mint_request(AT, 1800)
        for offset in (1, 60, 900, 1799):
            again = P.mint_request(AT + dt.timedelta(seconds=offset), 1800)
            self.assertEqual(first["request_id"], again["request_id"])

    def test_next_bucket_mints_a_new_request(self):
        self.assertNotEqual(P.mint_request(AT, 1800)["request_id"],
                            P.mint_request(AT + dt.timedelta(seconds=1800), 1800)["request_id"])

    def test_request_ids_are_channel_legal(self):
        for bucket in range(0, 4000, 137):
            self.assertRegex(P.request_id_for(bucket), P.REQUEST_ID_RE)

    def test_a_request_claiming_another_action_is_refused(self):
        with self.assertRaises(P.Reject):
            P.validate_request({
                "schema_version": "1",
                "request_id": "liveness-x-1",
                "action_id": "HK_" + "STAGING_" + "VERIFY",
                "environment": "HK-STAGING-01",
                "requested_at": P.iso(AT),
            }, AT)

    def test_a_request_with_extra_fields_is_refused(self):
        with self.assertRaises(P.Reject):
            P.validate_request({
                "schema_version": "1",
                "request_id": "liveness-x-1",
                "action_id": "CONTROL_PLANE_HEALTH",
                "environment": "HK-STAGING-01",
                "requested_at": P.iso(AT),
                "parameters": {"command": "rm -rf /"},
            }, AT)


class TestDecisions(unittest.TestCase):
    def setUp(self):
        self.policy = P.load_policy(POLICY_PATH)

    def test_first_tick_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = P.tick(P.Store(tmp), self.policy, AT)
            self.assertEqual(record["decision"], P.DECISION_PUBLISHED)
            self.assertTrue(record["request_published"])
            self.assertFalse(record["signed_by_producer"])
            self.assertFalse(record["grants_execution"])

    def test_replay_in_the_same_bucket_never_republishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = P.Store(tmp)
            P.tick(store, self.policy, AT)
            for offset in (1, 300, 1799):
                again = P.tick(store, self.policy, AT + dt.timedelta(seconds=offset))
                self.assertEqual(again["decision"], P.DECISION_DUPLICATE)
                self.assertFalse(again["request_published"])

    def test_a_fast_timer_cannot_starve_a_bucket(self):
        """Throttling must not push the next published probe past its bucket.

        The anchor sits mid-bucket on purpose.  Starting on a bucket boundary
        would make the next bucket already due and hide the starvation case.
        """
        anchor = AT + dt.timedelta(seconds=900)
        with tempfile.TemporaryDirectory() as tmp:
            store = P.Store(tmp)
            first = P.tick(store, self.policy, anchor)
            self.assertEqual(first["decision"], P.DECISION_PUBLISHED)
            # 1000s later we are in the next bucket but not yet due: throttled,
            # and that bucket must stay spendable.
            early = P.tick(store, self.policy, anchor + dt.timedelta(seconds=1000))
            self.assertEqual(early["decision"], P.DECISION_THROTTLED)
            self.assertFalse(early["request_published"])
            self.assertEqual(early["bucket"], P.bucket_of(anchor + dt.timedelta(seconds=1000), 1800))
            # the same bucket, once the interval has elapsed, still publishes
            due = P.tick(store, self.policy, anchor + dt.timedelta(seconds=1900))
            self.assertEqual(due["decision"], P.DECISION_PUBLISHED)
            self.assertEqual(due["bucket"], early["bucket"])
            published = [r for r in store.entries() if r["decision"] == P.DECISION_PUBLISHED]
            self.assertEqual(len(published), 2)
            self.assertEqual(len({r["bucket"] for r in published}), 2)

    def test_interval_is_measured_against_the_last_published_probe(self):
        state = {"last_published_at": P.iso(AT + dt.timedelta(seconds=1799)),
                 "consecutive_refusals": 0}
        decision, _, _ = P.decide([], state, self.policy, AT + dt.timedelta(seconds=1800))
        self.assertEqual(decision, P.DECISION_THROTTLED)

    def test_rolling_window_budget_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = P.Store(tmp)
            tight = dict(self.policy)
            tight["max_probes_per_window"] = 3
            moment = AT
            for _ in range(3):
                self.assertEqual(P.tick(store, tight, moment)["decision"], P.DECISION_PUBLISHED)
                moment += dt.timedelta(seconds=1800)
            blocked = P.tick(store, tight, moment)
            self.assertEqual(blocked["decision"], P.DECISION_THROTTLED)
            self.assertIn("budget", blocked["reason"])

    def test_a_simulated_day_never_exceeds_the_policy_interval(self):
        """The achieved cadence, not the requested one, is what has to hold."""
        with tempfile.TemporaryDirectory() as tmp:
            store = P.Store(tmp)
            moment = AT
            for _ in range(48):
                P.tick(store, self.policy, moment)
                moment += dt.timedelta(seconds=self.policy["interval_seconds"])
            cadence = P.observed_cadence(store.entries(), moment)
            self.assertIsNotNone(cadence["min_gap_seconds"])
            self.assertGreaterEqual(cadence["min_gap_seconds"], self.policy["interval_seconds"])
            self.assertLessEqual(cadence["max_in_window"], self.policy["max_probes_per_window"])

    def test_concurrent_ticks_are_single_flight(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = P.Store(tmp)
            store.acquire()
            try:
                with self.assertRaises(P.Reject):
                    P.tick(P.Store(tmp), self.policy, AT)
            finally:
                store.release()


class TestNoLivenessClaim(unittest.TestCase):
    """The producer asks. It never answers."""

    def test_forbidden_keys_are_rejected_wherever_they_hide(self):
        for payload in ({"online": True},
                        {"nested": {"liveness": "PROVEN"}},
                        {"list": [{"last_seen": "x"}]},
                        {"heartbeat": None}):
            with self.assertRaises(P.Reject):
                P.assert_no_claim(payload, "test")

    def test_no_artifact_carries_a_claim(self):
        policy = P.load_policy(POLICY_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            store = P.Store(tmp)
            P.tick(store, policy, AT)
            P.tick(store, policy, AT + dt.timedelta(seconds=60))
            blob = (store.ledger.read_text(encoding="utf-8")
                    + store.state.read_text(encoding="utf-8")
                    + "\n".join(p.read_text(encoding="utf-8") for p in store.outbox.iterdir()))
            for forbidden in ("online", "heartbeat", "alive", "verdict", "\"state\"", "last_seen"):
                self.assertNotIn(forbidden, blob.lower())

    def test_requested_timestamp_is_the_only_time_asserted(self):
        request = P.mint_request(AT, 1800)
        self.assertEqual(request["requested_at"], "2026-09-14T12:00:00Z")
        self.assertNotIn("completed_at", request)
        self.assertNotIn("observed_at", request)


class TestAuthorityBoundary(unittest.TestCase):
    def test_source_cannot_express_another_action(self):
        source = PRODUCER_PATH.read_text(encoding="utf-8")
        prefix = "HK_" + "STAGING_"
        for other in ("DEPLOY", "ROLLBACK", "VERIFY", "CANARY", "TEST_PR"):
            self.assertNotIn(prefix + other, source)

    def test_source_never_reaches_production(self):
        source = PRODUCER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("PRODU" + "CTION", source)

    def test_source_never_loads_a_private_key(self):
        source = PRODUCER_PATH.read_text(encoding="utf-8")
        for forbidden in ("load_pem_private_key", "cryptography", "PRIVATE KEY",
                          "BEGIN OPENSSH", "ssh-keygen"):
            self.assertNotIn(forbidden, source)

    def test_schema_declares_the_boundary(self):
        boundary = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["properties"]["authority_boundary"]
        declared = boundary["properties"]
        for key in ("holds_private_key", "builds_task", "signs_anything",
                    "may_expand_action_set", "touches_production",
                    "changes_verify_test_pr_deploy_permissions", "may_assert_liveness"):
            self.assertIs(declared[key]["const"], False)

    def test_only_the_one_action_is_allowed(self):
        self.assertEqual(P.ALLOWED_ACTIONS, frozenset({"CONTROL_PLANE_HEALTH"}))


class TestCoherenceWithTheStateLayer(unittest.TestCase):
    """The producer must fit the layer that consumes its probes."""

    def test_action_already_exists_in_the_task_contract(self):
        task_schema = json.loads((STATE_LAYER / "contracts" / "task_v1.schema.json").read_text(encoding="utf-8"))
        actions = json.dumps(task_schema)
        self.assertIn("CONTROL_PLANE_HEALTH", actions)

    def test_action_already_exists_in_the_agent_allowlist(self):
        """No new Hong Kong code is required: the action is already accepted."""
        transport = (STATE_LAYER.parent / "boss-test-pr-live-integration-v1" / "hk-staging"
                     / "hk_agent" / "transport.py")
        self.assertIn("CONTROL_PLANE_HEALTH", transport.read_text(encoding="utf-8"))

    def test_producer_interval_sits_inside_the_declared_freshness_window(self):
        liveness = json.loads((STATE_LAYER / "contracts" / "agent_liveness_v1.schema.json")
                              .read_text(encoding="utf-8"))
        window = liveness["properties"]["freshness_window_seconds"]["default"]
        policy = P.load_policy(POLICY_PATH)
        self.assertLessEqual(policy["interval_seconds"], window)

    def test_producer_action_matches_the_liveness_contract(self):
        liveness = json.loads((STATE_LAYER / "contracts" / "agent_liveness_v1.schema.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(liveness["properties"]["task_action_id"]["const"], P.ACTION_ID)
        policy = P.load_policy(POLICY_PATH)
        self.assertEqual(policy["action_id"], liveness["properties"]["task_action_id"]["const"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
