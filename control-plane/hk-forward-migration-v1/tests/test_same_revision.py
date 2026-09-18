"""No-DB contract/graph tests and mocked fixed executor side-effect boundary."""
import copy
from contextlib import ExitStack
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[3]
RT=ROOT/'hk-staging/source/executor/runtime'
CC=ROOT/'control-plane/boss-deploy-request-v1'
sys.path[:0]=[str(RT),str(CC)]
import hk_candidate_contract as contract
import same_revision_program as program
import same_revision_runtime as runtime
import deploy_runtime as deploy
import canary_runtime as canary
import plan_derivation as derivation

def load(name,path):
    loader=importlib.machinery.SourceFileLoader(name,str(path))
    spec=importlib.util.spec_from_loader(name,loader)
    value=importlib.util.module_from_spec(spec);loader.exec_module(value);return value

executor=load('same_executor',ROOT/'hk-staging/source/executor/go-hk-deployctl')
bridge=load('same_bridge',CC/'go-boss-request-bridge')

def fixture():
    return {'schema':contract.SAME_SCHEMA,'environment':contract.ENVIRONMENT,'profile':contract.PROFILE,
        'candidate':{'repository':contract.REPOSITORY,'source_commit':'a'*40,'application_git_tree':'b'*40,
                     'source_tree_sha256':'c'*64,'package_sha256':'d'*64,'image_id':'sha256:'+'e'*64},
        'expected_current_image_id':'sha256:'+'f'*64,'baseline_revision':'0137_fixture','target_revision':'0137_fixture',
        'migration_required':False,'migration_source_digest':'1'*64,'baseline_migration_source_digest':'1'*64,
        'test_pr_evidence_sha256':'2'*64}

class SameContractTests(unittest.TestCase):
    def test_explicit_false_identity_and_closed_schema(self):
        value=fixture();self.assertEqual(contract.validate(value,contract.digest(value)),value)
        self.assertFalse(contract.migration_required(value))
        self.assertEqual(contract.test_pr_digest(value),'2'*64)
        for mode in (True,None,0,'false'):
            changed={**value,'migration_required':mode}
            with self.assertRaises(contract.Reject): contract.validate(changed)
        for key in ('workdir','command','sql','rehearsal','schema_override'):
            with self.assertRaises(contract.Reject): contract.validate({**value,key:'x'})

    def test_wrong_baseline_target_or_graph_rejected(self):
        for key,value in [('baseline_revision','0133_old'),('target_revision','0138_new'),
                          ('migration_source_digest','3'*64),('baseline_migration_source_digest','3'*64),
                          ('migration_source_digest','bad'),('test_pr_evidence_sha256','bad')]:
            with self.subTest(key=key,value=value),self.assertRaises(contract.Reject):
                contract.validate({**fixture(),key:value})

    def test_v1_cannot_be_relabelled_as_v2(self):
        value=fixture();value['schema']=contract.SCHEMA
        with self.assertRaises(contract.Reject): contract.validate(value)

    def test_root_owned_active_record_preserves_mode_and_full_identity(self):
        value=fixture();candidate=value['candidate'];identity=contract.digest(value)
        block={'source_commit':candidate['source_commit'],'application_tree':candidate['application_git_tree'],
               'source_fingerprint':candidate['source_tree_sha256'],'artifact_digest':candidate['image_id'],
               'source_repository':candidate['repository'],'artifact_package':{'package_sha256':candidate['package_sha256']},
               'migration_required':False,'migration_head':value['target_revision'],
               'rollback_relation':{'previous_known_good_image_id':value['expected_current_image_id']},
               'candidate_contract_sha256':identity}
        record={'schema':'go.hk-active-candidate.v1','candidate_contract_sha256':identity,'admission':{'release_candidate_v1':block}}
        with patch.object(Path,'exists',return_value=True),patch.object(contract,'secure_read',return_value=json.dumps(record)),patch.object(contract,'load',return_value=value):
            self.assertEqual(contract.active(),(record,value))
            record['admission']['release_candidate_v1']['migration_required']=True
            with patch.object(contract,'secure_read',return_value=json.dumps(record)),self.assertRaises(contract.Reject): contract.active()

    def test_verify_v2_baseline_binds_existing_image_contract(self):
        value=fixture();baseline={'version':2,'environment':contract.ENVIRONMENT,'image_id':value['candidate']['image_id'],
               'evidence_task_id':'task','evidence_commit':'commit','evidence_path':'path','candidate_contract_sha256':contract.digest(value)}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'baseline.json';path.write_text(json.dumps(baseline))
            with patch.object(bridge.deploy_gate.candidate_contract,'load',return_value=value):
                self.assertEqual(bridge.load_baseline(path),baseline)
                task=bridge.derive({'request_id':'fixture'},baseline)
                self.assertEqual(task['parameters']['candidate_contract_sha256'],contract.digest(value))
                baseline['image_id']=value['expected_current_image_id'];path.write_text(json.dumps(baseline))
                with self.assertRaises(bridge.Reject):bridge.load_baseline(path)

