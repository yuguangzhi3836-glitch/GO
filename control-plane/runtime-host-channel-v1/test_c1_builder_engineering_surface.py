"""The C01 Builder's engineering action surface: what it may do, and what it may not.

#386 registered the gh-aw Builder workflow and bound the transport to it, but the agent
could only produce an answer: no repository editing beyond one file it then had to leave
alone, no shell, no pull request. That is an answer executor. The failure it leaves open is
not a security one - it is that the Runtime can accept a real engineering work order, the
executor cannot do the engineering, and the task can come back looking successful while
nothing was built.

This file tests the capability change and, at least as hard, its boundaries:

  A  the agent can edit and can run tests, and still gets no CLI proxy;
  B  the only repository write path is gh-aw's proven `create-pull-request` safe output -
     draft, one at most, onto the Builder's own branch namespace, with no merge capability
     anywhere in the compiled workflow;
  C  the agent job itself stays read-only: the write permissions exist only in the
     safe-outputs and conclusion jobs, which is what makes "the agent has no push
     authority" a property of the compiled file rather than of the prompt;
  D  this execution's own files cannot reach the pull request - by git-ignoring them *and*
     by a fail-closed patch guard whose behaviour is executed here, not read;
  E  a run that fails is never adopted as success, even when a result artifact exists;
  F  the U1 transport binding did not move while all of this was added.

What is real and what is a double: the workflow, its compiled form and its scripts are
real - the patch guard is EXTRACTED from the committed front matter and executed as a
subprocess against synthetic patches. The git behaviour it depends on is exercised with a
real `git` in a real temporary repository. The Runtime is the same fencing-faithful double
the U3/U10 and U1 rounds used. No dispatch is issued, no model is called.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402
import c1_execution_loop as loop_mod  # noqa: E402
import c1_ghaw_builder_worker as ghaw  # noqa: E402
import c1_worker as worker  # noqa: E402
import test_c1_ghaw_registration as u1  # noqa: E402
import test_c1_execution_loop as harness  # noqa: E402

REPO_ROOT = HERE.parents[1]
SOURCE = u1.BUILDER_SOURCE
LOCK = u1.BUILDER_LOCK
GITIGNORE = REPO_ROOT / ".gitignore"

RUNTIME_FILES = ("c1_builder_task.json", "ghaw_builder_answer.txt", "c1_result.json")
TASK = "rt_" + "b" * 32
WORKER = "c01-builder-surface-test"
LEASE_S = 120

GIT = shutil.which("git")
needs_git = unittest.skipUnless(GIT, "git is required to exercise the patch mechanism")
# The guard is a bash script that the runner executes with bash; executing it here needs
# the same shell. The Linux CI job and the local WSL laboratory both have it.
needs_posix_shell = unittest.skipUnless(
    os.name == "posix" and Path("/bin/bash").exists(),
    "the patch guard is a bash script; the Linux CI job covers this")


def lock_text():
    return LOCK.read_text(encoding="utf-8")


def lock_document():
    return yaml.safe_load(lock_text())


def safe_outputs_config():
    """The safe-outputs configuration as the runner receives it.

    gh-aw passes it as a JSON string inside an environment variable, so reading it back is
    the only way to see what will actually be enforced - the front matter is the intent.
    """
    line = next(raw for raw in lock_text().splitlines()
                if raw.strip().startswith("GH_AW_SAFE_OUTPUTS_CONFIG:"))
    return json.loads(json.loads(line.split(":", 1)[1].strip()))


def step_lines(marker):
    return [index + 1 for index, line in enumerate(lock_text().splitlines())
            if marker in line]


class TheAgentCanDoEngineeringWork(unittest.TestCase):
    """A - the capability that turns an answerer into a builder."""

    def setUp(self):
        self.front = u1.front_matter(SOURCE)
        self.lock = lock_text()

    def test_the_agent_may_edit_and_may_run_tests(self):
        self.assertIn("edit", self.front["tools"])
        self.assertIs(self.front["tools"]["bash"], True)
        # The codex harness disables the shell with this flag when bash is off; with bash
        # on it must be gone, or the agent would have the capability on paper only.
        self.assertNotIn("features.shell_tool=false", self.lock)
        self.assertIn("codex_harness.cjs codex exec", self.lock)

    def test_the_agent_gets_no_cli_proxy(self):
        self.assertIs(self.front["tools"]["cli-proxy"], False)

    def test_the_prompt_no_longer_confines_the_agent_to_a_single_answer_file(self):
        body = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("only file you may create or modify", body)
        for required in ("Read `c1_builder_task.json`", "Run the relevant tests",
                         "c01-builder/", "create_pull_request", "ghaw_builder_answer.txt"):
            with self.subTest(required=required):
                self.assertIn(required, body)

    def test_the_prompt_states_the_boundaries_it_relies_on(self):
        body = SOURCE.read_text(encoding="utf-8")
        for boundary in ("No merge, no approve", "No secrets", "No Production",
                         "yours to touch by default", "do not widen the scope"):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, body)


class TheOnlyWritePathIsAProvenSafeOutput(unittest.TestCase):
    """B - one Draft PR, on the Builder's own branch namespace, and no merge anywhere."""

    def setUp(self):
        self.config = safe_outputs_config()
        self.lock = lock_text()

    def test_the_compiled_pull_request_config_is_the_source_declared_one(self):
        """The lock is generated; the source is what a reviewer actually reads.

        Asserting only the compiled file would let the source drift: a `draft: false` in
        the front matter would pass every test until somebody recompiled, at which point
        the enforced behaviour would change without a single test noticing. So the two are
        asserted against each other, and this is what caught exactly that gap.
        """
        declared = u1.front_matter(SOURCE)["safe-outputs"]["create-pull-request"]
        compiled = self.config["create_pull_request"]
        self.assertEqual(declared["draft"], compiled["draft"])
        self.assertEqual(declared["max"], compiled["max"])
        self.assertEqual(declared["base-branch"], compiled["base_branch"])
        self.assertEqual(list(declared["allowed-branches"]), compiled["allowed_branches"])
        self.assertEqual(declared["fallback-as-issue"], compiled["fallback_as_issue"])
        self.assertEqual(declared["auto-close-issue"], compiled["auto_close_issue"])
        self.assertEqual(declared["if-no-changes"], compiled["if_no_changes"])

    def test_exactly_one_draft_pull_request_against_main(self):
        self.assertIn("create_pull_request", self.config)
        pr = self.config["create_pull_request"]
        self.assertIs(pr["draft"], True)
        self.assertEqual(pr["max"], 1)
        self.assertEqual(pr["base_branch"], "main")
        self.assertIs(pr["fallback_as_issue"], False)
        self.assertIs(pr["auto_close_issue"], False)
        self.assertEqual(pr["allowed_branches"], ["c01-builder/*"])

    def test_the_builder_cannot_merge(self):
        for capability in ("merge_pull_request", "auto_merge", "enable_auto_merge",
                           "push_to_pull_request_branch", "create_or_update_secret",
                           "update_pull_request_branch"):
            with self.subTest(capability=capability):
                self.assertNotIn(capability, self.config)
                self.assertNotIn(capability, self.lock)

    def test_the_patch_guard_is_wired_into_the_safe_outputs_job(self):
        # The guard runs before "Process Safe Outputs" in this job; a non-zero exit there
        # aborts the job, which is what makes it a gate rather than a report.
        self.assertIn("Builder patch guard (fail-closed)", self.lock)
        guard = step_lines("name: Builder patch guard (fail-closed)")[0]
        safe_outputs_job = step_lines("  safe_outputs:")[0]
        self.assertGreater(guard, safe_outputs_job)
        self.assertIn("BUILDER_PATCH_GUARD=FAIL", self.lock)

    def test_the_safe_output_is_gh_aw_s_and_not_a_new_writer(self):
        source = (HERE / "c1_ghaw_builder_worker.py").read_text(encoding="utf-8")
        self.assertNotIn("pull_request", source)
        # No second workflow, no PR broker: the capability lives inside this one file.
        self.assertEqual(sorted(path.name for path in u1.WORKFLOWS.iterdir()
                                if path.name.startswith("c1-gh-aw-builder")),
                         ["c1-gh-aw-builder-v1.lock.yml", "c1-gh-aw-builder-v1.md"])


