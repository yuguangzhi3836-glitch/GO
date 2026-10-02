"""Bounded qualification + ABBA in the already approved four-vCPU Codespace."""
from pathlib import Path
import hashlib,json,os,re,runpy,shlex,signal,subprocess,sys,time,zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
PYTHON='/workspaces/.go-capacity-venv/bin/python'
NAME='literate-winner-vpqqjgwvpjprcp7gw'
BRANCH='evidence/query-cost-ride-query-20261002'
PG='go-query-cost-ride-query-pg'
OUT=ROOT/'ride-query-qualification';OUT.mkdir(exist_ok=False)
START=time.monotonic();DEADLINE=START+5400
HEAD=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
TREE=subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip()
ENV=dict(os.environ,EXPECTED_HEAD=HEAD,GO_MULTI_DATABASE_URL='postgresql+psycopg://go_ci:isolated_multi_only@127.0.0.1:5432/go_c11_isolated',APP_ENV='test',MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',TRAVEL_INTELLIGENCE_ENABLED='false',PYTHONUNBUFFERED='1',PYTHONPATH=str(ROOT/'application/src'))
state={'head':HEAD,'application_tree':TREE,'status':'SETUP','maximum_seconds':5400,'configuration':'4 processes x4 connections','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'acceptance':False,'original_2vcpu_acceptance':'FAIL'}
def save():(OUT/'status.json').write_text(json.dumps(state,indent=2)+'\n')
def run(args,cwd=ROOT,env=ENV,check=True,log=None):
    stream=log.open('w') if log else None
    print('RUN',args[0],args[1:3],flush=True)
    try:p=subprocess.Popen(args,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT if stream else None,start_new_session=True)
    finally:
        if stream:stream.close()
    try:code=p.wait(timeout=max(1,DEADLINE-time.monotonic()))
    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait();raise
    if check and code:raise subprocess.CalledProcessError(code,args)
    return code
def junit(path,expected):
    root=ET.parse(path).getroot();suites=list(root.iter('testsuite'))
    assert sum(int(s.get('tests','0')) for s in suites)==expected
    assert all(int(s.get(k,'0'))==0 for s in suites for k in ('failures','errors','skipped'))

pg=False
try:
    save();assert os.environ.get('CODESPACE_NAME')==NAME
    assert not subprocess.check_output(['git','diff','HEAD','--','application'],cwd=ROOT)
    (OUT/'hardware.json').write_text(json.dumps(runpy.run_path(str(ROOT/'ci/four_vcpu/run.py'))['capacity'](),indent=2)+'\n')
    (OUT/'packages.txt').write_text(subprocess.check_output([PYTHON,'-m','pip','freeze'],text=True))
    run([PYTHON,'-m','pytest','-p','no:cacheprovider','ci/ride_query/test_gate.py','ci/multi_instance/test_profiling_cost.py','ci/journey_latency/test_measure.py','ci/journey_latency/test_verify.py','-q','--junitxml='+str(OUT/'harness.xml')],log=OUT/'harness.log')
    run(['docker','run','--name',PG,'--rm','-d','-e','POSTGRES_USER=go_ci','-e','POSTGRES_PASSWORD=isolated_multi_only','-e','POSTGRES_DB=go_c11_isolated','-p','127.0.0.1:5432:5432','postgres:18.4']);pg=True
    for _ in range(60):
        if run(['docker','exec',PG,'pg_isready','-U','go_ci','-d','go_c11_isolated'],check=False)==0:break
        time.sleep(1)
    else:raise RuntimeError('POSTGRES_NOT_READY')
    test_env=dict(ENV,GO_TEST_DATABASE_URL=ENV['GO_MULTI_DATABASE_URL'],GO_REQUIRE_POSTGRES='1')
    state['status']='BOUNDARY_SAFETY';save()
    run([PYTHON,'-m','pytest','-p','no:cacheprovider','-x','tests/payments/test_ride_money_query_cost.py','-o','junit_family=xunit1','--junitxml='+str(OUT/'boundaries.xml')],cwd=ROOT/'application',env=test_env,log=OUT/'boundaries.log')
    junit(OUT/'boundaries.xml',15)
    import yaml
    steps=yaml.safe_load((ROOT/'.github/workflows/multi-instance-transactions.yml').read_text())['jobs']['isolated']['steps']
    step=next(s for s in steps if s.get('name')=='Payment recovery and payment-inventory boundary regressions')
    line=next(s.strip() for s in step['run'].splitlines() if s.strip().startswith('python -m pytest '))
    args=[s for s in shlex.split(line)[3:] if not s.startswith('--junitxml=')]
    state['status']='FROZEN_250_REGRESSIONS';save()
    run([PYTHON,'-m','pytest','-p','no:cacheprovider',*args,'--junitxml='+str(OUT/'regressions.xml')],cwd=ROOT/'application',env=test_env,log=OUT/'regressions.log')
    junit(OUT/'regressions.xml',250)
    safety={'head':HEAD,'application_tree':TREE,'status':'PASS','regressions':250,'boundary_tests':15,'junit_sha256':{n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ('boundaries.xml','regressions.xml')}}
    (OUT/'safety.json').write_text(json.dumps(safety,indent=2)+'\n')
    state['status']='ABBA_RUNNING';save()
    state['experiment_exit_code']=run([PYTHON,'ci/ride_query/experiment.py'],check=False,log=OUT/'experiment.log')
    summary=ROOT/'ride-query-evidence/summary.json'
    state['status']=json.loads(summary.read_text())['status'] if summary.exists() else 'INCOMPLETE'
except Exception as exc:
    state.update(status='FAILED_OR_INCOMPLETE',error_type=type(exc).__name__);raise
finally:
    state['elapsed_seconds']=time.monotonic()-START;save()
    if pg:subprocess.run(['docker','stop',PG],cwd=ROOT,timeout=30,check=False)
    try:
        # Successful logs contain only test results. Fail closed on credential-like
        # material; no source code, arbitrary environment or authentication dump.
        files=[p for d in (OUT,ROOT/'ride-query-evidence') if d.exists() for p in d.rglob('*') if p.is_file()]
        secret=re.compile(rb'(?i)authorization[^\r\n]{0,20}bearer\s+[a-z0-9._-]{12,}|eyJ[a-zA-Z0-9_-]{15,}\.[a-zA-Z0-9_-]{15,}\.[a-zA-Z0-9_-]{15,}|(?:ghp_|github_pat_)[a-zA-Z0-9_]{20,}')
        assert not any(secret.search(p.read_bytes()) for p in files),'EVIDENCE_REDACTION_REQUIRED'
        dest=ROOT/'ci/ride_query/evidence'/HEAD[:12];dest.mkdir(parents=True,exist_ok=False)
        archive=dest/'raw.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for p in files:z.write(p,p.relative_to(ROOT))
        (dest/'SHA256.json').write_text(json.dumps({'raw.zip':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2)+'\n')
        (dest/'status.json').write_text(json.dumps(state,indent=2)+'\n')
        for name,source in [('summary.json',ROOT/'ride-query-evidence/summary.json'),('safety.json',OUT/'safety.json')]:
            if source.exists():(dest/name).write_bytes(source.read_bytes())
        subprocess.run(['git','add',str(dest.relative_to(ROOT))],cwd=ROOT,check=True,timeout=30)
        subprocess.run(['git','commit','-m','test: archive PR284 safety and bounded ABBA evidence'],cwd=ROOT,check=True,timeout=30)
        subprocess.run(['git','push','origin','HEAD:refs/heads/'+BRANCH],cwd=ROOT,check=True,timeout=120)
        print('EVIDENCE_PUBLISHED',flush=True)
    finally:subprocess.run(['gh','api','-X','POST','/user/codespaces/'+NAME+'/stop'],cwd=ROOT,timeout=60,check=False)
