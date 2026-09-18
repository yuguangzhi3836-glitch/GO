import copy,hashlib,importlib.util,json,pathlib,sys,tempfile,unittest
from contextlib import ExitStack
from unittest.mock import Mock,patch
ROOT=pathlib.Path(__file__).resolve().parents[2];RT=ROOT/'hk-staging/source/executor/runtime';CC=ROOT/'control-plane/boss-deploy-request-v1';sys.path[:0]=[str(RT),str(CC)]
import media_topology_runtime as media
import hk_candidate_contract as contracts
import deploy_runtime as deploy
import collector_runtime as collector
import rollback_runtime as rollback
import same_revision_runtime as same_runtime

def contract():
 return {'schema':contracts.TOPOLOGY_SCHEMA,'environment':contracts.ENVIRONMENT,'profile':contracts.PROFILE,'candidate':{'repository':contracts.REPOSITORY,'source_commit':'a'*40,'application_git_tree':'b'*40,'source_tree_sha256':'c'*64,'package_sha256':'d'*64,'image_id':'sha256:'+'e'*64},'expected_current_image_id':'sha256:'+'f'*64,'baseline_revision':'0574_fixture','target_revision':'0574_fixture','migration_required':False,'migration_source_digest':'1'*64,'baseline_migration_source_digest':'1'*64,'test_pr_evidence_sha256':'2'*64,'topology':{'topology_id':media.TOPOLOGY_ID,'topology_version':2,'topology_sha256':media.TOPOLOGY_SHA,'baseline_topology_version':1,'media_rollback_compatible':True}}
def inventory(image,mounted):
 return [{'Id':'id'+str(i),'Image':image,'Config':{'Labels':{'com.docker.compose.project':'go-822-staging','com.docker.compose.service':s},'Env':['GO_MEDIA_CACHE_DIR='+media.CACHE] if mounted else []},'Mounts':[{'Type':'bind','Source':media.CACHE,'Destination':media.CACHE,'RW':True}] if mounted else []} for i,s in enumerate(media.SERVICES)]
