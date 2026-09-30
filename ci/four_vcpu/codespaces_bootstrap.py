"""One bounded isolated Codespaces experiment; synthetic local PostgreSQL only."""
from pathlib import Path
import json, os, signal, subprocess, sys, time, zipfile, hashlib, runpy
ROOT = Path('/workspaces/GO')
HEAD = '40d59f85bc667754707c2d40ca1eedbf95e239d4'
CANDIDATE = '4048cbe64d0551130618d5d028204f770143aab7'
BASELINE = '059ebec3ab379099ef258effc3ab0a9833d52c35'
PYTHON = '/tmp/go-capacity-venv/bin/python'
OUT = ROOT / 'codespaces-capacity-evidence'
OUT.mkdir(exist_ok=False)
START = time.monotonic()
DEADLINE = START + 5400
ENV = dict(os.environ, GO_MULTI_DATABASE_URL='postgresql+psycopg://go_ci:isolated_multi_only@127.0.0.1:5432/go_c11_isolated',
           APP_ENV='test', MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false', TRAVEL_INTELLIGENCE_ENABLED='false', PYTHONUNBUFFERED='1')
state = {'source_head': HEAD, 'candidate': CANDIDATE, 'baseline': BASELINE, 'status': 'SETUP',
         'original_2vcpu_acceptance': 'FAIL', 'maximum_seconds': 5400, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

def save():
    (OUT / 'status.json').write_text(json.dumps(state, indent=2) + '\n')

def run(args, *, check=True):
    print('RUN', args[0], args[1:3], flush=True)
    process = subprocess.Popen(args, cwd=ROOT, env=ENV, start_new_session=True)
    try:
        code = process.wait(timeout=max(1, DEADLINE-time.monotonic()))
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait()
        raise
    if check and code: raise subprocess.CalledProcessError(code, args)
    return code

pg_started = False
try:
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==HEAD
    hardware = runpy.run_path(str(ROOT/'ci/four_vcpu/run.py'))['capacity']()
    (OUT/'hardware-preflight.json').write_text(json.dumps(hardware,indent=2)+'\n')
    run(['git','fetch','origin',CANDIDATE,BASELINE])
    run([PYTHON,'-m','pip','install','-e','./application[dev]','PyYAML'])
    (OUT/'packages.txt').write_text(subprocess.check_output([PYTHON,'-m','pip','freeze'],text=True))
    run([PYTHON,'-m','pytest','ci/four_vcpu/test_run.py','ci/test_cpu_candidate.py','ci/journey_latency/test_measure.py','ci/journey_latency/test_verify.py','-q','--junitxml='+str(OUT/'harness.xml')])
    run(['docker','run','--name','go-capacity-pg','--rm','-d','-e','POSTGRES_USER=go_ci','-e','POSTGRES_PASSWORD=isolated_multi_only','-e','POSTGRES_DB=go_c11_isolated','-p','127.0.0.1:5432:5432','postgres:18.4'])
    pg_started = True
    for _ in range(60):
        if run(['docker','exec','go-capacity-pg','pg_isready','-U','go_ci','-d','go_c11_isolated'],check=False)==0:break
        time.sleep(1)
    else:raise RuntimeError('POSTGRES_NOT_READY')
    state['status']='QUALIFICATION_THEN_ABBA'; save()
    state['experiment_exit_code']=run([PYTHON,'ci/four_vcpu/run.py'],check=False)
    summary=ROOT/'cpu-candidate-evidence/summary.json'
    state['status']=json.loads(summary.read_text())['status'] if summary.exists() else 'FAILED_BEFORE_COMPARISON'
except Exception as exc:
    state.update(status='FAILED',error_type=type(exc).__name__)
    raise
finally:
    state['elapsed_seconds']=time.monotonic()-START
    save()
    if pg_started:subprocess.run(['docker','stop','go-capacity-pg'],cwd=ROOT,timeout=30,check=False)
    archive=ROOT/'codespaces-four-vcpu.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for folder in [OUT,ROOT/'four-vcpu-qualification',ROOT/'cpu-candidate-evidence']:
            if folder.exists():
                for f in folder.rglob('*'):
                    if f.is_file():z.write(f,f.relative_to(ROOT))
    print('FINAL',json.dumps(state),flush=True)
    print('ARCHIVE_SHA256',hashlib.sha256(archive.read_bytes()).hexdigest(),flush=True)
