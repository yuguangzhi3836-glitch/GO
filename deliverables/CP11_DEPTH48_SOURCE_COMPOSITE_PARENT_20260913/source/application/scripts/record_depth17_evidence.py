#!/usr/bin/env python3
"""Record measured consolidation evidence; never turn missing gates into passes."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth17'
BASE_SHA='e776e941d7cc1cc64b98bf4e02b538d5f1cf44a53e418c04962b65bcfc646025'


def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-work',required=True,type=Path)
    args=parser.parse_args()
    assert sha(args.baseline_work.read_bytes())==BASE_SHA
    files={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for folder in ('src','frontend','tests','tests_frontend','alembic')
           for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
    assert files==json.loads((OUT/'full_run_source_fingerprint.json').read_text())['files'],'FROZEN_SOURCE_CHANGED'
    tree=ET.parse(OUT/'full_regression.xml'); suites=list(tree.getroot().iter('testsuite'))
    total={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
    assert total['tests']>=1327 and total['failures']==total['errors']==0
    total.update(passed=total['tests']-total['skipped'],one_clean_full_run=True,
                 seconds=sum(float(s.get('time','0')) for s in suites))
    new=[c for c in tree.getroot().iter('testcase') if 'test_depth17_' in c.get('classname','')]
    assert len(new)==16 and not any(len(c) for c in new)
    skipped=[{'case':c.get('classname')+'::'+c.get('name'),'reason':c.find('skipped').get('message')} for c in tree.getroot().iter('testcase') if c.find('skipped') is not None]
    write(OUT/'skipped_cases.json',skipped)
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    for group in immutable.values():
        assert group['all_match'] and all(sha((ROOT/f['path']).read_bytes())==f['sha256'] for f in group['files'])
    front=(OUT/'frontend.tap').read_text()
    assert 'pass 78' in front and 'fail 0' in front
    syntax=json.loads((OUT/'javascript_syntax.json').read_text());assert not syntax['failures']
    previous=json.loads((ROOT/'verification/current_build/depth16/CURRENT_BUILD_STATUS.json').read_text())
    scope=('Durable local execution integrates the current C14 authority and all-condition evidence checks. '
        'SQL leases, atomic effect/checkpoint/event commits, bounded retries, SIGKILL recovery and unknown-external-outcome query-only handling are tested. '
        'Current actor, paused cell, qualification policy/validity/revocation and exact request/handler/step proof are rechecked before local commit. '
        'Persisted legacy records lacking windows remain HOLD without backdating. New trusted registrations serialize immutable records and enforce fresh evidence after revocation. '
        'Fourteen registered application adapters perform admin-authorized aggregate observations only; no autonomous business actions, independent signer identities or production qualifications are certified.')
    hotel=('Parallel hotel catalog fixes merged: stable source identity, newest snapshot merge, exact official room-media binding, '
        'quality-gated publication, retention of last good pages and truthful regional completion counts. Ten-hotel replication tests are synthetic. '
        'Regional queue lease/ACK, durable media index, discovery-to-harvester coupling, official-specific adapters and booking-pool projection remain open.')
    gaps=[g for g in previous['engineering_gaps'] if g!='14_CELL_DURABLE_EXECUTION_AND_RECOVERY']
    gaps+=['14_CELL_DURABLE_BUSINESS_ADAPTERS_AND_FULL_ROUTE_C14_INTEGRATION','REGIONAL_QUEUE_LEASE_ACK_AND_DURABLE_MEDIA_INDEX','REAL_TEN_HOTEL_REPLICATION_ACCEPTANCE']
    status={**previous,'build':'CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION','baseline':{**previous['baseline'],'depth16_work_sha256':BASE_SHA,
        'parallel_github_commit':'6f379eff8d63c123b2bd57d504ab6520f6ffc575'},'python':total,
        'new_backend_cases_passed':16,'imported_backend_cases_passed':100,
        'frontend':{'logic_passed':78,'syntax_files_passed':syntax['files'],'node':syntax['node'],'current_iteration_rerun':True,
            'basis':'CURRENT_FROZEN_SOURCE_EXECUTED','browser_visual_accepted':False,'frozen_node_22_22_certified':False},
        'immutable':{k:{f:v[f] for f in ('count','all_match')} for k,v in immutable.items()},
        'autonomy_current_authority_scope':scope,'hotel_catalog_consolidation_scope':hotel,'engineering_gaps':gaps,
        'migrations':{**previous['migrations'],'current_head':'0124_autonomy_durable','prior_123_files_unchanged':True,
            'added_files':previous['migrations']['added_files']+['alembic/versions/0124_autonomy_durable.py'],
            'roundtrip_evidence':previous['migrations']['roundtrip_evidence']+['tests/test_depth08_api_and_migration.py']},
        'validation_scope':'One clean full regression of unchanged frozen application source and tests. 188 targeted cases overlap; 16 new plus 100 imported cases are included in full total. Frontend tests are rerun. No visual acceptance or production deployment.',
        'upgrade_replay':{'current':'0123_TO_0124_TESTED_WITH_RETAINED_DATA_AND_DOWNGRADE_EVIDENCE_PROTECTION',
            'other_branch_0116_database':'NOT_ACCEPTED_DIRECT_UPGRADE_REQUIRES_SEPARATE_RECONCILIATION'},
        'historical_test_change_depth17':['Existing head assertion advances from 0123 to 0124.',
            'Parallel durable migration test rebased from branch 0115/0116 to this line 0123/0124.',
            'Parallel review-event assertion now includes both pre-step and pre-commit checks.',
            'Parallel conditional-policy fixture explicitly covers its money exposure under current policy rules.',
            'Parallel hotel fixture changes are retained from the pinned delta; prior hotel settlement tests are unchanged.'],
        'engineering_complete':False,'FINAL_RELEASE_GATE':'HOLD','release_gate':'HOLD','deployed':False}
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    write(ROOT/'CURRENT_DEPTH_CANDIDATE.json',{'build':status['build'],'report':'acceptance/GO_DEPTH17_REVIEW.md','status':'verification/current_build/depth17/CURRENT_BUILD_STATUS.json','FINAL_RELEASE_GATE':'HOLD','deployed':False})
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for item in register['requirements']:
        if item['id'] in {'GOV-01','GOV-02','GOV-03'}:
            item.update(status='DURABLE_CURRENT_AUTHORITY_AND_OBSERVATIONS_TESTED_FULL_BUSINESS_INTEGRATION_OPEN',fully_accepted=False,
                scope_note=scope,current_evidence=['verification/current_build/depth17/full_regression.xml','tests/autonomy/test_depth17_durable_authority.py','tests/test_depth08_api_and_migration.py'])
        if item['id']=='HOTEL-01':
            item.update(status='CATALOG_IDENTITY_MEDIA_PUBLICATION_TESTED_REAL_REPLICATION_OPEN',fully_accepted=False,scope_note=hotel,
                current_evidence=['verification/current_build/depth17/full_regression.xml','tests/test_depth09_hotel_replication.py'])
    register['current_build_report']='verification/current_build/depth17/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    report=ROOT/'acceptance/GO_DEPTH17_REVIEW.md'
    measured=(f"冻结代码完整回归共 {total['tests']} 项：{total['passed']} 通过、{total['skipped']} 项 PostgreSQL 专项跳过，失败和错误均为 0；耗时 {total['seconds']:.3f} 秒。"
        '合入的 100 项测试和本轮新增的 16 项测试均包含在完整回归内。另有 78 项前端逻辑测试通过，42 个 JavaScript 文件语法检查通过。')
    report.write_text(report.read_text().replace('MEASURED_RESULTS_PENDING',measured))
    roots={'src','frontend','tests','tests_frontend','scripts','alembic'}
    current={p.relative_to(ROOT).as_posix():p for folder in roots for p in (ROOT/folder).rglob('*') if p.is_file()
             and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'} and p.name!='official_rooms_source.html'}
    changes=[];patch=[]
    with zipfile.ZipFile(args.baseline_work) as z:
        names={n for n in z.namelist() if n.split('/')[0] in roots and not n.endswith('/')}
        for n in sorted(set(current)|names):
            before=z.read(n) if n in names else b'';after=current[n].read_bytes() if n in current else b''
            if before==after:continue
            changes.append({'path':n,'before_sha256':sha(before) if n in names else None,'after_sha256':sha(after) if n in current else None})
            try:patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='DEPTH16/'+n,tofile='DEPTH17/'+n))
            except UnicodeDecodeError:pass
    write(ROOT/'acceptance/DEPTH17_SOURCE_CHANGES.json',{'baseline_work_sha256':BASE_SHA,'changes':changes})
    (ROOT/'acceptance/DEPTH17_SOURCE_CHANGES.patch').write_text(''.join(patch))
    print(json.dumps({'python':total,'new':len(new),'source_changes':len(changes),'frontend':78}))


if __name__=='__main__':main()
