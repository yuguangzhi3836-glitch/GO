"""Observe the database engine the C13 machine inventory ACTUALLY ran on.

C13's machine job is the only place in this cell where candidate code executes, and the
whole reason it runs in a disposable container is PostgreSQL 18.4: the constraints,
transaction behaviour and column types that decide whether a migration is correct are
*PostgreSQL's*, not SQLite's. For a while the job published a version it had never looked
at. The version was a literal in the workflow, and the database the suite used was chosen
by the candidate's own ``application/tests/conftest.py`` - which, when
``GO_TEST_DATABASE_URL`` is absent, replaces ``DATABASE_URL`` with a private SQLite file.
A real round therefore recorded ``"postgres_version": "18.4"`` while every assertion ran on
SQLite. ``docs/acceptance/c13-supplement-533/database-preflight.json`` reached the same
finding independently and named it exactly: ``"manifest_version_source": "literal in
workflow, not actual application database observation"``.

This module is the missing half, and it asks the question directly: **which database engine
did this pytest process actually connect with?** It is a pytest plugin, so the answer comes
from the process itself rather than from anything written around it. It reads no URL out of
the environment and trusts no string.

How the answer is obtained
--------------------------

``sqlalchemy.engine.Engine`` is listened to at class level, so every engine the suite
builds reports itself. The hook is the ``engine_connect`` event, which fires when a
``Connection`` is *procured* - not when an ``Engine`` is constructed. That difference is
the point: a suite that builds an engine and never touches it must not be reported as
having used a database, and a suite that runs a single read-only ``SELECT`` - creating no
table and changing no schema - must not be reported as not having used one. Both were
measured on a real disposable PostgreSQL 18.4 (see the PR evidence), and *neither* the
schema nor any row it contains is part of the judgement here.

When at least one engine that actually connected reports the ``postgresql`` dialect, the
server's own ``server_version_num`` is read through that same engine, and the version it
reports is the only version this module will ever name. It is read from the server, never
computed from an environment variable, so no literal can be substituted for a measurement.
``version_text`` renders the server's own arithmetic (180004 -> "18.4"); if a future server
answers 19.2, the record says 19.2.

What this deliberately is NOT
-----------------------------

* not a schema observation - an earlier revision proved "PostgreSQL was used" by watching
  the database's table list change. That was wrong twice over: it turned a hard condition
  out of something that a legitimate read-only suite never does, and it let a *write* count
  as evidence of a *connection*. The engine reports the dialect; nothing else is consulted;
* not a new service, database, role or reviewer - it uses the disposable PostgreSQL the job
  already starts, the engine the suite already builds, and the credentials the job already
  has;
* not a gate. It reports what it saw and changes nothing about the run: the manifest is the
  only consumer, and the pre-existing ``c13_machine_job_postgres_missing`` rule in
  ``lite_bundle`` is what refuses a C13 record that cannot name its database. This module
  never raises into the test session and never alters an exit status - an observation that
  could turn a green suite red would be a worse defect than the one it repairs.

Boundary, stated plainly: the hook sees SQLAlchemy engines. A candidate that reached the
database through a raw driver without SQLAlchemy would connect unseen, and this module
would then report that no engine connected - so such a round fails closed rather than being
credited with a PostgreSQL test it cannot show.
"""
from __future__ import annotations

import json
import os
import pathlib

#: The one line the CI log carries, so the observation can be read without unzipping the
#: evidence bundle. It lands in the hashed ``stdout.txt`` as well as in the sidecar.
REPORT_PREFIX = "C13_DATABASE_OBSERVATION"

#: The dialect that has to be observed for a round to be allowed to call itself a
#: PostgreSQL test.
POSTGRESQL = "postgresql"

#: Where the sidecar goes. The workflow's manifest hash-binds this file; tests point the
#: variable at a temporary path.
OUT_ENV = "C13_DATABASE_OBSERVATION_OUT"
DEFAULT_OUT = "/out/database.json"

#: Asked of the SERVER, over the engine the suite used. Never read from the environment.
SERVER_FACTS = "SELECT current_setting('server_version_num')::int, current_database()"

#: One row per (dialect, driver, url) that actually opened a connection.
_ENGINES: list = []
#: True while this module is reading the server's facts, so its own connection is not
#: mistaken for one made by the tests.
_PROBING = False

#: Errors raised inside the engine hook, which are recorded rather than propagated.
_ERRORS: list = []

#: Why the engine hook could not be attached, when that is the case.
_UNAVAILABLE = None


def version_text(server_version_num) -> str:
    """``180004`` -> ``"18.4"``. PostgreSQL's own arithmetic, not ours."""
    major, minor = divmod(int(server_version_num), 10000)
    return f"{major}.{minor}"


def reset() -> None:
    """Forget every observation. Tests use this; the plugin's own session never repeats."""
    _ENGINES.clear()
    _ERRORS.clear()


def _row(dialect, driver, url) -> dict:
    for row in _ENGINES:
        if (row["dialect"], row["driver"], row["url"]) == (dialect, driver, url):
            return row
    row = {"dialect": dialect, "driver": driver, "url": url, "connections": 0,
           "server_version_num": None, "database": None, "engine": None}
    _ENGINES.append(row)
    return row


def observe_connection(connection) -> None:
    """Record an engine that ACTUALLY procured a connection, and which dialect it used.

    Called from the ``engine_connect`` event. Nothing is inferred: a row exists here only
    because a connection was really handed out, which is why an engine that was built and
    never used stays invisible.
    """
    if _PROBING:
        return
    dialect = connection.dialect
    engine = getattr(connection, "engine", None)
    url = engine.url.render_as_string(hide_password=True) if engine is not None else None
    row = _row(dialect.name, dialect.driver, url)
    row["connections"] += 1
    if engine is not None:
        row["engine"] = engine


