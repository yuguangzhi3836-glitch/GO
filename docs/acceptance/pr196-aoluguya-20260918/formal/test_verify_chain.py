import copy,json,tempfile,unittest
from pathlib import Path
from cryptography.exceptions import InvalidSignature
import verify_chain as m

class ChainTests(unittest.TestCase):
 def setUp(self):
  self.task=m.read(m.HERE/'CANARY_TASK.json');self.evidence=m.read(m.HERE/'CANARY_EVIDENCE.json');self.contracts=m.contracts()
 def test_real_canary_signatures_without_evidence_package(self):
  self.assertNotIn('candidate_package_sha256',self.evidence)
  self.assertEqual(m.verify_pair('CANARY',self.task,self.evidence,self.contracts)['status'],'PASS')
 def test_missing_pairs_are_wait_never_chain_pass(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)
   for name in ('CANARY_TASK.json','CANARY_EVIDENCE.json'):(p/name).write_bytes((m.HERE/name).read_bytes())
   r=m.verify_chain(p);self.assertEqual(r['status'],'WAIT');self.assertEqual(r['stages']['CANARY']['status'],'PASS');self.assertEqual(r['stages']['DEPLOY']['status'],'WAIT')
 def test_canary_task_package_must_match_immutable_contract(self):
  self.task['parameters']['candidate_package_sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'task_package_contract_binding'):m.bindings('CANARY',self.task,self.evidence,self.contracts)
 def test_nonce_identity_mismatch_rejected(self):
  self.evidence['nonce']='different'
  with self.assertRaisesRegex(ValueError,'task_evidence_binding:nonce'):m.bindings('CANARY',self.task,self.evidence,self.contracts)
 def test_tampered_original_signature_rejected(self):
  self.evidence['candidate_image_id']=m.CURRENT_IMAGE
  with self.assertRaises(InvalidSignature):m.verify_pair('CANARY',self.task,self.evidence,self.contracts)
 def make_verify_binding_fixture(self,stage):
  action,contract,image,current,result=m.STAGES[stage]
  t,e=copy.deepcopy(self.task),copy.deepcopy(self.evidence);t['action_id']=e['action_id']=action
  t['parameters'].pop('candidate_package_sha256');e['executor_result']=result;e['gate_results']={g:'PASS' for g in m.GATES[stage]}
  for key,value in [('candidate_contract_sha256',contract),('candidate_image_id',image),('expected_current_image_id',current)]:t['parameters'][key]=e[key]=value
  return t,e
 def test_ordinary_verify_uses_pr192_contract_not_pending_candidate(self):
  t,e=self.make_verify_binding_fixture('VERIFY');m.bindings('VERIFY',t,e,self.contracts)
  t['parameters']['candidate_contract_sha256']=e['candidate_contract_sha256']=m.CANDIDATE_CONTRACT
  with self.assertRaisesRegex(ValueError,'stage_binding:candidate_contract_sha256'):m.bindings('VERIFY',t,e,self.contracts)
 def test_post_verify_requires_new_image_as_current(self):
  t,e=self.make_verify_binding_fixture('POST_VERIFY');m.bindings('POST_VERIFY',t,e,self.contracts)
  t['parameters']['expected_current_image_id']=e['expected_current_image_id']=m.CURRENT_IMAGE
  with self.assertRaisesRegex(ValueError,'stage_binding:expected_current_image_id'):m.bindings('POST_VERIFY',t,e,self.contracts)
 def test_deploy_must_reference_this_canary_release(self):
  task={'parameters':{'canary_evidence_id':self.task['parameters']['release_id']}}
  m.deployment_canary_link(task,self.task)
  task['parameters']['canary_evidence_id']='unrelated-canary'
  with self.assertRaisesRegex(ValueError,'deploy_canary_reference_mismatch'):m.deployment_canary_link(task,self.task)
 def test_existing_window_allows_timely_claim_not_unbounded_completion(self):
  p=m.ROOT/'integration-gate/closeout';t=m.read(p/'DEPLOY_TASK.json');e=m.read(p/'DEPLOY_EVIDENCE.json');w=m.window_module()
  self.assertGreater(w.stamp(e['completed_at']),w.stamp(t['expires_at']));w.validate(t,e)
  e['execution_window']['elapsed_milliseconds']=900001
  with self.assertRaises(w.Invalid):w.validate(t,e)

if __name__=='__main__':unittest.main()
