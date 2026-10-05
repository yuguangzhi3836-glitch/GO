"""No-DB Builder dependency smoke; run with the prepared interpreter inside AWF.

Host success is deliberately recorded as HOST_ONLY, never as sandbox validation.
An agent-context report must still be bound to the real Builder run/log by review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


TEST_SOURCE = '''import importlib.metadata
import sys

import fastapi
import httpx
import psycopg
import pytest
import sqlalchemy
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy.dialects import postgresql


def test_dependency_imports_and_python():
    assert sys.version_info >= (3, 11)
    for name in ("pytest", "fastapi", "sqlalchemy", "psycopg"):
        assert importlib.metadata.version(name)


def test_in_process_http_without_network_or_database():
    app = fastapi.FastAPI()

    @app.get("/builder-smoke")
    def smoke():
        return {"ready": True}

    with TestClient(app) as client:
        response = client.get("/builder-smoke")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


def test_sql_compile_without_database_connection():
    table = sqlalchemy.table("probe", sqlalchemy.column("id"))
    compiled = sqlalchemy.select(table.c.id).where(table.c.id == 7).compile(
        dialect=postgresql.dialect())
    assert compiled.params == {"id_1": 7}
    assert "probe.id" in str(compiled)


def test_pydantic_rejects_invalid_input():
    class Request(BaseModel):
        count: int
    assert Request(count="3").count == 3
    with pytest.raises(ValidationError):
        Request(count="invalid")
'''


def run_smoke(python: Path, evidence: Path, context: str) -> dict:
    """Invoke a real isolated interpreter; retain a nonzero result on every failure."""
    report = {"schema_version": 1, "status": "FAIL", "context": context,
              "sandbox_validation": "PENDING_EXTERNAL_RUN_VERIFICATION",
              "python": str(python), "database_tested": False,
              "test_source_sha256": hashlib.sha256(TEST_SOURCE.encode()).hexdigest()}
    # -I ignores PYTHONPATH, user site packages and working-directory shadow modules.
    # pytest runs outside application/tests so its DB-reset conftest is never imported.
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    probe = (
        "import json,sys,importlib.metadata as m; "
        "assert sys.version_info >= (3,11), 'PYTHON_TOO_OLD'; "
        "import pytest,fastapi,sqlalchemy,psycopg; "
        "print(json.dumps({'sys_executable':sys.executable,'version':sys.version,"
        "'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
        "'packages':{n:m.version(n) for n in ['pytest','fastapi','sqlalchemy','psycopg']}}))"
    )
    try:
        result = subprocess.run([str(python), "-I", "-c", probe], env=env,
                                text=True, capture_output=True, timeout=60)
        report["probe_exit_code"] = result.returncode
        if result.returncode:
            report["reason"] = "INTERPRETER_OR_DEPENDENCY_PROBE_FAILED"
            # Do not copy arbitrary environment values or full subprocess logs to evidence.
            return report
        report["interpreter"] = json.loads(result.stdout)
        with tempfile.TemporaryDirectory(prefix="go-builder-no-db-") as directory:
            root = Path(directory)
            test = root / "test_builder_dependencies.py"
            test.write_text(TEST_SOURCE, encoding="utf-8")
            config = root / "pytest.ini"
            config.write_text("[pytest]\n", encoding="utf-8")
            command = [str(python), "-I", "-m", "pytest", "-c", str(config),
                       "--confcutdir", str(root), "-p", "no:cacheprovider", "-q", str(test)]
            report["pytest_command"] = command
            result = subprocess.run(command, cwd=root, env=env, text=True,
                                    capture_output=True, timeout=120)
            report["pytest_exit_code"] = result.returncode
            report["pytest_stdout"] = result.stdout
            report["pytest_stderr"] = result.stderr
            if result.returncode:
                report["reason"] = "REAL_PYTEST_FAILED"
                return report
        report["status"] = "PASS"
        report["sandbox_validation"] = ("HOST_ONLY" if context == "host"
                                          else "PENDING_EXTERNAL_RUN_VERIFICATION")
        return report
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        report["reason"] = type(error).__name__
        return report
    finally:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--context", choices=("host", "agent"), required=True)
    args = parser.parse_args()
    report = run_smoke(args.python, args.evidence, args.context)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
