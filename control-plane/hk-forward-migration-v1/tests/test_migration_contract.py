"""Boundary tests for the installed producer, consumer and durable failure fence."""
import copy
import hashlib
import importlib.util
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
CC=ROOT/'control-plane/boss-deploy-request-v1'
RT=ROOT/'hk-staging/source/executor/runtime'
sys.path.insert(0,str(CC))
sys.path.insert(0,str(RT))
import hk_candidate_contract as contract
import migration_runtime as migration
import canary_runtime as canary
import collector_runtime as collector
import migration_program as program

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value

adapter=module('migration_adapter',ROOT/'control-plane/boss-test-pr-live-integration-v1/hk-staging/hk_agent/deployment_actions.py')

def fixture():
    evidence=json.loads((ROOT/'ci/hk-migration-admission/PR183_REHEARSAL_EVIDENCE.json').read_text())
    b=evidence['binding']
    candidate={'repository':contract.REPOSITORY,'source_commit':b['candidate_sha'],
               'application_git_tree':b['candidate_application_tree'],'source_tree_sha256':b['candidate_fingerprint_sha256'],
               'package_sha256':b['artifact_package_sha256'],'image_id':b['artifact_image_id']}
    return {'schema':contract.SCHEMA,'environment':contract.ENVIRONMENT,'profile':contract.PROFILE,
            'candidate':candidate,'expected_current_image_id':'sha256:'+'1'*64,
            'baseline_revision':b['baseline_revision'],'target_revision':b['target_revision'],
            'rehearsal':evidence,'rehearsal_sha256':hashlib.sha256((json.dumps(evidence,sort_keys=True,indent=2)+'\n').encode()).hexdigest()}

class ContractTests(unittest.TestCase):
    def test_original_ci_evidence_and_full_identity_are_accepted(self):
        value=fixture();self.assertEqual(contract.validate(value,contract.digest(value)),value)

    def test_every_candidate_identity_substitution_is_rejected(self):
        for field in contract.CANDIDATE_FIELDS:
            with self.subTest(field=field):
                value=fixture();value['candidate'][field]='wrong'
                with self.assertRaises(contract.Reject): contract.validate(value)

    def test_migration_head_source_and_package_cannot_be_mixed(self):
        for field in ('baseline_revision','target_revision','rehearsal_sha256'):
            value=fixture();value[field]='0'*64
            with self.assertRaises(contract.Reject): contract.validate(value)
        value=fixture()
        with self.assertRaises(contract.Reject): contract.bind(value,'sha256:'+'2'*64,value['expected_current_image_id'])
        with self.assertRaises(contract.Reject): contract.bind(value,value['candidate']['image_id'],value['expected_current_image_id'],'f'*64)

    def test_rehearsal_pass_cannot_replace_missing_or_failed_gates(self):
        for field in ('source_binding','migration_lineage','forward_upgrade','existing_data_retention','target_noop'):
            value=fixture();value['rehearsal'][field]='FAIL'
            value['rehearsal_sha256']=hashlib.sha256((json.dumps(value['rehearsal'],sort_keys=True,indent=2)+'\n').encode()).hexdigest()
            with self.assertRaises(contract.Reject): contract.validate(value)

    def test_caller_command_sql_revision_workdir_are_closed(self):
        for field in ('command','sql','revision','workdir','database_url','production'):
            value=fixture();value[field]='unsafe'
            with self.assertRaises(contract.Reject): contract.validate(value)

    def test_duplicate_json_and_nonfinite_are_rejected(self):
        for raw in ('{"schema":1,"schema":2}','{"value":NaN}'):
            with self.assertRaises(contract.Reject): contract.parse(raw)

    def test_verify_profile_requires_exact_image(self):
        value=fixture()
        self.assertEqual(contract.verify_profile(value,value['candidate']['image_id']),('/workspace','0137_hosted_unknown_episode'))
        with self.assertRaises(contract.Reject): contract.verify_profile(value,value['expected_current_image_id'])

    def test_adapter_closed_contract_and_exact_output_binding(self):
        value=fixture();identity=contract.digest(value)
        params={'release_id':'fixture','candidate_image_id':value['candidate']['image_id'],
                'expected_current_image_id':value['expected_current_image_id'],
                'candidate_package_sha256':value['candidate']['package_sha256'],
                'candidate_contract_sha256':identity}
        cmd=adapter.argv('HK_STAGING_CANARY',params)
        self.assertEqual(cmd[-2:],['--candidate-contract-sha256',identity])
        for field in ('revision','sql','workdir','command'):
            with self.assertRaises(adapter.Reject): adapter.argv('HK_STAGING_CANARY',{**params,field:'x'})
        result={'schema_version':'1','executor_version':'fixture','action_id':'HK_STAGING_CANARY',
                'status':'SUCCESS','release_id':'fixture','candidate_image_id':params['candidate_image_id'],
                'expected_current_image_id':params['expected_current_image_id'],'result':'CANARY_OK',
                'gate_results':{'candidate':'PASS'},'candidate_contract_sha256':identity}
        adapter.parse_executor_output(json.dumps(result,separators=(',',':')),'HK_STAGING_CANARY',params)
        result['candidate_contract_sha256']='a'*64
        with self.assertRaises(adapter.Reject): adapter.parse_executor_output(json.dumps(result),'HK_STAGING_CANARY',params)