class TheAgentJobItselfCannotWrite(unittest.TestCase):
    """C - writes live in the safe-outputs job, never in the job the agent runs in."""

    def setUp(self):
        jobs = lock_document()["jobs"]
        self.jobs = jobs

    def test_the_workflow_defaults_to_no_permissions(self):
        self.assertEqual(lock_document()["permissions"], {})

    def test_the_agent_job_is_read_only(self):
        self.assertEqual(self.jobs["agent"]["permissions"],
                         {"actions": "read", "contents": "read"})

    def test_the_repository_write_permissions_exist_only_outside_the_agent_job(self):
        writes = {name: job.get("permissions", {})
                  for name, job in self.jobs.items()
                  if "write" in json.dumps(job.get("permissions", {}))}
        self.assertEqual(sorted(writes), ["conclusion", "safe_outputs"])
        for name in ("activation", "agent", "detection"):
            self.assertNotIn("write", json.dumps(self.jobs[name].get("permissions", {})))

    def test_no_job_has_a_permission_beyond_what_the_builder_needs(self):
        allowed = {"actions", "contents", "issues", "pull-requests"}
        for name, job in self.jobs.items():
            for scope in job.get("permissions", {}):
                with self.subTest(job=name, scope=scope):
                    self.assertIn(scope, allowed)


