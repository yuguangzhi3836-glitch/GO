"""The C1 worker's contract: it owns AI_WORK_V1 and nothing else.

The two properties this file exists to keep true:

  1. the worker claims `AI_WORK_V1` tasks and only those - a queued `RUNTIME_PROBE` task
     is never selected, and is provably untouched afterwards (still QUEUED, attempts 0);
  2. the worker never reaches into the probe path - it does not import the channel, the
     flow or the host-probe adapter, does not know the bridge directories, and cannot
     name a model credential.

It reuses the Runtime and GitHub doubles from `test_c1_execution_loop`, so the Runtime
fencing rules exercised here are literally the same ones the loop tests use.
"""
import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_execution_contract as contract  # noqa: E402
import c1_worker as worker  # noqa: E402
import test_c1_execution_loop as harness  # noqa: E402

UNIT = HERE / "systemd/go-runtime-host-c1-worker.service"
TMPFILES = HERE / "systemd/go-runtime-host-c1-worker.tmpfiles.conf"
PROBE_KEY = "probe-fixture"


class WorkerCase(harness.LoopCase):
    """A loop harness plus the worker entry point, with the doubles already wired."""

    def setUp(self):
        super().setUp()
        self.worker_outbox = self.outbox

    def enqueue_probe(self):
        # Queued FIRST on purpose: if the worker's kind filter were absent, the probe
        # would be the task it picks up.
        return self.runtime.enqueue("C1", "RUNTIME_PROBE", {"probe": 1},
                                    idempotency_key=PROBE_KEY)

    def worker_tick(self):
        return worker.tick(self.runtime, self.worker_outbox, self.github, clock=self.clock)

    def run_main(self, argv, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = worker.main(argv, runtime=self.runtime, outbox=self.worker_outbox,
                               client=self.github, clock=self.clock, **kwargs)
        return code, buf.getvalue()


class TheWorkerOwnsOnlyAiWork(WorkerCase):
    def test_a_queued_probe_is_never_selected_even_when_it_is_first_in_line(self):
        probe_task_id = self.enqueue_probe()
        ai_task_id = self.enqueue_c1()

        outcome = self.worker_tick()

        self.assertEqual(outcome["status"], "ADVANCED", outcome)
        self.assertEqual(outcome["runtime_task_id"], ai_task_id)
        self.assertEqual(outcome["kind"], contract.KIND)
        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual(self.github.dispatch_calls, 1)

        # The probe is exactly as it was: never claimed, attempts never incremented.
        self.assertEqual(self.runtime.status_of(probe_task_id), "QUEUED")
        self.assertEqual(self.runtime.tasks[probe_task_id].attempts, 0)
        self.assertIsNone(self.runtime.tasks[probe_task_id].lease_owner)

    def test_a_lone_probe_leaves_the_worker_idle(self):
        probe_task_id = self.enqueue_probe()

        outcome = self.worker_tick()

        self.assertEqual(outcome, {"status": "IDLE", "claimed": False})
        self.assertEqual(self.github.dispatch_calls, 0)
        self.assertEqual(self.runtime.status_of(probe_task_id), "QUEUED")
        # The enqueue its own Evidence is expected; what must NOT exist is a claim.
        events = [row["event_type"] for row in self.runtime.evidence]
        self.assertEqual(events, ["TASK_ENQUEUED"])
        self.assertNotIn("TASK_CLAIMED", events)

    def test_the_claimed_kind_set_is_exactly_ai_work_v1(self):
        self.assertEqual(worker.CLAIM_KINDS, ("AI_WORK_V1",))
        self.assertNotIn("RUNTIME_PROBE", worker.CLAIM_KINDS)
        self.assertEqual(worker.OWNER_C, "C1")

    def test_two_ticks_do_not_dispatch_twice(self):
        self.enqueue_c1()
        self.assertEqual(self.worker_tick()["action"], "COMPLETED")
        second = self.worker_tick()
        self.assertEqual(second["status"], "IDLE")
        self.assertEqual(self.github.dispatch_calls, 1)


class NoClaimWithoutACredential(WorkerCase):
    """Claiming a task the worker cannot execute would burn one of its attempts."""

    def test_a_missing_credential_means_nothing_is_claimed(self):
        task_id = self.enqueue_c1()

        def absent():
            raise contract.Refused("TOKEN_FILE_UNREADABLE")

        code, out = self.run_main(["--once"], token_loader=absent)

        self.assertEqual(code, 1)
        self.assertIn("no_github_credential", out)
        self.assertEqual(self.runtime.status_of(task_id), "QUEUED")
        self.assertEqual(self.runtime.tasks[task_id].attempts, 0)
        self.assertEqual(self.github.dispatch_calls, 0)

    def test_an_empty_credential_means_nothing_is_claimed(self):
        task_id = self.enqueue_c1()
        code, out = self.run_main(["--once"], token_loader=lambda: "   ")
        self.assertEqual(code, 1)
        self.assertIn("empty_github_credential", out)
        self.assertEqual(self.runtime.status_of(task_id), "QUEUED")

    def test_check_reports_readiness_without_claiming(self):
        task_id = self.enqueue_c1()
        code, out = self.run_main(["--check"], token_loader=lambda: "present")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["claimed_kinds"], ["AI_WORK_V1"])
        self.assertEqual(payload["credential"], "present")
        # Readiness only: nothing was claimed and nothing was executed.
        self.assertEqual(self.runtime.status_of(task_id), "QUEUED")
        self.assertEqual(self.github.dispatch_calls, 0)

    def test_the_credential_value_never_appears_in_the_status_line(self):
        secret = "github_pat_DO-NOT-PRINT-THIS-VALUE"
        code, out = self.run_main(["--check"], token_loader=lambda: secret)
        self.assertEqual(code, 0)
        self.assertNotIn(secret, out)
        self.assertNotIn("github_pat_", out)


