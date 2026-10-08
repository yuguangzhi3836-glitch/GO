"""Observe which database the C13 machine inventory actually ran against.

C13's machine job is the only place in this cell where candidate code executes, and the
whole reason it runs in a disposable container is PostgreSQL 18.4: the constraints,
transaction behaviour and column types that decide whether a migration is correct are
*PostgreSQL's*, not SQLite's. For a while the job published a version it had never
looked at. The version was a literal in the workflow, and the database the suite used
was chosen by the candidate's own ``application/tests/conftest.py`` - which, when
``GO_TEST_DATABASE_URL`` is absent, replaces ``DATABASE_URL`` with a private SQLite
file. A real round therefore recorded ``"postgres_version": "18.4"`` while every
assertion ran on SQLite. ``docs/acceptance/c13-supplement-533/database-preflight.json``
reached the same finding independently and named it exactly:
``"manifest_version_source": "literal in workflow, not actual application database
observation"``.

This module is the missing half. It reads no URL out of the environment and trusts no
string: it connects to the PostgreSQL service the job already starts, over the libpq
variables the job already passes, and takes a **fingerprint of that database's own
schema** before and after the pytest run. The two probes bracket the run inside a
container whose only other actions are pip installs, so a changed fingerprint is the
suite's own doing. When the fingerprints are equal nothing can be said about which
database ran - so nothing is claimed, and the caller fails closed. Only an observation
that the database itself changed lets a round name a PostgreSQL version, and the name it
may use is the one the server reported, never one written down here.

What this deliberately is NOT:

* not a pytest plugin and not a profile - the Owner-authorized #533 supplement plugin
  was removed from the machine step and must not come back;
* not a new service, database, role or reviewer - it uses the disposable PostgreSQL
  service the job already starts and the credentials the job already has;
* not a system of record - it produces one small JSON observation per phase, and the
  manifest is what hash-binds it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys

#: The schema the product's own migrations write into. Named once, so the before and the
#: after fingerprint cannot disagree about what they were looking at.
SCHEMA = "public"

#: The server's own answer, never an environment variable. ``server_version_num`` is the
#: machine form of the version (18.4 -> 180004) and ``current_database()`` proves both
#: phases were pointed at the same database.
SERVER_FACTS = "SELECT current_setting('server_version_num')::int, current_database()"

#: Every table the database holds in the observed schema, ordered so the fingerprint is a
#: function of the SET and not of the catalog's row order.
TABLES = ("SELECT table_name FROM information_schema.tables "
          "WHERE table_schema = %s ORDER BY table_name")

#: A probe that cannot answer is a record, not a crash: the run still has to produce its
#: test evidence, and it is the AFTER phase that refuses to name a version.
CONNECT_TIMEOUT_SECONDS = 15

#: The one line the CI log carries, so the proof can be read without unzipping anything.
#: The witness (before the run) and the verdict (after it) share this prefix and differ by
#: suffix, so `grep C13_DATABASE_OBSERVATION` shows both halves of the measurement.
REPORT_PREFIX = "C13_DATABASE_OBSERVATION"
WITNESS_SUFFIX = "_WITNESS"


def _params() -> dict:
    """The connection, from the libpq variables the machine step already passes."""
    return {
        "host": os.environ.get("PGHOST", "host.docker.internal"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname": os.environ.get("PGDATABASE", "c13_lite"),
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
    }


def version_text(server_version_num: int) -> str:
    """``180004`` -> ``"18.4"``. PostgreSQL's own arithmetic, not ours."""
    major, minor = divmod(int(server_version_num), 10000)
    return f"{major}.{minor}"


def fingerprint(tables) -> str:
    """A digest of the observed table set; equal digests mean "nothing to report"."""
    return hashlib.sha256("\n".join(tables).encode("utf-8")).hexdigest()


def probe() -> dict:
    """One observation of the PostgreSQL service, or a record of why there is none."""
    try:
        # Imported here so that a missing driver is a record rather than a traceback: the
        # run has to survive to the AFTER phase, which is where the refusal happens.
        import psycopg
    except Exception as error:  # noqa: BLE001 - any import failure is the same fact
        return {"reachable": False, "reason": "PSYCOPG_UNAVAILABLE",
                "error": type(error).__name__}
    try:
        with psycopg.connect(**_params(), autocommit=True) as connection:
            server_version_num, database = connection.execute(SERVER_FACTS).fetchone()
            tables = [row[0] for row in connection.execute(TABLES, (SCHEMA,)).fetchall()]
    except Exception as error:  # noqa: BLE001 - unreachable is a result, not a defect
        return {"reachable": False, "reason": "POSTGRESQL_NOT_REACHED",
                "error": f"{type(error).__name__}: {error}"[:400]}
    return {
        "reachable": True,
        "database": database,
        "schema": SCHEMA,
        "server_version_num": int(server_version_num),
        "observed_postgres_version": version_text(server_version_num),
        "tables": len(tables),
        "schema_fingerprint": fingerprint(tables),
    }


