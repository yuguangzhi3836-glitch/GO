"""The machine job may report only the database it OBSERVED.

``docs/acceptance/c13-supplement-533/database-preflight.json`` recorded this defect
independently and named it exactly::

    "manifest_version_source": "literal in workflow, not actual application database
     observation"

A real round was published as a PostgreSQL 18.4 test while the entire inventory ran on
SQLite, because the version was a literal in the workflow and the database was chosen by
the candidate's own ``application/tests/conftest.py``. The repair is a measurement, so the
tests here are measurements too:

* the decision function is exercised over the shapes a real round produces (PostgreSQL up
  and used, PostgreSQL up and touched by nobody, PostgreSQL unreachable);
* the CLI contract is exercised - a witness before the run, a verdict after it;
* the workflow's **real embedded manifest block** is extracted and executed, so the claim
  the round publishes is tested as the bytes that actually run rather than as a pattern;
* the backend's version source is pinned to the observation, and to nothing else.

Nothing here needs PostgreSQL or Docker: the observation itself is proven on a real
disposable PostgreSQL 18.4 in the round's own evidence, and what these tests pin is that
the code cannot claim more than that measurement showed.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "c13-quality-acceptance.yml"

import lite_database_observation as observation  # noqa: E402 - path set by discovery
import lite_cli  # noqa: E402 - path set by discovery


def snapshot(tables, version=180004, database="c13_lite", reachable=True) -> dict:
    """One probe of the service, in the shape the module writes."""
    if not reachable:
        return {"reachable": False, "reason": "POSTGRESQL_NOT_REACHED"}
    return {
        "reachable": True,
        "database": database,
        "schema": observation.SCHEMA,
        "server_version_num": version,
        "observed_postgres_version": observation.version_text(version),
        "tables": len(tables),
        "schema_fingerprint": observation.fingerprint(tables),
    }


class VersionTextTests(unittest.TestCase):
    def test_the_server_number_is_rendered_with_postgresqls_own_arithmetic(self):
        self.assertEqual(observation.version_text(180004), "18.4")
        self.assertEqual(observation.version_text(180000), "18.0")
        self.assertEqual(observation.version_text(160001), "16.1")

    def test_the_fingerprint_follows_the_set_and_not_the_order(self):
        self.assertEqual(observation.fingerprint(["a", "b"]),
                         observation.fingerprint(["a", "b"]))
        self.assertNotEqual(observation.fingerprint(["a", "b"]),
                            observation.fingerprint(["b", "a"]))


class EvaluationTests(unittest.TestCase):
    """What a round is allowed to claim, given two observations of the service."""

    def test_a_schema_that_moved_proves_postgresql_was_used(self):
        record = observation.evaluate(snapshot([]), snapshot(["episodes", "orders"]))
        self.assertTrue(record["postgresql_actually_used"])
        self.assertTrue(record["schema_changed_during_the_run"])
        self.assertEqual(record["reason"], "POSTGRESQL_OBSERVED")
        self.assertEqual(record["postgres_version"], "18.4")

    def test_an_unchanged_schema_claims_no_version(self):
        """The measured shape of a round that only *looked* like PostgreSQL.

        PostgreSQL 18.4 was up and healthy; the suite used SQLite; the manifest said
        PostgreSQL. The proof is that the service's schema did not move, so the round may
        not name a version - while the observation itself is still preserved, because the
        record has to show what was measured, not only what was concluded.
        """
        record = observation.evaluate(snapshot([]), snapshot([]))
        self.assertFalse(record["postgresql_actually_used"])
        self.assertIsNone(record["postgres_version"])
        self.assertEqual(record["reason"], "SCHEMA_UNCHANGED_BY_THE_RUN")
        self.assertEqual(record["observed_postgres_version"], "18.4")

    def test_an_unreachable_service_claims_no_version(self):
        record = observation.evaluate(snapshot([], reachable=False), snapshot(["t"]))
        self.assertFalse(record["postgresql_actually_used"])
        self.assertIsNone(record["postgres_version"])
        self.assertEqual(record["reason"], "POSTGRESQL_NOT_REACHED")

    def test_a_service_that_fails_after_the_run_claims_no_version(self):
        record = observation.evaluate(snapshot([]), snapshot(["t"], reachable=False))
        self.assertFalse(record["postgresql_actually_used"])
        self.assertIsNone(record["postgres_version"])

    def test_a_before_probe_that_never_answered_claims_no_version(self):
        record = observation.evaluate({"reachable": False, "reason": "PSYCOPG_UNAVAILABLE"},
                                      snapshot(["t"]))
        self.assertFalse(record["postgresql_actually_used"])
        self.assertEqual(record["reason"], "PSYCOPG_UNAVAILABLE")

    def test_two_different_databases_claim_no_version(self):
        record = observation.evaluate(snapshot([]), snapshot(["t"], database="other_db"))
        self.assertFalse(record["postgresql_actually_used"])
        self.assertEqual(record["reason"], "PROBES_DISAGREE_ABOUT_THE_DATABASE")

    def test_a_resolved_version_is_never_a_literal(self):
        """A service that answers 19.x is reported as 19.x.

        Guarding the arithmetic is not pedantry: the whole defect was a version written
        down in advance, so a record that returned the written-down number whatever the
        server said would be the same defect wearing the observation's clothes.
        """
        record = observation.evaluate(snapshot([]), snapshot(["t"], version=190002))
        self.assertEqual(record["postgres_version"], "19.2")


class CommandLineTests(unittest.TestCase):
    """The step's own contract: a witness before the run, a verdict after it."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())

    def test_the_before_phase_is_a_witness_and_never_gates(self):
        out = self.root / "before.json"
        status = observation.main(
            ["--phase", "before", "--out", str(out)],
            probe_fn=lambda: {"reachable": False, "reason": "POSTGRESQL_NOT_REACHED"})
        self.assertEqual(status, 0, "the run must still happen; the AFTER phase is the gate")
        self.assertFalse(json.loads(out.read_text())["reachable"])

    def test_the_before_line_is_a_witness_and_not_a_verdict(self):
        """A successful run must not print a verdict-shaped line full of nulls.

        The first version did, and in a green run it read like a verdict that had failed
        to form - the exact ambiguity this change exists to remove. There is no conclusion
        before the run, so the line must not look like one.
        """
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            observation.main(["--phase", "before", "--out", str(self.root / "before.json")],
                             probe_fn=lambda: snapshot([]))
        line = stream.getvalue().strip().splitlines()[-1]
        self.assertTrue(line.startswith(observation.REPORT_PREFIX + observation.WITNESS_SUFFIX))
        payload = json.loads(line.split(" ", 1)[1])
        self.assertEqual(payload["phase"], "before")
        self.assertNotIn("postgresql_actually_used", payload)
        self.assertNotIn("postgres_version", payload)
        self.assertEqual(payload["tables"], 0)

    def test_the_after_line_is_the_verdict(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            observation.main(
                ["--phase", "after", "--before", str(self.root / "absent.json"),
                 "--out", str(self.root / "after.json")],
                probe_fn=lambda: snapshot(["episodes"]))
        line = stream.getvalue().strip().splitlines()[-1]
        payload = json.loads(line.split(" ", 1)[1])
        self.assertIn("postgresql_actually_used", payload)
        self.assertIsNone(payload["postgres_version"])

    def test_the_after_phase_gates_on_the_proof(self):
        before = self.root / "before.json"
        before.write_text(json.dumps(snapshot([])))
        out = self.root / "after.json"
        status = observation.main(
            ["--phase", "after", "--before", str(before), "--out", str(out)],
            probe_fn=lambda: snapshot(["episodes", "orders"]))
        self.assertEqual(status, 0)
        record = json.loads(out.read_text())
        self.assertEqual(record["postgres_version"], "18.4")
        self.assertEqual(record["before"]["tables"], 0)
        self.assertEqual(record["after"]["tables"], 2)

    def test_an_unproven_after_phase_exits_non_zero(self):
        before = self.root / "before.json"
        before.write_text(json.dumps(snapshot([])))
        out = self.root / "after.json"
        status = observation.main(
            ["--phase", "after", "--before", str(before), "--out", str(out)],
            probe_fn=lambda: snapshot([]))
        self.assertEqual(status, 1, "an unproven round must fail the step, never pass quietly")
        self.assertIsNone(json.loads(out.read_text())["postgres_version"])

    def test_a_missing_before_record_cannot_be_proven(self):
        out = self.root / "after.json"
        status = observation.main(
            ["--phase", "after", "--before", str(self.root / "absent.json"), "--out", str(out)],
            probe_fn=lambda: snapshot(["episodes"]))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(out.read_text())["reason"], "BEFORE_PHASE_RECORD_MISSING")


