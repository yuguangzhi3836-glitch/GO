import copy,unittest
from validate_ledger import audit,scope_hash,CELLS,CATEGORIES

def fixture():
    binding=dict(head_sha='test-only-head',product_sha='test-only-product',application_tree='test-only-tree',source_fingerprint='test-only-fingerprint',checklist_version='test-only-v1')
    modules=[];req=[]
    for c in CELLS:
        rows=[]
        for n,cat in enumerate(sorted(CATEGORIES)):
            iid=f'{c}-{n}';case=iid+'-case';uri='test-only://'+case
            row=dict(id=iid,cell=c,category=cat,requirement_ref='test-only requirement',actor='test-only actor',preconditions='isolated test',trigger='test-only trigger',expected_result='test-only result',verification_cases=[dict(id=case,required=True)],dependencies=[],applicability='REQUIRED',review_status='PASS',candidate_binding=binding,evidence_state='VERIFIED',independent_review=True,reviewer='reviewer',implementation_actor='author',reviewed_at='test-only date',evidence_refs=[dict(uri=uri,sha256='a'*64,candidate_binding=binding,independently_verified=True)],case_results=[dict(id=case,status='PASS',evidence_uris=[uri])])
            rows.append(row);req.append(dict(id=iid,status='RESOLVED',item_ids=[iid]))
        modules.append(dict(cell=c,items=rows,coverage={i['category']:[i['id']] for i in rows}))
    result=dict(schema_version=1,checklist_version='test-only-v1',modules=modules,requirement_register=req,freeze_status='FROZEN',scope_complete=True,freeze_review_ref='test-only review',candidate_binding=binding,historical_pass_transferred=False,open_blockers=[],integration_gate=dict(status='PASS',candidate_binding=binding,independently_verified=True,evidence_ref='test-only gate'))
    result['frozen_scope_hash']=scope_hash(result);return result

class LedgerAuditTests(unittest.TestCase):
    def test_complete_claim_fixture_is_structurally_eligible_not_real_acceptance(self):
        r=audit(fixture());self.assertEqual(r['errors'],[]);self.assertEqual(r['c01_c12_mean_completion_percent'],100);self.assertTrue(r['all_14_internal_scope_complete'])
    def test_unfrozen_has_no_completion_percent(self):
        x=fixture();x['freeze_status']='DRAFT';r=audit(x);self.assertIsNone(r['c01_c12_mean_completion_percent']);self.assertFalse(r['all_14_internal_scope_complete'])
    def test_removed_obligation_breaks_frozen_hash(self):
        x=fixture();x['modules'][0]['items'].pop();self.assertIn('frozen scope hash mismatch',audit(x)['errors'])
    def test_skip_cannot_pass(self):
        x=fixture();x['modules'][0]['items'][0]['case_results'][0]['status']='SKIP';self.assertFalse(audit(x)['all_14_internal_scope_complete'])
    def test_historical_source_cannot_pass(self):
        x=fixture();i=x['modules'][0]['items'][0];i['candidate_binding']=dict(i['candidate_binding'],head_sha='old');self.assertTrue(any('wrong candidate' in s for s in audit(x)['errors']))
    def test_missing_case_evidence_cannot_pass(self):
        x=fixture();x['modules'][0]['items'][0]['case_results'][0]['evidence_uris']=[];self.assertFalse(audit(x)['all_14_internal_scope_complete'])
    def test_author_cannot_review_own_implementation(self):
        x=fixture();x['modules'][0]['items'][0]['reviewer']='author';self.assertFalse(audit(x)['all_14_internal_scope_complete'])
    def test_dependency_cycle_rejected(self):
        x=fixture();a,b=x['modules'][0]['items'][:2];a['dependencies']=[b['id']];b['dependencies']=[a['id']];x['frozen_scope_hash']=scope_hash(x);self.assertTrue(any('cycle' in s for s in audit(x)['errors']))
    def test_blocker_holds_even_if_count_is_100(self):
        x=fixture();x['open_blockers']=['test-only blocker'];r=audit(x);self.assertEqual(r['c01_c12_mean_completion_percent'],100);self.assertFalse(r['all_14_internal_scope_complete'])
    def test_unresolved_requirement_prevents_100(self):
        x=fixture();x['requirement_register'][0]['status']='UNKNOWN';x['frozen_scope_hash']=scope_hash(x);self.assertIsNone(audit(x)['c01_c12_mean_completion_percent'])
    def test_missing_case_result_returns_invalid_not_exception(self):
        x=fixture();x['modules'][0]['items'][0]['case_results']=[];self.assertEqual(audit(x)['structural_status'],'INVALID')

if __name__=='__main__':unittest.main()
