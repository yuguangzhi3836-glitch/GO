"""Migrate and test a disposable loopback PostgreSQL database; never a deployed DB."""
import json,os,pathlib,subprocess,sys,xml.etree.ElementTree as ET
from sqlalchemy import create_engine,text

root=pathlib.Path(__file__).resolve().parents[2]
app=root/'application';out=pathlib.Path(os.environ['RUNNER_TEMP'])/'postgres-evidence'
out.mkdir(parents=True,exist_ok=True)
url='postgresql+psycopg://go_ci:isolated_ci_only@127.0.0.1:5432/go_ci'
env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TZ')}
env.update(PYTHONPATH=str(root/'ci/retention/guard')+os.pathsep+str(app/'src')+os.pathsep+str(app)+os.pathsep+str(app/'tests'),
    PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',APP_ENV='test',
    MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',DATABASE_URL=url,POSTGRES_TEST_DATABASE_URL=url)
def run(name,args):
    with (out/name).open('w') as f:r=subprocess.run([sys.executable,*args],cwd=app,env=env,stdout=f,stderr=subprocess.STDOUT)
    print((out/name).read_text()[-16000:])
    if r.returncode:raise SystemExit(r.returncode)
run('migration.log',['-m','alembic','upgrade','head'])
run('postgres-tests.log',['-m','pytest','-p','pytest_asyncio.plugin','-p','no:cacheprovider','-o','addopts=','-q',
    'tests/test_p0_0100_postgres_concurrency.py','tests/test_p0_0101_postgres_race_matrix.py','--junitxml='+str(out/'junit.xml')])
suites=ET.parse(out/'junit.xml').getroot().findall('testsuite')
metrics={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
assert metrics==dict(tests=6,failures=0,errors=0,skipped=0),metrics
from go_hotel.db.models import PostgresRaceProofEvidenceRow as Proof
engine=create_engine(url)
with engine.connect() as c:
    version=c.execute(text('select version()')).scalar_one()
    revisions=list(c.execute(text('select version_num from alembic_version')).scalars())
    rows=[dict(r) for r in c.execute(Proof.__table__.select()).mappings()]
proof=[{k:r[k] for k in ('scenario_key','worker_count','commit_count','reject_count','assertion_state','evidence_hash')} for r in rows]
assert {r['scenario_key'] for r in proof}=={'ORDER_PAYMENT_ROOT_EXACTLY_ONCE','WEBHOOK_REPLAY_UNIQUE','CAPTURE_REFUND_SERIALIZATION','FINANCE_CLOSE_APPROVAL_RACE'}
assert all(r['assertion_state']=='PASS' and r['commit_count']==1 and r['reject_count']==r['worker_count']-1 for r in proof)
report={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
    'application_git_tree':subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=root,text=True).strip(),
    'postgres_version':version,'migration_heads':revisions,'metrics':metrics,'race_proofs':proof,
    'migration':'PASS','database':'DISPOSABLE_GITHUB_ACTIONS_SERVICE','external_providers':'NOT_RUN','deployment':'NOT_RUN'}
(out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
engine.dispose()