class WorkflowManifestTests(unittest.TestCase):
    """The workflow's REAL embedded manifest block, executed.

    Extracted from the shipped YAML and run as its own process, the same way
    ``test_lite_machine_inventory`` pins the block's hashing behaviour: a pattern match on
    a file cannot show what the round would actually publish, and this is the field the
    reviewer and the sealed record both read.
    """

    def manifest(self, database_bytes=None) -> dict:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("      - name: Record the machine-test manifest", 1)[1]
        source = textwrap.dedent(step.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
        root = pathlib.Path(tempfile.mkdtemp())
        output = root / "machine"
        output.mkdir()
        (output / "exit_code.txt").write_text("0\n")
        (output / "stdout.txt").write_text("passed\n")
        (output / "junit.xml").write_text('<testsuite tests="1" failures="0"/>')
        if database_bytes is not None:
            (output / "database.json").write_bytes(database_bytes)
        result = subprocess.run(
            [sys.executable, "-c", source], capture_output=True, text=True, timeout=60,
            env={**os.environ, "RUNNER_TEMP": str(root), "MACHINE_INVENTORY": "application/tests",
                 "CANDIDATE_SHA": "a" * 40, "APPLICATION_TREE": "b" * 40,
                 "MACHINE_OUTCOME": "success"})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((output / "manifest.json").read_text())

    def test_a_proven_observation_is_the_version_the_manifest_reports(self):
        manifest = self.manifest(json.dumps({
            "observed": True,
            "postgresql_actually_used": True,
            "postgres_version": "18.4",
            "observed_postgres_version": "18.4",
            "reason": "POSTGRESQL_OBSERVED",
            "after": {"tables": 563},
        }).encode())
        self.assertEqual(manifest["postgres_version"], "18.4")
        self.assertTrue(manifest["database_observation"]["postgresql_actually_used"])

    def test_an_unproven_observation_removes_the_postgresql_claim(self):
        manifest = self.manifest(json.dumps({
            "observed": True,
            "postgresql_actually_used": False,
            "postgres_version": None,
            "observed_postgres_version": "18.4",
            "reason": "SCHEMA_UNCHANGED_BY_THE_RUN",
        }).encode())
        self.assertIsNone(manifest["postgres_version"],
                          "an unproven round must not describe itself as PostgreSQL")
        self.assertEqual(manifest["database_observation"]["reason"], "SCHEMA_UNCHANGED_BY_THE_RUN")

    def test_a_sidecar_that_only_says_postgresql_is_not_a_proof(self):
        """A file full of the right words proves nothing without the measurement.

        This is the shape a string-based fix would have produced: the version present, the
        observation absent. The claim is refused anyway.
        """
        manifest = self.manifest(json.dumps({"postgres_version": "18.4"}).encode())
        self.assertIsNone(manifest["postgres_version"])

    def test_an_absent_observation_removes_the_postgresql_claim(self):
        manifest = self.manifest()
        self.assertIsNone(manifest["postgres_version"])
        self.assertIsNone(manifest["database_observation"])


class VersionClaimSourceTests(unittest.TestCase):
    """The version the C13 record binds comes from the observation, and from nowhere else."""

    def manifest_file(self, payload) -> str:
        path = pathlib.Path(tempfile.mkdtemp()) / "manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def test_the_observed_version_is_what_the_spec_carries(self):
        path = self.manifest_file({"postgres_version": "18.4"})
        self.assertEqual(lite_cli._observed_postgres_version(path), "18.4")

    def test_an_unproven_manifest_contributes_no_version(self):
        path = self.manifest_file({"postgres_version": None,
                                   "database_observation": {"reason": "SCHEMA_UNCHANGED_BY_THE_RUN"}})
        self.assertIsNone(lite_cli._observed_postgres_version(path))

    def test_a_missing_or_unreadable_manifest_contributes_no_version(self):
        self.assertIsNone(lite_cli._observed_postgres_version(
            str(pathlib.Path(tempfile.mkdtemp()) / "absent.json")))

    def test_no_literal_in_the_backend_can_invent_a_version(self):
        """``lite_cli.py`` must carry nothing it could fall back to.

        Comments are stripped on purpose: the file explains the literal that was removed,
        and a scan that read the explanation would fail on the fix it documents - the same
        trap ``lite_workflow_check._code_lines`` exists for. An environment variable is
        equally unacceptable: ``LITE_POSTGRES_VERSION`` let the dispatch name a version
        nothing had measured.
        """
        source = "\n".join(
            line.split(" #", 1)[0]
            for line in (ROOT / "lite_cli.py").read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("#"))
        self.assertNotIn("LITE_POSTGRES_VERSION", source)
        self.assertNotIn("18.4", source)


class MachineStepInvocationTests(unittest.TestCase):
    """The shipped step must still call the observation on both sides of the run."""

    def test_the_shipped_step_brackets_pytest_with_the_observation(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        machine = workflow.split("        id: machine_run", 1)[1].split(
            "      - name: Record the machine-test manifest", 1)[0]
        before = machine.index("--phase before")
        run = machine.index("python -m pytest")
        after = machine.index("--phase after")
        self.assertLess(before, run, "the before-observation must precede the inventory")
        self.assertLess(run, after, "the after-observation must follow the inventory")
        self.assertIn("/out/database.json", machine, "the manifest reads this file")
        self.assertIn("exit \"$observation_status\"", machine,
                      "the step must fail when the observation cannot prove the database")


if __name__ == "__main__":
    unittest.main(verbosity=2)