class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.versions=self.root/'alembic/versions';self.versions.mkdir(parents=True)
        (self.versions/'0001.py').write_text("revision='0001'\ndown_revision=None\n")
        (self.versions/'0137.py').write_text("revision='0137_fixture'\ndown_revision='0001'\n")
        (self.root/'alembic.ini').write_text('[alembic]\nscript_location=alembic\n')
        (self.root/'alembic/env.py').write_text('# env\n')
        proof={'schema':'go.hk-migration-graph.v1','revision':'0137_fixture','graph':program.graph(self.versions),
               'auxiliary':{p:hashlib.sha256((self.root/p).read_bytes()).hexdigest() for p in ['alembic.ini', *sorted(str(x.relative_to(self.root)) for x in (self.root/'alembic').rglob('*.py'))]}}
        self.spec={'revision':'0137_fixture','graph_sha256':hashlib.sha256((json.dumps(proof,sort_keys=True,indent=2)+'\n').encode()).hexdigest()}

    def test_complete_graph_and_auxiliary_exact_identity(self):
        self.assertFalse(program.check_source(self.spec,self.root)['migration_required'])
        for path in [self.versions/'0001.py',self.root/'alembic/env.py',self.root/'alembic.ini']:
            old=path.read_text();path.write_text(old+'# changed\n')
            with self.assertRaises(ValueError):program.check_source(self.spec,self.root)
            path.write_text(old)

    def test_unknown_head_extra_root_and_cycle_fail(self):
        with self.assertRaises(ValueError):program.check_source({**self.spec,'revision':'0138_other'},self.root)
        (self.versions/'9999.py').write_text("revision='9999'\ndown_revision=None\n")
        with self.assertRaises(ValueError):program.check_source(self.spec,self.root)
        (self.versions/'9999.py').unlink()
        (self.versions/'0001.py').write_text("revision='0001'\ndown_revision='0137_fixture'\n")
        with self.assertRaises(ValueError):program.check_source(self.spec,self.root)

    def test_mode_cannot_invoke_migrate(self):
        with patch.object(sys,'argv',['program','migrate',json.dumps(self.spec)]),patch('builtins.print'),self.assertRaises(SystemExit):program.entry()