class TheStatusLineIsAnAllowlist(WorkerCase):
    def test_a_tick_emits_only_allowed_fields(self):
        self.enqueue_c1()
        code, out = self.run_main(["--once"], token_loader=lambda: "present")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertLessEqual(set(payload), set(worker.STATUS_FIELDS))
        self.assertEqual(payload["status"], "ADVANCED")
        self.assertEqual(payload["claimed"], True)
        self.assertEqual(payload["verb"], "c1-worker-tick")

    def test_an_unknown_field_is_dropped_rather_than_printed(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            worker.emit({"status": "READY", "a_token": "leak", "detail": "x"})
        self.assertEqual(json.loads(buf.getvalue()), {"status": "READY", "detail": "x"})

    def test_a_bad_argument_is_refused(self):
        code, out = self.run_main(["--nonsense"], token_loader=lambda: "present")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["reason"], "bad_argument")

    def test_the_interval_is_bounded(self):
        for bad in ("0", "-1", "99999", "abc"):
            code, out = self.run_main(["--interval", bad], token_loader=lambda: "present")
            self.assertEqual(code, 1, bad)
            self.assertIn(json.loads(out)["reason"], ("interval_out_of_range", "bad_argument"))


class ArgumentHandling(WorkerCase):
    def test_argv_with_or_without_the_program_name_behaves_the_same(self):
        # `main(sys.argv)` includes the program name; a programmatic caller usually does
        # not. Treating a missing program name as "no mode flag" would silently start the
        # resident loop, so both forms are pinned here.
        self.enqueue_c1()
        code_with, out_with = self.run_main(["c1_worker.py", "--check"],
                                            token_loader=lambda: "present")
        code_without, out_without = self.run_main(["--check"], token_loader=lambda: "present")
        self.assertEqual((code_with, code_without), (0, 0))
        self.assertEqual(json.loads(out_with)["status"], "READY")
        self.assertEqual(json.loads(out_without)["status"], "READY")

    def test_no_arguments_is_the_only_way_into_the_resident_loop(self):
        # Every bounded mode is explicit, so a mistake here cannot spin a paid worker.
        source = (HERE / "c1_worker.py").read_text(encoding="utf-8")
        self.assertIn('if once:\n            return 0\n        time.sleep(interval)', source)


class ItRefusesToStartWithoutItsRuntime(unittest.TestCase):
    def test_the_runtime_is_imported_from_its_installed_path_and_nowhere_else(self):
        self.assertEqual(worker.RUNTIME_SOURCE_DIR, "/opt/go/c1-c14-runtime")
        with self.assertRaises(ModuleNotFoundError):
            worker.load_runtime("/nonexistent/go-runtime-source-dir")

    def test_the_installed_locations_are_constants_not_inputs(self):
        # Same pattern as the bridge service: the two components cannot disagree about
        # where the Runtime is, and neither accepts a path from a caller.
        self.assertEqual(worker.RUNTIME_DB, "/var/lib/go-c-runtime/runtime.db")
        self.assertEqual(worker.OUTBOX_DB, "/var/lib/go-runtime-c1/outbox.db")


