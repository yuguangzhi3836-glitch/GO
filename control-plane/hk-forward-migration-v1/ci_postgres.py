"""Exercise the unchanged executor program in a disposable candidate container/DB."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
PROGRAM=ROOT/'hk-staging/source/executor/runtime/migration_program.py'
EVIDENCE=ROOT/'ci/hk-migration-admission/PR183_REHEARSAL_EVIDENCE.json'
URL='postgresql+psycopg://go_ci:isolated_ci_only@127.0.0.1:5432/go_issue103_executor'

def run(argv,**kw): return subprocess.run(argv,check=True,capture_output=True,text=True,**kw).stdout

def main(candidate,wheels,output):
    assert os.environ.get('GITHUB_ACTIONS')=='true','CI_ONLY'
    evidence=json.loads(EVIDENCE.read_text());b=evidence['binding']
    assert run(['git','-C',str(candidate),'rev-parse','HEAD']).strip()==b['candidate_sha']
    assert run(['git','-C',str(candidate),'rev-parse','HEAD:application']).strip()==b['candidate_application_tree']
    fingerprint={}
    for name in run(['git','-C',str(candidate),'ls-files','application']).splitlines():
        path=candidate/name;assert path.is_file() and not path.is_symlink()
        fingerprint[name[len('application/'):]]=hashlib.sha256(path.read_bytes()).hexdigest()
    fp=hashlib.sha256(''.join(f'{n}\0{h}\n' for n,h in sorted(fingerprint.items())).encode()).hexdigest()
    assert fp==b['candidate_fingerprint_sha256']
    output.mkdir(parents=True,exist_ok=True)
    tag='go-issue103-executor-ci:'+os.environ['GITHUB_RUN_ID']
    with tempfile.TemporaryDirectory() as tmp:
        ctx=Path(tmp);shutil.copytree(candidate/'application',ctx/'application')
        shutil.copytree(wheels/'wheelhouse',ctx/'wheelhouse')
        shutil.copy(candidate/'ci/retention/requirements.lock',ctx/'requirements.lock')
        (ctx/'Dockerfile').write_text('FROM python:3.13.5-slim\nCOPY wheelhouse /wheels\nCOPY requirements.lock /requirements.lock\nRUN python -m pip install --no-index --find-links /wheels -r /requirements.lock\nWORKDIR /workspace\nCOPY application /workspace\nENV PYTHONPATH=/workspace/src PYTHONDONTWRITEBYTECODE=1\n')
        run(['docker','pull','python:3.13.5-slim'])
        build=run(['docker','build','--network=none','--tag',tag,str(ctx)],timeout=360)
        (output/'build.log').write_text(build)
    image=run(['docker','image','inspect',tag,'--format','{{.Id}}']).strip()
    prefix=['docker','run','--rm','--network','host','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,nosuid,nodev,size=64m',
            '--env','DATABASE_URL='+URL,'--env','MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED=false',
            '--env','TRAVEL_INTELLIGENCE_ENABLED=false','--workdir','/workspace',
            '--entrypoint','/usr/local/bin/python',image]
    try:
        baseline=run(prefix+['-m','alembic','upgrade',b['baseline_revision']],timeout=300)
        (output/'baseline.log').write_text(baseline)
        from sqlalchemy import create_engine,text
        engine=create_engine(URL)
        with engine.begin() as connection:
            assert connection.execute(text('SELECT current_database()')).scalar_one()=='go_issue103_executor'
            connection.execute(text("INSERT INTO flight_change_plan (quote_id,order_id,account_id,plan_json,plan_hash,created_at) VALUES ('executor-retention','test-order','test-account',CAST(:plan AS JSON),:digest,'2026-09-17T00:00:00Z')"),{'plan':'{"retain":true}','digest':'a'*64})
        spec={'baseline_revision':b['baseline_revision'],'target_revision':b['target_revision'],
              'lineage_sha256':evidence['migration_source_digest']}
        program=PROGRAM.read_text()+'\nentry()\n'
        source=json.loads(run(prefix+['-c',program,'source',json.dumps(spec)],timeout=60))
        actual=json.loads(run(prefix+['-c',program,'migrate',json.dumps(spec)],timeout=300))
        assert actual=={'source':'PASS','lineage_sha256':spec['lineage_sha256'],
                        'prestate':b['baseline_revision'],'poststate':b['target_revision']}
        second=subprocess.run(prefix+['-c',program,'migrate',json.dumps(spec)],capture_output=True,text=True,timeout=60)
        assert second.returncode==2 and json.loads(second.stdout)=={'error':'RDS_PRESTATE_MISMATCH'}
        bad={**spec,'lineage_sha256':'f'*64}
        drift=subprocess.run(prefix+['-c',program,'migrate',json.dumps(bad)],capture_output=True,text=True,timeout=60)
        assert drift.returncode==2 and json.loads(drift.stdout)=={'error':'MIGRATION_SOURCE_DIGEST'}
        with engine.connect() as connection:
            assert list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())==[b['target_revision']]
            assert connection.execute(text("SELECT plan_hash FROM flight_change_plan WHERE quote_id='executor-retention'")).scalar_one()=='a'*64
            indexes=connection.execute(text("SELECT indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE c.relname IN ('ix_go_journey_title_lower_trgm','ix_go_journey_destination_lower_trgm')")).scalars().all()
            assert indexes==[True,True]
        result={'status':'PASS_SCOPED','source_sha':b['candidate_sha'],'application_tree':b['candidate_application_tree'],
                'source_fingerprint':fp,'migration_program_sha256':hashlib.sha256(PROGRAM.read_bytes()).hexdigest(),
                'rehearsal_sha256':hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
                'isolated_image':image,'source_check':source,'forward_migration':actual,
                'repeat_prestate_refused':True,'wrong_lineage_refused':True,'data_retention':'PASS',
                'valid_indexes':2,'live_database_touched':False,'inherited_cell_tests_rerun':False,
                'deployment_ready':False,'scope':'DISPOSABLE_CI_EXECUTOR_PROGRAM_ONLY'}
        raw=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
        (output/'EVIDENCE.json').write_bytes(raw)
        print(json.dumps(result,sort_keys=True));print('EVIDENCE_SHA256='+hashlib.sha256(raw).hexdigest())
    finally:
        run(['docker','image','rm',tag])

if __name__=='__main__': main(*(Path(x).resolve() for x in sys.argv[1:]))
