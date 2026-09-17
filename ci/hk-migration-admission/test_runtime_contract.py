import importlib.util
import json
import pathlib
import sys
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[2]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

CP=ROOT/'control-plane/boss-deploy-request-v1'
sys.path.insert(0,str(CP))
gate=load('migration_test_gate',pathlib.Path('control-plane/boss-deploy-request-v1/go_deploy_request.py'))
sys.modules['go_deploy_request']=gate
derivation=load('migration_test_derivation',pathlib.Path('control-plane/boss-deploy-request-v1/plan_derivation.py'))
agent=load('migration_test_agent',pathlib.Path('hk-staging/source/agent/hk_agent/deployment_actions.py'))
runtime=load('migration_test_runtime',pathlib.Path('hk-staging/source/executor/runtime/deploy_runtime.py'))

def contract(**changes):
    value={'schema':'go.forward-migration-admission.v1','source_commit':'a'*40,
           'application_git_tree':'b'*40,'source_fingerprint_sha256':'c'*64,
           'prestate_revision':'0133_flight_change_plan','target_revision':'0137_hosted_unknown_episode',
           'lineage_sha256':'d'*64,'forward_only':True,'arbitrary_sql':False,
           'rehearsal_evidence_sha256':'e'*64,'rehearsal_postgres_version':'18.4'}
    value.update(changes);return value

class MigrationContractTests(unittest.TestCase):
    def test_candidate_proposal_is_bound_to_real_pg_rehearsal(self):
        proposal=json.loads((ROOT/'ci/hk-migration-admission/CANDIDATE_PROPOSAL.json').read_text())
        evidence=json.loads((ROOT/'ci/hk-migration-admission/EVIDENCE_BINDING.json').read_text())
        block=proposal['release_candidate_v1'];admission=block['migration_admission']
        self.assertEqual(derivation.migration_from_admission(block),admission)
        self.assertEqual(admission['rehearsal_evidence_sha256'],evidence['evidence_json_sha256'])
        self.assertEqual(admission['lineage_sha256'],evidence['lineage_sha256'])
        self.assertEqual((admission['source_commit'],admission['application_git_tree'],
                          admission['source_fingerprint_sha256']),
                         (evidence['candidate_commit'],evidence['candidate_application_tree'],
                          evidence['candidate_fingerprint_sha256']))
        self.assertEqual((evidence['prestate_revision'],evidence['target_revision']),
                         ('0133_flight_change_plan','0137_hosted_unknown_episode'))

    def test_derivation_accepts_only_source_bound_contract(self):
        block={'migration_required':True,'migration_head':'0137_hosted_unknown_episode',
               'source_commit':'a'*40,'application_tree':'b'*40,'source_fingerprint':'c'*64,
               'migration_admission':contract()}
        self.assertEqual(derivation.migration_from_admission(block),contract())
        block['migration_admission']=contract(source_commit='f'*40)
        with self.assertRaisesRegex(gate.Reject,'candidate_admission_incomplete'):
            derivation.migration_from_admission(block)

    def test_non_migrating_candidate_stays_false(self):
        self.assertIs(derivation.migration_from_admission({'migration_required':False}),False)

    def test_gate_rejects_sql_or_non_forward_contract(self):
        candidate={'source_commit':'a'*40,'application_git_tree':'b'*40,
                   'source_tree_sha256':'c'*64}
        self.assertEqual(gate.validate_migration(contract(),candidate),contract())
        for bad in (contract(arbitrary_sql=True),contract(forward_only=False),
                    contract(target_revision='0133_flight_change_plan'),
                    contract(rehearsal_postgres_version='18.3')):
            with self.assertRaises(gate.Reject): gate.validate_migration(bad,candidate)

    def test_agent_emits_data_not_a_command(self):
        params={'release_id':'release1','candidate_image_id':'sha256:'+'1'*64,
                'candidate_package_sha256':'2'*64,'expected_current_image_id':'sha256:'+'3'*64,
                'canary_evidence_id':'canary1','approval_id':'approval1','migration':contract()}
        binding={'task_id':'task.1','nonce':'nonce_1','authority':'GO-COMMAND-CENTER',
                 'canonical_sha256':'4'*64}
        argv=agent.argv('HK_STAGING_DEPLOY',params,binding)
        self.assertNotIn('/bin/sh',argv);self.assertNotIn('sql',argv)
        value=json.loads(argv[argv.index('--migration-json')+1])
        self.assertEqual(value,contract())
        with self.assertRaises(agent.Reject):
            agent.validate('HK_STAGING_DEPLOY',{**params,'migration':{**contract(),'sql':'DROP TABLE x'}})

    def test_executor_revalidates_and_uses_fixed_python_program(self):
        class Result:
            returncode=0
            stdout=json.dumps({'prestate_revision':'0133_flight_change_plan',
              'target_revision':'0137_hosted_unknown_episode','poststate_revision':'0137_hosted_unknown_episode',
              'lineage_sha256':'d'*64,'forward_only':True,'arbitrary_sql':False})
        class Runner:
            def __init__(self): self.argv=None
            def run(self,argv): self.argv=argv;return Result()
        runner=Runner();gates=runtime._forward_migrate(runner,'/fixed/override.yml',contract())
        self.assertEqual(gates['migration_poststate'],'PASS')
        self.assertNotIn('/bin/sh',runner.argv);self.assertNotIn('-c',runner.argv[:-5])
        self.assertEqual(runner.argv[-3:],['0133_flight_change_plan','0137_hosted_unknown_episode','d'*64])
        with self.assertRaises(runtime.Reject): runtime._migration_contract({**contract(),'command':'id'})

if __name__=='__main__': unittest.main()
