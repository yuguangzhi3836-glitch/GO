"""Offline C2-C14 integration. Real ingress/outbox/backend subprocess/result pull;
Runtime fencing and GitHub transport are doubles. Not live-host/model evidence.
"""
import tempfile
import unittest
from pathlib import Path

from c1_dispatch_outbox import DispatchOutbox
from c1_execution_contract import (Refused, build_dispatch_request, task_spec,
                                   REAL_TASK_KIND, KIND, PAYLOAD)
from c1_issue_ingress import plan_ingress
from cell_channel import cell_config
from cell_issue_consumer import poll_cell
from cell_worker import tick_cell
from test_c1_real_task_contract import Clock, RuntimeDouble, StubGitHub


class OwnerCheckingRuntime(RuntimeDouble):
    def complete(self, c_id, task_id, **kwargs):
        if self.tasks[task_id].owner_c != c_id:
            raise AssertionError("completion routed to the wrong cell")
        return super().complete(c_id, task_id, **kwargs)


def issue(cell, number=500, author="owner"):
    padded = "C%02d" % int(cell[1:])
    return {"number": number, "state": "open", "user": {"login": author},
            "title": "%s · V70-R4-%s-01 · channel acceptance" % (padded, padded),
            "body": "Task: inspect the supplied test facts only; no mutation.\n\n"
                    "source_anchor: " + "a" * 40}


class Reader:
    def __init__(self, issues):
        self.issues = issues

    def list_open_issues(self, **kwargs):
        return {"issues": self.issues, "listed": len(self.issues), "pages_fetched": 1}


def config(cell, enabled=True):
    return cell_config(cell, {"C%02d_RUNTIME_INGRESS_ENABLED" % int(cell[1:]): str(enabled),
                              "CELL_TASK_AUTHORS": "owner"})


