"""Structural/claim audit only; does not verify remote artifacts or grant acceptance."""
import argparse
import hashlib
import json
from pathlib import Path

CELLS = [f'C{i:02d}' for i in range(1, 15)]
CATEGORIES = {'NORMAL','ERROR_UNKNOWN','AUTH_TENANT','CONCURRENCY_RECOVERY','TRUTH_CROSS_DOMAIN','ROLE_UI','OPERATIONS'}
BINDING_KEYS = ('head_sha','product_sha','application_tree','source_fingerprint','checklist_version')
SCOPE_KEYS = ('id','cell','requirement_ref','category','actor','preconditions','trigger','expected_result','verification_cases','dependencies','applicability','exclusion_review')

def scope_hash(ledger):
    # Evidence updates do not alter obligations. Any denominator/criterion change does.
    body = {'version': ledger.get('checklist_version'), 'requirements': ledger.get('requirement_register'),
            'items': sorted([{k:i.get(k) for k in SCOPE_KEYS} for m in ledger.get('modules',[]) for i in m.get('items',[])],key=lambda x:str(x['id']))}
    return hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def audit(ledger):
    errors=[]; modules=ledger.get('modules',[]); all_items=[i for m in modules for i in m.get('items',[])];ids=[i.get('id') for i in all_items]
    def check(value,message):
        if not value:errors.append(message)
    check(ledger.get('schema_version')==1,'schema_version must be 1')
    check(sorted(m.get('cell','') for m in modules)==CELLS,'exact C01-C14 module set required')
    check(len(ids)==len(set(ids)) and all(ids),'item IDs missing/duplicated')
    items={i.get('id'):i for i in all_items}; frozen=ledger.get('freeze_status')=='FROZEN'
    check(ledger.get('historical_pass_transferred') is False,'historical PASS transfer must be false')
    if frozen:
        check(ledger.get('scope_complete') is True,'scope completeness not reviewed')
        check(ledger.get('frozen_scope_hash')==scope_hash(ledger),'frozen scope hash mismatch')
        check(bool(ledger.get('freeze_review_ref')),'freeze review record missing')
        check(bool(ledger.get('requirement_register')),'full requirement register missing')
        for r in ledger.get('requirement_register',[]):
            check(r.get('status')=='RESOLVED' and bool(r.get('item_ids')) and all(i in items for i in r.get('item_ids',[])),f"unresolved/unmapped requirement:{r.get('id')}")
    binding=ledger.get('candidate_binding') or {};valid=set();required_by_cell={};unresolved=False
    if binding:
        check(all(binding.get(k) for k in BINDING_KEYS),'incomplete candidate binding')
        check(binding.get('checklist_version')==ledger.get('checklist_version'),'binding checklist version mismatch')
    for m in modules:
        cell=m.get('cell');required_by_cell[cell]=[];coverage=m.get('coverage',{})
        check(set(coverage)==CATEGORIES,f'{cell}: seven-category coverage required')
        for cat,refs in coverage.items():
            check(isinstance(refs,list) and bool(refs) and all(r in items and items[r].get('cell')==cell and items[r].get('category')==cat for r in refs),f'{cell}:{cat}: invalid coverage references')
        for i in m.get('items',[]):
            iid=i.get('id');app=i.get('applicability');check(i.get('cell')==cell,f'{iid}: wrong owner')
            check(all(i.get(k) for k in ('requirement_ref','actor','preconditions','trigger','expected_result')),f'{iid}: missing atomic criterion')
            cases=i.get('verification_cases',[]);caseids=[c.get('id') for c in cases if c.get('required') is True]
            check(bool(caseids) and all(caseids) and len(caseids)==len(set(caseids)),f'{iid}: required cases invalid')
            check(all(d in items and d!=iid for d in i.get('dependencies',[])),f'{iid}: unknown/self dependency')
            if app=='REQUIRED':required_by_cell[cell].append(iid)
            elif app=='APPROVED_OUT_OF_SCOPE':
                ex=i.get('exclusion_review') or {};check(all(ex.get(k) for k in ('reason','authority_ref','reviewer')),f'{iid}: unreviewed exclusion')
                check(i.get('review_status')!='PASS',f'{iid}: excluded obligation cannot PASS')
            else:unresolved=True;check(not frozen,f'{iid}: unresolved applicability')
            if i.get('review_status')!='PASS':continue
            before=len(errors)
            check(app=='REQUIRED',f'{iid}: invalid PASS applicability')
            check(bool(binding) and i.get('candidate_binding')==binding,f'{iid}: wrong candidate binding')
            check(i.get('evidence_state')=='VERIFIED' and i.get('independent_review') is True,f'{iid}: evidence not independently verified')
            check(bool(i.get('reviewer')) and bool(i.get('implementation_actor')) and i['reviewer']!=i['implementation_actor'],f'{iid}: missing/separation reviewer identity')
            check(bool(i.get('reviewed_at')) and not i.get('stale_reason'),f'{iid}: stale/undated PASS')
            refs=i.get('evidence_refs',[])
            check(bool(refs) and all(e.get('uri') and len(e.get('sha256',''))==64 and e.get('candidate_binding')==binding and e.get('independently_verified') is True for e in refs),f'{iid}: missing/bad raw evidence claims')
            results=i.get('case_results',[]);resultids=[r.get('id') for r in results]
            check(len(resultids)==len(set(resultids)) and set(caseids).issubset(resultids),f'{iid}: missing/duplicate case results')
            check(all(next((r for r in results if r.get('id')==c),{}).get('status')=='PASS' for c in caseids),f'{iid}: required case not passed')
            check(all(next((r for r in results if r.get('id')==c),{}).get('evidence_uris') and all(u in {e.get('uri') for e in refs} for u in next(r for r in results if r.get('id')==c)['evidence_uris']) for c in caseids),f'{iid}: case evidence mapping missing')
            if len(errors)==before:valid.add(iid)
    # Reject cycles and require every dependency's effective PASS, not merely a label.
    visiting=set();done=set()
    def visit(iid):
        if iid in visiting:check(False,f'dependency cycle:{iid}');return
        if iid in done:return
        visiting.add(iid)
        for d in items[iid].get('dependencies',[]):
            if d in items:visit(d)
        visiting.remove(iid);done.add(iid)
    for iid in items:visit(iid)
    changed=True
    while changed:
        changed=False
        for iid in list(valid):
            if any(d not in valid for d in items[iid].get('dependencies',[])):
                valid.remove(iid);check(False,f'{iid}: unsatisfied dependency');changed=True
    ready=frozen and not unresolved and not errors
    counts={c:{'required':len(v),'effective_pass':len(set(v)&valid),'completion_percent':100*len(set(v)&valid)/len(v) if ready and v else None} for c,v in required_by_cell.items()}
    gates=ledger.get('integration_gate') or {}; gate_pass=gates.get('status')=='PASS' and gates.get('candidate_binding')==binding and gates.get('independently_verified') is True and bool(gates.get('evidence_ref'))
    all_complete=ready and len(counts)==14 and all(v['required']>0 and v['effective_pass']==v['required'] for v in counts.values()) and gate_pass and not ledger.get('open_blockers')
    mean=sum(counts[c]['completion_percent'] for c in CELLS[:12])/12 if ready and all(c in counts and counts[c]['completion_percent'] is not None for c in CELLS[:12]) else None
    return {'structural_status':'VALID' if not errors else 'INVALID','errors':errors,'computed_scope_hash':scope_hash(ledger),'scope_frozen':frozen,'counts':counts,'c01_c12_mean_completion_percent':mean,'all_14_internal_scope_complete':all_complete,'release_gate':'ELIGIBLE_FOR_INDEPENDENT_SIGNOFF' if all_complete else 'HOLD','warning':'Valid claims are not independent verification; no deployment authority or evidence-maturity score is inferred.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('ledger');p.add_argument('--output');args=p.parse_args()
    result=audit(json.loads(Path(args.ledger).read_text()));text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:Path(args.output).write_text(text)
    print(text,end='');raise SystemExit(0 if result['structural_status']=='VALID' else 1)
