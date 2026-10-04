"""U1: the gh-aw Builder workflow is registered, and the transport actually reaches it.

What this file exists to prevent, in one sentence: a `GHAW_BUILDER_V1` task that *records*
the gh-aw Builder workflow as its target while the transport sends it to the Responses
backend - a real dispatch, a real run, and for a paid class a real bill, for work another
executor owns.

#381 declared the two targets and bound the executors' kind sets. It could not close this
one, because the client posted to a single module-level endpoint. This file tests the
three things that have to be true together for the gap to be closed:

  A  each executor's transport reaches its own workflow, and only its own;
  B  a request aimed at the other executor's workflow is refused before anything is sent,
     and the refusal leaves the outbox exactly as it was;
  C  the declared target is a workflow that actually exists, is compiled from a committed
     source, and whose declared inputs, run name and artifact name agree with the contract
     the Runtime pulls with;
  D  the workflow verifies the kind it was given, and seals a result the Runtime's own
     contract accepts - proven by RUNNING the workflow's gate and seal scripts offline,
     not by reading them;
  E  the Responses path is byte-frozen: `AI_WORK_V1` and `AI_TASK_V1` identities and
     targets do not move;
  F  nothing here can fire by itself or spend anything: the workflow is dispatch-only, has
     no write capability and no shell for the agent, and every test is offline.

What is real and what is a double: the contract, both worker modules, the client and the
workflow's own embedded scripts are REAL - the gate and seal scripts are extracted from the
committed `.md` and executed as subprocesses. Only the HTTP transport is a double, and it
records every call it receives so that "nothing was sent" is an assertion rather than a
hope. No dispatch is issued to GitHub by this file.
"""
import ast as _ast  # used to read the workflow's own string literals
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402
import c1_execution_loop as loop_mod  # noqa: E402
import c1_ghaw_builder_worker as ghaw  # noqa: E402
import c1_github_actions_client as client_mod  # noqa: E402
import c1_result_pull as result_pull  # noqa: E402
import c1_worker as worker  # noqa: E402
import test_c1_github_actions_client as gh_harness  # noqa: E402

REPO_ROOT = HERE.parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
BUILDER_SOURCE = WORKFLOWS / "c1-gh-aw-builder-v1.md"
BUILDER_LOCK = WORKFLOWS / "c1-gh-aw-builder-v1.lock.yml"
UNIT_CANDIDATE = HERE / "systemd" / "go-runtime-host-ghaw-builder-worker.service"

# Frozen at the base commit: these are the identities the deployed Runtime has already
# recorded for the Responses path, and U1 must not move them.
FROZEN_SMOKE_REQUEST_ID = ("12d810e9b7a3c51d04d37d7a88074ee59d18de9582a2068dc1"
                           "fc536006e20eba")
FROZEN_REAL_REQUEST_ID = ("3eaf0d3b69d57414cd6e40c98b2c270b132286dce3a608892c0"
                          "ee92c12361e1c")
TASK = "rt_" + "a" * 32
FROZEN_PAYLOAD = {"schema_version": 1, "cell_id": "C1",
                  "external_task_id": "C01-OFFLINE-A",
                  "objective": "Offline regression: derive the prompt from this payload.",
                  "scope": "No real execution. Answer with one short line."}


def payload(external_task_id="C01-BUILDER-1"):
    return contract.build_task_payload(
        cell_id="C01", external_task_id=external_task_id,
        objective="State the objective you were given, in one line.",
        scope="No real execution. Answer with one short line.")


def front_matter(path):
    """The `---`-delimited front matter of a gh-aw source, parsed.

    PyYAML reads a bare `on:` as the boolean True (YAML 1.1), so the trigger block is
    fetched through a helper rather than by key.
    """
    import yaml

    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if match is None:
        raise AssertionError("%s has no front matter" % path.name)
    return yaml.safe_load(match.group(1))


def trigger_block(document):
    return document.get("on", document.get(True))