class Hooks(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=media.CACHE;media.CACHE=str(pathlib.Path(self.tmp.name)/'cache');self.identity=media.bootstrap_new_cache(media.TOPOLOGY_SHA);self.c=contract();self.install={'media_storage_identity':self.identity,'baseline_image_id':self.c['expected_current_image_id'],'runtime_profile':{'revision':self.c['baseline_revision'],'workdir':'/workspace','migration_source_digest':'1'*64}}
 def tearDown(self):media.CACHE=self.old;self.tmp.cleanup()
 def test_strict_v3_and_legacy_contract_retained(self):
  contracts.validate(self.c,contracts.digest(self.c));self.assertFalse(contracts.migration_required(self.c))
  old=copy.deepcopy(self.c);old.pop('topology');old['schema']=contracts.SAME_SCHEMA;contracts.validate(old)
  for key,value in [('topology_version',3),('topology_sha256','0'*64),('media_rollback_compatible',False),('baseline_topology_version',True),('command','bad')]:
   c=copy.deepcopy(self.c);c['topology'][key]=value
   with self.assertRaises(contracts.Reject):contracts.validate(c)
 def test_missing_installation_and_legacy_downgrade_refused(self):
  with patch.object(media,'installed',return_value=None),self.assertRaisesRegex(media.Reject,'CHANGE_REQUIRED'):media.predeploy(self.c,[],self.c['expected_current_image_id'])
  with patch.object(media,'installed',return_value=self.install),self.assertRaisesRegex(media.Reject,'CONTRACT_REQUIRED'):media.predeploy(None,[],self.c['expected_current_image_id'])
 def test_first_transition_verify_only_before_durable_start(self):
  old=inventory(self.c['expected_current_image_id'],False)
  with patch.object(media,'installed',return_value=self.install):
   self.assertEqual(media.verify(old,self.c['expected_current_image_id'],True)['media_persistence'],'NOT_ACTIVE')
   media.begin(self.identity,self.c,{'deploy_record_sha256':'3'*64})
   with self.assertRaises(media.Reject):media.verify(old,self.c['expected_current_image_id'],True)
   with self.assertRaisesRegex(media.Reject,'BASELINE_DRIFT'):media.predeploy(self.c,old,self.c['expected_current_image_id'])
 def test_actual_deploy_hooks_bind_durable_record_and_post_mounts(self):
  before=inventory(self.c['expected_current_image_id'],False);after=inventory(self.c['candidate']['image_id'],True);record=pathlib.Path(self.tmp.name)/'record.json';override=pathlib.Path(self.tmp.name)/'override.yml';override.write_text('test')
  written=[];calls=[]
  def persist(data):written.append(data);record.write_text(json.dumps(data));return {'record_path':str(record),'deploy_record_schema_version':'2','deploy_record_id':'5'*64,'deploy_record_sha256':'6'*64}
  with ExitStack() as stack:
   for target,name,value in [(media,'installed',self.install),(deploy,'_precheck',before),(deploy,'_override',str(override)),(deploy,'_protected_non_target_snapshot',([], 'protected')),(deploy,'_non_target_snapshot','non-target'),(deploy,'_repo_digest',None),(deploy,'_ids',['id']*8),(deploy,'_inspect',after)]:stack.enter_context(patch.object(target,name,return_value=value))
   stack.enter_context(patch.object(deploy,'_atomic_record',side_effect=persist));stack.enter_context(patch.object(deploy,'_run',side_effect=lambda r,a,*extra:calls.append(a)));stack.enter_context(patch.object(deploy,'_wait_for_api_health'))
   col=Mock();col._collect_verify.return_value={'target_service_count':8};same=same_runtime;binding={'task_id':'signed-task','nonce':'abc','authority':'GO-COMMAND-CENTER','canonical_sha256':'7'*64}
   runner=Mock();runner.run.side_effect=lambda argv: Mock(returncode=0,stdout=json.dumps({'source':'PASS','revision':self.c['target_revision'],'graph_sha256':self.c['migration_source_digest'],'migration_required':False}) if argv[1]=='run' else '')
   result=deploy.run_deploy('release',self.c['candidate']['image_id'],self.c['candidate']['package_sha256'],self.c['expected_current_image_id'],binding,runner,col,Mock(),contract=self.c,contract_sha=contracts.digest(self.c),same_revision=same,topology=media)
  self.assertEqual(result['media_persistence'],'PASS');self.assertEqual(written[0]['media_storage_identity'],self.identity);self.assertEqual(written[0]['topology_version'],2);self.assertIn(media.COMPOSE,calls[0]);self.assertEqual(calls[0][-8:],list(media.SERVICES));self.assertTrue(media.transition_started());self.assertIs(col._collect_verify.call_args.kwargs['topology'],media)
 def test_record_cannot_rollback_without_same_storage(self):
  record={**media.record_fields(self.identity,self.c)};media.require_record_binding(record,self.identity)
  bad={**self.identity,'inode':0}
  with self.assertRaises(media.Reject):media.require_record_binding(record,bad)
 def test_collector_collects_real_fixed_eight_mount_inventory(self):
  image=self.c['candidate']['image_id'];rows=inventory(image,True);runner=Mock();runner.run.side_effect=[Mock(returncode=0,stdout=x['Id']) for x in rows]+[Mock(returncode=0,stdout=json.dumps(rows))]
  with patch.object(media,'installed',return_value=self.install),patch.object(collector,'sha256_file',side_effect=['compose','env']),patch.object(collector,'collect_api',return_value={}),patch.object(collector,'workers',return_value={'process_liveness_pass':7}),patch.object(collector,'_collect_alembic_for_api',return_value={'current_revision':'x','head_revision':'x'}):
   inputs=Mock(compose_sha256='compose',env_sha256='env');result=collector._collect_verify(runner,image,image,inputs,contract=self.c,topology=media)
  self.assertEqual(result['media_persistence'],'PASS');self.assertEqual(result['topology_version'],2);self.assertEqual(len(runner.run.call_args_list),9)
 def test_executor_preserves_pending_metadata_for_command_center(self):
  import importlib.machinery
  import go_deploy_request as gate
  loader=importlib.machinery.SourceFileLoader('verify_launcher_proof',str(ROOT/'hk-staging/source/executor/go-hk-deployctl'))
  spec=importlib.util.spec_from_loader(loader.name,loader);launcher=importlib.util.module_from_spec(spec);loader.exec_module(launcher)
  image=self.c['expected_current_image_id'];rows=inventory(image,False);runner=Mock()
  runner.run.side_effect=[Mock(returncode=0,stdout=x['Id']) for x in rows]+[Mock(returncode=0,stdout=json.dumps(rows))]
  with ExitStack() as stack:
   for target,name,value in [(media,'installed',self.install),(launcher,'_load_collector',collector),(launcher,'_topology',media),(launcher,'_contract',None),(collector,'collect_api',{}),(collector,'workers',{'process_liveness_pass':7}),(collector,'_collect_alembic_for_api',{'current_revision':'x','head_revision':'x'})]:
    stack.enter_context(patch.object(target,name,return_value=value))
   stack.enter_context(patch.object(collector,'sha256_file',side_effect=['compose','env']))
   out,rc=launcher._verify('release',image,image,runner,Mock(compose_sha256='compose',env_sha256='env'))
  self.assertEqual(rc,0);self.assertEqual(out['gate_results']['topology_pending_version'],2)
  metadata=gate.validate_topology_evidence(out['gate_results'],gate.VERIFY_ACTION)
  self.assertTrue(all(v=='PASS' or v is False for k,v in out['gate_results'].items() if k not in metadata))

class SignedTopologyPlan(unittest.TestCase):
 def test_actual_pending_topology_verify_output_passes_signed_gate(self):
  fx,f,c=self.fixture()
  pending=media.verify
  installation={'baseline_image_id':c['expected_current_image_id']}
  with patch.object(media,'installed',return_value=installation),patch.object(media,'transition_started',return_value=False):
   gates=pending(inventory(c['expected_current_image_id'],False),c['expected_current_image_id'],True)
  self.assertEqual(gates['topology_pending_version'],2)
  f.bundle['preflight_evidence']['gate_results'].update(gates);f.seal()
  with patch.object(fx.gate.candidate_contract,'load',return_value=c):f.validate()
  for invalid in (None,True,1,3,'2'):
   f.bundle['preflight_evidence']['gate_results']['topology_pending_version']=invalid;f.seal()
   with patch.object(fx.gate.candidate_contract,'load',return_value=c),self.assertRaises(fx.gate.Reject):f.validate()
 def fixture(self):
  spec=importlib.util.spec_from_file_location('signed_topology_fixture',CC/'tests/test_deploy_entry.py');fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures);f=fixtures.Fixture();c=contract();c['candidate']=copy.deepcopy(f.bundle['plan']['candidate']);c['expected_current_image_id']=f.current;c['test_pr_evidence_sha256']=fixtures.gate.digest(f.bundle['test_pr_evidence']);identity=contracts.digest(c)
  f.bundle['plan'].update(candidate_contract_sha256=identity,topology=c['topology']);f.bundle['approval']['scope']='HK_STAGING_DEPLOY_FIXED_EIGHT_TOPOLOGY_V2';f.bundle['canary_task']['parameters']['candidate_contract_sha256']=identity;f.bundle['canary_evidence']['candidate_contract_sha256']=identity;f.bundle['canary_evidence']['gate_results'].update(topology_preflight='PASS',topology_sha256=media.TOPOLOGY_SHA,topology_version=2,topology_id=media.TOPOLOGY_ID,media_storage_identity={'topology_id':media.TOPOLOGY_ID,'topology_version':2,'contract_sha256':media.TOPOLOGY_SHA,'host_path':'/var/lib/go-hotel/media-cache','container_path':'/var/lib/go-hotel/media-cache','device':1,'inode':2,'marker_sha256':'3'*64});f.bundle['preflight_evidence']['gate_results'].update(topology_id=media.TOPOLOGY_ID,topology_version=1,topology_pending_version=2,media_persistence='NOT_ACTIVE');f.seal();return fixtures,f,c
 def test_signed_topology_plan_and_legacy_scope_refusal(self):
  fx,f,c=self.fixture()
  with patch.object(fx.gate.candidate_contract,'load',return_value=c):
   f.validate();f.bundle['approval']['scope']='HK_STAGING_DEPLOY_FIXED_EIGHT';f.seal()
   with self.assertRaises(fx.gate.Reject):f.validate()
 def test_even_signed_wrong_topology_proof_rejected(self):
  fx,f,c=self.fixture()
  with patch.object(fx.gate.candidate_contract,'load',return_value=c):
   f.bundle['canary_evidence']['gate_results']['topology_sha256']='0'*64;f.seal()
   with self.assertRaises(fx.gate.Reject):f.validate()
 def test_signature_tamper_is_not_hidden_by_topology(self):
  fx,f,c=self.fixture();f.bundle['canary_evidence']['gate_results']['topology_version']=1
  with patch.object(fx.gate.candidate_contract,'load',return_value=c),self.assertRaises(fx.gate.Reject):f.validate()


