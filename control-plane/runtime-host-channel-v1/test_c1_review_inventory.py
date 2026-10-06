"""Regression for #533: unchanged required tests must survive formal admission."""
import copy
import unittest

from c1_execution_contract import Refused
from c1_issue_ingress import INGRESS_ENABLED_ENV
from c1_review_inventory import explicit_inventory
from c1_review_issue_ingress import plan_review_ingress, ingest_review

SHA = "0b7d0403f9f171844fdcf9bf3330ff9386e82943"
ROOT, APP, TESTS, BLOB = (character * 40 for character in "abcd")
FILES = [
    "test_depth25_migration_history.py",
    "test_unknown_episode_retention.py",
    "test_v70_r4_c01_unknown_episode.py",
    "test_v70_next_c01_unknown_funding.py",
    "test_depth06_direct_checkout.py",
]
INVENTORY = " ".join("application/tests/" + name for name in FILES[:-1]) + (
    " application/tests/test_depth06_direct_checkout.py"
    "::test_unknown_funds_keep_inventory_and_block_cancel_and_timeout"
)
ENV = {INGRESS_ENABLED_ENV: "true"}


class Reader:
    def __init__(self):
        self.calls = []
        self.head = SHA
        self.trees = {
            ROOT: [dict(path="application", type="tree", mode="040000", sha=APP)],
            APP: [dict(path="tests", type="tree", mode="040000", sha=TESTS)],
            TESTS: [dict(path=name, type="blob", mode="100644", sha=BLOB) for name in FILES],
        }

    def read_pull(self, number):
        return dict(head_sha=self.head, base_ref="main")

    def read_commit_tree(self, sha):
        assert sha == SHA
        return ROOT

    def read_tree(self, sha):
        self.calls.append(sha)
        return copy.deepcopy(self.trees[sha])

    def read_pull_files(self, number):
        return [dict(filename="application/tests/" + name, status="modified")
                for name in FILES[:3]]


def issue(inventory=None):
    body = f"Candidate PR: #531\nCandidate SHA: {SHA}\n"
    if inventory is not None:
        body += "Machine inventory: " + inventory + "\n"
    return dict(number=533, state="open", title="C14 · REVIEW · frozen scope", body=body)


class InventoryTests(unittest.TestCase):
    def plan(self, inventory=INVENTORY, reader=None):
        return plan_review_ingress(issue(inventory), reader=reader or Reader(), environ=ENV)

    def test_533_reproducer_preserves_all_five_explicit_paths(self):
        plan = self.plan()
        self.assertEqual(plan["machine_inventory"], INVENTORY)
        self.assertEqual(len(plan["machine_inventory"].split()), 5)
        self.assertEqual(plan["machine_inventory_source"], "explicit_frozen_issue_inventory")
        self.assertEqual(plan["would_enqueue"]["payload"]["machine_inventory"], INVENTORY)

    def test_legacy_inventory_and_round_identity_do_not_change(self):
        legacy = self.plan(None)
        explicit = self.plan()
        self.assertEqual(len(legacy["machine_inventory"].split()), 3)
        self.assertEqual(legacy["machine_inventory_source"], "candidate_changed_tests")
        for key in ("ledger_round_id", "candidate_sha"):
            self.assertEqual(legacy[key], explicit[key])
        self.assertEqual(legacy["would_enqueue"]["idempotency_key"],
                         explicit["would_enqueue"]["idempotency_key"])
        self.assertEqual(explicit["would_enqueue"]["max_attempts"], 1)
        self.assertTrue(explicit["enabled"])
        self.assertFalse(explicit["enqueued"])

    def test_comments_and_free_prose_are_not_execution_instructions(self):
        candidate = issue()
        candidate["body"] += "Please run " + INVENTORY
        candidate["comments"] = ["Machine inventory: " + INVENTORY]
        plan = plan_review_ingress(candidate, reader=Reader(), environ=ENV)
        self.assertEqual(len(plan["machine_inventory"].split()), 3)

    def test_empty_or_invalid_explicit_field_never_falls_back(self):
        for text in ("", "application/tests", "tests/test_x.py", "application/tests/../test_x.py",
                     "application/tests/test_x.py;id", "application/tests/test_x.py $(id)",
                     "application/tests/test_x.py --collect-only", "`application/tests/test_x.py`",
                     "application/tests/test_x.py::test_x[a]", "application/tests/test_x.py\x00"):
            with self.subTest(text=text), self.assertRaises(Refused):
                self.plan(text)

    def test_duplicates_and_oversized_scope_refuse_without_truncation(self):
        for value in (INVENTORY + " " + INVENTORY.split()[0], "x" * 401,
                      "application/tests/test_x.py application/tests/test_x.py"):
            with self.subTest(value=value), self.assertRaises(Refused):
                explicit_inventory("Machine inventory: " + value)
        with self.assertRaisesRegex(Refused, "AMBIGUOUS"):
            explicit_inventory("Machine inventory: " + INVENTORY + "\nMachine inventory: " + INVENTORY)

    def test_missing_frozen_file_refuses(self):
        reader = Reader()
        reader.trees[TESTS].pop()
        with self.assertRaisesRegex(Refused, "FILE_NOT_IN_FROZEN_TREE"):
            self.plan(reader=reader)

    def test_symlink_and_submodule_refuse(self):
        for kind, mode in (("blob", "120000"), ("commit", "160000")):
            reader = Reader()
            reader.trees[TESTS][0].update(type=kind, mode=mode)
            with self.subTest(mode=mode), self.assertRaisesRegex(Refused, "NOT_A_REGULAR_FILE"):
                self.plan(reader=reader)

    def test_symlink_parent_refuses(self):
        reader = Reader()
        reader.trees[APP][0].update(type="blob", mode="120000")
        with self.assertRaisesRegex(Refused, "NOT_A_REGULAR_DIRECTORY"):
            self.plan(reader=reader)

    def test_changed_candidate_refuses_before_scope_resolution(self):
        reader = Reader()
        reader.head = "e" * 40
        with self.assertRaisesRegex(Refused, "HEAD_MOVED"):
            self.plan(reader=reader)
        self.assertEqual(reader.calls, [])

    def test_tree_reads_are_cached_and_frozen(self):
        reader = Reader()
        self.plan(reader=reader)
        self.assertEqual(reader.calls, [ROOT, APP, TESTS])

    def test_missing_node_remains_machine_collection_responsibility(self):
        self.plan("application/tests/test_depth06_direct_checkout.py::test_missing")

    def test_invalid_scope_cannot_enqueue(self):
        class Runtime:
            def enqueue(self, *args, **kwargs):
                raise AssertionError("must not enqueue invalid scope")
        with self.assertRaises(Refused):
            ingest_review(issue("application/tests/../test_escape.py"), reader=Reader(),
                          runtime=Runtime(), environ=ENV)


if __name__ == "__main__":
    unittest.main()
