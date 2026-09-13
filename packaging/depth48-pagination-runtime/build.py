"""Build/restore the fixed business image on a disposable GitHub runner only."""
import gzip, hashlib, json, os, pathlib, subprocess, tarfile, tempfile, zipfile
from datetime import datetime, timezone
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'runtime-package-evidence';OUT.mkdir(exist_ok=True)
BINDING=json.loads((ROOT/'packaging/depth48-pagination-runtime/CANDIDATE.json').read_text())
SHA=BINDING['source_tree_sha256']; TREE=BINDING['application_git_tree']
COMMIT=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
TAG='go-hotel:depth48-admin-pagination-'+COMMIT[:12]
def run(args, **kw):
    print('+', ' '.join(map(str,args)),flush=True)
    return subprocess.check_output(args,cwd=ROOT,text=True,**kw)
def save(name,data): (OUT/name).write_text(json.dumps(data,indent=2)+'\n')
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()
paths=run(['git','ls-tree','-r','--name-only','HEAD','application']).splitlines()
fp={p[len('application/'):]:digest(ROOT/p) for p in paths}
assert len(fp)==1325
assert hashlib.sha256(''.join(f'{p}\0{h}\n' for p,h in sorted(fp.items())).encode()).hexdigest()==SHA
assert run(['git','rev-parse','HEAD:application']).strip()==TREE
save('source-fingerprint.json',fp)
subprocess.run(['docker','build','--label','org.opencontainers.image.revision='+COMMIT,'--tag',TAG,'application'],cwd=ROOT,check=True)
image=json.loads(run(['docker','image','inspect',TAG]))[0]
image_id=image['Id'];save('image-inspect.json',image)
verify=r'''
import hashlib,importlib.metadata,json,pathlib,sys
fp=json.load(sys.stdin);root=pathlib.Path('/app');excluded=[];checked=[]
for rel,expected in fp.items():
    if rel=='.gitignore' or rel.startswith('.pytest_cache/') or rel.startswith('var/') or '__pycache__' in pathlib.PurePosixPath(rel).parts or rel.endswith(('.pyc','.pyo')):
        excluded.append(rel);continue
    p=root/rel
    assert p.is_file(),rel
    assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,rel
    checked.append(rel)
print(json.dumps({'result':'PASS','verified_runtime_files':len(checked),'dockerignore_exclusions':excluded,'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}}))
'''
inside=json.loads(run(['docker','run','--rm','-i','--network','none','--entrypoint','python',TAG,'-c',verify],input=json.dumps(fp)))
save('image-source-verification.json',inside)
smoke=r'''
import importlib,json,os,pathlib,secrets,subprocess,time,urllib.request
os.environ.update(DATABASE_URL='sqlite+pysqlite:////tmp/go-package-smoke.db',APP_ENV='local',GO_MEDIA_CACHE_DIR='/tmp/media-cache',JWT_SIGNING_KEY=secrets.token_hex(32),CONNECTOR_VAULT_MASTER_KEY=secrets.token_hex(32),BOOTSTRAP_ADMIN_PASSWORD=secrets.token_urlsafe(32),BOOTSTRAP_SUPPLIER_PASSWORD=secrets.token_urlsafe(32),VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED='false',HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED='false',READINESS_REQUIRE_POSTGRES='false',MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',OIDC_ENABLED='false')
from alembic.config import Config
from alembic.script import ScriptDirectory
heads=ScriptDirectory.from_config(Config('/app/alembic.ini')).get_heads()
assert heads==['0133_flight_change_plan'],heads
from go_hotel.db.models import Base
from go_hotel.db.session import engine
assert engine.url.get_backend_name()=='sqlite'
Base.metadata.create_all(engine)
workers=['outbox_worker','recovery_worker','reconciliation_worker','judgment_worker','mobile_engagement_worker','mobile_push_worker','mobile_push_receipt_worker']
for worker in workers:importlib.import_module('go_hotel.workers.'+worker)
p=subprocess.Popen(['uvicorn','go_hotel.main:app','--host','127.0.0.1','--port','8000'],stdout=open('/tmp/smoke-server.log','w'),stderr=subprocess.STDOUT,cwd='/tmp')
try:
    for _ in range(60):
        if p.poll() is not None:raise RuntimeError(pathlib.Path('/tmp/smoke-server.log').read_text())
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2) as r:health=json.load(r);assert r.status==200
            break
        except OSError:time.sleep(1)
    else:raise RuntimeError('HEALTH_TIMEOUT')
    statuses={}
    for path in ['/health','/openapi.json','/go-app/','/supplier-console/','/go-admin/']:
        with urllib.request.urlopen('http://127.0.0.1:8000'+path,timeout=10) as r:statuses[path]=r.status;assert r.status==200
    print(json.dumps({'result':'PASS','image_health':health,'http':statuses,'alembic_heads':heads,'worker_imports':workers,'worker_processes_started':False,'database':'NEW_PRIVATE_SQLITE','network':'DOCKER_NONE','migration_executed':False,'scope':'IMAGE_BOOT_SMOKE_ONLY; not login, PostgreSQL or HK deployment'}))
finally:p.terminate();p.wait(timeout=20)
'''
smoke_raw=run(['docker','run','--rm','--network','none','--tmpfs','/tmp','--entrypoint','python',TAG,'-c',smoke])
(OUT/'image-smoke.log').write_text(smoke_raw)
smoke_result=json.loads(smoke_raw.strip().splitlines()[-1]);assert smoke_result['result']=='PASS'
save('image-smoke.json',smoke_result)
# Test the actual built image and resolved dependency set, not the host Python.
container_tests=run(['docker','run','--rm','--network','none','--tmpfs','/tmp',
    '-e','PYTHONDONTWRITEBYTECODE=1','-v',str(ROOT/'packaging/depth48-pagination-runtime')+':/verify:ro',
    '-v',str(OUT)+':/evidence','--entrypoint','python',TAG,'-B','-m','pytest','-q',
    '-p','no:cacheprovider','/verify/test_pagination.py','--junitxml=/evidence/image-pagination-junit.xml'])
