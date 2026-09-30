"""Bounded fixed4x4 validation in the approved four-vCPU Codespace."""
from pathlib import Path
import hashlib,json,os,runpy,signal,subprocess,sys,time,zipfile
ROOT=Path(__file__).resolve().parents[2]
PYTHON='/workspaces/.go-capacity-venv/bin/python'
NAME='literate-winner-vpqqjgwvpjprcp7gw';BRANCH='experiment/capacity-4x4-validation-20260930'
OUT=ROOT/'capacity-4x4-qualification';EVIDENCE=ROOT/'capacity-4x4-evidence'
OUT.mkdir(exist_ok=False);EVIDENCE.mkdir(exist_ok=False)
HEAD=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
START=time.monotonic();DEADLINE=START+5400
ENV=dict(os.environ,EXPECTED_HEAD=HEAD,GO_MULTI_DATABASE_URL='postgresql+psycopg://go_ci:isolated_multi_only@127.0.0.1:5432/go_c11_isolated',APP_ENV='test',MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',TRAVEL_INTELLIGENCE_ENABLED='false',PYTHONUNBUFFERED='1',PYTHONPATH=str(ROOT/'application/src'))
state={'head':HEAD,'status':'SETUP','configuration':'4 processes x4 connections','maximum_seconds':5400,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'original_2vcpu_acceptance':'FAIL'}
def save():(OUT/'status.json').write_text(json.dumps(state,indent=2)+'\n')
def run(args,cwd=ROOT,env=ENV,check=True,log=None):
    print('RUN',args[0],args[1:4],flush=True)
    stream=(log.open('w') if log else None)
    try:p=subprocess.Popen(args,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT if stream else None,start_new_session=True)
    finally:
        if stream:stream.close()
    try:code=p.wait(timeout=max(1,DEADLINE-time.monotonic()))
    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait();raise
    if check and code:raise subprocess.CalledProcessError(code,args)
    return code
pg=False
try:
    save();assert subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip()=='6570b66bc977f89c0311d67bdc6b721cd70d4e09'
    (OUT/'hardware.json').write_text(json.dumps(runpy.run_path(str(ROOT/'ci/four_vcpu/run.py'))['capacity'](),indent=2)+'\n')
    run([PYTHON,'-m','pytest','-p','no:cacheprovider','ci/journey_latency/test_measure.py','ci/journey_latency/test_verify.py','ci/process_pool/test_run.py','-q','--junitxml='+str(OUT/'harness.xml')])
    run(['docker','run','--name','go-capacity-4x4-pg','--rm','-d','-e','POSTGRES_USER=go_ci','-e','POSTGRES_PASSWORD=isolated_multi_only','-e','POSTGRES_DB=go_c11_isolated','-p','127.0.0.1:5432:5432','postgres:18.4']);pg=True
    for _ in range(60):
        if run(['docker','exec','go-capacity-4x4-pg','pg_isready','-U','go_ci','-d','go_c11_isolated'],check=False)==0:break
        time.sleep(1)
    else:raise RuntimeError('POSTGRES_NOT_READY')
    state['status']='FORMAL_4X4';save()
    for n in (1,2):
        code=run([PYTHON,'ci/process_pool/run.py','--instances','4','--pool','4','--out',str(EVIDENCE/f'formal-{n}')],check=False,log=EVIDENCE/f'formal-{n}-command.log')
        assert code==0,'FORMAL_4X4_FAILED'
    state['status']='JOURNEY_4X4';save()
    for n in (1,2):
        code=run([PYTHON,'ci/journey_latency/measure.py','--instances-per-operation','4','--pool-per-instance','4','--application-tree','6570b66bc977f89c0311d67bdc6b721cd70d4e09','--out',str(EVIDENCE/f'journey-{n}')],check=False,log=EVIDENCE/f'journey-{n}-command.log')
        assert code==0,'JOURNEY_4X4_FAILED'
    run([PYTHON,'ci/capacity_4x4/verify.py',str(EVIDENCE),HEAD],log=EVIDENCE/'verify.log')
    state['status']='PASS_4X4_SYNTHETIC_SCOPE'
except Exception as exc:
    state.update(status='FAILED_OR_INCOMPLETE',error_type=type(exc).__name__);raise
finally:
    state['elapsed_seconds']=time.monotonic()-START;save()
    if pg:subprocess.run(['docker','stop','go-capacity-4x4-pg'],cwd=ROOT,timeout=30,check=False)
    try:
        dest=ROOT/'ci/capacity_4x4/evidence/20260930';dest.mkdir(parents=True,exist_ok=False);archive=dest/'raw.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            launch=ROOT/'capacity-4x4-launch.log'
            if launch.exists():z.write(launch,launch.name)
            for folder in (OUT,EVIDENCE):
                for f in folder.rglob('*'):
                    if f.is_file():z.write(f,f.relative_to(ROOT))
        (dest/'SHA256.json').write_text(json.dumps({'raw.zip':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2)+'\n');(dest/'status.json').write_text(json.dumps(state,indent=2)+'\n')
        summary=EVIDENCE/'verified-summary.json'
        if summary.exists():(dest/'verified-summary.json').write_bytes(summary.read_bytes())
        subprocess.run(['git','add','ci/capacity_4x4/evidence/20260930'],cwd=ROOT,check=True,timeout=30)
        subprocess.run(['git','commit','-m','test: archive fixed four-by-four capacity validation'],cwd=ROOT,check=True,timeout=30)
        subprocess.run(['git','push','origin','HEAD:refs/heads/'+BRANCH],cwd=ROOT,check=True,timeout=120)
    finally:subprocess.run(['gh','api','-X','POST','/user/codespaces/'+NAME+'/stop'],cwd=ROOT,timeout=60,check=False)