class TheWorkerStaysOutOfTheProbePath(unittest.TestCase):
    """Asserted against the module's *code*, never against its prose.

    The docstring legitimately names the bridge service and the probe path - that is how
    it explains why this component exists separately - so scanning the raw text would fail
    for the wrong reason. The AST is the honest surface: what the module imports, which
    strings it actually builds, and what it calls.
    """

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse((HERE / "c1_worker.py").read_text(encoding="utf-8"))

    def imported_roots(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def code_strings(self):
        """Every string literal that is not a docstring."""
        docstrings = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docstrings.add(id(body[0].value))
        return [n.value for n in ast.walk(self.tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings]

    def test_it_does_not_import_the_probe_channel(self):
        for forbidden in ("channel", "flow", "adapter", "runtime_bridge", "agent_service"):
            self.assertNotIn(forbidden, self.imported_roots(), forbidden)

    def test_it_cannot_name_a_channel_action_or_a_bridge_path(self):
        joined = "\n".join(self.code_strings())
        for forbidden in ("RUNTIME_HOST_PROBE_V1", "RUNTIME_C1_PROBE_V1", "RUNTIME_PROBE",
                          "/var/lib/go-runtime-bridge", "registry"):
            self.assertNotIn(forbidden, joined, forbidden)

    def test_it_has_no_model_credential(self):
        joined = "\n".join(self.code_strings())
        for forbidden in ("OPENAI_API_KEY", "api.openai.com", "go-runtime-worker-c1",
                          "/etc/go-runtime-worker-c1.env"):
            self.assertNotIn(forbidden, joined, forbidden)

    def test_it_prints_nothing_and_logs_nothing(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(node.func.id, "print", "untargeted print")
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(getattr(node.value, "id", None), "logging")


class TheUnitKeepsTheWorkerUnprivilegedAndScoped(unittest.TestCase):
    def setUp(self):
        self.unit = UNIT.read_text(encoding="utf-8")

    def test_it_runs_as_the_account_that_owns_the_runtime_database(self):
        self.assertIn("User=go-runtime", self.unit)
        self.assertIn("Group=go-runtime", self.unit)
        self.assertNotIn("User=root", self.unit)

    def test_it_fails_closed_without_the_credential(self):
        self.assertIn("ConditionPathExists=/etc/go-runtime-c1/github-token", self.unit)
        self.assertIn("Environment=C1_GITHUB_TOKEN_PATH=/etc/go-runtime-c1/github-token",
                      self.unit)

    def directives(self):
        """Real directives only. Comments legitimately mention other units' settings."""
        lines = []
        for raw in self.unit.splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and not line.startswith("["):
                lines.append(line)
        return lines

    def test_it_is_hardened_but_keeps_its_one_legitimate_egress(self):
        for line in ("NoNewPrivileges=true", "ProtectSystem=strict", "PrivateTmp=true",
                     "ProtectHome=true", "PrivateDevices=true"):
            self.assertIn(line, self.directives())
        # The one runtime-host component that needs network, and only for api.github.com.
        # Asserted on directives, so the comment explaining the rule cannot satisfy it.
        self.assertNotIn("PrivateNetwork=true", self.directives())
        self.assertNotIn("PrivateNetwork=false", self.directives())
        self.assertIn("ONE runtime-host component with outbound network access", self.unit)

    def test_it_can_write_only_the_runtime_state_and_its_own_outbox(self):
        writable = [line for line in self.unit.splitlines() if line.startswith("ReadWritePaths=")]
        self.assertEqual(len(writable), 1)
        self.assertIn("/var/lib/go-c-runtime", writable[0])
        self.assertIn("/var/lib/go-runtime-c1", writable[0])
        readonly = [line for line in self.unit.splitlines() if line.startswith("ReadOnlyPaths=")]
        self.assertEqual(len(readonly), 1)
        self.assertIn("/opt/go/c1-c14-runtime", readonly[0])

    def test_it_is_not_installed_inside_the_agent_bundle(self):
        # The Agent's executor_sha256 covers every *.py in its bundle directory and is
        # bound by the registration. Installing the C1 line there would change the Agent's
        # identity and make it refuse with local_executor_mismatch until a re-registration.
        self.assertIn("ExecStart=/usr/bin/python3 -B "
                      "/opt/go/runtime-host-c1-worker/c1_worker.py", self.unit)
        self.assertIn("ConditionPathExists=/opt/go/runtime-host-c1-worker/c1_worker.py",
                      self.unit)
        for line in self.directives():
            if line.startswith(("ExecStart=", "WorkingDirectory=", "ConditionPathExists=")):
                self.assertNotIn("/opt/go/runtime-host-agent", line, line)

    def test_it_does_not_run_as_the_agent_or_touch_the_agent_config(self):
        self.assertNotIn("agent_service.py", self.unit)
        self.assertNotIn("/etc/go-runtime-host", self.unit)
        self.assertIn("WorkingDirectory=/opt/go/runtime-host-c1-worker", self.unit)

    def test_the_two_directories_are_single_owner_and_closed(self):
        conf = TMPFILES.read_text(encoding="utf-8")
        self.assertIn("d /etc/go-runtime-c1 0700 go-runtime go-runtime -", conf)
        self.assertIn("d /var/lib/go-runtime-c1 0700 go-runtime go-runtime -", conf)
        for line in conf.splitlines():
            if line.startswith("d "):
                self.assertIn("0700", line)
                self.assertNotIn("0640", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