class AllCells(unittest.TestCase):
    def test_all_thirteen_cells_enqueue_claim_restart_pull_and_complete_once(self):
        for n in range(2, 15):
            cell = "C%d" % n
            with self.subTest(cell=cell), tempfile.TemporaryDirectory() as directory:
                runtime = OwnerCheckingRuntime(Clock())
                cfg = config(cell)
                reader = Reader([issue(cell)])
                for _ in range(3):
                    report = poll_cell(cfg, reader=reader, runtime=runtime)
                    self.assertEqual(report["status"], "PASS")
                self.assertEqual(len(runtime.tasks), 1)
                task = next(iter(runtime.tasks.values()))
                self.assertEqual(task.owner_c, cell)
                self.assertEqual(task.max_attempts, 1)
                db = str(Path(directory) / "outbox.db")
                outbox = DispatchOutbox(db)
                github = StubGitHub(hold_ticks=1)
                try:
                    first = tick_cell(cfg, runtime, outbox, github)
                    self.assertTrue(first["claimed"])
                    self.assertEqual(github.dispatch_calls, 1)
                    outbox.close()
                    outbox = DispatchOutbox(db)  # real SQLite restart/resume
                    for _ in range(4):
                        tick_cell(cfg, runtime, outbox, github)
                    self.assertEqual(task.status, "SUCCEEDED")
                    self.assertEqual(task.attempts, 1)
                    self.assertEqual(github.dispatch_calls, 1)
                    self.assertFalse(task.result["authorizes_any_action"])
                finally:
                    outbox.close()
                    github.close()

    def test_new_cell_services_never_take_c1_or_unknown_domains(self):
        for cell in ("C1", "C01", "C15", "../C2"):
            with self.subTest(cell=cell), self.assertRaises(Refused):
                cell_config(cell, {})

    def test_disabled_ingress_and_absent_authors_never_open_runtime(self):
        def forbidden():
            raise AssertionError("Runtime touched")
        for cfg in (config("C2", False), cell_config("C2", {"C02_RUNTIME_INGRESS_ENABLED": "true"})):
            report = poll_cell(cfg, reader=Reader([issue("C2")]), runtime_factory=forbidden)
            self.assertEqual(report["enqueued"], [])

    def test_wrong_author_other_cell_and_container_comment_are_not_tasks(self):
        runtime = OwnerCheckingRuntime(Clock())
        reserved = issue("C2")
        reserved["title"] = "C02 · Persistent Runtime Cell · canonical slot"
        report = poll_cell(config("C2"), runtime=runtime,
                           reader=Reader([issue("C2", author="stranger"), issue("C3"), reserved]))
        self.assertEqual(report["enqueued"], [])
        self.assertFalse(runtime.tasks)
        self.assertEqual(len(report["refused"]), 1)

    def test_worker_does_not_claim_other_cells_or_smoke_or_probes(self):
        runtime = OwnerCheckingRuntime(Clock())
        payload = plan_ingress(issue("C3"), owner_c="C3")["would_enqueue"]["payload"]
        runtime.enqueue("C3", REAL_TASK_KIND, payload)
        runtime.enqueue("C2", KIND, PAYLOAD)
        runtime.enqueue("C2", "RUNTIME_PROBE", {})
        with tempfile.TemporaryDirectory() as directory:
            outbox = DispatchOutbox(str(Path(directory) / "outbox.db"))
            try:
                report = tick_cell(config("C2"), runtime, outbox, None)
                self.assertEqual(report["status"], "IDLE")
                self.assertTrue(all(t.attempts == 0 for t in runtime.tasks.values()))
            finally:
                outbox.close()

    def test_payload_cannot_impersonate_another_owner_and_resume_is_fenced(self):
        runtime = OwnerCheckingRuntime(Clock())
        payload = plan_ingress(issue("C3"), owner_c="C3")["would_enqueue"]["payload"]
        runtime.enqueue("C2", REAL_TASK_KIND, payload)
        with tempfile.TemporaryDirectory() as directory:
            outbox = DispatchOutbox(str(Path(directory) / "outbox.db"))
            try:
                result = tick_cell(config("C2"), runtime, outbox, None)
                self.assertEqual(result["action"], "NOT_A_C1_TASK")
                self.assertEqual(outbox.unfinished(), [])
                request = build_dispatch_request("rt_wrong_owner", 1, task_spec(REAL_TASK_KIND, payload))
                outbox.register("rt_wrong_owner", 1, request=request)
                result = tick_cell(config("C2"), runtime, outbox, None)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertFalse(result["claimed"])
            finally:
                outbox.close()

    def test_cell_identity_separates_dispatch_and_result(self):
        requests = []
        for cell in ("C2", "C13", "C14"):
            payload = plan_ingress(issue(cell), owner_c=cell)["would_enqueue"]["payload"]
            req = build_dispatch_request("rt_same", 1, task_spec(REAL_TASK_KIND, payload))
            self.assertEqual(req["owner_c"], cell)
            requests.append(req["execution_request_id"])
        self.assertEqual(len(set(requests)), 3)

    def test_failure_completion_uses_the_original_cell(self):
        from c1_result_pull import fail_after_pull
        runtime = OwnerCheckingRuntime(Clock())
        cfg = config("C14")
        report = poll_cell(cfg, reader=Reader([issue("C14")]), runtime=runtime)
        task_id = report["enqueued"][0]["runtime_task_id"]
        task = runtime.claim("C14", worker_id=cfg["worker_id"], kinds=(REAL_TASK_KIND,))
        with tempfile.TemporaryDirectory() as directory:
            outbox = DispatchOutbox(str(Path(directory) / "outbox.db"))
            try:
                request = build_dispatch_request(task_id, 1, task_spec(task.kind, task.payload))
                outbox.register(task_id, 1, request=request)
                fail_after_pull(outbox, runtime, task_id, 1, worker_id=cfg["worker_id"],
                                request_id=request["execution_request_id"], conclusion="failure")
                self.assertEqual(runtime.tasks[task_id].status, "FAILED")
            finally:
                outbox.close()

    def test_cell_services_keep_distinct_outboxes_and_enable_switches(self):
        configs = [config("C%d" % i) for i in range(2, 15)]
        self.assertEqual(len({c["outbox"] for c in configs}), 13)
        self.assertEqual(len({c["worker_id"] for c in configs}), 13)
        self.assertFalse(cell_config("C2", {"C01_RUNTIME_INGRESS_ENABLED": "true"})["enabled"])


if __name__ == "__main__":
    unittest.main()
