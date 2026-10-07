"""Frozen baseline regressions, including a real multi-commit Git history."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import c1_execution_contract as contract
import c1_c13c14_review as review
import c1_review_base as gate
import c1_review_issue_ingress as ingress
from test_c1_review_issue_ingress import happy_reader, review_issue, CANDIDATE, CANDIDATE_TREE

BASE = {"ref": "release/hk", "sha": "a" * 40, "pr_number": 394}


def issue():
    value = review_issue()
    value["body"] += "Candidate base ref: release/hk\nCandidate base SHA: " + BASE["sha"] + "\n"
    value["body"] += "Machine inventory: application/tests/test_x.py\n"
    return value


def reader():
    value = happy_reader()
    value.pull.update(base_ref=BASE["ref"], base_sha=BASE["sha"])
    value.trees[CANDIDATE_TREE] = [{"path": "tests", "type": "tree", "mode": "040000", "sha": "b" * 40}]
    value.trees["b" * 40] = [{"path": "test_x.py", "type": "blob", "mode": "100644", "sha": "c" * 40}]
    value.read_compare = lambda base, head: {"status": "ahead", "merge_base_commit": {"sha": base}}
    return value


class FrozenBaseIngress(unittest.TestCase):
    def test_explicit_base_plans_one_c14_and_preserves_attempt_limit(self):
        plan = ingress.plan_review_ingress(issue(), reader=reader())
        self.assertEqual(plan["would_enqueue"]["payload"]["frozen_base"], BASE)
        self.assertEqual(plan["would_enqueue"]["max_attempts"], 1)
        self.assertEqual(plan["would_enqueue"]["owner_c"], "C14")

    def test_base_drift_refused(self):
        for key, value in (("base_ref", "other"), ("base_sha", "b" * 40)):
            with self.subTest(key=key):
                r = reader()
                r.pull[key] = value
                with self.assertRaisesRegex(contract.Refused, "BASE_MOVED"):
                    ingress.plan_review_ingress(issue(), reader=r)

    def test_non_ancestor_and_incomplete_compare_refused(self):
        for value in ({}, {"status": "diverged"}, {"status": "ahead", "merge_base_commit": {"sha": "b" * 40}}):
            with self.subTest(value=value):
                r = reader()
                r.read_compare = lambda *_: value
                with self.assertRaisesRegex(contract.Refused, "NOT_ANCESTOR"):
                    ingress.plan_review_ingress(issue(), reader=r)

    def test_non_main_without_opt_in_still_refused(self):
        with self.assertRaisesRegex(contract.Refused, "BASE_IS_NOT_MAIN"):
            ingress.plan_review_ingress(review_issue(), reader=reader())

    def test_partial_duplicate_and_unsafe_binding_refused(self):
        for suffix in ("Candidate base ref: release/hk\n", "Candidate base SHA: " + "a" * 40,
                       "Candidate base ref: ../x\nCandidate base SHA: " + "a" * 40,
                       "Candidate base ref: release/hk\nCandidate base ref: other\nCandidate base SHA: " + "a" * 40):
            with self.subTest(suffix=suffix), self.assertRaises(contract.Refused):
                v = review_issue()
                v["body"] += suffix
                ingress.parse_review_issue(v)

    def test_explicit_inventory_required_and_blank_duplicate_rejected(self):
        v = issue()
        v["body"] = v["body"].replace("Machine inventory: application/tests/test_x.py\n", "")
        with self.assertRaisesRegex(contract.Refused, "REQUIRES_EXPLICIT_INVENTORY"):
            ingress.plan_review_ingress(v, reader=reader())
        v = issue()
        v["body"] += "Candidate base ref:\n"
        with self.assertRaisesRegex(contract.Refused, "AMBIGUOUS"):
            ingress.parse_review_issue(v)

    def test_consumer_compare_is_one_read_only_get(self):
        from c1_issue_consumer import GitHubIssuesReader
        from test_c1_review_issue_ingress import FakeResponse
        calls = []
        def opener(request, **kwargs):
            calls.append((request.method, request.full_url))
            return FakeResponse(json.dumps({"status": "ahead", "merge_base_commit": {"sha": BASE["sha"]}}).encode())
        r = GitHubIssuesReader(token_loader=lambda: "test", opener=opener)
        self.assertEqual(r.read_compare(BASE["sha"], CANDIDATE)["status"], "ahead")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "GET")
        self.assertTrue(calls[0][1].endswith("/compare/" + BASE["sha"] + "..." + CANDIDATE))

    def test_scope_edit_cannot_purchase_new_round(self):
        first = ingress.plan_review_ingress(issue(), reader=reader())
        v = issue()
        v["body"] = v["body"].replace("release/hk", "release/other")
        r = reader()
        r.pull["base_ref"] = "release/other"
        second = ingress.plan_review_ingress(v, reader=r)
        self.assertEqual(first["would_enqueue"]["idempotency_key"], second["would_enqueue"]["idempotency_key"])
        self.assertNotEqual(first["payload_sha256"], second["payload_sha256"])

    def test_binding_survives_c14_c13_and_dispatch_without_extra_input(self):
        payload = ingress.plan_review_ingress(issue(), reader=reader())["would_enqueue"]["payload"]
        c13 = review.c13_payload_from_c14(payload, {"github_run_id": 123, "runtime_task_id": "rt_example"})
        for kind, p in ((contract.C14_REVIEW_KIND, payload), (contract.C13_REVIEW_KIND, c13)):
            request = {"payload": p, "task_kind": kind, "runtime_task_id": "rt_example",
                       "attempt": 1, "execution_request_id": "f" * 64, "owner_c": p["cell_id"]}
            self.assertEqual(review.validate_review_payload_for_request(request)["frozen_base"], BASE)
            inputs = contract.dispatch_inputs(request)
            self.assertLessEqual(len(inputs), 10)
            self.assertEqual(json.loads(inputs["runtime_transport"])["frozen_base"], BASE)

    def test_eleven_long_paths_are_not_truncated(self):
        from c1_review_inventory import explicit_inventory
        paths = ["application/tests/test_long_business_acceptance_case_%02d.py" % n for n in range(11)]
        value = " ".join(paths)
        self.assertGreater(len(value), 400)
        self.assertEqual(explicit_inventory("Machine inventory: " + value), value)
        with self.assertRaises(contract.Refused):
            explicit_inventory("Machine inventory: " + " ".join(paths + ["application/tests/test_x%d.py" % n for n in range(10)]))


class WorkflowBindings(unittest.TestCase):
    def test_workflow_gates_precede_machine_and_ai(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        for filename in ("c14-rule-compliance.yml", "c13-quality-acceptance.yml"):
            doc = yaml.safe_load((root / ".github/workflows" / filename).read_text())
            for job in doc["jobs"].values():
                steps = job.get("steps", [])
                gates = [i for i, step in enumerate(steps) if "c1_review_base.py" in step.get("run", "")]
                self.assertEqual(len(gates), 1, filename)
                gate_index = gates[0]
                self.assertEqual(steps[gate_index]["env"]["RUNTIME_TRANSPORT"], "${{ inputs.runtime_transport }}")
                for i, step in enumerate(steps):
                    if "docker run" in step.get("run", "") or " ai-review " in step.get("run", ""):
                        self.assertLess(gate_index, i, filename)


class RealGitBaseline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        self.commit("base.txt")
        self.base = {**BASE, "sha": self.git("rev-parse", "HEAD")}
        self.commit("first_fix.txt")
        self.commit("second_fix.txt")
        self.head = self.git("rev-parse", "HEAD")
        self.brief = {"status": "OK", "candidate_sha": self.head, "pull_request": {
            "number": BASE["pr_number"], "head_sha": self.head,
            "base_ref": BASE["ref"], "base_sha": self.base["sha"]}}

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def commit(self, name):
        (self.repo / name).write_text(name)
        self.git("add", name)
        self.git("commit", "-qm", name)

    def test_full_base_diff_includes_both_commits(self):
        gate.verify(self.brief, self.base, self.head, self.repo)
        self.assertEqual(set(self.git("diff", "--name-only", self.base["sha"] + "...HEAD").split()),
                         {"first_fix.txt", "second_fix.txt"})

    def test_brief_drift_refused_before_execution(self):
        for key, value in (("base_sha", self.head), ("base_ref", "other"), ("head_sha", self.base["sha"]), ("number", 999)):
            brief = copy.deepcopy(self.brief)
            brief["pull_request"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(contract.Refused, "BRIEF_MISMATCH"):
                gate.verify(brief, self.base, self.head, self.repo)

    def test_unrelated_base_refused(self):
        self.git("checkout", "--orphan", "other")
        self.git("rm", "-rf", ".")
        self.commit("unrelated.txt")
        base = {**self.base, "sha": self.git("rev-parse", "HEAD")}
        self.git("checkout", "--detach", self.head)
        self.brief["pull_request"]["base_sha"] = base["sha"]
        with self.assertRaisesRegex(contract.Refused, "NOT_ANCESTOR"):
            gate.verify(self.brief, base, self.head, self.repo)

    def test_non_main_cannot_omit_binding_at_executor(self):
        with self.assertRaisesRegex(contract.Refused, "REQUIRES_EXPLICIT"):
            gate.verify(self.brief, None, self.head, self.repo)


if __name__ == "__main__":
    unittest.main()
