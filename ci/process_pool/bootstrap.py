"""Bounded Codespaces run, atomic archive, explicit evidence commit, stop self."""
from pathlib import Path
import hashlib,json,os,runpy,shlex,signal,subprocess,sys,time,zipfile
ROOT=Path(__file__).resolve().parents[2]
PYTHON='/workspaces/.go-capacity-venv/bin/python'
NAME='literate-winner-vpqqjgwvpjprcp7gw'
BRANCH='experiment/process-pool-20260930'
OUT=ROOT/'process-pool-qualification'
OUT.mkdir(exist_ok=False)
START=time.monotonic();DEADLINE=START+5400
HEAD=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
ENV=dict(os.environ,EXPECTED_HEAD=HEAD,GO_MULTI_DATABASE_URL='postgresql+psycopg://go_ci:isolated_multi_only@127.0.0.1:5432/go_c11_isolated',APP_ENV='test',MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',TRAVEL_INTELLIGENCE_ENABLED='false',PYTHONUNBUFFERED='1')
ENV['PYTHONPATH']=str(ROOT/'application/src')
state={'head':HEAD,'status':'SETUP','maximum_seconds':5400,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'acceptance':False}
def save(): (OUT/'status.json').write_text(json.dumps(state,indent=2)+'\n')
def run(args,cwd=ROOT,env=ENV,check=True):
    print('RUN',args[0],args[1:3],flush=True)
    p=subprocess.Popen(args,cwd=cwd,env=env,start_new_session=True)
    try:code=p.wait(timeout=max(1,DEADLINE-time.monotonic()))
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGKILL);p.wait();raise
    if check and code:raise subprocess.CalledProcessError(code,args)
    return code
pg=False
try:
    save()
    assert subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip()=='6570b66bc977f89c0311d67bdc6b721cd70d4e09'
    hardware=runpy.run_path(str(ROOT/'ci/four_vcpu/run.py'))['capacity']()
    (OUT/'hardware.json').write_text(json.dumps(hardware,indent=2)+'\n')
    # Preserve dependencies from the preceding experiment, no upgrades.
    (OUT/'packages.txt').write_text(subprocess.check_output([PYTHON,'-m','pip','freeze'],text=True))
    run([PYTHON,'-m','pytest','ci/process_pool/test_run.py','ci/multi_instance/test_thread_switch.py','-q','--junitxml='+str(OUT/'harness.xml')])
    run(['docker','run','--name','go-process-pool-pg','--rm','-d','-e','POSTGRES_USER=go_ci','-e','POSTGRES_PASSWORD=isolated_multi_only','-e','POSTGRES_DB=go_c11_isolated','-p','127.0.0.1:5432:5432','postgres:18.4']);pg=True
    for _ in range(60):
        if run(['docker','exec','go-process-pool-pg','pg_isready','-U','go_ci','-d','go_c11_isolated'],check=False)==0:break
        time.sleep(1)
    else:raise RuntimeError('POSTGRES_NOT_READY')
    import yaml,xml.etree.ElementTree as ET
    steps=yaml.safe_load((ROOT/'.github/workflows/multi-instance-transactions.yml').read_text())['jobs']['isolated']['steps']
    step=next(s for s in steps if s.get('name')=='Payment recovery and payment-inventory boundary regressions')
    line=next(s.strip() for s in step['run'].splitlines() if s.strip().startswith('python -m pytest '))
    args=[s for s in shlex.split(line)[3:] if not s.startswith('--junitxml=')]
    state['status']='REGRESSIONS';save()
    run([PYTHON,'-m','pytest',*args,'--junitxml='+str(OUT/'original.xml')],cwd=ROOT/'application',env=dict(ENV,GO_TEST_DATABASE_URL=ENV['GO_MULTI_DATABASE_URL']))
    suite=ET.parse(OUT/'original.xml').getroot().find('testsuite')
    assert int(suite.get('tests'))==250 and all(int(suite.get(k,'0'))==0 for k in ('failures','errors','skipped'))
    state['status']='FACTORIAL_RUNNING';save()
    code=run([PYTHON,'ci/process_pool/experiment.py'],check=False)
    state['experiment_exit_code']=code
    summary=ROOT/'process-pool-evidence/summary.json'
    state['status']=json.loads(summary.read_text())['status'] if summary.exists() else 'INCOMPLETE'
except Exception as exc:
    state.update(status='FAILED_OR_INCOMPLETE',error_type=type(exc).__name__)
    raise
finally:
    state['elapsed_seconds']=time.monotonic()-START;save()
    if pg:subprocess.run(['docker','stop','go-process-pool-pg'],cwd=ROOT,timeout=30,check=False)
    try:
        dest=ROOT/'ci/process_pool/evidence/20260930';dest.mkdir(parents=True,exist_ok=False)
        archive=dest/'raw.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for folder in (OUT,ROOT/'process-pool-evidence'):
                if folder.exists():
                    for f in folder.rglob('*'):
                        if f.is_file():z.write(f,f.relative_to(ROOT))
        (dest/'SHA256.json').write_text(json.dumps({'raw.zip':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2)+'\n')
        (dest/'status.json').write_text(json.dumps(state,indent=2)+'\n')
        summary=ROOT/'process-pool-evidence/summary.json'
        if summary.exists():(dest/'summary.json').write_bytes(summary.read_bytes())
        subprocess.run(['git','add','ci/process_pool/evidence/20260930'],cwd=ROOT,check=True,timeout=30)
        subprocess.run(['git','commit','-m','test: archive bounded process and pool attribution evidence'],cwd=ROOT,check=True,timeout=30)
        subprocess.run(['git','push','origin','HEAD:refs/heads/'+BRANCH],cwd=ROOT,check=True,timeout=120)
        print('EVIDENCE_PUBLISHED',flush=True)
    finally:
        print('STOPPING_CODESPACE',flush=True)
        subprocess.run(['gh','api','-X','POST','/user/codespaces/'+NAME+'/stop'],cwd=ROOT,timeout=60,check=False)