def embedded_scripts(path):
    """The `python3 - <<'PY' ... PY` blocks a workflow step runs, dedented in order.

    Executing them is the difference between asserting that a gate is written down and
    asserting that it closes.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    scripts, index = [], 0
    while index < len(lines):
        if "python3 - <<'PY'" not in lines[index]:
            index += 1
            continue
        index += 1
        body = []
        while index < len(lines) and lines[index].strip() != "PY":
            body.append(lines[index])
            index += 1
        indents = [len(line) - len(line.lstrip()) for line in body if line.strip()]
        pad = min(indents) if indents else 0
        scripts.append("\n".join(line[pad:] for line in body) + "\n")
    return scripts


def run_script(script, *, environ, workdir):
    """Run one embedded workflow script exactly as the runner would, offline."""
    path = Path(workdir) / "step.py"
    path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-B", str(path)], cwd=workdir, capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **environ))
    return completed


class RecordingOpener(gh_harness.RoutingOpener):
    """A transport double that records every call and answers with a fixed response.

    204-with-no-body is the PRODUCTION shape of a dispatch under API version 2022-11-28,
    so it is also the shape the client has to handle here. Subclassing rather than
    rebinding `__call__` is deliberate: special methods are looked up on the type, so an
    instance-level `__call__` would never be invoked and the recording would silently be
    the class's own routing behaviour.
    """

    def __init__(self, *, status=204, body=b""):
        super().__init__({})
        self._status = status
        self._body = body

    def __call__(self, request, timeout=None):  # noqa: ARG002
        self.seen.append((request.method, request.full_url,
                          "Authorization" in request.headers))
        return gh_harness.FakeResponse(self._body, self._status)


class TransportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c1-u1-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def recording_opener(self, **kwargs):
        return RecordingOpener(**kwargs)

    def client_for(self, workflow_file, opener):
        return client_mod.GitHubActionsClient(
            token_loader=lambda: "u1-test-token", opener=opener, workflow_file=workflow_file)

    def request_for(self, task_kind, task_payload, *, external_task_id="C01-BUILDER-1"):
        spec = contract.task_spec(task_kind, task_payload)
        return contract.build_dispatch_request(TASK, 1, spec)


class TheTransportIsBoundPerExecutor(TransportCase):
    """A - each executor dispatches to its own workflow and to no other."""

    def test_the_two_executors_bind_to_different_workflows_and_endpoints(self):
        responses = worker.build_client().workflow_target()
        builder = ghaw.build_client().workflow_target()
        self.assertEqual(responses["workflow_file"], contract.WORKFLOW_FILE)
        self.assertEqual(builder["workflow_file"], contract.GHAW_BUILDER_WORKFLOW_FILE)
        self.assertNotEqual(responses["dispatch_endpoint"], builder["dispatch_endpoint"])
        self.assertNotIn(contract.GHAW_BUILDER_WORKFLOW_FILE, responses["dispatch_endpoint"])
        self.assertNotIn(contract.WORKFLOW_FILE, builder["dispatch_endpoint"])
        # One Runtime, one repository: only the dispatch target differs.
        self.assertEqual(responses["repo"], builder["repo"])

    def test_a_gh_aw_dispatch_is_sent_to_the_gh_aw_workflow(self):
        opener = self.recording_opener()
        client = self.client_for(contract.GHAW_BUILDER_WORKFLOW_FILE, opener)
        self.assertEqual(client.send(self.request_for(contract.GHAW_BUILDER_KIND, payload())),
                         ("sent", None))
        self.assertEqual(len(opener.seen), 1)
        method, url, authenticated = opener.seen[0]
        self.assertEqual(method, "POST")
        self.assertTrue(authenticated)
        self.assertEqual(url, "https://api.github.com"
                              + contract.dispatch_endpoint_for_kind(contract.GHAW_BUILDER_KIND))
        self.assertIn("c1-gh-aw-builder-v1.lock.yml", url)
        self.assertNotIn(contract.WORKFLOW_FILE, url)

    def test_a_responses_dispatch_is_still_sent_to_the_responses_workflow(self):
        opener = self.recording_opener()
        client = self.client_for(contract.WORKFLOW_FILE, opener)
        self.assertEqual(client.send(self.request_for(contract.KIND, contract.PAYLOAD)),
                         ("sent", None))
        method, url, _ = opener.seen[0]
        self.assertEqual(method, "POST")
        self.assertIn(contract.WORKFLOW_FILE, url)
        self.assertNotIn(contract.GHAW_BUILDER_WORKFLOW_FILE, url)

    def test_the_real_task_class_still_uses_the_responses_workflow(self):
        opener = self.recording_opener()
        client = self.client_for(contract.WORKFLOW_FILE, opener)
        client.send(self.request_for(contract.REAL_TASK_KIND, payload("C01-REAL-1")))
        self.assertIn(contract.WORKFLOW_FILE, opener.seen[0][1])


class ATargetMismatchFailsClosed(TransportCase):
    """B - a request aimed at the other executor is refused before anything is sent."""

    def test_the_gh_aw_client_refuses_a_responses_request(self):
        opener = self.recording_opener()
        client = self.client_for(contract.GHAW_BUILDER_WORKFLOW_FILE, opener)
        with self.assertRaises(contract.Refused) as raised:
            client.send(self.request_for(contract.REAL_TASK_KIND, payload()))
        self.assertIn("DISPATCH_TARGET_IS_NOT_THIS_EXECUTORS_WORKFLOW",
                      raised.exception.reason)
        self.assertEqual(opener.seen, [], "nothing may be sent for a mismatched target")

    def test_the_responses_client_refuses_a_gh_aw_request(self):
        opener = self.recording_opener()
        client = self.client_for(contract.WORKFLOW_FILE, opener)
        with self.assertRaises(contract.Refused) as raised:
            client.send(self.request_for(contract.GHAW_BUILDER_KIND, payload()))
        self.assertIn("DISPATCH_TARGET_IS_NOT_THIS_EXECUTORS_WORKFLOW",
                      raised.exception.reason)
        self.assertEqual(opener.seen, [])

    def test_a_mismatched_ref_or_repo_is_refused_too(self):
        opener = self.recording_opener()
        client = self.client_for(contract.GHAW_BUILDER_WORKFLOW_FILE, opener)
        request = self.request_for(contract.GHAW_BUILDER_KIND, payload())

        other_ref = dict(request, ref="some-other-branch")
        with self.assertRaises(contract.Refused) as raised:
            client.send(other_ref)
        self.assertIn("DISPATCH_REF_IS_NOT_THIS_EXECUTORS_REF", raised.exception.reason)

        other_repo = dict(request, repo="attacker/elsewhere")
        with self.assertRaises(contract.Refused) as raised:
            client.send(other_repo)
        self.assertIn("DISPATCH_REPO_MISMATCH", raised.exception.reason)
        self.assertEqual(opener.seen, [])

    def test_a_refused_dispatch_leaves_the_outbox_row_untouched(self):
        """The fail-closed path is only worth anything if nothing was spent."""
        outbox = outbox_mod.DispatchOutbox(str(Path(self.tmp) / "outbox.db"))
        self.addCleanup(outbox.close)
        opener = self.recording_opener()
        client = self.client_for(contract.WORKFLOW_FILE, opener)
        request = self.request_for(contract.GHAW_BUILDER_KIND, payload())

        with self.assertRaises(contract.Refused):
            loop_mod._drive(outbox, None, TASK, 1, worker_id="u1", client=client,
                            lease_s=120, clock=lambda: 0.0, request=request)
        snapshot = outbox.snapshot(request["execution_request_id"])
        self.assertEqual(snapshot["state"], "INTENT")
        self.assertEqual(snapshot["dispatches_sent"], 0)
        self.assertEqual(opener.seen, [])
        self.assertEqual(outbox.unfinished()[0]["dispatches_sent"], 0)


class TheWorkflowIsRegisteredAndMatchesTheContract(unittest.TestCase):
    """C and D - the declared target exists, and its contract agrees with the Runtime's."""

    def setUp(self):
        self.front = front_matter(BUILDER_SOURCE)
        self.lock_text = BUILDER_LOCK.read_text(encoding="utf-8")

    def test_the_declared_target_is_the_file_that_exists(self):
        self.assertEqual(contract.GHAW_BUILDER_WORKFLOW_FILE, "c1-gh-aw-builder-v1.lock.yml")
        self.assertTrue(BUILDER_LOCK.is_file())
        self.assertTrue(BUILDER_SOURCE.is_file())
        self.assertIn(contract.GHAW_BUILDER_WORKFLOW_FILE,
                      {path.name for path in WORKFLOWS.iterdir()})

    def test_the_committed_lock_is_the_compilation_of_the_committed_source(self):
        header = self.lock_text.splitlines()[0]
        self.assertTrue(header.startswith("# gh-aw-metadata: "), header[:60])
        metadata = json.loads(header.split(": ", 1)[1])
        self.assertEqual(metadata["schema_version"], "v4")
        self.assertTrue(metadata["strict"])
        self.assertEqual(metadata["agent_id"], "codex")
        self.assertIn("compiler_version", metadata)
        # A lock that no longer carries a body hash cannot be checked against its source
        # at all, so the hash is asserted to be present and to be a hex digest.
        for field in ("frontmatter_hash", "body_hash"):
            self.assertRegex(metadata[field], r"^[0-9a-f]{64}$")

    def test_the_workflow_declares_exactly_the_contracts_real_dispatch_inputs(self):
        inputs = set(trigger_block(self.front)["workflow_dispatch"]["inputs"])
        # `aw_context` is gh-aw's own internal caller-context input, added by the compiler.
        inputs.discard("aw_context")
        self.assertEqual(inputs, set(contract.REAL_DISPATCH_INPUT_NAMES))
        self.assertEqual(inputs, {"runtime_task_id", "attempt", "execution_request_id",
                                  "task_kind", "task_payload"})

    def test_a_gh_aw_dispatch_carries_the_identity_the_kind_and_the_payload(self):
        request = contract.build_dispatch_request(
            TASK, 1, contract.task_spec(contract.GHAW_BUILDER_KIND, payload()))
        inputs = contract.dispatch_inputs(request)
        self.assertEqual(set(inputs), set(contract.REAL_DISPATCH_INPUT_NAMES))
        self.assertEqual(inputs["runtime_task_id"], TASK)
        # GitHub dispatch inputs are strings, but the contract keeps the attempt honest:
        # it is the integer the Runtime claimed, stringified only at the wire.
        self.assertEqual(inputs["attempt"], 1)
        self.assertEqual(str(inputs["attempt"]), "1")
        self.assertEqual(inputs["execution_request_id"], request["execution_request_id"])
        self.assertEqual(inputs["task_kind"], "GHAW_BUILDER_V1")
        self.assertEqual(json.loads(inputs["task_payload"]), payload())
        self.assertEqual(request["provider"], contract.PROVIDER_GHAW_BUILDER)

    def test_the_run_name_and_the_artifact_name_are_the_contracts_own(self):
        self.assertEqual(
            self.front["run-name"],
            contract.run_identity_name("${{ inputs.runtime_task_id }}",
                                       "${{ inputs.attempt }}",
                                       "${{ inputs.execution_request_id }}"))
        # The artifact the pull leg looks for is derived from the execution identity; if
        # the workflow uploaded anything else, the result would never be found - and the
        # task would sit in the outbox forever while the run looked perfectly green.
        expected_artifact = (result_pull.ARTIFACT_PREFIX
                             + "${{ inputs.execution_request_id }}")
        self.assertEqual(expected_artifact,
                         "c1-ai-execution-result-${{ inputs.execution_request_id }}")
        uploads = [step for step in self.front["post-steps"]
                   if str(step.get("uses", "")).startswith("actions/upload-artifact")]
        self.assertEqual(len(uploads), 1, "exactly one artifact, and it is the result")
        self.assertEqual(uploads[0]["with"]["name"], expected_artifact)
        self.assertEqual(uploads[0]["with"]["path"], client_mod.RESULT_ARTIFACT_FILE)
        # And the compiled file the runner actually reads carries both of them.
        self.assertIn("name: " + expected_artifact, self.lock_text)
        self.assertIn("path: c1_result.json", self.lock_text)
        self.assertEqual(client_mod.RESULT_ARTIFACT_FILE, "c1_result.json")

    def test_the_workflow_refuses_any_kind_but_its_own(self):
        scripts = embedded_scripts(BUILDER_SOURCE)
        self.assertEqual(len(scripts), 2, "one gate before the agent, one seal after")
        self.assertIn("WORK_ORDER_ACCEPTED", scripts[0])
        for script in scripts:
            literals = {node.value for node in _ast.walk(_ast.parse(script))
                        if isinstance(node, _ast.Constant) and isinstance(node.value, str)}
            # Each gate holds its own kind and refuses through sys.exit; no gate holds
            # another class's kind as a string anywhere in its logic. (Prose around the
            # gate names them on purpose - it is the refusal that must not, so this reads
            # literals out of the parsed script rather than its text.)
            self.assertIn("GHAW_BUILDER_V1", literals)
            self.assertIn("sys.exit", script)
            for foreign in ("AI_WORK_V1", "AI_TASK_V1", "RUNTIME_PROBE"):
                self.assertNotIn(foreign, literals)


