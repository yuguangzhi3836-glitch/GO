import hashlib,json,os,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
root=Path('/workspace/scratch/f016e17148d8/go-depth30-restored')
package=Path('/workspace/scratch/f016e17148d8/go-depth30/deliverables/CP11_DEPTH30_NATIVE_PAYMENT_20260909')
e=package/'evidence/local';e.mkdir(parents=True,exist_ok=True)
python='/workspace/scratch/af00ce8c656d/go-depth28-restore-manual-check/gate_runtime/python/bin/python'
fp=json.loads((package/'SOURCE_FINGERPRINT.json').read_text())
tree=hashlib.sha256(''.join(f'{k}\0{v}\n' for k,v in sorted(fp.items())).encode()).hexdigest()
def verify():
    for p,h in fp.items():assert hashlib.sha256((root/p).read_bytes()).hexdigest()==h,p
verify()
tests=['test_depth29_trip_reentry','test_depth27_session_isolation','test_consumer_unified_lifecycle','test_master03_closure','test_sprint3e_unified_trips','test_depth05_money_retries','test_depth19_travel_facts','test_depth20_api_fulfillment','test_depth21_refund_recovery','test_depth22_rail_resolution','test_depth23_capacity','test_depth24_expiry','test_depth30_native_api_contract']
commands=[('backend',[python,'-m','pytest',*[f'tests/{t}.py' for t in tests],'--junitxml='+str(e/'backend.xml')]),
 ('frontend',['node','--experimental-strip-types','--test','--test-reporter=spec','--test-reporter-destination='+str(e/'frontend.log'),'--test-reporter=junit','--test-reporter-destination='+str(e/'frontend.xml'),*[str(p.relative_to(root)) for p in sorted((root/'tests_frontend').glob('*.test.mjs'))]])]
record={'source_tree_sha256':tree,'verified_files':len(fp),'environment':'Local isolated restored source; FastAPI SQLite TestClient, Node VM/pure helpers and stdio API bridge','python':subprocess.check_output([python,'--version'],text=True).strip(),'node':subprocess.check_output(['node','--version'],text=True).strip(),'runs':[],'browser':False,'native_build':False,'device':False,'hong_kong':False,'independent_ci':False,'release_gate':'HOLD'}
for name,command in commands:
    run={'name':name,'command':command,'started_at_utc':datetime.now(timezone.utc).isoformat()}
    with (e/(name+'-runner.log')).open('w') as output:
        p=subprocess.run(command,cwd=root,stdout=output,stderr=subprocess.STDOUT,timeout=300)
    run.update(exit_code=p.returncode,finished_at_utc=datetime.now(timezone.utc).isoformat());record['runs'].append(run)
    print(json.dumps(run),flush=True)
    if p.returncode:print((e/(name+'-runner.log')).read_text()[-5000:],flush=True)
verify();record['source_verified_after_tests']=True
(e/'LOCAL_RUN_RECORD.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
assert all(r['exit_code']==0 for r in record['runs'])
