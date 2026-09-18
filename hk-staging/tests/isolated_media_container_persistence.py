"""Opt-in isolated local Docker regression; never targets an existing container/project.
Requires preloaded compatible Python images. No pull, compose, network, service restart.
Not a formal HK E2E or authorization to operate on HK.
"""
import argparse,hashlib,json,os,pathlib,re,subprocess,tempfile,uuid
IMAGE=re.compile(r'^sha256:[0-9a-f]{64}$')
WRITE="""import base64,hashlib,json,pathlib
from go_hotel.services.media_index import MediaIndex
p=pathlib.Path('/test-cache');(p/'files').mkdir()
b=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII=')
h=hashlib.sha256(b).hexdigest();name=h+'.png';index=MediaIndex(p)
record={'asset_id':'isolated-persistence-proof','hotel_id':'isolated-not-a-real-hotel','cache_file':name,'sha256':h,'rights':'RIGHTS_UNKNOWN','publishable':False,'rights_history':[]}
index.insert(record,lambda:(p/'files'/name).write_bytes(b))
assert index.snapshot()['_revision']==1
print(h)
"""
READ="""import hashlib,pathlib,sqlite3
from go_hotel.services.media_index import MediaIndex
p=pathlib.Path('/test-cache')
index=MediaIndex(p);r=index.get('isolated-persistence-proof')
assert r['rights']=='RIGHTS_UNKNOWN' and r['publishable'] is False and r['revision']==1
assert index.snapshot()['_revision']==1
assert hashlib.sha256((p/'files'/r['cache_file']).read_bytes()).hexdigest()==r['sha256']
with sqlite3.connect((p/'index.sqlite3').as_uri()+'?mode=ro',uri=True) as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print(r['sha256'])
"""
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--run-isolated-docker',action='store_true',required=True);parser.add_argument('--image',required=True);parser.add_argument('--rollback-image',required=True);args=parser.parse_args()
 if not IMAGE.fullmatch(args.image) or not IMAGE.fullmatch(args.rollback_image):raise SystemExit('LOCAL_IMAGE_IDS_REQUIRED')
 outputs=[]
 with tempfile.TemporaryDirectory(prefix='go-media-topology-isolated-') as d:
  root=pathlib.Path(d);before=root.stat()
  for phase,image,code in [('seed',args.image,WRITE),('recreate',args.image,READ),('image_rollback',args.rollback_image,READ)]:
   name='go-media-isolated-'+uuid.uuid4().hex
   argv=['docker','run','--rm','--pull=never','--network=none','--user',str(os.getuid())+':'+str(os.getgid()),'--read-only','--pids-limit','64','--memory','128m','--cpus','0.5','--cap-drop=ALL','--security-opt=no-new-privileges','--label','go.media.topology.test=isolated','--name',name,'--mount','type=bind,source='+d+',target=/test-cache','--env','PYTHONPATH=/workspace/src','--env','PYTHONDONTWRITEBYTECODE=1','--workdir','/workspace','--entrypoint','python',image,'-B','-c',code]
   try:r=subprocess.run(argv,check=True,capture_output=True,text=True,timeout=60)
   except BaseException:
    # Cleanup is restricted to this generated test container, never broad prune.
    subprocess.run(['docker','rm','-f',name],capture_output=True,text=True,timeout=15);raise
   outputs.append({'phase':phase,'image':image,'sha256':r.stdout.strip()})
   after=root.stat();assert (after.st_dev,after.st_ino)==(before.st_dev,before.st_ino)
  assert len({x['sha256'] for x in outputs})==1
 print(json.dumps({'status':'PASS','isolated':True,'host_runtime_targeted':False,'phases':outputs}))
if __name__=='__main__':main()