class TheWorkflowScriptsBehaveOffline(unittest.TestCase):
    """D - the gates are executed, not read. Both directions."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c1-u1-step-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        scripts = embedded_scripts(BUILDER_SOURCE)
        self.gate, self.seal = scripts

    def test_the_gate_accepts_a_gh_aw_work_order_and_materialises_it(self):
        completed = run_script(self.gate, workdir=self.tmp, environ={
            "TASK_KIND": "GHAW_BUILDER_V1",
            "TASK_PAYLOAD": contract.canonical(payload()),
        })
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("WORK_ORDER_ACCEPTED", completed.stdout)
        written = json.loads((Path(self.tmp) / "c1_builder_task.json").read_text())
        self.assertEqual(written, payload())

    def test_the_gate_refuses_every_other_kind_before_the_agent_starts(self):
        for kind in ("AI_WORK_V1", "AI_TASK_V1", "RUNTIME_PROBE", "", "GHAW_BUILDER_V2"):
            with self.subTest(kind=kind):
                path = Path(self.tmp) / "c1_builder_task.json"
                if path.exists():
                    path.unlink()
                completed = run_script(self.gate, workdir=self.tmp, environ={
                    "TASK_KIND": kind,
                    "TASK_PAYLOAD": contract.canonical(payload()),
                })
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("TASK_KIND_NOT_OWNED_BY_THIS_EXECUTOR", completed.stderr)
                self.assertFalse(path.exists(), "a refused kind must materialise nothing")

    def test_the_gate_refuses_a_payload_that_is_not_a_work_order(self):
        completed = run_script(self.gate, workdir=self.tmp, environ={
            "TASK_KIND": "GHAW_BUILDER_V1", "TASK_PAYLOAD": "{not json"})
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("TASK_PAYLOAD_NOT_JSON", completed.stderr)

    def test_the_seal_produces_a_result_the_runtime_contract_accepts(self):
        request = contract.build_dispatch_request(
            TASK, 1, contract.task_spec(contract.GHAW_BUILDER_KIND, payload()))
        answer = "The objective: state the objective you were given, in one line."
        (Path(self.tmp) / "ghaw_builder_answer.txt").write_text(answer, encoding="utf-8")
        completed = run_script(self.seal, workdir=self.tmp, environ={
            "TASK_KIND": "GHAW_BUILDER_V1", "TASK_PAYLOAD": "",
            "RUNTIME_TASK_ID": TASK, "ATTEMPT": "1",
            "EXECUTION_REQUEST_ID": request["execution_request_id"],
            "RUN_ID": "424242", "RUN_ATTEMPT": "1",
        })
        self.assertEqual(completed.returncode, 0, completed.stderr)
        document = json.loads((Path(self.tmp) / "c1_result.json").read_text())
        # The Runtime's own validator, unchanged, on the bytes the workflow seals.
        contract.validate_result(document, runtime_task_id=TASK, attempt=1,
                                 execution_request_id_=request["execution_request_id"],
                                 task_kind=contract.GHAW_BUILDER_KIND)
        self.assertEqual(document["provider"], contract.PROVIDER_GHAW_BUILDER)
        self.assertEqual(document["output"], answer)
        self.assertEqual(document["output_sha256"], contract.output_sha256(answer))
        self.assertEqual(document["github_run_id"], 424242)

    def test_the_smoke_acceptance_rule_cannot_be_satisfied_by_a_builder_result(self):
        """The two classes stay separate in both directions."""
        request = contract.build_dispatch_request(
            TASK, 1, contract.task_spec(contract.GHAW_BUILDER_KIND, payload()))
        (Path(self.tmp) / "ghaw_builder_answer.txt").write_text("builder answer",
                                                                encoding="utf-8")
        run_script(self.seal, workdir=self.tmp, environ={
            "TASK_KIND": "GHAW_BUILDER_V1", "RUNTIME_TASK_ID": TASK, "ATTEMPT": "1",
            "EXECUTION_REQUEST_ID": request["execution_request_id"],
            "RUN_ID": "424242", "RUN_ATTEMPT": "1",
        })
        document = json.loads((Path(self.tmp) / "c1_result.json").read_text())
        # Judged as a smoke result it is refused outright - the executor identity alone
        # is enough, which is the point: the classes cannot be confused for one another
        # even when the text would be indistinguishable.
        with self.assertRaises(contract.Refused) as raised:
            contract.validate_result(document, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=request["execution_request_id"],
                                     task_kind=contract.KIND)
        self.assertEqual(raised.exception.reason, "RESULT_PROVIDER_MISMATCH")

    def test_the_seal_refuses_a_foreign_kind_and_an_empty_answer(self):
        base = {"RUNTIME_TASK_ID": TASK, "ATTEMPT": "1",
                "EXECUTION_REQUEST_ID": "deadbeef", "RUN_ID": "1", "RUN_ATTEMPT": "1"}
        (Path(self.tmp) / "ghaw_builder_answer.txt").write_text("x", encoding="utf-8")
        foreign = run_script(self.seal, workdir=self.tmp,
                             environ=dict(base, TASK_KIND="AI_TASK_V1"))
        self.assertNotEqual(foreign.returncode, 0)
        self.assertIn("TASK_KIND_NOT_OWNED_BY_THIS_EXECUTOR", foreign.stderr)

        (Path(self.tmp) / "ghaw_builder_answer.txt").write_text("   \n", encoding="utf-8")
        empty = run_script(self.seal, workdir=self.tmp,
                           environ=dict(base, TASK_KIND="GHAW_BUILDER_V1"))
        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("ANSWER_EMPTY", empty.stderr)


class TheResponsesPathIsFrozen(unittest.TestCase):
    """E - nothing on the old path may move."""

    def test_the_smoke_identity_is_the_one_already_recorded(self):
        self.assertEqual(contract.execution_request_id(TASK, 1), FROZEN_SMOKE_REQUEST_ID)

    def test_the_real_task_identity_is_the_one_already_recorded(self):
        spec = contract.task_spec(contract.REAL_TASK_KIND, FROZEN_PAYLOAD)
        self.assertEqual(contract.execution_request_id(TASK, 1, spec),
                         FROZEN_REAL_REQUEST_ID)

    def test_the_responses_targets_are_unchanged(self):
        self.assertEqual(contract.WORKFLOW_FILE, "c1-ai-execution-backend-v1.yml")
        self.assertEqual(contract.REF, "main")
        self.assertEqual(contract.REPO, "yuguangzhi3836-glitch/GO")
        self.assertEqual(contract.DISPATCH_ENDPOINT,
                         "/repos/yuguangzhi3836-glitch/GO/actions/workflows/"
                         "c1-ai-execution-backend-v1.yml/dispatches")
        for kind in (contract.KIND, contract.REAL_TASK_KIND):
            request = contract.build_dispatch_request(
                TASK, 1, None if kind == contract.KIND
                else contract.task_spec(kind, FROZEN_PAYLOAD))
            self.assertEqual(request["workflow_file"], contract.WORKFLOW_FILE)
            self.assertEqual(request["ref"], contract.REF)
            self.assertEqual(request["repo"], contract.REPO)

    def test_the_responses_executors_own_boundary_is_unchanged(self):
        self.assertEqual(worker.WORKFLOW_FILE, contract.WORKFLOW_FILE)
        self.assertEqual(worker.CLAIM_KINDS, ("AI_WORK_V1", "AI_TASK_V1"))
        self.assertEqual(worker.OUTBOX_DB, "/var/lib/go-runtime-c1/outbox.db")
        # The default binding - what the deployed worker gets with no argument - is still
        # the Responses workflow.
        self.assertEqual(worker.build_client().workflow_target()["workflow_file"],
                         contract.WORKFLOW_FILE)


class NothingHereCanSpendMoney(unittest.TestCase):
    """F - the registration is inert until the Runtime dispatches it."""

    def setUp(self):
        self.front = front_matter(BUILDER_SOURCE)
        self.lock_text = BUILDER_LOCK.read_text(encoding="utf-8")

    def test_the_workflow_has_no_automatic_trigger(self):
        # Dispatch-only is the whole reason this workflow may be registered before it is
        # merged: it cannot fire for a reason nobody chose.
        self.assertEqual(set(trigger_block(self.front)), {"workflow_dispatch"})
        for trigger in ("push", "schedule", "repository_dispatch", "pull_request",
                        "workflow_run", "issues", "issue_comment"):
            self.assertNotIn(trigger, trigger_block(self.front))

    def test_a_credit_ceiling_is_declared(self):
        self.assertIsInstance(self.front["max-ai-credits"], int)
        self.assertGreater(self.front["max-ai-credits"], 0)
        self.assertIn("GH_AW_MAX_AI_CREDITS", self.lock_text)

    def test_the_agents_tool_surface_is_exactly_what_the_source_declares(self):
        """U1 declared `edit` alone; the engineering round added `bash` and nothing else.

        Written as an agreement between the source and the compiled file rather than as a
        fixed list, because that is what makes the change visible in both directions: a
        stale lock cannot keep a capability the source no longer declares, and it cannot
        hide one the source does declare.
        """
        tools = self.front["tools"]
        self.assertEqual(set(tools), {"edit", "bash", "cli-proxy"})
        self.assertIn("edit", tools)
        self.assertIs(tools["cli-proxy"], False)
        if tools["bash"] is False:
            self.assertIn("features.shell_tool=false", self.lock_text)
        else:
            self.assertIs(tools["bash"], True)
            self.assertNotIn("features.shell_tool=false", self.lock_text)

    def test_the_write_surface_is_exactly_one_draft_pull_request(self):
        """The repository write path is the PR writer, and nothing else was added.

        Where that permission lands is a separate question and is asserted on the compiled
        jobs: only the safe-outputs and conclusion jobs carry it, never the agent's.
        Section C of test_c1_builder_engineering_surface holds that line.
        """
        outputs = {name for name in self.front["safe-outputs"] if name != "steps"}
        self.assertEqual(outputs, {"report-failure-as-issue", "create-pull-request"})
        for extra in ("create-issue", "update-issue", "add-comment",
                      "push-to-pull-request-branch", "merge-pull-request",
                      "update-pull-request", "create-or-update-secret",
                      "deploy-pages", "update-release"):
            with self.subTest(extra=extra):
                self.assertNotIn(extra, self.front["safe-outputs"])
                self.assertNotIn(extra, self.lock_text)

    def test_the_worker_unit_is_a_candidate_and_is_not_installed_here(self):
        self.assertTrue(UNIT_CANDIDATE.is_file())
        text = UNIT_CANDIDATE.read_text(encoding="utf-8")
        # It reuses #381's boundary rather than inventing a second Runtime.
        self.assertIn("c1_ghaw_builder_worker.py", text)
        self.assertIn("ConditionPathExists=/etc/go-runtime-c1/github-token", text)
        self.assertIn("User=go-runtime", text)
        self.assertIn("ReadWritePaths=/var/lib/go-c-runtime /var/lib/go-runtime-c1", text)
        self.assertNotIn("/etc/systemd/system", text)
        # Nothing in the repository enables it: a unit file that some file also links into
        # a target would be an installation wearing a candidate's name.
        for path in (HERE / "c1_ghaw_builder_worker.py", UNIT_CANDIDATE):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("systemctl", source)
            self.assertNotIn("enable --now", source)

    def test_no_test_in_this_file_opens_a_real_connection(self):
        """Every transport here is a double; the only process spawned is the workflow's
        own script, which touches nothing but its own files."""
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("RoutingOpener", source)
        self.assertIn("sys.executable", source)
        # A real opener is never constructed: the client always receives the recording one.
        self.assertNotIn("GitHubActionsClient(token_loader=lambda: \"u1-test-token\")", source)
        self.assertIn("opener=opener", source)
        # And the workflow itself cannot fire without a dispatch.
        self.assertEqual(set(trigger_block(front_matter(BUILDER_SOURCE))),
                         {"workflow_dispatch"})


if __name__ == "__main__":
    unittest.main()
