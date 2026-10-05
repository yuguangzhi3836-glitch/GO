"""Offline regressions for #447 identity collision and per-issue failure isolation."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c1_issue_consumer as consumer
from c1_issue_ingress import issue_identity_collisions
from test_c1_issue_consumer import Case, ENABLED, FIXTURE_SOURCE, MOVED_ON_SOURCE


class Reader:
    def __init__(self, issues):
        self.issues = issues

    def read_current_source(self):
        return FIXTURE_SOURCE

    def list_open_issues(self, **kwargs):
        return dict(issues=self.issues, listed=len(self.issues), pages_fetched=1)

    def read_pull(self, number):
        return dict(number=number, base_ref="main", head_sha=FIXTURE_SOURCE)

    def read_pull_files(self, number):
        return []

    def read_commit_tree(self, sha):
        return "a" * 40

    def read_tree(self, sha):
        return [dict(path="application", type="tree", sha="b" * 40)]


class IngressRecovery(Case):
    def builder(self, number, task=1):
        issue = self.issue(79)
        issue.update(number=number, title="C12 · V79-R1-C12-%02d · bounded repair" % task)
        return issue

    def review(self, number):
        return dict(number=number, state="open", title="C14 · REVIEW · frozen candidate",
                    body="Candidate PR: #442\nCandidate SHA: " + FIXTURE_SOURCE)

    def poll(self, issues, **kwargs):
        kwargs.setdefault("runtime", self.runtime)
        kwargs.setdefault("environ", ENABLED)
        return consumer.poll_once(reader=Reader(issues), **kwargs)

    def test_different_issues_same_identity_are_refused(self):
        result = self.poll([self.builder(447), self.builder(420)])
        self.assertEqual(self.runtime.task_count(), 0)
        self.assertEqual(len(result["refused"]), 2)
        for entry in result["refused"]:
            self.assertEqual(entry["reason"], "INGRESS_TASK_ID_COLLISION")
            self.assertEqual(entry["conflicting_issue_numbers"], [420, 447])

    def test_old_source_collision_is_seen_before_freshness_gate(self):
        old = self.builder(420)
        old["body"] = old["body"].replace(FIXTURE_SOURCE, MOVED_ON_SOURCE)
        result = self.poll([self.builder(447), old])
        self.assertEqual(self.runtime.task_count(), 0)
        self.assertEqual(result["refused"][0]["reason"], "INGRESS_TASK_ID_COLLISION")

    def test_same_issue_repeat_remains_one_task(self):
        issue = self.builder(448)
        results = [self.poll([issue, issue]) for _ in range(3)]
        self.assertEqual(self.runtime.task_count(), 1)
        self.assertTrue(all(not r["refused"] for r in results))

    def test_snapshot_check_has_no_cross_poll_store(self):
        self.poll([self.builder(447), self.builder(420)])
        result = self.poll([self.builder(448, 2)])
        self.assertEqual(len(result["enqueued"]), 1)

    def test_collision_past_work_limit_still_blocks_current_issue(self):
        issues = [self.builder(447)] + [self.builder(500+i, i+2) for i in range(10)]
        issues.append(self.builder(420))
        result = self.poll(issues)
        self.assertEqual(result["refused"][0]["issue_number"], 447)
        self.assertNotIn(447, [e["issue_number"] for e in result["enqueued"]])

    def test_malformed_issue_does_not_poison_valid_identity(self):
        malformed = self.builder(420)
        malformed["body"] = "no formal objective or source"
        result = self.poll([malformed, self.builder(448)])
        self.assertEqual(len(result["enqueued"]), 1)

    def test_closed_or_unlisted_history_is_not_claimed_as_detected(self):
        closed = self.builder(420)
        closed["state"] = "closed"
        self.assertEqual(issue_identity_collisions([closed, self.builder(448)]), {})

    def test_disabled_poll_never_opens_runtime(self):
        def forbidden():
            self.fail("disabled poll opened Runtime")
        result = self.poll([self.builder(447), self.builder(420)], runtime=None,
                           runtime_factory=forbidden, environ={})
        self.assertEqual(result["status"], "DISABLED")
        self.assertEqual(self.runtime.task_count(), 0)

    def test_collision_does_not_block_independent_builder_or_review(self):
        result = self.poll([self.builder(447), self.builder(420),
                            self.builder(448, 2), self.review(449)])
        self.assertEqual(len(result["enqueued"]), 1)
        self.assertEqual(len(result["review_enqueued"]), 1)

    def test_enqueue_error_does_not_block_next_builder_or_review(self):
        original = self.runtime.enqueue
        def enqueue(*args, **kwargs):
            if args[2]["issue_number"] == 447:
                raise RuntimeError("SECRET_SENTINEL")
            return original(*args, **kwargs)
        self.runtime.enqueue = enqueue
        result = self.poll([self.builder(447), self.builder(448, 2), self.review(449)])
        self.assertEqual(result["status"], "RUNTIME_ENQUEUE_FAILED")
        self.assertEqual(len(result["enqueued"]), 1)
        self.assertEqual(len(result["review_enqueued"]), 1)
        self.assertNotIn("SECRET_SENTINEL", json.dumps(result))

    def test_review_enqueue_error_does_not_block_next_review(self):
        original = self.runtime.enqueue
        def enqueue(*args, **kwargs):
            if args[2]["issue_number"] == 449:
                raise RuntimeError("SECRET_SENTINEL")
            return original(*args, **kwargs)
        self.runtime.enqueue = enqueue
        result = self.poll([self.review(449), self.review(450)])
        self.assertEqual(len(result["review_enqueued"]), 1)
        self.assertEqual(result["review_refused"][0]["reason"], "REVIEW_ENQUEUE_FAILED")
        self.assertNotIn("SECRET_SENTINEL", json.dumps(result))

    def test_runtime_open_failure_does_not_abort_review_family(self):
        calls = []
        def factory():
            calls.append(True)
            if len(calls) == 1:
                raise OSError("SECRET_SENTINEL")
            return self.runtime
        result = self.poll([self.builder(448), self.review(449)], runtime=None,
                           runtime_factory=factory)
        self.assertEqual(len(result["review_enqueued"]), 1)
        self.assertEqual(result["status"], "RUNTIME_UNAVAILABLE")
        self.assertNotIn("SECRET_SENTINEL", json.dumps(result))

    def test_uncertain_enqueue_is_recovered_by_existing_durable_key(self):
        original = self.runtime.enqueue
        failed = []
        def enqueue(*args, **kwargs):
            task = original(*args, **kwargs)
            if not failed:
                failed.append(True)
                raise OSError("response lost after durable insert")
            return task
        self.runtime.enqueue = enqueue
        issue = self.builder(448)
        self.assertEqual(self.poll([issue])["enqueued"], [])
        self.assertEqual(len(self.poll([issue])["enqueued"]), 1)
        self.assertEqual(self.runtime.task_count(), 1)


if __name__ == "__main__":
    unittest.main()