(OUT/'image-pagination-tests.log').write_text(container_tests)

image_tar=OUT/'business-image.tar.gz'
with image_tar.open('wb') as f:
    p=subprocess.Popen(['docker','save',TAG],stdout=subprocess.PIPE)
    with gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as gz:
        for block in iter(lambda:p.stdout.read(1048576),b''):gz.write(block)
    assert p.wait()==0
# Only the image tag created by this build is removed/reloaded on the disposable runner.
run(['docker','image','rm',TAG])
with gzip.open(image_tar,'rb') as source:
    p=subprocess.Popen(['docker','load'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    for block in iter(lambda:source.read(1048576),b''):p.stdin.write(block)
    p.stdin.close();reload_output=p.stdout.read().decode();assert p.wait()==0
assert json.loads(run(['docker','image','inspect',TAG]))[0]['Id']==image_id
save('image-restore.json',{'result':'PASS','image_id':image_id,'output':reload_output,'tar_sha256':digest(image_tar)})
source_tar=OUT/'source-and-runtime.tar.gz'
with source_tar.open('wb') as target:subprocess.run(['git','archive','--format=tar.gz','HEAD','application','deploy/hk-staging'],cwd=ROOT,stdout=target,check=True)
with tarfile.open(source_tar) as t:
    for rel,expected in fp.items():assert hashlib.sha256(t.extractfile('application/'+rel).read()).hexdigest()==expected,rel
manifest={**BINDING,'build_commit':COMMIT,'built_at':datetime.now(timezone.utc).isoformat(),'run_id':os.environ.get('GITHUB_RUN_ID'),'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'image_tag':TAG,'image_id':image_id,'image_archive_sha256':digest(image_tar),'source_archive_sha256':digest(source_tar),'build_restore_smoke':'PASS','actual_image_pagination_regression':'PASS','environment':'DISPOSABLE_GITHUB_RUNNER','tested_source_commit':'d8aa02fff7d1391132d9eee5daadcb3b90d04392','browser_run':34755489869,'release_approved':False,'deployed':False,'hong_kong':'NOT_ACCESSED','production':'NOT_ACCESSED','migration_required':False,'schema_head':'0133_flight_change_plan','deployment_hold':['Exact-source browser acceptance must pass','Fresh live drift and current DEPTH48 previous-state record','CANARY and signed DEPLOY/VERIFY through existing Command Center','Deploy channel usable/enabled evidence unavailable in current source scope'],'rollback_policy':'Preserve current live DEPTH48 image and durable state. Never use superseded DEPTH46/R3 as rollback source. No automatic rollback.'}
save('MANIFEST.json',manifest)
# Existing canonical runtime definitions are included verbatim, not converted to executor parameters.
(OUT/'README.md').write_text((ROOT/'packaging/depth48-pagination-runtime/README.md').read_text())
save('SHA256.json',{p.name:digest(p) for p in OUT.iterdir() if p.is_file() and p.name!='SHA256.json'})
package=ROOT/'GO_DEPTH48_ADMIN_PAGINATION_RUNTIME_20260913.zip'
with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_STORED) as z:
    for p in sorted(OUT.iterdir()):
        if p.is_file():z.write(p,p.name)
with zipfile.ZipFile(package) as z:
    for name,expected in json.loads(z.read('SHA256.json')).items():assert hashlib.sha256(z.read(name)).hexdigest()==expected,name
receipt={'package':package.name,'bytes':package.stat().st_size,'sha256':digest(package),'zip_readback':'PASS','image_id':image_id,'application_git_tree':TREE,'build_commit':COMMIT,'status':'BUILT_NOT_DEPLOYED'}
(ROOT/'RUNTIME_PACKAGE_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
