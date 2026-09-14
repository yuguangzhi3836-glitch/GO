"""Separate OS processes; optional CI PostgreSQL uses disposable per-case schemas."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

pytestmark=pytest.mark.no_db


class ProcessDriver:
    def __init__(self, directory, database_url, evidence):
        self.directory=directory
        self.database_url=database_url
        self.evidence=evidence
        self.evidence.mkdir(parents=True,exist_ok=True)
        self.processes=[]
        self.records=[]

    def start(self, operation, **config):
        index=len(self.processes)
        stdout=self.evidence/f"{index:02}-{operation}.stdout.log"
        stderr=self.evidence/f"{index:02}-{operation}.stderr.log"
        command=[sys.executable,str(Path(__file__).with_name("c07_preference_process_actor.py"))]
        env=os.environ.copy()
        env.update(DATABASE_URL=self.database_url,APP_ENV="test",PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=str(Path(__file__).resolve().parents[1]/"src"),
            CONNECTOR_VAULT_MASTER_KEY="c07-synthetic-isolated-test-key")
        record={"index":index,"operation":operation,"started_at":datetime.now(timezone.utc).isoformat(),
            "command":command,"stdout":stdout.name,"stderr":stderr.name}
        with stdout.open("w") as out,stderr.open("w") as err:
            proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=out,stderr=err,env=env,
                cwd=Path(__file__).resolve().parents[1],text=True)
        proc.stdin.write(json.dumps({"operation":operation,**config}));proc.stdin.close()
        record["pid"]=proc.pid
        self.processes.append((proc,stdout,stderr,record))
        return self.processes[-1]

    def finish(self, task, expected_exit=0):
        proc,stdout,stderr,record=task
        try:
            code=proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait();raise
        record.update(exit_code=code,finished_at=datetime.now(timezone.utc).isoformat())
        self.records.append(record)
        events=[json.loads(line) for line in stdout.read_text().splitlines() if line.startswith("{")]
        record["events"]=events
        (self.evidence/"process-ledger.json").write_text(json.dumps(self.records,indent=2)+"\n")
        assert code==expected_exit,stderr.read_text()+"\n"+stdout.read_text()
        if expected_exit==-9:
            return record
        results=[e for e in events if e["kind"]=="result"]
        assert len(results)==1,stdout.read_text()+stderr.read_text()
        return results[0]

    def run(self,operation,expected_exit=0,**config):
        return self.finish(self.start(operation,**config),expected_exit)

    def marker(self,name):
        return str(self.directory/name)

    def wait_marker(self,name):
        deadline=time.monotonic()+20
        while not Path(name).exists():
            assert time.monotonic()<deadline,"Process did not reach "+name
            time.sleep(0.01)

    def close(self):
        for proc,*_ in self.processes:
            if proc.poll() is None:
                proc.kill();proc.wait(timeout=5)


@pytest.fixture
def processes(tmp_path,request):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.schema import CreateSchema,DropSchema
    external=os.getenv("GO_C07_RUNTIME_DATABASE_URL")
    control=None
    schema=None
    if external:
        url=make_url(external)
        assert url.get_backend_name()=="postgresql"
        assert url.host in {"127.0.0.1","localhost","::1"},"Only explicitly isolated loopback CI database is accepted"
        assert url.database and url.database.startswith("go_c07_isolated"),"Use a dedicated C07 test database"
        control=create_engine(url)
        schema="c07_"+uuid.uuid4().hex
        with control.begin() as conn:
            conn.execute(CreateSchema(schema))
        # Each case has its own schema. No public tables or migration versions are touched.
        url=url.update_query_dict({"options":"-csearch_path="+schema})
        database_url=url.render_as_string(hide_password=False)
    else:
        database_url="sqlite+pysqlite:///"+str(tmp_path/"process.db")
    artifact_base=Path(os.getenv("GO_C07_PROCESS_EVIDENCE_DIR",str(tmp_path/"evidence")))
    evidence=artifact_base/request.node.name
    driver=ProcessDriver(tmp_path,database_url,evidence)
    driver.backend="postgresql" if external else "sqlite"
    try:
        yield driver
    finally:
        driver.close()
        if control is not None:
            with control.begin() as conn:
                conn.execute(DropSchema(schema,cascade=True))
            control.dispose()


def setup(driver):
    return driver.run("setup")["result"]["consent_id"]


def test_committed_value_survives_abrupt_process_exit_and_revoke_restart(processes):
    d=processes;cid=setup(d)
    saved=d.run("save_exit",expected_exit=73,consent_id=cid)["result"]
    read=d.run("read")["result"]
    assert read["preferences"]==read["graph_preferences"]==[saved]
    revoked=d.run("revoke_preference",preference_id=saved["preference_id"])["result"]
    assert revoked["status"]=="REVOKED"
    read=d.run("read")["result"]
    assert read["preferences"]==read["graph_preferences"]==[]
    assert len({p[0].pid for p in d.processes})==len(d.processes)


def test_killed_uncommitted_update_rolls_back_and_original_revision_remains(processes):
    d=processes;cid=setup(d)
    first=d.run("save",consent_id=cid)["result"]
    ready,release=d.marker("uncommitted-ready"),d.marker("uncommitted-release")
    update=d.start("save",consent_id=cid,quiet=False,expected_preference_id=first["preference_id"],
        pause="before_commit",ready=ready,release=release)
    d.wait_marker(ready)
    update[0].kill();d.finish(update,expected_exit=-9)
    assert d.run("read")["result"]["preferences"]==[first]
    final=d.run("save",consent_id=cid,quiet=False,expected_preference_id=first["preference_id"])["result"]
    assert final["preference_id"]!=first["preference_id"]
    facts=d.run("inspect")["result"]["facts"]
    assert len(facts)==2 and sum(f["status"]=="ACTIVE" for f in facts)==1


def test_two_process_first_writes_have_one_winner_and_one_revision_conflict(processes):
    d=processes;cid=setup(d);release=d.marker("writers-release")
    tasks=[d.start("save",consent_id=cid,quiet=quiet,pause="before_operation",
        ready=d.marker("writer-"+str(quiet)),release=release) for quiet in [True,False]]
    for quiet in [True,False]:d.wait_marker(d.marker("writer-"+str(quiet)))
    Path(release).touch()
    results=[d.finish(t) for t in tasks]
    assert sum("result" in r for r in results)==1
    assert [r["error"] for r in results if "error" in r]==["TRAVEL_PREFERENCE_REVISION_CONFLICT"]
    assert len(d.run("read")["result"]["preferences"])==1


def test_committed_consent_withdrawal_denies_waiting_writer_and_fresh_process_reads(processes):
    d=processes;cid=setup(d)
    ready,release=d.marker("waiting-writer-ready"),d.marker("waiting-writer-release")
    writer=d.start("save",consent_id=cid,pause="before_operation",ready=ready,release=release)
    d.wait_marker(ready)
    assert d.run("revoke_consent",consent_id=cid)["result"]["status"]=="REVOKED"
    Path(release).touch()
    assert d.finish(writer)["error"]=="TRAVEL_PREFERENCE_CONSENT_REQUIRED"
    read=d.run("read")["result"]
    assert read["preferences"]==read["graph_preferences"]==[]
    assert d.run("inspect")["result"]["facts"]==[]


def test_withdrawal_serializes_with_authorized_inflight_update_or_update_is_rejected(processes):
    d=processes;cid=setup(d)
    first=d.run("save",consent_id=cid)["result"]
    ready,release=d.marker("consent-checked"),d.marker("writer-release")
    writer=d.start("save",consent_id=cid,quiet=False,expected_preference_id=first["preference_id"],
        pause="after_consent",ready=ready,release=release)
    d.wait_marker(ready)
    revoke_started=d.marker("revoke-started")
    revoker=d.start("revoke_consent",consent_id=cid,started_marker=revoke_started)
    d.wait_marker(revoke_started)
    # Observe whether withdrawal can commit while the writer is paused after
    # authorization. SQLite holds its write transaction; PostgreSQL must prove
    # equivalent ordering or reject the writer when its consent becomes stale.
    deadline=time.monotonic()+1.0
    while revoker[0].poll() is None and time.monotonic()<deadline:
        time.sleep(0.01)
    revoked_before_release=revoker[0].poll() is not None
    Path(release).touch()
    written=d.finish(writer)
    revoked=d.finish(revoker)
    assert revoked["result"]["status"]=="REVOKED"
    observed={"backend":d.backend,"withdrawal_finished_before_writer_release":revoked_before_release,
        "writer_outcome":"REJECTED" if "error" in written else "COMMITTED"}
    (d.evidence/"ordering-observation.json").write_text(json.dumps(observed,indent=2)+"\n")
    assert not revoked_before_release or written.get("error")=="TRAVEL_PREFERENCE_CONSENT_REQUIRED",observed
    read=d.run("read")["result"]
    assert read["preferences"]==read["graph_preferences"]==[]
    assert d.run("save",consent_id=cid,quiet=True)["error"]=="TRAVEL_PREFERENCE_CONSENT_REQUIRED"


def test_withdrawal_serializes_with_inflight_read_or_old_grant_releases_nothing(processes):
    d=processes;cid=setup(d)
    d.run("save",consent_id=cid)
    ready,release=d.marker("reader-consent-checked"),d.marker("reader-release")
    reader=d.start("read",pause="after_consent",ready=ready,release=release)
    d.wait_marker(ready)
    revoke_started=d.marker("read-revoke-started")
    revoker=d.start("revoke_consent",consent_id=cid,started_marker=revoke_started)
    d.wait_marker(revoke_started)
    deadline=time.monotonic()+1.0
    while revoker[0].poll() is None and time.monotonic()<deadline:
        time.sleep(0.01)
    revoked_before_release=revoker[0].poll() is not None
    Path(release).touch()
    read=d.finish(reader)["result"]
    assert d.finish(revoker)["result"]["status"]=="REVOKED"
    observed={"backend":d.backend,"withdrawal_finished_before_reader_release":revoked_before_release,
        "released_preference_count":len(read["preferences"])}
    (d.evidence/"ordering-observation.json").write_text(json.dumps(observed,indent=2)+"\n")
    assert not revoked_before_release or read["preferences"]==[],observed
    after=d.run("read")["result"]
    assert after["preferences"]==after["graph_preferences"]==[]