class DurableFenceTests(unittest.TestCase):
    def setUp(self):
        self.owner=patch.object(migration,"TRUSTED_UID",os.getuid());self.owner.start();self.addCleanup(self.owner.stop)

    def test_failed_or_unknown_attempt_cannot_be_retried_under_new_task(self):
        with tempfile.TemporaryDirectory() as root:
            state=Path(root)/'state';value=fixture();identity=contract.digest(value)
            first=migration.prepare(value,identity,{'task_id':'first'},{'deploy_record_id':'a'*64},state)
            self.assertTrue(Path(first['path']).is_file())
            with self.assertRaisesRegex(migration.Reject,'UNRESOLVED'):
                migration.prepare(value,identity,{'task_id':'fresh-other'},{'deploy_record_id':'b'*64},state)
            with self.assertRaisesRegex(migration.Reject,'UNRESOLVED'): migration.require_clear(state)

    def test_only_completed_cutover_releases_fence_and_retains_intent(self):
        with tempfile.TemporaryDirectory() as root:
            state=Path(root)/'state';value=fixture()
            receipt=migration.prepare(value,contract.digest(value),{'task_id':'first'},{'deploy_record_id':'a'*64},state)
            migration.complete(receipt)
            migration.require_clear(state)
            self.assertTrue((state/('a'*64+'.intent.json')).is_file())

    def test_pending_symlink_is_not_followed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            state=Path(root)/'state';state.mkdir(mode=0o700)
            (state/'pending.json').symlink_to(Path(root)/'missing')
            with self.assertRaisesRegex(migration.Reject,'UNRESOLVED'):
                migration.prepare(fixture(),'a'*64,{}, {'deploy_record_id':'b'*64},state)

class SourceSelectionTests(unittest.TestCase):
    def test_canary_checks_candidate_workspace_without_network_or_mounts(self):
        argv=canary._isolated_args('fixture','sha256:'+'a'*64,'/usr/local/bin/python',['-m','compileall','-q','/workspace/src'],'/workspace')
        self.assertEqual(argv[argv.index('--workdir')+1],'/workspace')
        self.assertEqual(argv[argv.index('--network')+1],'none')
        self.assertIn('--read-only',argv)
        self.assertNotIn('--volume',argv)
        canary.parse_alembic_head('0137_hosted_unknown_episode (head)\n','0137_hosted_unknown_episode')
        with self.assertRaises(canary.Reject): canary.parse_alembic_head('0133_flight_change_plan (head)\n','0137_hosted_unknown_episode')

    def test_post_verify_reads_candidate_head_from_workspace(self):
        class Runner:
            def __init__(self): self.calls=[]
            def run(self,argv):
                self.calls.append(argv)
                return SimpleNamespace(returncode=0,stdout='Rev: 0137_hosted_unknown_episode (head)\n' if 'current' in argv else '0137_hosted_unknown_episode (head)\n')
        runner=Runner()
        collector._collect_alembic_for_api(runner,{'Id':'fixture'},'0137_hosted_unknown_episode','/workspace')
        self.assertEqual(len(runner.calls),2)
        self.assertTrue(all(v[3]=='/workspace' for v in runner.calls))

    def test_migration_program_pins_same_root_and_has_no_down_command(self):
        source=(RT/'migration_program.py').read_text()
        self.assertEqual(program.ROOT,Path('/workspace'))
        self.assertNotIn("'downgrade'",source)
        self.assertNotIn('shell=True',source)
        self.assertIn("'upgrade',spec['target_revision']",source)

if __name__=='__main__': unittest.main()
