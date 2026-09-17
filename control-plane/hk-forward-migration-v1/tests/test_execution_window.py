"""Actual HK Evidence producer -> CC proof -> independently signed projection."""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
CC=ROOT/'control-plane/boss-deploy-request-v1'
sys.path.insert(0,str(CC))
import execution_window
import go_deploy_request as gate

def load(name,path,package=False):
    spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(path.parent)] if package else None)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value

load('migration_hk_agent',ROOT/'control-plane/boss-test-pr-live-integration-v1/hk-staging/hk_agent/__init__.py',True)
from migration_hk_agent import transport
fixture=load('migration_projection_fixture',ROOT/'control-plane/command-center-state-v1/tests/test_state_projection.py')

class ExecutionWindowTests(unittest.TestCase):
    def setUp(self):
        self.task_key,self.task_pub=fixture.key_pair('migration-task')
        self.hk_key,self.hk_pub=fixture.key_pair('migration-evidence')
        now=dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.started=now-dt.timedelta(seconds=480)
        self.iso=lambda at:at.isoformat().replace('+00:00','Z')
        params={'release_id':'migration-fixture','candidate_image_id':'sha256:'+'a'*64,
                'candidate_package_sha256':'b'*64,'expected_current_image_id':'sha256:'+'c'*64,
                'canary_evidence_id':'canary-fixture','approval_id':'approval-fixture',
                'candidate_contract_sha256':'d'*64}
        self.task=fixture.sign(fixture.task(action='HK_STAGING_DEPLOY',parameters=params,
            issued_at=self.iso(self.started-dt.timedelta(seconds=10)),
            expires_at=self.iso(self.started+dt.timedelta(seconds=60))),self.task_key,'hex')
        self.window={'schema':'go.hk-execution-window.v1','task_sha256':execution_window.task_digest(self.task),
                     'candidate_contract_sha256':'d'*64,'claimed_at':self.iso(self.started-dt.timedelta(seconds=1)),
                     'started_at':self.iso(self.started),'completed_at':self.iso(now),
                     'elapsed_milliseconds':480000,'budget_seconds':900}
        gates={k:'PASS' for k in ('candidate_binding','current_state','durable_previous_state','fixed_scope',
               'post_deploy_verify','migration_source_bound','rds_prestate_match','alembic_forward_migration',
               'rds_poststate_match','migration_evidence')}
        self.result={'schema_version':'1','executor_version':'0.5.0-forward-migration','action_id':'HK_STAGING_DEPLOY',
                     'status':'SUCCESS','release_id':params['release_id'],'candidate_image_id':params['candidate_image_id'],
                     'expected_current_image_id':params['expected_current_image_id'],'result':'DEPLOY_OK',
                     'gate_results':{**gates,'migration_record_sha256':'e'*64},
                     'deploy_record_schema_version':'2','deploy_record_id':'f'*64,'deploy_record_sha256':'0'*64,
                     'candidate_contract_sha256':params['candidate_contract_sha256']}

    def evidence(self):
        return fixture.sign(transport.evidence(self.task,self.result,execution=self.window),self.hk_key,'base64')

    def record(self,ev,task=None):
        layout=fixture.layout(tasks=[('migration.json',task or self.task)],evidences=[('migration-result.json',ev)])
        state=fixture.project(*layout,task_pub=self.task_pub,evidence_pub=self.hk_pub,
                              at=dt.datetime.now(dt.timezone.utc))
        return state['tasks'][0]

    def test_timely_start_and_eight_minute_completion_is_proven(self):
        ev=self.evidence()
        self.assertGreater(ev['completed_at'],self.task['expires_at'])
        proof=gate.rollback_source_proof(self.task,ev,self.task_key.public_key(),self.hk_key.public_key())
        self.assertTrue(proof['migration_required'])
        record=self.record(ev)
        self.assertEqual(record['parameter_contract'],'CURRENT')
        self.assertEqual(record['lifecycle'],'COMPLETE')
        self.assertEqual(record['assertion']['state'],'PROVEN')

    def test_missing_proof_never_uses_new_semantics(self):
        with self.assertRaises(transport.Reject): transport.evidence(self.task,self.result)
        ev=self.evidence();ev.pop('execution_window');ev=fixture.sign(ev,self.hk_key,'base64')
        with self.assertRaises(gate.Reject): gate.rollback_source_proof(self.task,ev,self.task_key.public_key(),self.hk_key.public_key())
        self.assertEqual(self.record(ev)['lifecycle'],'EVIDENCE_INVALID')

    def test_late_start_over_budget_clock_disagreement_and_substitution_refused(self):
        baseline=self.evidence()
        changes=[('started_at',self.task['expires_at']),('elapsed_milliseconds',900001),
                 ('elapsed_milliseconds',1),('budget_seconds',1000),('task_sha256','1'*64),
                 ('candidate_contract_sha256','2'*64)]
        for key,value in changes:
            with self.subTest(key=key,value=value):
                ev=copy.deepcopy(baseline);ev['execution_window'][key]=value
                if key=='started_at':ev['started_at']=value
                ev=fixture.sign(ev,self.hk_key,'base64')
                with self.assertRaises(gate.Reject): gate.rollback_source_proof(self.task,ev,self.task_key.public_key(),self.hk_key.public_key())
                self.assertEqual(self.record(ev)['lifecycle'],'EVIDENCE_INVALID')

    def test_legacy_late_evidence_is_not_retroactively_accepted(self):
        task=copy.deepcopy(self.task);task['parameters'].pop('candidate_contract_sha256')
        task=fixture.sign(task,self.task_key,'hex')
        ev=self.evidence();ev.pop('execution_window');ev.pop('candidate_contract_sha256')
        ev=fixture.sign(ev,self.hk_key,'base64')
        self.assertEqual(self.record(ev,task)['lifecycle'],'EVIDENCE_TIMEOUT')

    def test_real_ledger_persists_start_before_dispatch_and_refuses_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=transport.Ledger(str(Path(root)/'ledger.sqlite'))
            with patch.object(transport,'utcnow',return_value=self.window['claimed_at']):
                self.assertTrue(ledger.claim_attempt(self.task['task_id'],self.task['nonce']))
            with patch.object(transport,'utcnow',return_value=self.window['started_at']):
                window,_=ledger.begin_execution(self.task)
                with self.assertRaises(transport.Reject):ledger.begin_execution(self.task)
            with sqlite3.connect(ledger.path) as db:
                saved=db.execute('SELECT task_sha256,claimed_at,started_at FROM execution_starts').fetchone()
            self.assertEqual(saved,(window['task_sha256'],window['claimed_at'],window['started_at']))

    def test_claim_before_expiry_does_not_allow_start_after_expiry(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=transport.Ledger(str(Path(root)/'ledger.sqlite'))
            with patch.object(transport,'utcnow',return_value=self.window['claimed_at']):
                ledger.claim_attempt(self.task['task_id'],self.task['nonce'])
            with patch.object(transport,'utcnow',return_value=self.task['expires_at']):
                with self.assertRaises(transport.Reject):ledger.begin_execution(self.task)

if __name__=='__main__': unittest.main()
