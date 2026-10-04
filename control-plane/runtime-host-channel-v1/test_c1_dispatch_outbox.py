"""Offline tests for the C1 dispatch outbox - the exactly-once model.

No network, no credential, no GitHub, no Runtime database. `send` and `find_run` are
injected, which is what makes the timeout and ambiguous-outcome paths reproducible.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402

TASK = "rt_" + "f" * 32
RUN_ID = 36871111111


def sealed_result(task, attempt, run_id=RUN_ID):
    return {
        "version": 1,
        "kind": contract.RESULT_KIND,
        "runtime_task_id": task,
        "attempt": attempt,
        "execution_request_id": contract.execution_request_id(task, attempt),
        "github_run_id": run_id,
        "github_run_attempt": 1,
        "provider": contract.PROVIDER,
        "model": "gpt-5.6-sol",
        "response_id": "resp_1",
        "status": "SUCCEEDED",
        "output_sha256": contract.output_sha256(contract.EXPECTED_OUTPUT),
        "output": contract.EXPECTED_OUTPUT,
        "accepted": True,
        "reused_terminal_result": False,
        "authorizes_any_action": False,
    }


class RecordingSender:
    """A fake dispatcher that records every call, so 'sent twice' is observable."""

    def __init__(self, behaviour="sent"):
        self.behaviour = behaviour
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.behaviour == "sent":
            return ("sent", RUN_ID)
        if self.behaviour == "sent_without_run_id":
            return ("sent", None)
        if self.behaviour == "ambiguous":
            return ("ambiguous", "dispatch_outcome_unknown")
        raise AssertionError("unexpected behaviour %r" % self.behaviour)


class OutboxCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "c1-outbox.db")
        self.outbox = outbox_mod.DispatchOutbox(self.db)

    def tearDown(self):
        self.outbox.close()
        self._tmp.cleanup()

    def request_id(self, attempt=1, task=TASK):
        return contract.execution_request_id(task, attempt)


class RegistrationTests(OutboxCase):
    def test_the_intent_is_durable_before_anything_is_sent(self):
        registered = self.outbox.register(TASK, 1)
        self.assertEqual(registered["action"], "DISPATCH")
        self.assertEqual(registered["request"]["execution_request_id"], self.request_id())
        self.assertEqual(self.outbox.snapshot(self.request_id())["state"], outbox_mod.INTENT)
        self.assertEqual(self.outbox.snapshot(self.request_id())["dispatches_sent"], 0)

    def test_registering_twice_never_offers_a_second_dispatch(self):
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(self.request_id(), github_run_id=RUN_ID)
        self.assertEqual(self.outbox.register(TASK, 1)["action"], "AWAIT_RESULT")

    def test_an_ambiguous_first_dispatch_offers_a_lookup_not_a_redispatch(self):
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(self.request_id())
        self.assertEqual(self.outbox.register(TASK, 1)["action"], "LOOKUP_RUN")

    def test_a_different_attempt_is_a_different_execution_identity(self):
        self.outbox.register(TASK, 1)
        second = self.outbox.register(TASK, 2)
        self.assertEqual(second["action"], "DISPATCH")
        self.assertNotEqual(second["request"]["execution_request_id"], self.request_id())

    def test_an_unknown_identity_cannot_be_advanced(self):
        with self.assertRaises(contract.Refused) as caught:
            self.outbox.next_action("0" * 64)
        self.assertEqual(caught.exception.reason, "UNKNOWN_EXECUTION_REQUEST_ID")


class ExactlyOnceTests(OutboxCase):
    def test_a_second_dispatch_for_the_same_identity_is_refused(self):
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(self.request_id(), github_run_id=RUN_ID)
        with self.assertRaises(contract.Refused) as caught:
            self.outbox.record_dispatch_sent(self.request_id(), github_run_id=RUN_ID)
        self.assertEqual(caught.exception.reason, "SECOND_DISPATCH_FORBIDDEN")
        self.assertEqual(self.outbox.snapshot(self.request_id())["dispatches_sent"], 1)

    def test_an_ambiguous_outcome_routes_to_lookup_not_to_a_second_post(self):
        sender = RecordingSender("ambiguous")
        first = outbox_mod.drive_once(self.outbox, TASK, 1, send=sender, find_run=lambda _n: None)
        self.assertEqual(first["action"], "DISPATCH_AMBIGUOUS")
        self.assertEqual(len(sender.calls), 1)

        second = outbox_mod.drive_once(self.outbox, TASK, 1, send=sender,
                                       find_run=lambda _n: RUN_ID)
        self.assertEqual(second["action"], "RUN_BOUND")
        self.assertEqual(len(sender.calls), 1, "a second POST was sent after an ambiguity")

    def test_a_sent_without_a_run_id_is_resolved_by_lookup(self):
        sender = RecordingSender("sent_without_run_id")
        first = outbox_mod.drive_once(self.outbox, TASK, 1, send=sender, find_run=lambda _n: None)
        self.assertEqual(first["action"], "DISPATCHED")
        self.assertFalse(first["resolved"])
        self.assertEqual(len(sender.calls), 1)

        second = outbox_mod.drive_once(self.outbox, TASK, 1, send=sender, find_run=lambda _n: None)
        self.assertEqual(second["action"], "LOOKUP_RUN_NOT_FOUND")
        self.assertEqual(len(sender.calls), 1)

        third = outbox_mod.drive_once(self.outbox, TASK, 1, send=sender, find_run=lambda _n: RUN_ID)
        self.assertEqual(third["action"], "RUN_BOUND")
        self.assertEqual(len(sender.calls), 1)

    def test_the_lookup_uses_the_deterministic_run_name(self):
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(self.request_id())
        seen = []

        def find_run(name):
            seen.append(name)
            return RUN_ID

        outbox_mod.drive_once(self.outbox, TASK, 1, send=RecordingSender(), find_run=find_run)
        self.assertEqual(seen, [contract.run_identity_name(TASK, 1, self.request_id())])

    def test_a_lookup_that_finds_nothing_does_not_trigger_a_redispatch(self):
        sender = RecordingSender("ambiguous")
        outbox_mod.drive_once(self.outbox, TASK, 1, send=sender, find_run=lambda _n: None)
        for _ in range(3):
            result = outbox_mod.drive_once(self.outbox, TASK, 1, send=sender,
                                           find_run=lambda _n: None)
            self.assertEqual(result["action"], "LOOKUP_RUN_NOT_FOUND")
        self.assertEqual(len(sender.calls), 1)

    def test_a_terminal_result_is_reused_instead_of_dispatching_again(self):
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(self.request_id(), github_run_id=RUN_ID)
        self.outbox.record_result(self.request_id(), sealed_result(TASK, 1),
                                  runtime_task_id=TASK, attempt=1)
        self.outbox.mark_completed(self.request_id())

        sender = RecordingSender()
        result = outbox_mod.drive_once(self.outbox, TASK, 1, send=sender, find_run=lambda _n: None)
        self.assertEqual(result["action"], "REUSE_TERMINAL")
        self.assertEqual(len(sender.calls), 0)
        self.assertEqual(result["result"]["output"], contract.EXPECTED_OUTPUT)

    def test_the_counter_survives_a_process_restart(self):
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(self.request_id())
        self.outbox.close()

        reopened = outbox_mod.DispatchOutbox(self.db)
        try:
            sender = RecordingSender()
            result = outbox_mod.drive_once(reopened, TASK, 1, send=sender,
                                           find_run=lambda _n: RUN_ID)
            self.assertEqual(result["action"], "RUN_BOUND")
            self.assertEqual(len(sender.calls), 0,
                             "a dispatch was sent again after a restart")
        finally:
            reopened.close()


class ResultTests(OutboxCase):
    def _sealed_run(self, attempt=1):
        self.outbox.register(TASK, attempt)
        self.outbox.record_dispatch_sent(self.request_id(attempt), github_run_id=RUN_ID)

    def test_identical_bytes_are_idempotent_and_different_bytes_refuse(self):
        self._sealed_run()
        document = sealed_result(TASK, 1)
        self.outbox.record_result(self.request_id(), document, runtime_task_id=TASK, attempt=1)
        self.outbox.record_result(self.request_id(), dict(document),
                                  runtime_task_id=TASK, attempt=1)

        conflicting = sealed_result(TASK, 1, run_id=RUN_ID + 1)
        with self.assertRaises(contract.Refused) as caught:
            self.outbox.record_result(self.request_id(), conflicting,
                                      runtime_task_id=TASK, attempt=1)
        self.assertEqual(caught.exception.reason, "CONFLICTING_RESULT_BYTES")

    def test_a_malformed_result_is_refused_before_it_is_stored(self):
        self._sealed_run()
        with self.assertRaises(contract.Refused):
            self.outbox.record_result(self.request_id(), {"kind": "not-a-result"},
                                      runtime_task_id=TASK, attempt=1)
        self.assertIsNone(self.outbox.terminal_result(self.request_id()))
        self.assertEqual(self.outbox.snapshot(self.request_id())["state"], outbox_mod.RUN_BOUND)

    def test_a_result_for_another_task_or_attempt_is_refused(self):
        self._sealed_run()
        with self.assertRaises(contract.Refused):
            self.outbox.record_result(self.request_id(), sealed_result("rt_" + "9" * 32, 1),
                                      runtime_task_id=TASK, attempt=1)
        with self.assertRaises(contract.Refused):
            self.outbox.record_result(self.request_id(), sealed_result(TASK, 2),
                                      runtime_task_id=TASK, attempt=1)

    def test_a_duplicate_result_does_not_change_the_stored_bytes(self):
        self._sealed_run()
        document = sealed_result(TASK, 1)
        self.outbox.record_result(self.request_id(), document, runtime_task_id=TASK, attempt=1)
        digest = self.outbox.snapshot(self.request_id())["result_sha256"]
        self.outbox.record_result(self.request_id(), document, runtime_task_id=TASK, attempt=1)
        self.assertEqual(self.outbox.snapshot(self.request_id())["result_sha256"], digest)

    def test_completion_requires_a_sealed_result(self):
        self._sealed_run()
        with self.assertRaises(contract.Refused) as caught:
            self.outbox.mark_completed(self.request_id())
        self.assertEqual(caught.exception.reason, "COMPLETION_WITHOUT_A_SEALED_RESULT")
        with self.assertRaises(contract.Refused):
            self.outbox.completion_binding(self.request_id())

    def test_completion_binding_carries_the_exact_attempt_for_runtime_fencing(self):
        self._sealed_run(attempt=3)
        self.outbox.record_result(self.request_id(3), sealed_result(TASK, 3),
                                  runtime_task_id=TASK, attempt=3)
        binding = self.outbox.completion_binding(self.request_id(3))
        # The owner cell is part of the binding: one Builder executor serves twelve cells,
        # so "which cell must be told" is read back from the identity rather than assumed
        # by the caller. A row registered with no explicit request is a C1 row.
        self.assertEqual(binding, {"owner_c": "C1", "runtime_task_id": TASK,
                                   "expected_attempt": 3})

    def test_a_stale_attempt_cannot_be_completed(self):
        self._sealed_run(attempt=1)
        self.outbox.record_result(self.request_id(1), sealed_result(TASK, 1),
                                  runtime_task_id=TASK, attempt=1)
        # A later attempt is a different execution and has no sealed result of its own.
        self.outbox.register(TASK, 2)
        with self.assertRaises(contract.Refused):
            self.outbox.completion_binding(self.request_id(2))

    def test_completion_is_idempotent(self):
        self._sealed_run()
        self.outbox.record_result(self.request_id(), sealed_result(TASK, 1),
                                  runtime_task_id=TASK, attempt=1)
        self.outbox.mark_completed(self.request_id())
        self.outbox.mark_completed(self.request_id())
        self.assertEqual(self.outbox.snapshot(self.request_id())["state"], outbox_mod.COMPLETED)
        self.assertEqual(self.outbox.next_action(self.request_id()), "REUSE_TERMINAL")

    def test_a_failed_execution_is_terminal_too(self):
        output = "not the smoke string"
        failed = sealed_result(TASK, 1)
        failed.update({"status": "FAILED", "accepted": False, "output": output,
                       "output_sha256": contract.output_sha256(output),
                       "failure_reason": "MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING"})
        self._sealed_run()
        self.outbox.record_result(self.request_id(), failed, runtime_task_id=TASK, attempt=1)
        self.assertEqual(self.outbox.next_action(self.request_id()), "REUSE_TERMINAL")

        sender = RecordingSender()
        result = outbox_mod.drive_once(self.outbox, TASK, 1, send=sender, find_run=lambda _n: None)
        self.assertEqual(result["action"], "REUSE_TERMINAL")
        self.assertEqual(len(sender.calls), 0)


class ActionSurfaceTests(OutboxCase):
    def test_the_outbox_never_holds_a_model_credential(self):
        text = (HERE / "c1_dispatch_outbox.py").read_text(encoding="utf-8")
        for forbidden in ("OPENAI_API_KEY", "api.openai.com", "Bearer"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_an_unknown_send_outcome_is_refused_rather_than_ignored(self):
        self.outbox.register(TASK, 1)
        with self.assertRaises(contract.Refused) as caught:
            outbox_mod.drive_once(self.outbox, TASK, 1, send=lambda _r: ("weird",),
                                  find_run=lambda _n: None)
        self.assertEqual(caught.exception.reason, "UNKNOWN_SEND_OUTCOME")

    def test_a_bad_run_id_cannot_be_bound(self):
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(self.request_id())
        for bad in (0, -1, "1", None):
            with self.assertRaises(contract.Refused, msg=repr(bad)):
                self.outbox.record_run_lookup(self.request_id(), bad)


class DispatchStatusTests(OutboxCase):
    """The outward-facing status vocabulary the Runtime-side contract reports."""

    def test_the_five_documented_statuses_exist(self):
        self.assertEqual(outbox_mod.DISPATCH_STATUS_VALUES,
                         ("CREATED", "DISPATCHED", "RUNNING", "COMPLETED", "FAILED"))

    def test_the_status_walks_from_created_to_completed(self):
        request_id = self.request_id()
        self.outbox.register(TASK, 1)
        self.assertEqual(self.outbox.dispatch_status(request_id), "CREATED")
        self.outbox.record_dispatch_sent(request_id)
        self.assertEqual(self.outbox.dispatch_status(request_id), "DISPATCHED")
        self.outbox.record_run_lookup(request_id, RUN_ID)
        self.assertEqual(self.outbox.dispatch_status(request_id), "RUNNING")
        self.outbox.record_result(request_id, sealed_result(TASK, 1),
                                  runtime_task_id=TASK, attempt=1)
        self.assertEqual(self.outbox.dispatch_status(request_id), "COMPLETED")
        self.outbox.mark_completed(request_id)
        self.assertEqual(self.outbox.dispatch_status(request_id), "COMPLETED")

    def test_a_failed_execution_reports_failed_not_completed(self):
        output = "not the smoke string"
        failed = sealed_result(TASK, 1)
        failed.update({"status": "FAILED", "accepted": False, "output": output,
                       "output_sha256": contract.output_sha256(output),
                       "failure_reason": "MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING"})
        request_id = self.request_id()
        self.outbox.register(TASK, 1)
        self.outbox.record_dispatch_sent(request_id, github_run_id=RUN_ID)
        self.outbox.record_result(request_id, failed, runtime_task_id=TASK, attempt=1)
        self.assertEqual(self.outbox.dispatch_status(request_id), "FAILED")

    def test_an_unknown_identity_has_no_status(self):
        with self.assertRaises(contract.Refused):
            self.outbox.dispatch_status("0" * 64)


if __name__ == "__main__":
    unittest.main()