class SignedTopologyRollback(unittest.TestCase):
 setUp=Hooks.setUp
 tearDown=Hooks.tearDown
 def test_signed_source_record_v2_mount_identity_and_tamper(self):
  import base64
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
  from cryptography.hazmat.primitives import serialization
  root=pathlib.Path(self.tmp.name);hand=root/'handoff';records=root/'records';hand.mkdir();records.mkdir();tk=Ed25519PrivateKey.generate();ek=Ed25519PrivateKey.generate()
  for key,name in [(tk,'task.pub'),(ek,'evidence.pub')]: (root/name).write_bytes(key.public_key().public_bytes(serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH))
  def sign(v,key,hexsig=False):
   sig=key.sign(rollback.canonical(v));return {**v,'signature':sig.hex() if hexsig else base64.b64encode(sig).decode()}
  identity=contracts.digest(self.c);task=sign({'schema_version':'1','action_id':'HK_STAGING_DEPLOY','environment':'HK-STAGING-01','authority':'GO-COMMAND-CENTER','task_id':'source','nonce':'source-nonce','issued_at':'2026-09-18T04:00:00Z','parameters':{'release_id':'release','candidate_contract_sha256':identity,'candidate_image_id':self.c['candidate']['image_id'],'expected_current_image_id':self.c['expected_current_image_id'],'candidate_package_sha256':self.c['candidate']['package_sha256']}},tk,True)
  record={'deploy_record_schema_version':'2','record_id':'a'*64,'task_id':'source','nonce':task['nonce'],'authority':task['authority'],'task_canonical_sha256':hashlib.sha256(rollback.canonical(task)).hexdigest(),'migration_required':False,'candidate_contract_sha256':identity,'baseline_revision':self.c['baseline_revision'],'target_revision':self.c['target_revision'],**media.record_fields(self.identity,self.c),'targets':[{'service':s,'image_id':self.c['expected_current_image_id']} for s in media.SERVICES],'protected_non_target_inventory':[{'service':'redis'},{'service':'caddy'}]}
  raw=json.dumps(record,sort_keys=True,separators=(',',':')).encode();sha=hashlib.sha256(raw).hexdigest();(records/(record['record_id']+'.json')).write_bytes(raw)
  evidence=sign({'schema_version':'1','action_id':'HK_STAGING_DEPLOY','environment':'HK-STAGING-01','status':'SUCCESS','executor_result':'DEPLOY_OK','task_id':'source','nonce':task['nonce'],'deploy_record_id':record['record_id'],'deploy_record_sha256':sha,'gate_results':{'topology_sha256':media.TOPOLOGY_SHA,'media_rollback_compatible':True,'media_persistence':'PASS'}},ek)
  handoff={'schema_version':'1','rollback_task_id':'rollback','source_task':task,'source_evidence':evidence,'source_deploy_task_id':'source','deploy_record_id':record['record_id'],'deploy_record_sha256':sha,'history':[{'task':task,'evidence':evidence}]};path=hand/'rollback.json';path.write_text(json.dumps(handoff))
  kwargs={'handoff_dir':str(hand),'deploy_dir':str(records),'task_key':str(root/'task.pub'),'evidence_key':str(root/'evidence.pub'),'topology':media,'contract_module':contracts}
  with patch.object(media,'installed',return_value=self.install),patch.object(contracts,'load',return_value=self.c):
   result=rollback.resolve_source('release','source','rollback',**kwargs);self.assertEqual(result[2]['media_storage_identity'],self.identity)
   handoff['source_evidence']['gate_results']['media_persistence']='PASS_FAKE';path.write_text(json.dumps(handoff))
   with self.assertRaisesRegex(rollback.Reject,'signature'):rollback.resolve_source('release','source','rollback',**kwargs)
 def test_actual_rollback_hooks_retain_mount_and_protected_inventory(self):
  root=pathlib.Path(self.tmp.name);compose=root/'base.yml';env=root/'runtime.env';compose.write_text('base');env.write_text('env');deploydir=root/'deploy';deploydir.mkdir();rollbackdir=root/'rollback';rollbackdir.mkdir();rundir=root/'run';rundir.mkdir();rid='8'*64
  source={'record_id':rid,'candidate_image_id':self.c['candidate']['image_id'],'baseline_revision':self.c['baseline_revision'],'compose_sha256':hashlib.sha256(compose.read_bytes()).hexdigest(),'env_sha256':hashlib.sha256(env.read_bytes()).hexdigest(),**media.record_fields(self.identity,self.c),'protected_non_target_inventory':[{'service':'redis','image_id':'redis-image'},{'service':'caddy','image_id':'caddy-image'}]};(deploydir/(rid+'.json')).write_text(json.dumps(source))
  targets=[{'service':s,'image_id':self.c['expected_current_image_id']} for s in media.SERVICES];current=[{'image_id':self.c['candidate']['image_id'],'running':True,'status':'running'} for s in media.SERVICES];after=[{'image_id':self.c['expected_current_image_id'],'running':True,'status':'running'} for s in media.SERVICES];protected=[{'service':s,'image_id':s+'-image','container_id':s+'-unchanged','running':True,'status':'running'} for s in ['redis','caddy']];calls=[];records=[]
  media.begin(self.identity,self.c,{'deploy_record_sha256':'4'*64})
  def run(runner,argv,*args):calls.append(argv);return argv[3] if argv[1:3]==['image','inspect'] else ''
  with ExitStack() as stack:
   for target,name,value in [(rollback,'COMPOSE',str(compose)),(rollback,'ENV_FILE',str(env)),(rollback,'TEMP_DIR',str(rundir))]:stack.enter_context(patch.object(target,name,value))
   stack.enter_context(patch.object(media,'installed',return_value=self.install));stack.enter_context(patch.object(rollback,'resolve_source',return_value=({}, {},source,targets)));stack.enter_context(patch.object(rollback,'_inventory',side_effect=[current,protected,after,protected]));stack.enter_context(patch.object(rollback,'_full_inventory',side_effect=[inventory(self.c['candidate']['image_id'],True),inventory(self.c['expected_current_image_id'],True)]));stack.enter_context(patch.object(rollback,'_atomic_record',side_effect=lambda record,d:(records.append(record) or ('a'*64,'b'*64))));stack.enter_context(patch.object(rollback,'_run',side_effect=run));stack.enter_context(patch.object(rollback,'_await_api_health'))
   col=Mock();result=rollback.run_rollback('release','source',{'task_id':'rollback','nonce':'n','authority':'GO-COMMAND-CENTER','canonical_sha256':'5'*64},Mock(),col,deploy_dir=str(deploydir),rollback_dir=str(rollbackdir),topology=media,contract_module=contracts)
  self.assertEqual(result['media_persistence'],'PASS');self.assertEqual(records[0]['media_storage_identity'],self.identity);argv=next(x for x in calls if x[1]=='compose');self.assertIn(media.COMPOSE,argv);self.assertEqual(argv[-8:],list(media.SERVICES));self.assertIs(col._collect_verify.call_args.kwargs['topology'],media)

