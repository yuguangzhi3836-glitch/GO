"""The machine job may report only the database it OBSERVED.

``docs/acceptance/c13-supplement-533/database-preflight.json`` recorded this defect
independently and named it exactly::

    "manifest_version_source": "literal in workflow, not actual application database
     observation"

A real round was published as a PostgreSQL 18.4 test while the entire inventory ran on
SQLite, because the version was a literal in the workflow and the database was chosen by
the candidate's own ``application/tests/conftest.py``. The repair is a measurement, so the
tests here are measurements too:

* the decision function is exercised over every shape a real round can produce (PostgreSQL
  connected, SQLite connected, nothing connected, the server unreachable, two servers);
* the engine hook is exercised against REAL SQLAlchemy engines, because the one property
  this revision turns on is a property of SQLAlchemy's events: an engine that CONNECTED is
  observed, and an engine that was merely BUILT is not;
* the plugin is run the way the machine step runs it - ``pytest -p lite_database_observation``
  over a real test file - and the sidecar it writes is read back;
* the workflow's **real embedded manifest block** is extracted and executed, so the claim
  the round publishes is tested as the bytes that actually run rather than as a pattern;
* the backend's version source is pinned to the observation, and to nothing else;
* and the refusal that makes an unproven round cost something is pinned to the pre-existing
  ``c13_machine_job_postgres_missing`` rule rather than to anything this revision added.

Nothing here needs PostgreSQL or Docker: a read-only-against-a-real-server round is proven
on a real disposable PostgreSQL 18.4 in the PR's evidence, and what these tests pin is that
the code cannot claim more than a measurement showed.
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
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "c13-quality-acceptance.yml"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_bundle  # noqa: E402 - path set here
import lite_cli  # noqa: E402
import lite_database_observation as observation  # noqa: E402
import lite_errors  # noqa: E402
import lite_fixtures as fx  # noqa: E402

try:
    from sqlalchemy import create_engine, make_url, text

    HAVE_SQLALCHEMY = True
except Exception:  # noqa: BLE001 - the engine-level tests are simply not run
    HAVE_SQLALCHEMY = False


# --------------------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------------------


class _FakeUrl:
    def __init__(self, rendered):
        self._rendered = rendered

    def render_as_string(self, hide_password=True):  # noqa: ARG002 - SQLAlchemy's signature
        return self._rendered


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeProbe:
    def __init__(self, engine):
        self._engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False

    def exec_driver_sql(self, statement):  # noqa: ARG002 - one statement is enough
        if self._engine.error is not None:
            raise self._engine.error
        return _FakeResult((self._engine.version, self._engine.database))


class FakeEngine:
    """An engine whose server answers, or refuses to."""

    def __init__(self, version=180004, database="c13_lite", error=None,
                 url="postgresql+psycopg://postgres:***@c13/c13_lite"):
        self.url = _FakeUrl(url)
        self.version = version
        self.database = database
        self.error = error

    def connect(self):
        return _FakeProbe(self)


class FakeDialect:
    def __init__(self, name, driver):
        self.name = name
        self.driver = driver


class FakeConnection:
    """What SQLAlchemy hands the ``engine_connect`` hook: a dialect and an owner."""

    def __init__(self, name, driver, engine=None):
        self.dialect = FakeDialect(name, driver)
        self.engine = engine


def connected(name, driver, engine=None) -> FakeConnection:
    return FakeConnection(name, driver, engine)


def sqlite_connection(engine=None) -> FakeConnection:
    return connected("sqlite", "pysqlite", engine)


def postgres_connection(engine=None) -> FakeConnection:
    return connected("postgresql", "psycopg", engine if engine is not None else FakeEngine())


# --------------------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------------------


class VersionTextTests(unittest.TestCase):
    def test_the_server_number_is_rendered_with_postgresqls_own_arithmetic(self):
        self.assertEqual(observation.version_text(180004), "18.4")
        self.assertEqual(observation.version_text(180000), "18.0")
        self.assertEqual(observation.version_text(160001), "16.1")


class ObservationTests(unittest.TestCase):
    """What a round may claim, given the engines the test process really connected with."""

    def setUp(self):
        observation.reset()
        self.addCleanup(observation.reset)

    def test_a_postgresql_engine_that_connected_lets_the_round_name_the_servers_version(self):
        observation.observe_connection(postgres_connection())
        record = observation.observe()
        self.assertTrue(record["postgresql_actually_used"])
        self.assertEqual(record["postgres_version"], "18.4")
        self.assertEqual(record["dialects_used"], ["postgresql"])
        self.assertEqual(record["reason"], "POSTGRESQL_ENGINE_CONNECTED")
        self.assertEqual(record["database"], "c13_lite")

    def test_a_sqlite_engine_that_connected_claims_no_postgresql_version(self):
        """The measured shape of a round that only *looked* like PostgreSQL.

        PostgreSQL 18.4 was up and healthy; the suite connected to SQLite; the manifest used
        to say PostgreSQL. The engine says which one it was, so no version may be named -
        and the observation itself is still recorded, because the record has to show what
        was measured, not only what was concluded.
        """
        observation.observe_connection(sqlite_connection())
        record = observation.observe()
        self.assertFalse(record["postgresql_actually_used"])
        self.assertIsNone(record["postgres_version"])
        self.assertEqual(record["dialects_used"], ["sqlite"])
        self.assertEqual(record["reason"], "NO_POSTGRESQL_ENGINE_CONNECTED")
        self.assertIsNone(record["observed_postgres_version"])

    def test_nothing_connected_claims_no_postgresql_version(self):
        record = observation.observe()
        self.assertFalse(record["postgresql_actually_used"])
        self.assertIsNone(record["postgres_version"])
        self.assertEqual(record["connections_observed"], 0)
        self.assertEqual(record["reason"], "NO_DATABASE_ENGINE_CONNECTED")

    def test_a_read_only_connection_is_a_connection(self):
        """The defect this revision repairs.

        An earlier revision decided "PostgreSQL was used" by watching the database's table
        list change. A suite that only SELECTs creates no table, so a perfectly real
        PostgreSQL round was refused. The engine cannot tell a read from a write, and the
        record no longer asks it to - it asks which engine connected.
        """
        observation.observe_connection(postgres_connection())
        record = observation.observe()
        self.assertTrue(record["postgresql_actually_used"],
                        "a read-only PostgreSQL round must not be called 'not PostgreSQL'")

    def test_a_server_that_does_not_answer_claims_no_version(self):
        observation.observe_connection(
            postgres_connection(FakeEngine(error=RuntimeError("server has gone away"))))
        record = observation.observe()
        self.assertFalse(record["postgresql_actually_used"])
        self.assertIsNone(record["postgres_version"])
        self.assertEqual(record["reason"], "POSTGRESQL_CONNECTED_VERSION_UNREADABLE")

    def test_two_servers_refuse_to_be_summarised_as_one(self):
        observation.observe_connection(postgres_connection(FakeEngine(version=180004)))
        observation.observe_connection(postgres_connection(
            FakeEngine(version=170001, url="postgresql+psycopg://postgres:***@other/c13_lite")))
        record = observation.observe()
        self.assertFalse(record["postgresql_actually_used"])
        self.assertIsNone(record["postgres_version"])
        self.assertEqual(record["reason"], "AMBIGUOUS_POSTGRESQL_SERVERS")

    def test_a_resolved_version_is_never_a_literal(self):
        """A service that answers 19.2 is reported as 19.2.

        Guarding the arithmetic is not pedantry: the whole defect was a version written down
        in advance, so a record that returned the written-down number whatever the server
        said would be the same defect wearing the observation's clothes.
        """
        observation.observe_connection(postgres_connection(FakeEngine(version=190002)))
        self.assertEqual(observation.observe()["postgres_version"], "19.2")

    def test_the_same_engine_is_counted_once_per_connection(self):
        engine = FakeEngine()
        for _ in range(3):
            observation.observe_connection(postgres_connection(engine))
        record = observation.observe()
        self.assertEqual(record["connections_observed"], 3)
        self.assertEqual(len(record["engines"]), 1)
        self.assertEqual(record["engines"][0]["connections"], 3)

    def test_a_report_that_cannot_be_written_is_a_refusal_not_a_crash(self):
        """An observation must never be able to turn a passing suite into a failing one."""
        blocker = pathlib.Path(tempfile.mkdtemp()) / "not-a-directory"
        blocker.write_text("x", encoding="utf-8")
        record = observation.observe()
        self.assertIsNone(observation.write_report(record, str(blocker / "database.json")))


# --------------------------------------------------------------------------------------
# The engine hook, against real SQLAlchemy engines
# --------------------------------------------------------------------------------------


@unittest.skipUnless(HAVE_SQLALCHEMY, "the observation listens to SQLAlchemy engines")
class RealEngineTests(unittest.TestCase):
    def setUp(self):
        observation.reset()
        self.addCleanup(observation.reset)

    def sqlite(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        return engine

    def test_the_engine_hook_attached(self):
        self.assertIsNone(observation._UNAVAILABLE,
                          "class-level engine_connect listening is what makes this work")

    def test_an_engine_that_connects_is_observed_as_the_dialect_it_used(self):
        with self.sqlite().connect() as connection:
            connection.execute(text("select 1")).scalar()
        record = observation.observe()
        self.assertEqual(record["dialects_used"], ["sqlite"])
        self.assertEqual(record["engines"][0]["driver"], "pysqlite")
        self.assertFalse(record["postgresql_actually_used"])
        self.assertIsNone(record["postgres_version"])
        self.assertEqual(record["reason"], "NO_POSTGRESQL_ENGINE_CONNECTED")

    def test_a_read_only_select_with_no_ddl_is_observed(self):
        with self.sqlite().connect() as connection:
            self.assertEqual(connection.execute(text("select 42")).scalar(), 42)
        self.assertEqual(observation.observe()["connections_observed"], 1)

    def test_an_engine_that_was_only_built_is_not_observed(self):
        """The property the first draft of this hook got wrong.

        Building an engine is not using one. If construction were enough, a suite that never
        touched a database would be reported as having used the PostgreSQL service it never
        contacted.
        """
        self.sqlite()
        record = observation.observe()
        self.assertEqual(record["connections_observed"], 0)
        self.assertEqual(record["engines"], [])
        self.assertEqual(record["reason"], "NO_DATABASE_ENGINE_CONNECTED")

    def test_the_record_carries_the_url_without_the_password(self):
        """The row is what a reviewer reads; a credential must not travel in it."""
        engine = types.SimpleNamespace(
            url=make_url("postgresql+psycopg://c13user:sup3rsecret@c13host/c13_lite"))
        observation.observe_connection(connected("postgresql", "psycopg", engine))
        url = observation._ENGINES[0]["url"]
        self.assertNotIn("sup3rsecret", url)
        self.assertIn("c13user", url)


# --------------------------------------------------------------------------------------
# The plugin, run the way the machine step runs it
# --------------------------------------------------------------------------------------


@unittest.skipUnless(HAVE_SQLALCHEMY, "the plugin observes SQLAlchemy engines")
class PluginHookTests(unittest.TestCase):
    """The plugin's own hooks, driven the way pytest drives them.

    The engine events, the verdict, the sidecar and the log line are all exercised here
    through the real listener and the real hook. That the machine step LOADS the plugin
    (``-p lite_database_observation``) is a different property, and it is pinned where it
    belongs: ``lite_workflow_check`` reads it out of the shipped step offline, and the C13
    machine step is where the plugin is really run - which is what the PR's Docker battery
    shows.
    """

    def setUp(self):
        observation.reset()
        self.addCleanup(observation.reset)

    def finish(self) -> tuple:
        """Drive the hook and read the sidecar.

        No connection is passed in: the engines the tests below connect with report
        themselves through the class-level listener, which is the path the machine step
        takes. Going through ``_on_engine_connect`` by hand would test the call rather than
        the wiring.
        """
        target = pathlib.Path(tempfile.mkdtemp()) / "database.json"
        os.environ[observation.OUT_ENV] = str(target)
        self.addCleanup(os.environ.pop, observation.OUT_ENV, None)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            observation.pytest_sessionfinish(session=None, exitstatus=0)
        record = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None
        return record, stream.getvalue()

    def sqlite(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        return engine

    def test_a_suite_that_used_sqlite_writes_no_postgresql_claim(self):
        engine = self.sqlite()
        with engine.connect() as connection:
            connection.execute(text("select 1")).scalar()
        record, log = self.finish()
        self.assertFalse(record["postgresql_actually_used"])
        self.assertEqual(record["dialects_used"], ["sqlite"])
        self.assertIsNone(record["postgres_version"])
        self.assertEqual(record["reason"], "NO_POSTGRESQL_ENGINE_CONNECTED")
        self.assertIn(observation.REPORT_PREFIX, log,
                      "the log line is the greppable half of the evidence")
        self.assertIn("sqlite", log)

    def test_a_suite_that_never_connected_writes_no_postgresql_claim(self):
        record, log = self.finish()
        self.assertEqual(record["connections_observed"], 0)
        self.assertEqual(record["reason"], "NO_DATABASE_ENGINE_CONNECTED")
        self.assertIn(observation.REPORT_PREFIX, log)

    def test_a_broken_hook_cannot_break_the_suite(self):
        """This hook runs inside ``Connection.__init__``.

        An exception here would surface as a failure of the candidate's own tests - an
        observation that can fail a suite it only describes would be a worse defect than the
        one it repairs. The failure is recorded instead, and nothing is claimed.
        """

        class Hostile:
            @property
            def dialect(self):
                raise RuntimeError("the candidate's own object")

        observation._on_engine_connect(Hostile())  # must not raise
        record = observation.observe()
        self.assertEqual(record["reason"], "NO_DATABASE_ENGINE_CONNECTED")
        self.assertEqual(len(record["observation_errors"]), 1)
        self.assertIn("RuntimeError", record["observation_errors"][0])


# --------------------------------------------------------------------------------------
# The workflow's real bytes
# --------------------------------------------------------------------------------------


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

    def observation(self, used, reason, version=None) -> bytes:
        return json.dumps({
            "observed": True,
            "how": "sqlalchemy-engine-connect",
            "dialects_used": ["postgresql"] if used else ["sqlite"],
            "connections_observed": 12,
            "engines": [{"dialect": "postgresql" if used else "sqlite", "connections": 12}],
            "postgresql_actually_used": used,
            "postgres_version": version,
            "observed_postgres_version": version,
            "reason": reason,
        }).encode()

    def test_a_proven_observation_is_the_version_the_manifest_reports(self):
        manifest = self.manifest(self.observation(True, "POSTGRESQL_ENGINE_CONNECTED", "18.4"))
        self.assertEqual(manifest["postgres_version"], "18.4")
        self.assertTrue(manifest["database_observation"]["postgresql_actually_used"])

    def test_an_unproven_observation_removes_the_postgresql_claim(self):
        manifest = self.manifest(self.observation(False, "NO_POSTGRESQL_ENGINE_CONNECTED"))
        self.assertIsNone(manifest["postgres_version"],
                          "an unproven round must not describe itself as PostgreSQL")
        self.assertEqual(manifest["database_observation"]["reason"],
                         "NO_POSTGRESQL_ENGINE_CONNECTED")
        self.assertEqual(manifest["database_observation"]["dialects_used"], ["sqlite"])

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
                                   "database_observation": {"reason": "NO_POSTGRESQL_ENGINE_CONNECTED"}})
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


class SealRefusalTests(unittest.TestCase):
    """What an unproven observation COSTS, and where that cost is charged.

    Not here and not in the workflow: a C13 record whose machine job cannot name its
    database is refused by ``lite_bundle``, a rule that predates this revision. Pinned
    because the whole fail-closed argument rests on it, and because a reader is entitled to
    see that removing the step-level gate did not remove the gate.
    """

    def test_a_machine_job_that_cannot_name_its_database_cannot_be_sealed(self):
        bundle = fx.make_round()["c13_bundle"]
        for unproven in (None, ""):
            with self.subTest(unproven=unproven):
                bundle["machine_job"]["postgres_version"] = unproven
                with self.assertRaises(lite_errors.Reject) as context:
                    lite_bundle.validate_c13(bundle)
                self.assertEqual(context.exception.reason, "c13_machine_job_postgres_missing")

    def test_a_machine_job_that_names_its_database_still_seals(self):
        """The same fixture, unmodified, so the test above fails for the right reason."""
        lite_bundle.validate_c13(fx.make_round()["c13_bundle"])


class MachineStepInvocationTests(unittest.TestCase):
    """The shipped step must LOAD the observation into the test process.

    An earlier revision bracketed pytest with two calls to the module; that shape belonged
    to a schema observation. What this revision needs is the load, and it is what the step
    must keep: a plugin that is mounted and never loaded reports nothing, the manifest then
    carries no version, and the sealed C13 record is refused - correct, but late, and
    ``lite_workflow_check`` is what says so before a round is ever spent.
    """

    def machine(self) -> str:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        return workflow.split("        id: machine_run", 1)[1].split(
            "      - name: Record the machine-test manifest", 1)[0]

    def test_the_shipped_step_loads_the_observation_into_pytest(self):
        machine = self.machine()
        self.assertIn("-p lite_database_observation", machine)

    def test_the_shipped_step_makes_the_plugin_importable(self):
        machine = self.machine()
        self.assertIn("PYTHONPATH=/opt", machine)
        self.assertIn(
            "lite_database_observation.py:/opt/lite_database_observation.py:ro", machine,
            "the plugin has to be mounted where PYTHONPATH can find it")

    def test_the_shipped_step_writes_the_sidecar_the_manifest_reads(self):
        machine = self.machine()
        self.assertIn(f"{observation.OUT_ENV}=" + observation.DEFAULT_OUT, machine)


if __name__ == "__main__":
    unittest.main(verbosity=2)
