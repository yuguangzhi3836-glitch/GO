"""Assemble immutable requirements with separately maintained verification claims."""
import argparse
import json
from pathlib import Path
from validate_ledger import audit,scope_hash

STATUS_KEYS={'review_status','evidence_state','candidate_binding','evidence_refs','case_results','implementation_state','implementation_actor','reviewer','reviewed_at','stale_reason','independent_review'}
def evaluate(requirements,verification):
    ledger=json.loads(json.dumps(requirements))
    assert verification['checklist_version']==ledger['checklist_version'],'version mismatch'
    assert verification['frozen_scope_hash']==ledger['frozen_scope_hash']==scope_hash(ledger),'definition changed'
    ids={i['id'] for m in ledger['modules'] for i in m['items']}
    assert set(verification['items'])==ids,'verification ID set mismatch'
    for m in ledger['modules']:
        for i in m['items']:
            status=verification['items'][i['id']]
            assert set(status)<=STATUS_KEYS,'verification cannot change requirement criteria'
            i.update(status)
    for k in ('candidate_binding','integration_gate','open_blockers'):ledger[k]=verification.get(k)
    assert scope_hash(ledger)==ledger['frozen_scope_hash']
    return audit(ledger)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--requirements',type=Path,default=Path(__file__).with_name('requirements.json'));p.add_argument('--verification',type=Path,default=Path(__file__).with_name('verification.json'));p.add_argument('--output',type=Path);a=p.parse_args()
    result=evaluate(json.loads(a.requirements.read_text()),json.loads(a.verification.read_text()))
    text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if a.output:a.output.write_text(text)
    print(text,end='');raise SystemExit(result['structural_status']!='VALID')