class InstallationBinding(unittest.TestCase):
 setUp=Hooks.setUp
 tearDown=Hooks.tearDown
 def test_installation_reads_actual_pinned_authorization_and_compose(self):
  root=pathlib.Path(self.tmp.name);compose=root/'compose.yml';compose.write_text('fixed compose');compose.chmod(0o400);authorization=root/'authorization.json';install=root/'installation.json'
  auth={'schema':'go.hk-media-topology-authorization.v1','action':'HK_STAGING_TOPOLOGY_V1_TO_V2_FIRST_INSTALL','topology_sha256':media.TOPOLOGY_SHA,'expected_image_id':self.c['expected_current_image_id'],'cache_path':media.CACHE,'source_helper_sha256':hashlib.sha256(pathlib.Path(media.__file__).read_bytes()).hexdigest()};authorization.write_text(json.dumps(auth));authorization.chmod(0o400)
  body={'schema':'go.hk-media-topology-installation.v1','topology_id':media.TOPOLOGY_ID,'topology_version':2,'topology_sha256':media.TOPOLOGY_SHA,'compose_sha256':hashlib.sha256(compose.read_bytes()).hexdigest(),'media_storage_identity':self.identity,'authorization_sha256':hashlib.sha256(authorization.read_bytes()).hexdigest(),'runtime_profile':self.install['runtime_profile'],'baseline_image_id':self.c['expected_current_image_id']};install.write_text(json.dumps(body));install.chmod(0o400)
  with patch.object(media,'INSTALLATION',str(install)),patch.object(media,'AUTHORIZATION',str(authorization)),patch.object(media,'COMPOSE',str(compose)),patch.object(media,'COMPOSE_SHA',body['compose_sha256']),patch.object(media,'trusted_ancestors'):
   self.assertEqual(media.installed()['media_storage_identity'],self.identity)
   authorization.chmod(0o600);authorization.write_text(json.dumps(auth)+'\n');authorization.chmod(0o400)
   with self.assertRaisesRegex(media.Reject,'AUTHORIZATION_ARTIFACT_DRIFT'):media.installed()
 def test_untrusted_writable_parent_rejected(self):
  p=pathlib.Path(self.tmp.name)/'unsafe';p.mkdir();p.chmod(0o777)
  with self.assertRaisesRegex(media.Reject,'UNTRUSTED'):media.trusted_ancestors(str(p))