class RuntimeTests(unittest.TestCase):
    def test_graph_check_both_images_isolated_and_cleanup_on_failure(self):
        value=fixture();out={'source':'PASS','revision':value['target_revision'],'graph_sha256':value['migration_source_digest'],'migration_required':False}
        runner=Mock();runner.run.return_value=NS(returncode=0,stdout=json.dumps(out))
        runtime.check_images(runner,value)
        calls=[c.args[0] for c in runner.run.call_args_list]
        self.assertEqual(len(calls),4)
        for command,image in zip(calls[::2],[value['expected_current_image_id'],value['candidate']['image_id']]):
            self.assertIn(image,command);self.assertIn('--read-only',command)
            self.assertEqual(command[command.index('--network')+1],'none')
            self.assertNotIn('--volume',command);self.assertEqual(command[-2],'source')
        runner.reset_mock();runner.run.side_effect=[NS(returncode=2,stdout=''),NS(returncode=0,stdout='')]
        with self.assertRaises(runtime.Reject):runtime.check_images(runner,value)
        self.assertEqual(runner.run.call_args_list[-1].args[0][:3],['/usr/bin/docker','rm','-f'])

    def test_pending_migration_blocks_same_revision(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(runtime,'PENDING',Path(tmp)/'pending.json'):
            runtime.require_clear();runtime.PENDING.symlink_to(Path(tmp)/'absent')
            with self.assertRaises(runtime.Reject):runtime.require_clear()

    def test_deploy_never_calls_migration_and_checks_database_before_cutover(self):
        value=fixture();same=Mock();migration=Mock();collector=Mock()
        collector._collect_verify.return_value={'target_service_count':8}
        events=[];collector._collect_alembic_for_api.side_effect=lambda *a:events.append('db-prestate')
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            record=Path(tmp)/'record.json';record.write_text(json.dumps({'protected_non_target_inventory_sha256':'hash'}))
            stack.enter_context(patch.object(deploy,'_precheck',return_value=[{'Id':'api'}]))
            stack.enter_context(patch.object(deploy,'_record_v2',return_value={'record_path':str(record)}))
            stack.enter_context(patch.object(deploy,'_override',return_value=str(Path(tmp)/'override')))
            stack.enter_context(patch.object(deploy,'_run',side_effect=lambda *a:events.append('cutover')))
            stack.enter_context(patch.object(deploy,'_protected_non_target_snapshot',return_value=([],'hash')))
            stack.enter_context(patch.object(deploy,'_wait_for_api_health'))
            stack.enter_context(patch.object(deploy.os,'unlink'))
            gates=deploy.run_deploy('release',value['candidate']['image_id'],value['candidate']['package_sha256'],value['expected_current_image_id'],{},Mock(),collector,Mock(),contract=value,contract_sha=contract.digest(value),migration=migration,same_revision=same)
            self.assertEqual(events,['db-prestate','cutover']);self.assertEqual(gates['no_migration'],'PASS')
            self.assertNotIn('alembic_forward_migration',gates);self.assertFalse(migration.mock_calls)
            collector._collect_alembic_for_api.side_effect=ValueError('wrong-db-head');events.clear()
            with self.assertRaises(ValueError):deploy.run_deploy('release',value['candidate']['image_id'],value['candidate']['package_sha256'],value['expected_current_image_id'],{},Mock(),collector,Mock(),contract=value,contract_sha=contract.digest(value),migration=migration,same_revision=same)
            self.assertEqual(events,[])

    def test_executor_never_loads_migration_module_for_same_revision(self):
        value=fixture();mock_runtime=Mock();mock_runtime.run_deploy.return_value={'deploy_record_schema_version':'2','deploy_record_id':'a'*64,'deploy_record_sha256':'b'*64,'no_migration':'PASS'}
        with patch.object(executor,'_contract',return_value=value),patch.object(executor,'_load_deploy',return_value=mock_runtime),patch.object(executor,'_load_collector'),patch.object(executor,'_load_artifact'),patch.object(executor,'_same_revision'),patch.object(executor,'_topology'),patch.object(executor,'_migration',side_effect=AssertionError('MIGRATION MODULE LOADED')):
            out,code=executor._deploy('release',value['candidate']['image_id'],value['candidate']['package_sha256'],value['expected_current_image_id'],'approval','canary',{},contract_sha=contract.digest(value))
            self.assertEqual(code,0);self.assertNotIn('migration',mock_runtime.run_deploy.call_args.kwargs)

class SignedPlanTests(unittest.TestCase):
    def setUp(self):
        self.fixtures=load('same_signed_fixture',CC/'tests/test_deploy_entry.py')
        self.f=self.fixtures.Fixture();self.value=fixture()
        self.value['candidate']=copy.deepcopy(self.f.bundle['plan']['candidate'])
        self.value['expected_current_image_id']=self.f.current
        self.value['test_pr_evidence_sha256']=self.fixtures.gate.digest(self.f.bundle['test_pr_evidence'])
        self.identity=contract.digest(self.value)
        self.f.bundle['plan']['candidate_contract_sha256']=self.identity
        self.f.bundle['canary_task']['parameters']['candidate_contract_sha256']=self.identity
        self.f.bundle['canary_evidence']['candidate_contract_sha256']=self.identity
        self.f.seal()
        self.loader=patch.object(self.fixtures.gate.candidate_contract,'load',return_value=self.value)
        self.loader.start();self.addCleanup(self.loader.stop)

    def test_same_revision_plan_with_real_signatures_passes(self):
        self.f.validate()
        self.assertFalse(self.f.bundle['plan']['migration'])

    def test_plan_mode_cannot_upgrade_to_migration(self):
        self.f.bundle['plan']['migration']=True;self.f.seal()
        with self.assertRaises(self.fixtures.gate.Reject):self.f.validate()

    def test_signed_test_pr_identity_cannot_be_substituted(self):
        self.value['test_pr_evidence_sha256']='0'*64
        with self.assertRaises(self.fixtures.gate.Reject):self.f.validate()

    def test_signed_canary_cannot_name_another_contract(self):
        self.f.bundle['canary_task']['parameters']['candidate_contract_sha256']='3'*64
        self.f.bundle['canary_evidence']['candidate_contract_sha256']='3'*64;self.f.seal()
        with self.assertRaises(self.fixtures.gate.Reject):self.f.validate()

if __name__=='__main__':unittest.main()
