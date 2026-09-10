"""Inspect startup of an already fingerprinted simulator artifact; do not rebuild."""
import hashlib,json,os,signal,subprocess,tarfile,time
from pathlib import Path
root=Path.cwd();evidence=root/'evidence';evidence.mkdir(exist_ok=True);original=root/'original'
def save(name,value):(evidence/name).write_text(json.dumps(value,indent=2)+'\n')
binding=json.loads((original/'source-binding.json').read_text())
assert binding['candidate']=='cb81f9ea32c88c4d349ed43d48c5b9d7027615ab'
assert binding['source_tree_sha256']=='2b77c929a361e34601e8e40cf97b2ba3b14e2407d6eef5e3926132c488620641'
archive=original/'ios-simulator-app.tar.gz';digest=hashlib.sha256(archive.read_bytes()).hexdigest()
assert digest=='38fc615bd161608335f1378d3829ad2675e0a8000dc7a98bbddbb703baadcc9f'
save('artifact-binding.json',dict(binding,build_run=34469458736,artifact_sha256=digest,rebuilt=False))
def run(name,args,timeout=180):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    (evidence/(name+'.log')).write_text(p.stdout+p.stderr)
    print(name,p.returncode,flush=True)
    if p.returncode:raise RuntimeError(name+' failed')
    return p.stdout
with tarfile.open(archive) as t:t.extractall(root/'app',filter='data')
app=list((root/'app').glob('*.app'))[0]
run('xcode-version',['xcodebuild','-version'])
devices=json.loads(run('available-devices',['xcrun','simctl','list','devices','available','-j']))['devices']
device=next(d for ds in devices.values() for d in ds if d['name'].startswith('iPhone'))
udid=device['udid']
if device['state']!='Booted':run('boot',['xcrun','simctl','boot',udid])
run('boot-ready',['xcrun','simctl','bootstatus',udid,'-b'])
run('install',['xcrun','simctl','install',udid,str(app)])
with (evidence/'app-console.log').open('w') as log:
    proc=subprocess.Popen(['xcrun','simctl','launch','--terminate-running-process','--console',udid,'travel.go.consumer'],stdout=log,stderr=subprocess.STDOUT,text=True)
    samples=[]
    try:
        start=time.monotonic()
        for second in (15,30,60):
            remaining=second-(time.monotonic()-start)
            if remaining>0:time.sleep(remaining)
            run('screen-'+str(second),['xcrun','simctl','io',udid,'screenshot',str(evidence/f'screen-{second}.png')])
            listing=run('processes-'+str(second),['xcrun','simctl','spawn',udid,'launchctl','list'])
            rows=[line for line in listing.splitlines() if 'travel.go.consumer' in line]
            samples.append({'elapsed_seconds':second,'console_exit_code':proc.poll(),'application_process_rows':rows})
            save('startup-samples.json',samples)
        run('application-unified-log',['xcrun','simctl','spawn',udid,'log','show','--last','3m','--style','compact','--predicate','process == "GO"'])
        save('device-smoke.json',{'device':device['name'],'samples':samples,'visual_review':'REQUIRED','physical_device':'NOT_RUN','backend_journeys':'NOT_RUN','rebuilt':False})
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
save('artifact-fingerprints.json',{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in evidence.iterdir() if p.is_file()})
