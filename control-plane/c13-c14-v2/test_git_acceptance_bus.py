"""Real local Git remotes; synthetic machine envelopes, never live C14 evidence."""
from contextlib import ExitStack
import multiprocessing
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from acceptance_gate import Refusal
from git_acceptance_bus import GitAcceptanceBus, REPOSITORIES, identity
from house_bridge import canonical, issue, receive_evidence
from c14_isolated_runner import execute
from test_c14_isolated_runner import RunnerHost, PINNED_REQUEST


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], stderr=subprocess.DEVNULL)


def crash_after_prepare(repository, task_id, raw):
    bus = GitAcceptanceBus(repository, "tasks", write_enabled=True)
    bus._send = lambda *_: os._exit(17)
    bus.publish_house_task(task_id, raw)


def concurrent_publish(repository, task_id, raw, results):
    try:
        GitAcceptanceBus(repository, "tasks", write_enabled=True).publish_house_task(task_id, raw)
        results.put("published")
    except Refusal as exc:
        results.put(str(exc))


class GitBusTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.repos, self.remotes = {}, {}
        for kind in ("tasks", "evidence"):
            remote, local = self.root / (kind + ".git"), self.root / kind
            subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)],
                           check=True, capture_output=True)
            subprocess.run(["git", "clone", str(remote), str(local)], check=True, capture_output=True)
            local.chmod(0o700)
            git(local, "config", "user.name", "Synthetic Test")
            git(local, "config", "user.email", "test@localhost")
            (local / "README").write_text("synthetic local Git transport fixture\n")
            git(local, "add", "README")
            git(local, "commit", "-m", "seed")
            git(local, "push", "origin", "HEAD:main")
            self.repos[kind], self.remotes[kind] = local, remote
        self.stack.enter_context(patch.dict(REPOSITORIES, {k: str(v) for k, v in self.remotes.items()}))
        self.task_bus = self.bus("tasks", write=True)
        self.evidence_bus = self.bus("evidence", write=True)
        self.host = RunnerHost()
        self.task = issue(PINNED_REQUEST, "C14", 100, self.host)
        self.task_raw = canonical(self.task) + b"\n"

    def bus(self, kind, write=False):
        return GitAcceptanceBus(self.repos[kind], kind, write_enabled=write)

    def remote_files(self, kind):
        return git(self.remotes[kind], "ls-tree", "-r", "--name-only", "main").decode().splitlines()

    def test_existing_runner_and_receiver_roundtrip_on_real_git(self):
        host = RunnerHost()
        host.publish_house_task = self.task_bus.publish_house_task
        host.read_house_task = self.bus("tasks").read_house_task
        host.publish_house_artifact = self.evidence_bus.publish_house_artifact
        host.publish_house_evidence = self.evidence_bus.publish_house_evidence
        reader = self.bus("evidence")
        host.read_house_evidence = reader.read_house_evidence
        host.read_house_artifact = reader.read_house_artifact
        task = issue(PINNED_REQUEST, "C14", 100, host)
        evidence = execute(task, 101, host)
        self.assertEqual(receive_evidence(task, 101, host)["receipt"]["test_count"], 71)
        self.assertEqual(reader.read_house_evidence(task["task_id"], task["nonce"]), canonical(evidence) + b"\n")
        # Exactly one remote commit contains Evidence AND all three raw artifacts.
        self.assertEqual(git(self.remotes["evidence"], "rev-list", "--count", "main").strip(), b"2")
        changed = git(self.remotes["evidence"], "diff-tree", "--no-commit-id", "--name-only", "-r", "main").decode().splitlines()
        self.assertEqual(len(changed), 4)
        self.assertTrue(any(p.startswith("evidence/") for p in changed))

    def test_stage_only_and_incomplete_or_changed_bundle_never_publish(self):
        evidence = execute(self.task, 101, self.host)
        tid, nonce = self.task["task_id"], self.task["nonce"]
        self.evidence_bus.publish_house_artifact(tid, nonce, "junit", self.host.artifacts[(tid, nonce, "junit")])
        self.assertEqual(self.remote_files("evidence"), ["README"])
        with self.assertRaises(Refusal):
            self.evidence_bus.publish_house_evidence(tid, nonce, canonical(evidence) + b"\n")
        with self.assertRaises(Refusal):
            self.evidence_bus.publish_house_artifact(tid, nonce, "junit", b"replacement")
        self.assertEqual(self.remote_files("evidence"), ["README"])

    def test_role_scope_and_remote_binding_refused(self):
        with self.assertRaisesRegex(Refusal, "bus_role"):
            self.bus("tasks").publish_house_task(self.task["task_id"], self.task_raw)
        changed = {**self.task, "action_id": "HK_STAGING_DEPLOY"}
        with self.assertRaisesRegex(Refusal, "bus_envelope"):
            self.task_bus.publish_house_task(self.task["task_id"], canonical(changed) + b"\n")
        with self.assertRaises(Refusal):
            self.task_bus.read_house_task("../../escape")
        git(self.repos["tasks"], "remote", "set-url", "origin", str(self.remotes["evidence"]))
        with self.assertRaisesRegex(Refusal, "bus_remote_binding"):
            self.task_bus.publish_house_task(self.task["task_id"], self.task_raw)
        self.assertEqual(self.remote_files("tasks"), ["README"])

    def test_worktree_and_staged_changes_are_not_published_or_reset(self):
        local = self.repos["tasks"]
        (local / "README").write_text("user staged change\n")
        git(local, "add", "README")
        (local / "not-for-bus").write_text("untracked\n")
        before = git(local, "diff", "--cached")
        self.task_bus.publish_house_task(self.task["task_id"], self.task_raw)
        self.assertEqual(git(local, "diff", "--cached"), before)
        self.assertEqual((local / "README").read_text(), "user staged change\n")
        self.assertNotIn("not-for-bus", self.remote_files("tasks"))
        self.assertEqual(git(self.remotes["tasks"], "show", "main:README"), b"synthetic local Git transport fixture\n")

    def test_local_follow_tags_config_cannot_publish_extra_refs(self):
        local = self.repos["tasks"]
        git(local, "tag", "-a", "not-a-task", "-m", "synthetic unrelated tag")
        git(local, "config", "push.followTags", "true")
        self.task_bus.publish_house_task(self.task["task_id"], self.task_raw)
        self.assertEqual(git(self.remotes["tasks"], "for-each-ref", "refs/tags"), b"")

    def test_hard_process_exit_recovery_uses_exact_persisted_task(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=crash_after_prepare, args=(self.repos["tasks"], self.task["task_id"], self.task_raw))
        process.start()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
            self.fail("transport fixture child hung")
        self.assertEqual(process.exitcode, 17)
        self.assertEqual(self.remote_files("tasks"), ["README"])
        reopened = self.bus("tasks", write=True)
        reopened.recover_publication(self.task["task_id"])
        self.assertEqual(reopened.read_house_task(self.task["task_id"]), self.task_raw)
        before = git(self.remotes["tasks"], "rev-parse", "main")
        reopened.recover_publication(self.task["task_id"])
        self.assertEqual(git(self.remotes["tasks"], "rev-parse", "main"), before)
        with self.assertRaisesRegex(Refusal, "bus_outbox_exists"):
            reopened.publish_house_task(self.task["task_id"], self.task_raw)

    def test_push_accepted_but_response_lost_is_resolved_by_readback(self):
        original = self.task_bus._git
        def disconnected(args, **kwargs):
            result = original(args, **kwargs)
            if args[0] == "push":
                raise Refusal("simulated_response_lost")
            return result
        self.task_bus._git = disconnected
        self.task_bus.publish_house_task(self.task["task_id"], self.task_raw)
        self.assertEqual(self.task_bus.read_house_task(self.task["task_id"]), self.task_raw)
        self.assertEqual(git(self.remotes["tasks"], "rev-list", "--count", "main").strip(), b"2")

    def test_concurrent_task_publications_have_one_winner(self):
        ctx = multiprocessing.get_context("fork")
        results = ctx.Queue()
        workers = [ctx.Process(target=concurrent_publish,
                   args=(self.repos["tasks"], self.task["task_id"], self.task_raw, results)) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            if worker.is_alive():
                worker.kill()
                worker.join()
                self.fail("concurrent transport child hung")
            self.assertEqual(worker.exitcode, 0)
        outcomes = [results.get(timeout=2) for _ in workers]
        self.assertCountEqual(outcomes, ["published", "bus_outbox_exists_use_recovery"])
        results.close()
        results.join_thread()
        self.assertEqual(git(self.remotes["tasks"], "rev-list", "--count", "main").strip(), b"2")

    def test_reopened_evidence_outbox_recovers_all_original_bytes(self):
        evidence = execute(self.task, 101, self.host)
        tid, nonce = self.task["task_id"], self.task["nonce"]
        raw = canonical(evidence) + b"\n"
        for name in ("junit", "stdout", "manifest"):
            self.evidence_bus.publish_house_artifact(tid, nonce, name, self.host.artifacts[(tid, nonce, name)])
        def interrupted(*_):
            raise Refusal("simulated_stop_after_prepare")
        self.evidence_bus._send = interrupted
        with self.assertRaisesRegex(Refusal, "simulated_stop"):
            self.evidence_bus.publish_house_evidence(tid, nonce, raw)
        self.assertEqual(self.remote_files("evidence"), ["README"])
        reopened = self.bus("evidence", write=True)
        reopened.recover_publication(tid, nonce)
        self.assertEqual(reopened.read_house_evidence(tid, nonce), raw)
        for name in ("junit", "stdout", "manifest"):
            self.assertEqual(reopened.read_house_artifact(tid, nonce, name), self.host.artifacts[(tid, nonce, name)])
        self.assertEqual(git(self.remotes["evidence"], "rev-list", "--count", "main").strip(), b"2")

    def test_failed_push_retains_outbox_and_recovery_preserves_new_health_commit(self):
        original = self.task_bus._git
        def offline(args, **kwargs):
            if args[0] == "push":
                raise Refusal("simulated_offline")
            return original(args, **kwargs)
        self.task_bus._git = offline
        with self.assertRaisesRegex(Refusal, "bus_publication_pending"):
            self.task_bus.publish_house_task(self.task["task_id"], self.task_raw)
        # Unrelated bus traffic advances main before explicit delivery recovery.
        local = self.repos["tasks"]
        (local / "health-record").write_text("synthetic concurrent health\n")
        git(local, "add", "health-record")
        git(local, "commit", "-m", "concurrent health")
        git(local, "push", "origin", "HEAD:main")
        reopened = self.bus("tasks", write=True)
        reopened.recover_publication(self.task["task_id"])
        self.assertEqual(reopened.read_house_task(self.task["task_id"]), self.task_raw)
        self.assertIn("health-record", self.remote_files("tasks"))

    def test_remote_conflict_is_never_overwritten(self):
        self.task_bus.publish_house_task(self.task["task_id"], self.task_raw)
        local = self.repos["tasks"]
        git(local, "fetch", "origin", "main")
        git(local, "reset", "--hard", "FETCH_HEAD")  # test fixture only
        path = local / "tasks" / (self.task["task_id"] + ".json")
        path.write_bytes(self.task_raw.replace(b'"nonce":', b'"tampered_nonce":'))
        git(local, "add", "tasks")
        git(local, "commit", "-m", "synthetic corruption")
        git(local, "push", "origin", "HEAD:main")
        before = git(self.remotes["tasks"], "rev-parse", "main")
        with self.assertRaises(Refusal):
            self.task_bus.recover_publication(self.task["task_id"])
        self.assertEqual(git(self.remotes["tasks"], "rev-parse", "main"), before)

    def test_artifact_reads_stay_on_the_evidence_snapshot(self):
        evidence = execute(self.task, 101, self.host)
        tid, nonce = self.task["task_id"], self.task["nonce"]
        for name in ("junit", "stdout", "manifest"):
            self.evidence_bus.publish_house_artifact(tid, nonce, name, self.host.artifacts[(tid, nonce, name)])
        self.evidence_bus.publish_house_evidence(tid, nonce, canonical(evidence) + b"\n")
        reader = self.bus("evidence")
        with self.assertRaises(Refusal):
            reader.read_house_artifact(tid, nonce, "stdout")
        reader.read_house_evidence(tid, nonce)
        local = self.repos["evidence"]
        git(local, "fetch", "origin", "main")
        git(local, "reset", "--hard", "FETCH_HEAD")
        (local / "artifacts" / "c14" / identity(tid, nonce) / "stdout").write_bytes(b"tampered")
        git(local, "add", "artifacts")
        git(local, "commit", "-m", "synthetic later change")
        git(local, "push", "origin", "HEAD:main")
        self.assertEqual(reader.read_house_artifact(tid, nonce, "stdout"), self.host.artifacts[(tid, nonce, "stdout")])


if __name__ == "__main__":
    unittest.main()
