import importlib.util,json,pathlib,sqlite3,subprocess,sys,tempfile,unittest,hashlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('media_topology',ROOT/'source/executor/runtime/media_topology_runtime.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
CONTRACT='a'*64
class MediaTopology(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.parent=pathlib.Path(self.tmp.name);self.original=m.CACHE;m.CACHE=str(self.parent/'cache')
 def tearDown(self):m.CACHE=self.original;self.tmp.cleanup()
 def inventory(self):
  return [{'Image':'sha256:'+'b'*64,'Config':{'Labels':{'com.docker.compose.service':s,'com.docker.compose.project':'go-822-staging'},'Env':['GO_MEDIA_CACHE_DIR='+m.CACHE]},'Mounts':[{'Type':'bind','Source':m.CACHE,'Destination':m.CACHE,'RW':True}]} for s in m.SERVICES]
 def test_bootstrap_exclusive_and_identity(self):
  first=m.bootstrap_new_cache(CONTRACT);self.assertEqual(first,m.storage_identity(CONTRACT))
  with self.assertRaisesRegex(m.Reject,'EXISTS'):m.bootstrap_new_cache(CONTRACT)
 def test_existing_target_no_overwrite(self):
  p=pathlib.Path(m.CACHE);p.mkdir();(p/'keep').write_text('preserve')
  with self.assertRaisesRegex(m.Reject,'EXISTS'):m.bootstrap_new_cache(CONTRACT)
  self.assertEqual((p/'keep').read_text(),'preserve')
 def test_symlink_leaf_or_parent_rejected(self):
  path=pathlib.Path(m.CACHE);path.symlink_to(self.parent/'missing')
  with self.assertRaises(m.Reject):m.bootstrap_new_cache(CONTRACT)
  path.unlink();(self.parent/'real').mkdir();(self.parent/'link').symlink_to(self.parent/'real',target_is_directory=True);m.CACHE=str(self.parent/'link'/'cache')
  with self.assertRaises(OSError):m.bootstrap_new_cache(CONTRACT)
 def test_marker_drift_reject(self):
  m.bootstrap_new_cache(CONTRACT)
  with self.assertRaisesRegex(m.Reject,'DRIFT'):m.storage_identity('b'*64)
 def test_recreated_and_rollback_processes_reopen_same_index_and_bytes(self):
  identity=m.bootstrap_new_cache(CONTRACT);root=pathlib.Path(m.CACHE);(root/'files').mkdir();payload=b'immutable media bytes';digest=hashlib.sha256(payload).hexdigest();(root/'files'/digest).write_bytes(payload)
  with sqlite3.connect(root/'index.sqlite3') as db:db.execute('CREATE TABLE assets (id TEXT PRIMARY KEY, sha TEXT)');db.execute('INSERT INTO assets VALUES (?,?)',('asset',digest))
  code="import hashlib,pathlib,sqlite3,sys; p=pathlib.Path(sys.argv[1]); db=sqlite3.connect((p/'index.sqlite3').as_uri()+'?mode=ro',uri=True); s=db.execute('SELECT sha FROM assets WHERE id=?',('asset',)).fetchone()[0]; assert hashlib.sha256((p/'files'/s).read_bytes()).hexdigest()==s; print(s)"
  # Separate processes model image-process replacement; actual Docker E2E is separate.
  for phase in ['recreate','image_rollback']:
   r=subprocess.run([sys.executable,'-B','-c',code,m.CACHE],capture_output=True,text=True,check=True);self.assertEqual(r.stdout.strip(),digest)
   self.assertEqual(m.storage_identity(CONTRACT),identity)
 def test_fixed_eight_mounts_and_environment(self):
  rows=self.inventory();self.assertEqual(m.validate_runtime_mounts(rows,'sha256:'+'b'*64)['service_count'],8)
  for changes in ['missing','wrong_path','readonly','extra','shadow','env']:
   copy=json.loads(json.dumps(rows))
   if changes=='missing':copy[0]['Mounts']=[]
   elif changes=='wrong_path':copy[0]['Mounts'][0]['Source']='/tmp/arbitrary'
   elif changes=='readonly':copy[0]['Mounts'][0]['RW']=False
   elif changes=='extra':copy.append(copy[0])
   elif changes=='shadow':copy[0]['Mounts'].append({'Type':'bind','Source':'/tmp/other','Destination':m.CACHE+'/files','RW':True})
   else:copy[0]['Config']['Env']=['GO_MEDIA_CACHE_DIR=relative']
   with self.assertRaises(m.Reject):m.validate_runtime_mounts(copy,'sha256:'+'b'*64)
 def test_rollback_binding_and_non_targets_unchanged(self):
  identity=m.bootstrap_new_cache(CONTRACT);record={'topology_id':m.TOPOLOGY_ID,'topology_version':2,'topology_sha256':m.TOPOLOGY_SHA,'media_storage_identity':identity};m.require_record_binding(record,identity)
  protected={'redis':'r1','caddy':'c1'};m.require_preserved(identity,m.storage_identity(CONTRACT),protected,dict(protected))
  with self.assertRaisesRegex(m.Reject,'NON_TARGET'):m.require_preserved(identity,identity,protected,{'redis':'r2','caddy':'c1'})
  with self.assertRaisesRegex(m.Reject,'RECORD'):m.require_record_binding({'topology_version':1},identity)
 def test_machine_contract_and_compose_fixed_scope(self):
  repo=ROOT.parents[0];contract=json.loads((repo/'docs/control-plane/hk-staging/DEPLOYMENT_TOPOLOGY_V2.json').read_text());self.assertEqual({x['name'] for x in contract['business_services']},set(m.SERVICES));self.assertEqual(contract['protected_non_targets'],['redis','caddy']);self.assertEqual(contract['topology_version'],2)
  text=(repo/'deploy/hk-staging/docker-compose.business-runtime-v2.yml').read_text();self.assertEqual(text.count('create_host_path: false'),8);self.assertEqual(text.count('GO_MEDIA_CACHE_DIR: /var/lib/go-hotel/media-cache'),8);self.assertNotIn('  redis:',text);self.assertNotIn('  caddy:',text)
if __name__=='__main__':unittest.main()
