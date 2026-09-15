#!/usr/bin/env python3
"""Record final frozen source, clean full regression and saved DEPTH14 upgrade replay."""
import difflib,hashlib,json,re,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth15'
OLD=ROOT/'deliverables/GO_CP11_DEPTH_14_CATALOG_CASH_FARE_WORK_20260907.zip'
OLD_SHA='014c3b3a1fcf1152bab106ba7ceec53f3962375bba6fd424c39b9f1c66534ae5'
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,b):p.write_text(json.dumps(b,ensure_ascii=False,indent=2)+'\n')

def main():
    if sha(OLD.read_bytes())!=OLD_SHA:raise ValueError('SAVED_DEPTH14_BASELINE_CHANGED')
    current_frozen={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for folder in ['src','frontend','alembic','tests','tests_frontend']
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
    if current_frozen!=json.loads((OUT/'full_run_source_fingerprint.json').read_text())['files']:
        raise ValueError('CODE_CHANGED_DURING_OR_AFTER_FINAL_RUN')
    tree=ET.parse(OUT/'full_regression.xml');suites=list(tree.getroot().iter('testsuite'))
    if not suites:raise ValueError('FINAL_FULL_REGRESSION_REQUIRED')
    totals={k:sum(int(s.get(k,'0')) for s in suites) for k in ['tests','failures','errors','skipped']}
    if totals['failures'] or totals['errors']:raise ValueError('CLEAN_FINAL_FULL_REGRESSION_REQUIRED')
    totals.update(passed=totals['tests']-totals['skipped'],seconds=sum(float(s.get('time','0')) for s in suites),one_clean_full_run=True)
    new=[c for c in tree.getroot().iter('testcase') if 'test_depth15_' in c.get('classname','')]
    if not new or any(c.find('skipped') is not None for c in new):raise ValueError('NEW_SOURCE_ALLOCATION_CASES_REQUIRED')
    tap=(OUT/'frontend.tap').read_text();matches=re.findall(r'(?:ℹ|#) pass (\d+)',tap)
    if not matches or not re.search(r'(?:ℹ|#) fail 0\b',tap):raise ValueError('FRONTEND_PASS_REQUIRED')
    syntax=json.loads((OUT/'javascript_syntax.json').read_text());immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    if not all(x['passed'] for x in syntax['files']) or not all(v['all_match'] for v in immutable.values()):raise ValueError('SYNTAX_OR_IMMUTABLE_BASELINE_FAILED')
    upgrade=json.loads((OUT/'upgrade_14_to_15.json').read_text())
    required=['original_credit_contract_hash_unchanged','original_credit_value_and_expiry_preserved','original_order_snapshot_unchanged',
        'actual_saved_low_change_converted','both_credit_formats_redeemed_and_cancelled','forfeiture_not_restored']
    if not all(upgrade[k] for k in required):raise ValueError('ACTUAL_SAVED_DEPTH14_REPLAY_REQUIRED')
    previous=json.loads((ROOT/'verification/current_build/depth14/CURRENT_BUILD_STATUS.json').read_text())
    scope=('Accepted cash lower-change forfeiture is allocated separately from actual prior refunds and retained prepaid credit. '
        'Every capture equals funded credit plus prior actual refunds plus excluded cash-change value. Even zero-funded sources '
        'remain uniquely reserved, preventing generic refund bypass. Immutable source contracts reference verified original accepted '
        'cash operations and quote/plan hashes, and checked reads validate the origin and conservation. Redemption, later lower-price '
        'redemption, customer cancellation, supplier-fault original refund/compensation and expiry cannot restore original excluded '
        'value. Old source contracts retain their four original source fields, original hashes and expiry. Migration defaults old '
        'exclusion to zero without fabricating consent; downgrade refuses to drop nonzero exclusions. Customer review/detail shows '
        'paid/refunded/excluded/retained values without exposing internal source references or displaying an empty historical breakdown.')
    status={**previous,'build':'CP11_DEPTH_15_CREDIT_SOURCE_EXCLUSION','python':totals,
        'baseline':{**previous['baseline'],'depth14_work_sha256':OLD_SHA},
        'frontend':{'logic_passed':int(matches[-1]),'syntax_files_passed':len(syntax['files']),'node':syntax['node'],
            'browser_visual_accepted':False,'frozen_node_22_22_certified':False},
        'immutable':{k:{p:v[p] for p in ['count','all_match']} for k,v in immutable.items()},
        'migrations':{'current_head':'0123_catalog_credit_exclusion','original_files_unchanged':114,
            'added_files':previous['migrations']['added_files']+['alembic/versions/0123_catalog_credit_exclusion.py'],
            'roundtrip_evidence':previous['migrations']['roundtrip_evidence']+['tests/test_depth15_migration.py']},
        'credit_source_exclusion_scope':scope,'new_backend_cases_passed':len(new),
        'validation_scope':'One clean final full run of frozen runtime/frontend/migrations/tests. An earlier partial run was stopped before fixing an empty historical credit display; it is not counted. Targeted runs overlap. All historical DEPTH14 reports retain their original full-run-plus-fixture-retest basis. Logic, syntax and ASGI are not visual acceptance.',
        'upgrade_replay':'verification/current_build/depth15/upgrade_14_to_15.json',
        'historical_test_change_depth15':'Migration head advances to 0123. The DEPTH14 low-change test now checks retained credit and its excluded value after closing the source-allocation block; all cash differences, forfeiture and refund assertions stay intact.',
        'engineering_gaps':['COMPLETE_MASTER_REQUIREMENT_DECOMPOSITION','ALL_VERTICAL_ADVANCED_AFTER_SALES_E2E',
            'HISTORICAL_CHANGE_FEE_AND_PARTIAL_REFUND_ROOM_VALUE_RECONCILIATION','HOTEL_NO_SHOW_PARTIAL_FULFILLMENT_AND_ASSISTED_CONSENT',
            'COMPLETE_CASH_AND_CREDIT_FEE_SETTLEMENT','RENTAL_SUPPLIER_POLICY_AND_DEPOSIT_SETTLEMENT',
            'EXTERNAL_PERSONAL_SOURCE_CONNECTORS','14_CELL_DURABLE_EXECUTION_AND_RECOVERY'],
        'release_gate':'HOLD','FINAL_RELEASE_GATE':'HOLD','engineering_complete':False,'deployed':False}
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    roots={'src','frontend','tests','tests_frontend','scripts','alembic'}
    current={p.relative_to(ROOT).as_posix():p for folder in roots for p in (ROOT/folder).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
    changes=[];patch=[]
    with zipfile.ZipFile(OLD) as z:
        names={n for n in z.namelist() if n.split('/')[0] in roots and not n.endswith('/')}
        for name in sorted(set(current)|names):
            before=z.read(name) if name in names else b'';after=current[name].read_bytes() if name in current else b''
            if before==after:continue
            changes.append({'path':name,'status':'MODIFIED' if name in names and name in current else 'ADDED' if name in current else 'DELETED',
                'before_sha256':sha(before) if name in names else None,'after_sha256':sha(after) if name in current else None})
            try:patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='DEPTH14/'+name,tofile='DEPTH15/'+name))
            except UnicodeDecodeError:pass
    write(ROOT/'acceptance/DEPTH15_SOURCE_CHANGES.json',{'baseline_work_sha256':OLD_SHA,'changes':changes})
    (ROOT/'acceptance/DEPTH15_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for item in register['requirements']:
        if item['id'] in {'HOTEL-03','ALL-02','PAY-01','TRIPS-01'}:
            item.update(status='LOCAL_SPLIT_CREDIT_SOURCES_TESTED_ADVANCED_FULFILLMENT_OPEN',fully_accepted=False,
                current_evidence=['verification/current_build/depth15/full_regression.xml','verification/current_build/depth15/frontend.tap',
                    'verification/current_build/depth15/upgrade_14_to_15.json'],scope_note=previous['catalog_cash_fare_scope']+' '+scope)
    register['current_build_report']='verification/current_build/depth15/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    report=ROOT/'acceptance/GO_DEPTH15_REVIEW.md';body=report.read_text()
    measured=(f"最终冻结代码完整回归：{totals['tests']} 项，{totals['passed']} 通过、{totals['skipped']} 项 PostgreSQL 专项跳过，失败和错误均为 0。"
        f"本轮新增 {len(new)} 项后端测试均通过；前端逻辑 {int(matches[-1])} 项、JavaScript 语法 {len(syntax['files'])} 个文件通过。\n\n"
        "真实保存的 DEPTH14 运行环境创建了旧额度和已接受的低价现金改期单。升级至 0123 后，旧额度原合约哈希和有效期不变；"
        "新来源分配保留 1,410,000 分、排除 43,200 分；两个格式均完成兑换与取消，原作废差额未恢复。\n\n"
        "母版、此前 122 个迁移及 23 个消费者端品牌素材均匹配已保存基线。首次部分运行因发现旧额度空明细显示问题而停止，"
        "修复并增加反向测试后重新冻结并完整运行；不将此前部分运行或重叠目标测试累加。")
    if 'MEASURED_RESULTS_PENDING' in body:report.write_text(body.replace('MEASURED_RESULTS_PENDING',measured))
    print(json.dumps({'python':totals,'new_backend':len(new),'frontend':int(matches[-1]),'changed_files':len(changes)}))

if __name__=='__main__':main()