class ReviewRegression(unittest.TestCase):
 def test_real_same_revision_v3_and_no_mutation_for_invalid_descriptor(self):
  c=contract();runner=Mock();runner.run.side_effect=lambda argv: Mock(returncode=0,stdout=json.dumps({'source':'PASS','revision':c['target_revision'],'graph_sha256':c['migration_source_digest'],'migration_required':False}) if argv[1]=='run' else '')
  same_runtime.check_images(runner,c)
  self.assertEqual(len(runner.run.call_args_list),4)
  self.assertEqual([x.args[0][-5] for x in runner.run.call_args_list if x.args[0][1]=='run'],[c['expected_current_image_id'],c['candidate']['image_id']])
  for value in ['bad',None,dict(c['topology'],topology_version=True),dict(c['topology'],topology_sha256='0'*64)]:
   runner.reset_mock();bad=copy.deepcopy(c);bad['topology']=value
   with self.assertRaises(same_runtime.Reject):same_runtime.check_images(runner,bad)
   runner.run.assert_not_called()
 def test_cli_topology_validator_defined_before_main_executes(self):
  import ast
  source=(CC/'go_deploy_request.py').read_text();tree=ast.parse(source)
  main=next(n for n in tree.body if isinstance(n,ast.If) and '__name__' in ast.unparse(n.test))
  prefix=ast.Module(body=[n for n in tree.body if n.lineno<main.lineno],type_ignores=[]);scope={'__file__':str(CC/'go_deploy_request.py'),'__name__':'cli_regression'}
  exec(compile(prefix,str(CC/'go_deploy_request.py'),'exec'),scope)
  self.assertEqual(scope['validate_topology_evidence']({'topology_id':media.TOPOLOGY_ID,'topology_version':1,'topology_pending_version':2,'media_persistence':'NOT_ACTIVE'},scope['VERIFY_ACTION']),{'topology_id','topology_version','topology_pending_version','media_persistence'})
 def test_provision_uses_full_container_id_from_realistic_ps(self):
  path=ROOT/'hk-staging/install/provision_media_topology.py';spec=importlib.util.spec_from_file_location('provision_regression',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  ids=[format(i+1,'064x') for i in range(8)];calls=[]
  def run(argv,**kwargs):
   calls.append(argv)
   if argv[1]=='ps':
    i=media.SERVICES.index(argv[-1].split('=')[-1]);value=ids[i] if '--no-trunc' in argv else ids[i][:12]
   elif argv[3]=='{{json .Mounts}}':value='[]'
   else:value=next(cid for cid in ids if cid.startswith(argv[-1]))+' '+mod.IMAGE+' true'
   return Mock(stdout=value,returncode=0)
  with patch.object(mod.subprocess,'run',side_effect=run):self.assertEqual(mod.baseline_inventory(media),ids)
  self.assertEqual(len(calls),24)

if __name__=='__main__':unittest.main()
