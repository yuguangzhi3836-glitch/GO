"""Trusted backend plugin: select and observe only the disposable C13 PostgreSQL.

Loaded explicitly for PG533-15-V1; never installed into or copied over #531.
"""
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime-host-channel-v1"))
import c1_c13_supplement_contract as fixed
from lite_pg533 import expected_selection

URL = "postgresql+psycopg://postgres:c13-lite-local-only@host.docker.internal:5432/c13_lite"


def observe():
    from sqlalchemy import text
    from go_hotel.db.session import engine
    from sqlalchemy.engine import make_url
    if engine.dialect.name != "postgresql" or engine.url != make_url(URL):
        raise pytest.UsageError("PG533_APPLICATION_ENGINE_MISMATCH")
    with engine.connect() as connection:
        version = int(connection.scalar(text("SHOW server_version_num")))
        database = connection.scalar(text("SELECT current_database()"))
    if version != 180004 or database != "c13_lite":
        raise pytest.UsageError("PG533_ACTUAL_POSTGRES_18_4_REQUIRED")
    return {"dialect": "postgresql", "server_version_num": version, "database": database}


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    if (os.environ.get("C13_PG533_PROFILE") != fixed.PROFILE
            or os.environ.get("C13_CANDIDATE_SHA") != fixed.CANDIDATE):
        raise pytest.UsageError("PG533_PROFILE_NOT_AUTHORIZED")
    if "go_hotel.db.session" in sys.modules or "go_hotel.core.config" in sys.modules:
        raise pytest.UsageError("PG533_DATABASE_SELECTED_TOO_LATE")
    # Legacy conftest has been loaded. Replace only the test process's selected
    # URL, before application settings/engine import and before schema fixtures.
    os.environ["DATABASE_URL"] = URL
    config._pg533 = {"candidate_sha": fixed.CANDIDATE, "application_tree": fixed.APPLICATION_TREE,
                      "profile": fixed.PROFILE, "observed_cases": {}, **observe()}


def pytest_collection_finish(session):
    try:
        expected_selection([item.nodeid for item in session.items])
    except ValueError as error:
        raise pytest.UsageError(str(error)) from None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    before = observe()
    yield
    after = observe()
    item.config._pg533["observed_cases"][item.nodeid] = {"before": before, "after": after}


def pytest_sessionfinish(session, exitstatus):
    evidence = getattr(session.config, "_pg533", None)
    if evidence is not None:
        evidence["pytest_exit_code"] = int(exitstatus)
        Path("/out/database.json").write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
