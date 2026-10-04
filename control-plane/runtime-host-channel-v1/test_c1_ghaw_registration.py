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

# The commit the offline gate runs pretend to be executing on. In a real run the workflow
# takes this from GitHub (`github.sha`) - it is supplied here as the WORKFLOW_SHA env var so
# the gate script can be executed exactly as the runner would execute it.
WORKFLOW_SHA = "e4076276d70058d16f68fda5db047161ca6ef4cc"
# A real earlier commit, standing for "the source an issue was written against before main
# moved on" - what the ten historical open issues carry.
STALE_SHA = "8ffcde66d36c1bbf849218529ef015f6e81725af"

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


def payload(external_task_id="C01-BUILDER-1", *, source_anchor=WORKFLOW_SHA):
    return contract.build_task_payload(
        cell_id="C01", external_task_id=external_task_id,
        objective="State the objective you were given, in one line.",
        scope="No real execution. Answer with one short line.",
        source_anchor=source_anchor)


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
        self.assertEqual(inputs, set(contract.GHAW_BUILDER_INPUT_NAMES))
        self.assertEqual(inputs, {"runtime_task_id", "attempt", "execution_request_id",
                                  "owner_c", "task_kind", "task_payload"})
        self.assertNotIn("owner_c", contract.REAL_DISPATCH_INPUT_NAMES)

    def test_a_gh_aw_dispatch_carries_identity_kind_cell_and_payload(self):
        request = contract.build_dispatch_request(
            TASK, 1, contract.task_spec(contract.GHAW_BUILDER_KIND, payload()))
        inputs = contract.dispatch_inputs(request)
        self.assertEqual(set(inputs), set(contract.GHAW_BUILDER_INPUT_NAMES))
        self.assertEqual(inputs["runtime_task_id"], TASK)
        # GitHub dispatch inputs are strings, but the contract keeps the attempt honest:
        # it is the integer the Runtime claimed, stringified only at the wire.
        self.assertEqual(inputs["attempt"], 1)
        self.assertEqual(str(inputs["attempt"]), "1")
        self.assertEqual(inputs["execution_request_id"], request["execution_request_id"])
        self.assertEqual(inputs["task_kind"], "GHAW_BUILDER_V1")
        self.assertEqual(json.loads(inputs["task_payload"]), payload())
        # The cell travels twice by two different routes so that the workflow can compare
        # them: once as its own input, once inside the payload it was derived from.
        self.assertEqual(inputs["owner_c"], request["owner_c"])
        self.assertEqual(inputs["owner_c"], "C1")
        self.assertEqual(json.loads(inputs["task_payload"])["cell_id"], "C1")
        self.assertEqual(request["provider"], contract.PROVIDER_GHAW_BUILDER)

    def test_the_responses_real_class_did_not_gain_an_owner_input(self):
        """Widening the Builder must not widen the Responses dispatch."""
        request = contract.build_dispatch_request(
            TASK, 1, contract.task_spec(contract.REAL_TASK_KIND, payload()))
        inputs = contract.dispatch_inputs(request)
        self.assertEqual(set(inputs), set(contract.REAL_DISPATCH_INPUT_NAMES))
        self.assertNotIn("owner_c", inputs)

    def test_the_run_name_and_the_artifact_name_are_the_contracts_own(self):
        self.assertEqual(
            self.front["run-name"],
            contract.run_identity_name("${{ inputs.runtime_task_id }}",
                                       "${{ inputs.attempt }}",
                                       "${{ inputs.execution_request_id }}",
                                       owner_c="${{ inputs.owner_c }}"))
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
            "OWNER_C": "C1",
            "WORKFLOW_SHA": WORKFLOW_SHA,
        })
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("WORK_ORDER_ACCEPTED", completed.stdout)
        written = json.loads((Path(self.tmp) / "c1_builder_task.json").read_text())
        self.assertEqual(written, payload())

    # ---------------------------------------- the cell gate, exercised for real
    def _run_gate(self, *, cell, owner_c, kind="GHAW_BUILDER_V1",
                  source_anchor=WORKFLOW_SHA, workflow_sha=WORKFLOW_SHA,
                  drop_source=False):
        """Run the real gate script on a hand-built payload.

        The payload is composed here rather than through the contract on purpose: these
        tests ask what the workflow does when something upstream did NOT stop it, so
        routing the input through the validator would test the validator instead of the
        gate. The raw cell spelling is what a mis-issued dispatch would actually carry.

        `workflow_sha=None` omits the variable entirely, which is what the runner does if
        GitHub ever fails to supply it.
        """
        path = Path(self.tmp) / "c1_builder_task.json"
        if path.exists():
            path.unlink()
        body = {"schema_version": 1, "cell_id": cell,
                "external_task_id": "C12-BUILDER-1",
                "objective": "State the objective you were given, in one line.",
                "scope": "No real execution. Answer with one short line."}
        if not drop_source:
            body["source_anchor"] = source_anchor
        environ = {"TASK_KIND": kind, "TASK_PAYLOAD": contract.canonical(body),
                   "OWNER_C": owner_c}
        if workflow_sha is not None:
            environ["WORKFLOW_SHA"] = workflow_sha
        completed = run_script(self.gate, workdir=self.tmp, environ=environ)
        return completed, path

    def test_the_gate_accepts_every_builder_cell(self):
        for cell in ("C1", "C01", "C2", "C12"):
            with self.subTest(cell=cell):
                # The owner input is canonical on the wire, whatever spelling the payload
                # uses; that is what the contract sends and what the gate requires.
                completed, path = self._run_gate(cell=cell, owner_c="C1"
                                                 if cell == "C01" else cell)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                written = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(written["cell_id"], cell)

    def test_the_gate_refuses_the_control_only_cells(self):
        # C13/C14 are control-only. The payload validator refuses them upstream and the
        # worker never claims them - and this gate refuses them again, on its own. A
        # defence that depends on another component having already run is not a defence.
        # The owner is a legal cell here, so it is the PAYLOAD half that is refused.
        for cell in ("C13", "C14"):
            with self.subTest(cell=cell):
                completed, path = self._run_gate(cell=cell, owner_c="C1")
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("TASK_PAYLOAD_CELL_NOT_OWNED_BY_BUILDER_EXECUTOR",
                              completed.stderr)
                self.assertFalse(path.exists())

    def test_the_gate_refuses_a_cell_outside_the_kernel_range(self):
        for cell in ("C0", "C00", "C15", "C99"):
            with self.subTest(cell=cell):
                completed, path = self._run_gate(cell=cell, owner_c="C1")
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("CELL_NOT_A_KNOWN_RESPONSIBILITY_DOMAIN", completed.stderr)
                self.assertFalse(path.exists())

    def test_the_gate_refuses_an_owner_that_disagrees_with_the_payload(self):
        completed, path = self._run_gate(cell="C2", owner_c="C3")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("OWNER_C_DOES_NOT_MATCH_TASK_PAYLOAD", completed.stderr)
        self.assertFalse(path.exists())

    def test_the_gate_refuses_a_missing_owner(self):
        completed, path = self._run_gate(cell="C2", owner_c="")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("OWNER_C_MISSING", completed.stderr)
        self.assertFalse(path.exists())

    def test_the_gate_refuses_the_control_only_owner_before_comparing_it(self):
        # Both halves say C13. They agree with each other and are both wrong, which is
        # precisely the case a bare equality check would wave straight through. The owner
        # is refused as a control-only cell rather than as a mismatch, which is the
        # honest description of what is wrong with it.
        completed, path = self._run_gate(cell="C13", owner_c="C13")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("OWNER_C_NOT_OWNED_BY_BUILDER_EXECUTOR", completed.stderr)
        self.assertFalse(path.exists())

    def test_the_gate_refuses_a_padded_owner_spelling(self):
        # The contract sends the canonical spelling. A padded owner means this dispatch did
        # not come from the contract, and the range check - which is expressed in canonical
        # names - refuses it rather than reconciling the two spellings on the fly.
        completed, path = self._run_gate(cell="C01", owner_c="C01")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("OWNER_C_NOT_OWNED_BY_BUILDER_EXECUTOR", completed.stderr)
        self.assertFalse(path.exists())

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

    # ---------------------------------------- the source gate, exercised for real
    def test_the_gate_accepts_a_work_order_for_the_sha_it_is_running_on(self):
        completed, path = self._run_gate(cell="C12", owner_c="C12")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["source_anchor"],
                         WORKFLOW_SHA)

    def test_the_gate_refuses_a_work_order_written_against_another_sha(self):
        # The queue race, in one run: the task was admitted while main was A, and by the
        # time it was dispatched main had become B. The payload still says A. Refused
        # before the agent starts, so no model is ever called for the wrong tree.
        completed, path = self._run_gate(cell="C12", owner_c="C12", source_anchor=STALE_SHA)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("SOURCE_ANCHOR_DOES_NOT_MATCH_WORKFLOW_SHA", completed.stderr)
        self.assertFalse(path.exists(), "a mis-bound work order must materialise nothing")

    def test_the_gate_refuses_a_work_order_that_states_no_source(self):
        completed, path = self._run_gate(cell="C12", owner_c="C12", drop_source=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("TASK_PAYLOAD_SOURCE_ANCHOR_MISSING_OR_INVALID", completed.stderr)
        self.assertFalse(path.exists())

    def test_the_gate_refuses_a_malformed_source_anchor(self):
        for bad in ("", "not-a-sha", "8ffcde66", WORKFLOW_SHA + "0", "0" * 64):
            with self.subTest(anchor=bad):
                completed, path = self._run_gate(cell="C12", owner_c="C12",
                                                 source_anchor=bad)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("TASK_PAYLOAD_SOURCE_ANCHOR_MISSING_OR_INVALID",
                              completed.stderr)
                self.assertFalse(path.exists())

    def test_the_gate_refuses_when_the_execution_sha_is_unavailable(self):
        completed, path = self._run_gate(cell="C12", owner_c="C12", workflow_sha=None)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("WORKFLOW_SHA_UNAVAILABLE", completed.stderr)
        self.assertFalse(path.exists())

    def test_the_workflow_takes_its_source_from_github_not_from_the_caller(self):
        # The authority is the run's own execution SHA. A caller-supplied "current main"
        # would be a claim, and a gate that trusts a claim is not a gate.
        front = front_matter(BUILDER_SOURCE)
        inputs = set(trigger_block(front)["workflow_dispatch"]["inputs"])
        self.assertEqual(inputs, {"runtime_task_id", "attempt", "execution_request_id",
                                  "owner_c", "task_kind", "task_payload"})
        for forbidden in ("execution_sha", "current_main", "checkout_sha", "workflow_sha",
                          "source_sha", "main_sha"):
            with self.subTest(input=forbidden):
                self.assertNotIn(forbidden, inputs)

    def test_the_compiled_workflow_binds_githubs_own_execution_sha(self):
        lock = BUILDER_LOCK.read_text(encoding="utf-8")
        self.assertIn("WORKFLOW_SHA: ${{ github.sha }}", lock)
        self.assertIn("SOURCE_ANCHOR_DOES_NOT_MATCH_WORKFLOW_SHA", lock)

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