def _read_server_facts(row: dict) -> None:
    """Ask the server for its own version, through the engine the suite used."""
    try:
        with row["engine"].connect() as probe:
            num, database = probe.exec_driver_sql(SERVER_FACTS).fetchone()
    except Exception as error:  # noqa: BLE001 - an unreadable version is a record, not a crash
        row["error"] = f"{type(error).__name__}: {error}"[:200]
        return
    row["server_version_num"] = int(num)
    row["database"] = database


def observe() -> dict:
    """What this pytest process actually connected with, and nothing else.

    Exactly one reason describes every outcome, and ``postgresql_actually_used`` is true
    for one of them. There is no path on which a version is named without a PostgreSQL
    dialect having been observed on a real connection.
    """
    global _PROBING
    _PROBING = True
    try:
        for row in _ENGINES:
            if row["dialect"] == POSTGRESQL and row["engine"] is not None:
                _read_server_facts(row)
    finally:
        _PROBING = False

    engines = [{key: value for key, value in row.items() if key != "engine"}
               for row in _ENGINES]
    dialects = sorted({row["dialect"] for row in _ENGINES})
    postgres = [row for row in _ENGINES if row["dialect"] == POSTGRESQL]
    versions = sorted({row["server_version_num"] for row in postgres
                       if row["server_version_num"] is not None})

    if not _ENGINES:
        reason = "SQLALCHEMY_UNAVAILABLE" if _UNAVAILABLE else "NO_DATABASE_ENGINE_CONNECTED"
    elif not postgres:
        reason = "NO_POSTGRESQL_ENGINE_CONNECTED"
    elif not versions:
        reason = "POSTGRESQL_CONNECTED_VERSION_UNREADABLE"
    elif len(versions) > 1:
        # Two different servers answered. Naming either one would be a guess.
        reason = "AMBIGUOUS_POSTGRESQL_SERVERS"
    else:
        reason = "POSTGRESQL_ENGINE_CONNECTED"

    proven = reason == "POSTGRESQL_ENGINE_CONNECTED"
    return {
        "observed": True,
        "how": "sqlalchemy-engine-connect",
        "unavailable": _UNAVAILABLE,
        "observation_errors": list(_ERRORS),
        "connections_observed": sum(row["connections"] for row in _ENGINES),
        "dialects_used": dialects,
        "engines": engines,
        "postgresql_actually_used": proven,
        "observed_postgres_version": version_text(versions[0]) if proven else None,
        # THE CLAIM. It exists only where the evidence does.
        "postgres_version": version_text(versions[0]) if proven else None,
        "database": postgres[0]["database"] if len(postgres) == 1 and proven else None,
        "reason": reason,
    }


def summary(record: dict) -> dict:
    """The greppable line: the verdict and what it was measured from, nothing else."""
    return {
        "postgresql_actually_used": record.get("postgresql_actually_used"),
        "postgres_version": record.get("postgres_version"),
        "dialects_used": record.get("dialects_used"),
        "connections_observed": record.get("connections_observed"),
        "engines": [{key: row.get(key) for key in
                     ("dialect", "driver", "url", "connections", "server_version_num",
                      "database")}
                    for row in record.get("engines") or []],
        "reason": record.get("reason"),
    }


def write_report(record: dict, path: str | None = None) -> str | None:
    """Write the sidecar the manifest hash-binds. Never raises into the test session.

    If the path cannot be written the log line still carries the observation, and the
    manifest falls back to ``null`` - a refusal, which is the safe direction.
    """
    target = pathlib.Path(path or os.environ.get(OUT_ENV) or DEFAULT_OUT)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    except OSError:
        return None
    return str(target)


def _on_engine_connect(connection, *_legacy_branch) -> None:
    """The hook, and why it is shaped this way.

    ``engine_connect`` was ``(conn, branch)`` through SQLAlchemy 1.4 and is ``(conn)`` from
    2.0. Declaring two named parameters would trip SQLAlchemy's legacy-conversion shim,
    which issues a deprecation warning and is scheduled for removal; declaring one named
    parameter keeps the current contract and still tolerates the old second argument, so a
    candidate whose own pin differs cannot break the observation by arity.

    Nothing here may raise. This runs inside ``Connection.__init__``; an exception would
    surface as a failure of the candidate's OWN tests, and an observation that can fail a
    suite it is only supposed to describe is a worse defect than the one this module
    repairs. A failure is therefore recorded and the record stays honest - the run is not
    affected, and the version simply is not claimed.
    """
    try:
        observe_connection(connection)
    except Exception as error:  # noqa: BLE001 - see the docstring: never breaks a test
        _ERRORS.append(f"{type(error).__name__}: {error}"[:200])


def _attach() -> str | None:
    """Listen to every SQLAlchemy engine this process will build. Returns why, if not."""
    try:
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
    except Exception as error:  # noqa: BLE001 - unobservable is a recorded fact
        return f"{type(error).__name__}: {error}"[:200]
    try:
        # Class-level, so it covers engines built AFTER this line - which is all of them,
        # because a pytest plugin is imported before any conftest or test module.
        event.listen(Engine, "engine_connect", _on_engine_connect)
    except Exception as error:  # noqa: BLE001
        return f"{type(error).__name__}: {error}"[:200]
    return None


_UNAVAILABLE = _attach()


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001 - pytest hook signature
    """Report after the run. Deliberately after: nothing here can affect a test result."""
    record = observe()
    write_report(record)
    print(f"{REPORT_PREFIX} " + json.dumps(summary(record)))
