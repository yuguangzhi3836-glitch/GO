"""Bind the current DEPTH48 source, then run cumulative isolated browser users."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = '--preflight' in sys.argv
OUT = ROOT / ('load1000-preflight' if PREFLIGHT else 'load1000-evidence')
COMMIT = '286e294d92df4b7d1c0073116a8e628734abec6c'
TREE = '3025b2b6b36ea9211da561a4631f304216de9d90'
SHA256 = 'd90a9e26c3a64b98009aaf170056f4b3acfa6acebd41baaed276b7baf17c6925'

def save(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2)+'\n')

def source_check():
    paths=subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD','application'],cwd=ROOT,text=True).splitlines()
    fp={p[len('application/'):]:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    actual=hashlib.sha256(''.join(f'{p}\0{h}\n' for p,h in sorted(fp.items())).encode()).hexdigest()
    assert len(fp)==1325 and actual==SHA256, 'CANONICAL_SOURCE_BYTES_MISMATCH'
    assert subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip()==TREE
    assert set(fp)=={p.relative_to(ROOT/'application').as_posix() for p in (ROOT/'application').rglob('*') if p.is_file()}, 'UNTRACKED_SOURCE_FILES'
    pointer=json.loads((ROOT/'docs/canonical-baseline/CURRENT_HK_RUNTIME.json').read_text())
    assert pointer['runtime_generation']=='DEPTH48'
    assert pointer['canonical_runtime_identity']['canonical_runtime_application_tree']==TREE
    assert pointer['canonical_runtime_identity']['canonical_runtime_source_sha256']==SHA256
    return fp

def main():
    OUT.mkdir(exist_ok=True)
    fp=source_check()
    session=str(uuid.uuid4())
    binding={'candidate_commit':COMMIT,'commit':COMMIT,'application_git_tree':TREE,'source_tree_sha256':SHA256,
        'verified_source_files':len(fp),'runtime_generation':'DEPTH48','session_id':session,
        'harness_commit':os.environ.get('GITHUB_SHA'),'run_id':os.environ.get('GITHUB_RUN_ID'),
        'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'job':os.environ.get('GITHUB_JOB'),
        'os':platform.platform(),'hostname':platform.node(),'python':sys.version,
        'started_at':datetime.now(timezone.utc).isoformat(),'scope':'ISOLATED_SYNTHETIC_ONLY',
        'target_runtime_image_reference':'sha256:57beafa250f42eb1319ae561e0b79f432bb80d7171592392303a31446cd8ac6c',
        'image_note':'Reference identity only. Test executes source in isolated Python, not the deployed HK image.',
        'database':'NEW_PRIVATE_SQLITE','hong_kong':'NOT_ACCESSED','production':'NOT_ACCESSED'}
    save('source-binding.json',binding);save('source-fingerprint.json',fp)
    command=[sys.executable,'-B',str(ROOT/'application/scripts/acceptance_runtime.py'),
        '--source',str(ROOT/'application'),'--fingerprint',str(OUT/'source-fingerprint.json'),
        '--expected-tree',SHA256,'--state','STATE','--port','4186','--journey-suppliers','--hotel-price-scenarios']
    result={'result':'HOLD','browser':'NOT_STARTED','ledger':'NOT_STARTED'}
    with tempfile.TemporaryDirectory(prefix='go-depth48-load1000-') as temp:
        state=Path(temp)/'state';command[command.index('STATE')]=str(state)
        env={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL','TZ','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_JOB','RUNNER_OS'}}
        env['PYTHONDONTWRITEBYTECODE']='1'
        with (OUT/'runtime.log').open('w') as logfile:
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=logfile,stderr=subprocess.STDOUT)
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(180):
                    if process.poll() is not None:raise RuntimeError('ISOLATED_RUNTIME_STARTUP_FAILED')
                    try:
                        live=json.load(opener.open('http://127.0.0.1:4186/__acceptance/binding',timeout=2))
                        assert live['source_tree_sha256']==SHA256;break
                    except (OSError,ValueError):time.sleep(1)
                else:raise RuntimeError('ISOLATED_RUNTIME_STARTUP_TIMEOUT')
                shutil.copyfile(state/'runtime-binding.json',OUT/'runtime-binding.json')
                env.update(GO_JOURNEY_STATE=str(state),GO_LOAD_EVIDENCE=str(OUT),GO_JOURNEY_EVIDENCE=str(OUT))
                with (OUT/'browser.log').open('w') as log:
                    browser=subprocess.run(['node',str(ROOT/('ci/journey-v2/browser.mjs' if PREFLIGHT else 'ci/load1000/browser.mjs'))],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                result['browser_exit']=browser.returncode
                report=json.loads((OUT/'browser-results.json').read_text())
                result['browser']=report['result']
                if report['order_checks']:
                    sys.path.insert(0,str(ROOT/('ci/journey-v2' if PREFLIGHT else 'ci/load1000')))
                    from ledger import audit
                    audit(state,OUT)
                    if PREFLIGHT:
                        subprocess.run([sys.executable,'-B',str(ROOT/'ci/journey-v2/hotel-ledger.py'),str(state),str(OUT)],check=True,cwd=ROOT,env=env)
                    result['ledger']='PASS'
                result['result']='SCOPED_PASS' if browser.returncode==0 and result['ledger']=='PASS' else 'HOLD'
            except Exception as error:
                result['error']=str(error)
            finally:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.kill();process.wait()
    result['source_unchanged_after']=source_check()==fp
    save('result.json',dict(binding,**result,finished_at=datetime.now(timezone.utc).isoformat()))
    save('SHA256.json',{str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file() and p.name!='SHA256.json'})
    print(json.dumps(result),flush=True)
    return 0 if result['result']=='SCOPED_PASS' else 1

if __name__=='__main__':sys.exit(main())
