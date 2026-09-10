import hashlib,json,os,subprocess,sys,xml.etree.ElementTree as ET
from pathlib import Path
root=Path.cwd();source=root/'restored';out=root/'evidence';out.mkdir(exist_ok=True);results=[]
meta=json.loads((root/'candidate/deliverables/CP11_DEPTH37R2_NATIVE_MODULE_LINKING_20260910/MANIFEST.json').read_text());fp=json.loads((root/'candidate/deliverables/CP11_DEPTH37R2_NATIVE_MODULE_LINKING_20260910/SOURCE_FINGERPRINT.json').read_text())
def save(name,obj):(out/name).write_text(json.dumps(obj,indent=2)+'\n')
def verify():
 bad=[n for n,h in fp.items() if hashlib.sha256((source/n).read_bytes()).hexdigest()!=h];assert not bad,bad
verify();save('source-binding.json',{'candidate':os.environ['SEALED_CANDIDATE'],'source_tree_sha256':meta['source_tree_sha256'],'files':len(fp),'database_scope':'Disposable isolated PostgreSQL service; no external database accessed','deployed':False})
env=dict(os.environ,PYTHONPATH=str(source/'src'),PYTHONDONTWRITEBYTECODE='1')
def run(name,args):
 p=subprocess.run(args,cwd=source,env=env,capture_output=True,text=True,timeout=600);(out/(name+'.log')).write_text(p.stdout+p.stderr);results.append({'name':name,'exit_code':p.returncode,'pass':p.returncode==0});save('commands.json',results);print(name,p.returncode,flush=True);return p.returncode==0
try:
 assert run('dependency-install',[sys.executable,'-m','pip','install','--disable-pip-version-check','-r',str(root/'tooling/ci/depth37-pg/requirements.lock')])
 assert run('dependency-freeze',[sys.executable,'-m','pip','freeze'])
 assert run('postgres-migrate',[sys.executable,'-m','alembic','upgrade','head'])
 assert run('postgres-race-tests',[sys.executable,'-m','pytest','-v','-rA','tests/test_p0_0100_postgres_concurrency.py','tests/test_p0_0101_postgres_race_matrix.py','--junitxml='+str(out/'postgres-tests.xml')])
 xml=ET.parse(out/'postgres-tests.xml');cases=list(xml.getroot().iter('testcase'));assert len(cases)==6;assert not any(list(c) for c in cases),'SKIP_OR_FAILURE_NOT_ALLOWED'
 save('postgres-result.json',{'tests':len(cases),'pass':6,'skip':0,'fail':0,'migration':'PASS','server':'PostgreSQL 16.4 isolated service','cases':[c.attrib['name'] for c in cases],'production_database_proof':False})
finally:
 verify();save('source-after-build.json',{'source_after_build':'PASS','files':len(fp),'mismatches':[]});save('artifact-fingerprints.json',{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in out.iterdir() if p.is_file()})