class TheExecutionsOwnFilesCannotReachThePullRequest(unittest.TestCase):
    """D - proven twice: by git-ignoring them, and by a guard whose behaviour is run."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="c01-surface-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_seal_runs_after_the_patch_is_collected(self):
        # c1_result.json does not exist while the agent runs and does not exist when the
        # patch is captured: it is written by a post-step that runs later in the same job.
        collected = step_lines("id: collect_output")[0]
        seal = step_lines("name: Seal the C1 result")[0]
        self.assertGreater(seal, collected)
        self.assertNotIn("c1_result.json", self._patch_capture_region())

    def _patch_capture_region(self):
        lines = lock_text().splitlines()
        start = next(i for i, line in enumerate(lines) if "id: collect_output" in line)
        end = next(i for i, line in enumerate(lines) if "name: Seal the C1 result" in line)
        return "\n".join(lines[start:end])

    def test_the_runtime_files_are_git_ignored_at_the_repository_root(self):
        self.assertTrue(GITIGNORE.is_file())
        entries = {line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.strip().startswith("#")}
        for name in RUNTIME_FILES:
            with self.subTest(name=name):
                self.assertIn("/" + name, entries)

    @needs_git
    def test_git_add_cannot_pick_up_the_runtime_files(self):
        """The real mechanism, with the real git: what the capture can never see."""
        import subprocess as sp

        work = self.tmp / "repo"
        work.mkdir()
        sp.run([GIT, "init", "-q"], cwd=work, check=True)
        sp.run([GIT, "config", "user.email", "t@example.invalid"], cwd=work, check=True)
        sp.run([GIT, "config", "user.name", "t"], cwd=work, check=True)
        (work / ".gitignore").write_text(GITIGNORE.read_text(encoding="utf-8"),
                                         encoding="utf-8")
        (work / "seed.txt").write_text("seed\n", encoding="utf-8")
        sp.run([GIT, "add", "seed.txt", ".gitignore"], cwd=work, check=True)
        sp.run([GIT, "commit", "-qm", "seed"], cwd=work, check=True)

        for name in RUNTIME_FILES:
            (work / name).write_text("{}\n", encoding="utf-8")
        (work / "fixed.py").write_text("print('fix')\n", encoding="utf-8")

        status = sp.run([GIT, "status", "--porcelain", "--untracked-files=all"],
                        cwd=work, capture_output=True, text=True, check=True).stdout
        for name in RUNTIME_FILES:
            self.assertNotIn(name, status, "%s must be invisible to git status" % name)
        self.assertIn("fixed.py", status)

        sp.run([GIT, "add", "-A"], cwd=work, check=True)
        staged = sp.run([GIT, "diff", "--cached", "--name-only"],
                        cwd=work, capture_output=True, text=True, check=True).stdout
        for name in RUNTIME_FILES:
            self.assertNotIn(name, staged, "git add -A must not stage %s" % name)
        self.assertIn("fixed.py", staged)

        # And the patch the Builder's PR is built from carries only the engineering change.
        sp.run([GIT, "commit", "-qm", "fix"], cwd=work, check=True)
        patch = sp.run([GIT, "format-patch", "-1", "--stdout"],
                       cwd=work, capture_output=True, text=True, check=True).stdout
        self.assertIn("+++ b/fixed.py", patch)
        for name in RUNTIME_FILES:
            self.assertNotIn(name, patch)

    def _guard_script(self):
        front = u1.front_matter(SOURCE)
        steps = front["safe-outputs"]["steps"]
        self.assertEqual(len(steps), 1)
        script = steps[0]["run"]
        # The guard reads the runner's own paths. The test rewrites exactly those two, so
        # it stays hermetic; each rewrite is required to apply exactly once, so editing
        # the paths in the workflow breaks this test loudly instead of silently. The glob
        # itself is preserved - rewriting it to a single filename would quietly turn the
        # ambiguity check into a no-op.
        self.assertEqual(script.count("/tmp/gh-aw/aw-*.patch"), 1)
        self.assertEqual(script.count("/tmp/builder-guard-paths.txt"), 4)
        return (script.replace("/tmp/gh-aw/aw-*.patch",
                               str(self.tmp / "gh-aw") + "/aw-*.patch")
                      .replace("/tmp/builder-guard-paths.txt",
                               str(self.tmp / "builder-guard-paths.txt")))

    def _run_guard(self, patch_body):
        (self.tmp / "gh-aw").mkdir(exist_ok=True)
        for stale in (self.tmp / "gh-aw").glob("aw-*.patch"):
            stale.unlink()
        if patch_body is not None:
            (self.tmp / "gh-aw" / "aw-builder.patch").write_text(patch_body,
                                                                 encoding="utf-8")
        script = self.tmp / "guard.sh"
        script.write_text(self._guard_script(), encoding="utf-8")
        return subprocess.run(["/bin/bash", str(script)], cwd=self.tmp,
                              capture_output=True, text=True)

    @needs_posix_shell
    def test_the_guards_paths_were_actually_rewritten(self):
        script = self._guard_script()
        self.assertNotIn("/tmp/gh-aw/aw-*.patch", script)
        self.assertNotIn("/tmp/builder-guard-paths.txt", script)

    @needs_posix_shell
    def test_the_guard_passes_a_patch_of_engineering_changes(self):
        completed = self._run_guard(
            "diff --git a/fixed.py b/fixed.py\n"
            "--- a/fixed.py\n"
            "+++ b/fixed.py\n"
            "@@\n-print('a')\n+print('b')\n")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("BUILDER_PATCH_GUARD=PASS", completed.stdout)

    @needs_posix_shell
    def test_the_guard_refuses_a_patch_that_contains_the_executions_own_files(self):
        for name in RUNTIME_FILES:
            with self.subTest(name=name):
                completed = self._run_guard(
                    "diff --git a/fixed.py b/fixed.py\n"
                    "--- a/fixed.py\n+++ b/fixed.py\n@@\n-x\n+y\n"
                    "diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n@@\n+\n" % ((name,) * 4))
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("RUNTIME_EXECUTION_FILE_IN_PATCH", completed.stdout)

    @needs_posix_shell
    def test_the_guard_refuses_a_patch_that_changes_nothing(self):
        completed = self._run_guard("From 0" + "0" * 39 + " Mon Sep 17 00:00:00 2001\n")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("NO_CHANGED_PATHS", completed.stdout)

    @needs_posix_shell
    def test_the_guard_refuses_when_there_is_no_patch_to_inspect(self):
        completed = self._run_guard(None)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("NO_UNAMBIGUOUS_PATCH_ARTIFACT", completed.stdout)

    @needs_posix_shell
    def test_the_guard_refuses_an_ambiguous_patch_artifact(self):
        self._run_guard("x")
        (self.tmp / "gh-aw" / "aw-second.patch").write_text("y", encoding="utf-8")
        script = self.tmp / "guard.sh"
        script.write_text(self._guard_script(), encoding="utf-8")
        completed = subprocess.run(["/bin/bash", str(script)], cwd=self.tmp,
                                   capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("NO_UNAMBIGUOUS_PATCH_ARTIFACT", completed.stdout)


class AFailedWorkflowIsNeverAdoptedAsSuccess(unittest.TestCase):
    """E - a result that exists is still not an answer if the run did not succeed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="c01-adopt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.clock = harness.Clock()
        self.runtime = harness.RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(str(self.tmp / "outbox.db"))
        self.addCleanup(self.outbox.close)

    def _payload(self):
        return contract.build_task_payload(
            cell_id="C01", external_task_id="C01-BUILDER-ADOPT",
            objective="Change one file and open a Draft PR.",
            scope="No real execution; this is the failure-adoption test.")

    def test_a_run_that_did_not_succeed_is_reported_to_the_runtime_and_settled(self):
        task_payload = self._payload()
        run_id = 616161
        # The identity comes from the Runtime, exactly as `advance` would take it.
        task_id = self.runtime.enqueue("C1", contract.GHAW_BUILDER_KIND, task_payload,
                                       idempotency_key="adopt-test", max_attempts=1)
        request = contract.build_dispatch_request(
            task_id, 1, contract.task_spec(contract.GHAW_BUILDER_KIND, task_payload))
        # The artifact exists: the agent did produce a result. The run still failed, which
        # is the shape "edits succeeded but the Draft PR step did not".
        answer = "I changed fixed.py and could not open the pull request."
        document = {
            "version": contract.SCHEMA_VERSION, "kind": contract.RESULT_KIND,
            "runtime_task_id": task_id, "attempt": 1,
            "execution_request_id": request["execution_request_id"],
            "github_run_id": run_id, "github_run_attempt": 1,
            "provider": contract.PROVIDER_GHAW_BUILDER, "model": "codex",
            "response_id": "gh-aw-run-%d" % run_id, "status": "SUCCEEDED",
            "output_sha256": contract.output_sha256(answer), "output": answer,
            "accepted": True, "reused_terminal_result": False,
            "authorizes_any_action": False,
        }
        raw = contract.canonical(document).encode("utf-8")
        artifact = {"bytes": raw,
                    "digest": "sha256:" + contract.sha256_hex(raw.decode("utf-8")),
                    "github_run_id": run_id}

        class FailedRunTransport:
            """The run exists, its artifact exists, and it concluded failure."""

            def __init__(self):
                self.pulls = 0

            def send(self, request):                       # pragma: no cover - not reached
                raise AssertionError("the failing run must not be re-dispatched")

            def find_run(self, name):
                return None

            def find_run_by_name(self, name):
                return {"id": run_id, "run_attempt": 1, "status": "completed",
                        "conclusion": "failure", "head_sha": "0" * 40}

            def get_run(self, run_id_):
                return {"id": run_id_, "run_attempt": 1, "status": "completed",
                        "conclusion": "failure", "head_sha": "0" * 40}

            def download_artifact(self, run_id_, name):
                self.pulls += 1
                return artifact

        transport = FailedRunTransport()
        self.outbox.register(task_id, 1, request=request)
        self.outbox.record_dispatch_sent(request["execution_request_id"],
                                         github_run_id=run_id)
        self.runtime.claim("C1", worker_id=WORKER, lease_s=LEASE_S,
                           kinds=(contract.GHAW_BUILDER_KIND,))

        outcome = loop_mod.resume(self.outbox, self.runtime, task_id, 1, worker_id=WORKER,
                                  client=transport, lease_s=LEASE_S, clock=self.clock,
                                  claimable_kinds=ghaw.CLAIM_KINDS)

        # Settled as failed, not completed - and the Runtime was told so.
        self.assertEqual(outcome["action"], "RUN_FAILED")
        self.assertNotEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        self.assertEqual(self.runtime.status_of(task_id), "FAILED")
        self.assertNotIn("COMPLETED",
                         self.outbox.snapshot(request["execution_request_id"])["state"])
        self.assertEqual(self.outbox.snapshot(request["execution_request_id"])["state"],
                         "RUN_FAILED")
        # And the artifact was never even consulted: a failed run has no answer.
        self.assertEqual(transport.pulls, 0)
        completed = [row for row in self.runtime.evidence
                     if row["event_type"] == "TASK_COMPLETED"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["body"]["status"], "FAILED")

    def test_the_runtime_contract_refuses_a_result_that_does_not_match_its_run(self):
        """The other half: identity is what ties a result to a task, not the text."""
        request = contract.build_dispatch_request(
            TASK, 1, contract.task_spec(contract.GHAW_BUILDER_KIND, self._payload()))
        answer = "ok"
        document = {
            "version": contract.SCHEMA_VERSION, "kind": contract.RESULT_KIND,
            "runtime_task_id": TASK, "attempt": 1,
            "execution_request_id": request["execution_request_id"],
            "github_run_id": 4242, "github_run_attempt": 1,
            "provider": contract.PROVIDER_GHAW_BUILDER, "model": "codex",
            "response_id": "gh-aw-run-4242", "status": "SUCCEEDED",
            "output_sha256": contract.output_sha256(answer), "output": answer,
            "accepted": True, "reused_terminal_result": False,
            "authorizes_any_action": False,
        }
        contract.validate_result(document, runtime_task_id=TASK, attempt=1,
                                 execution_request_id_=request["execution_request_id"],
                                 task_kind=contract.GHAW_BUILDER_KIND)
        with self.assertRaises(contract.Refused) as raised:
            contract.validate_result(dict(document, attempt=2), runtime_task_id=TASK,
                                     attempt=1,
                                     execution_request_id_=request["execution_request_id"],
                                     task_kind=contract.GHAW_BUILDER_KIND)
        self.assertEqual(raised.exception.reason, "RESULT_ATTEMPT_MISMATCH")


