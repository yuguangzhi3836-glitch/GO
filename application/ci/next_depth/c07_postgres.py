"""Run C07 process acceptance against an explicitly isolated loopback PostgreSQL.

CI supplies GO_C07_RUNTIME_DATABASE_URL and GO_C07_SOURCE_COMMIT. The URL must
point to a dedicated database named go_c07_isolated*. Tests create/drop only
random c07_* schemas. Never use this runner with a business or remote database.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--evidence-dir",required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    output=Path(args.evidence_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    execution={"task":"V70-R2-C07-02","started_at":datetime.now(timezone.utc).isoformat(),
        "source_commit":os.getenv("GO_C07_SOURCE_COMMIT","UNSPECIFIED"),
        "python":sys.version,"workers":"normal isolated subprocesses; no xdist", "C14":"PENDING","C13":"PENDING"}
    files=["src/go_hotel/travel_intelligence/preferences.py","src/go_hotel/travel_intelligence/service.py",
        "src/go_hotel/api/routes/travel_intelligence.py","tests/test_round2_c07_process_recovery.py",
        "tests/c07_preference_process_actor.py","ci/next_depth/c07_postgres.py"]
    execution["source_files"]=[{"path":p,"sha256":hashlib.sha256((root/p).read_bytes()).hexdigest()} for p in files]
    raw=os.getenv("GO_C07_RUNTIME_DATABASE_URL")
    if not raw:
        execution.update(status="HOLD",reason="ISOLATED_POSTGRES_URL_NOT_SUPPLIED")
        (output/"execution.json").write_text(json.dumps(execution,indent=2)+"\n")
        print(json.dumps({"status":"HOLD","reason":execution["reason"]}));return 2
    url=make_url(raw)
    if url.get_backend_name()!="postgresql" or url.host not in {"127.0.0.1","localhost","::1"} or not (url.database or "").startswith("go_c07_isolated"):
        execution.update(status="HOLD",reason="ISOLATED_LOOPBACK_DATABASE_REQUIRED")
        (output/"execution.json").write_text(json.dumps(execution,indent=2)+"\n")
        print(json.dumps({"status":"HOLD","reason":execution["reason"]}));return 2
    engine=create_engine(url,connect_args={"connect_timeout":5})
    try:
        with engine.connect() as connection:
            execution["postgres_server_version"]=connection.scalar(text("SHOW server_version"))
    except Exception as exc:
        execution.update(status="HOLD",reason="ISOLATED_POSTGRES_UNAVAILABLE",error_type=type(exc).__name__)
        (output/"execution.json").write_text(json.dumps(execution,indent=2)+"\n")
        print(json.dumps({"status":"HOLD","reason":execution["reason"],"error_type":type(exc).__name__}));return 2
    finally:
        engine.dispose()
    command=[sys.executable,"-m","pytest","-ra","-p","no:cacheprovider","tests/test_round2_c07_process_recovery.py",
        "--junitxml="+str(output/"junit.xml"),"--tb=short"]
    env=os.environ.copy()
    env.update(PYTHONPATH=str(root/"src"),PYTHONDONTWRITEBYTECODE="1",GO_C07_PROCESS_EVIDENCE_DIR=str(output/"processes"))
    execution.update(command=command,status="RUNNING")
    (output/"execution.json").write_text(json.dumps(execution,indent=2)+"\n")
    with (output/"pytest.log").open("w") as log:
        result=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
    execution.update(finished_at=datetime.now(timezone.utc).isoformat(),exit_code=result.returncode,
        status="EVIDENCE_READY" if result.returncode==0 else "TEST_FAILED")
    (output/"execution.json").write_text(json.dumps(execution,indent=2)+"\n")
    print(json.dumps({"status":execution["status"],"exit_code":result.returncode,
        "postgres_server_version":execution["postgres_server_version"]}))
    return result.returncode


if __name__=="__main__":
    sys.exit(main())