def evaluate(before: dict, after: dict) -> dict:
    """What this round may claim, given the two observations.

    ``postgresql_actually_used`` is true only when the service answered BOTH probes, both
    probes were pointed at the same database, and that database's schema fingerprint
    moved between them. When that cannot be shown, ``postgres_version`` stays ``None`` -
    the record keeps the server's version as an *observation*, but the round may not
    report a PostgreSQL test it did not prove. The reason is carried separately so a
    refusal can be read instead of guessed at.
    """
    same_database = bool(before.get("database")) and before.get("database") == after.get("database")
    changed = bool(before.get("schema_fingerprint")) and (
        before.get("schema_fingerprint") != after.get("schema_fingerprint"))
    used = bool(before.get("reachable") and after.get("reachable") and same_database and changed)
    if used:
        reason = "POSTGRESQL_OBSERVED"
    elif not before.get("reachable"):
        reason = before.get("reason") or "POSTGRESQL_NOT_REACHED"
    elif not after.get("reachable"):
        reason = after.get("reason") or "POSTGRESQL_NOT_REACHED"
    elif not same_database:
        reason = "PROBES_DISAGREE_ABOUT_THE_DATABASE"
    else:
        reason = "SCHEMA_UNCHANGED_BY_THE_RUN"
    return {
        "observed": True,
        "postgresql_actually_used": used,
        "schema_changed_during_the_run": changed,
        "reason": reason,
        "database": after.get("database"),
        "observed_postgres_version": after.get("observed_postgres_version"),
        # THE CLAIM. It exists only where the proof does.
        "postgres_version": after.get("observed_postgres_version") if used else None,
        "before": before,
        "after": after,
    }


def _write(path: str, payload: dict) -> None:
    pathlib.Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")


def _read(path: str):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _summary(record: dict) -> dict:
    """The greppable line: the verdict and both measurements, nothing else."""
    before, after = record.get("before") or {}, record.get("after") or {}
    return {
        "postgresql_actually_used": record.get("postgresql_actually_used"),
        "postgres_version": record.get("postgres_version"),
        "observed_postgres_version": record.get("observed_postgres_version"),
        "database": record.get("database"),
        "tables_before": before.get("tables"),
        "tables_after": after.get("tables"),
        "reason": record.get("reason"),
    }


def _witness(observation: dict) -> dict:
    """The before-phase line: what was seen, with no verdict, because there is none yet.

    Written this way for a reason. The first version printed the verdict shape with every
    field ``null``, which in a successful run reads like a verdict that failed to form -
    and this whole change exists so that a reader can tell what was measured from what was
    concluded. There is no conclusion before the run, so this line does not look like one.
    """
    return {
        "phase": "before",
        "reachable": observation.get("reachable"),
        "database": observation.get("database"),
        "observed_postgres_version": observation.get("observed_postgres_version"),
        "tables": observation.get("tables"),
        "schema_fingerprint": observation.get("schema_fingerprint"),
        "reason": observation.get("reason"),
    }


def main(argv=None, probe_fn=None) -> int:
    parser = argparse.ArgumentParser(description="Observe the database the C13 inventory ran on")
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--out", required=True, help="where to write this phase's JSON record")
    parser.add_argument("--before", help="the before-phase record, required for --phase after")
    args = parser.parse_args(argv)

    observation = (probe_fn or probe)()

    if args.phase == "before":
        # A witness, not a gate: the run must still happen, and the AFTER phase is what
        # refuses to name a version.
        _write(args.out, observation)
        print(f"{REPORT_PREFIX}{WITNESS_SUFFIX} {json.dumps(_witness(observation))}")
        return 0

    if not args.before:
        parser.error("--phase after requires --before <the before-phase record>")
    before = _read(args.before)
    if before is None:
        # The container never got as far as its first probe, so there is nothing to
        # compare - which is exactly a run whose database cannot be named.
        before = {"reachable": False, "reason": "BEFORE_PHASE_RECORD_MISSING"}
    record = evaluate(before, observation)
    _write(args.out, record)
    print(f"{REPORT_PREFIX} {json.dumps(_summary(record))}")
    return 0 if record["postgresql_actually_used"] else 1


if __name__ == "__main__":
    sys.exit(main())