class TheU1TransportDidNotMove(unittest.TestCase):
    """F - adding capability must not re-wire which executor runs which task."""

    def test_the_two_executors_still_target_different_workflows(self):
        self.assertEqual(worker.build_client().workflow_target()["workflow_file"],
                         contract.WORKFLOW_FILE)
        self.assertEqual(ghaw.build_client().workflow_target()["workflow_file"],
                         contract.GHAW_BUILDER_WORKFLOW_FILE)
        self.assertEqual(contract.GHAW_BUILDER_WORKFLOW_FILE,
                         "c1-gh-aw-builder-v1.lock.yml")
        request = contract.build_dispatch_request(
            TASK, 1, contract.task_spec(contract.GHAW_BUILDER_KIND, u1.payload()))
        self.assertEqual(request["workflow_file"], contract.GHAW_BUILDER_WORKFLOW_FILE)
        self.assertEqual(request["provider"], contract.PROVIDER_GHAW_BUILDER)
        self.assertEqual(
            contract.build_dispatch_request(
                TASK, 1, contract.task_spec(contract.REAL_TASK_KIND, u1.payload())
            )["workflow_file"], contract.WORKFLOW_FILE)

    def test_the_run_name_and_artifact_name_still_agree_with_the_contract(self):
        front = u1.front_matter(SOURCE)
        self.assertEqual(front["run-name"],
                         contract.run_identity_name("${{ inputs.runtime_task_id }}",
                                                    "${{ inputs.attempt }}",
                                                    "${{ inputs.execution_request_id }}"))
        self.assertIn("name: c1-ai-execution-result-${{ inputs.execution_request_id }}",
                      lock_text())
        self.assertIn("path: c1_result.json", lock_text())

    def test_the_workflow_is_still_dispatch_only(self):
        self.assertEqual(set(u1.trigger_block(u1.front_matter(SOURCE))),
                         {"workflow_dispatch"})


if __name__ == "__main__":
    unittest.main()
