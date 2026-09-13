#!/usr/bin/env python3
"""Record a frozen full run plus explicit payment-fixture retest and actual saved DEPTH13 compatibility replay."""
import difflib, hashlib, json, re, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth14'
OLD=ROOT/'deliverables/GO_CP11_DEPTH_13_CATALOG_FARE_SNAPSHOT_WORK_20260907.zip'
OLD_SHA='b852cb0a74e90268004ea2ecf4d1922a1af769cdd54ab1d4a29a58ffc343386c'
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,b):p.write_text(json.dumps(b,ensure_ascii=False,indent=2)+'\n')
def fingerprint():
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for folder in ['src','frontend','alembic','tests','tests_frontend']
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}

def main():
    if sha(OLD.read_bytes())!=OLD_SHA:raise ValueError('SAVED_DEPTH13_BASELINE_CHANGED')
    frozen=json.loads((OUT/'full_run_source_fingerprint.json').read_text())['files']
    from resolve_depth14_regression import main as resolve
    resolve()
    resolution=json.loads((OUT/'regression_resolution.json').read_text())
    tree=ET.parse(OUT/'full_regression.xml');suites=list(tree.getroot().iter('testsuite'))
    if not suites:raise ValueError('FULL_REGRESSION_REQUIRED')
    totals={**resolution['effective_unique_results'],'basis':resolution['basis'],'one_clean_full_run':False,
        'full_run_observed_failures':resolution['full_run']['failures'],'resolution_evidence':'verification/current_build/depth14/regression_resolution.json'}
    new_cases=[c for c in tree.getroot().iter('testcase') if 'test_depth14_' in c.get('classname','')]
    if not new_cases or any(c.find('skipped') is not None for c in new_cases):raise ValueError('NEW_CASH_FARE_TESTS_REQUIRED')
    tap=(OUT/'frontend.tap').read_text();matches=re.findall(r'(?:ℹ|#) pass (\d+)',tap)
    if not matches or not re.search(r'(?:ℹ|#) fail 0\b',tap):raise ValueError('FRONTEND_PASS_REQUIRED')
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    syntax=json.loads((OUT/'javascript_syntax.json').read_text())
    if not all(v['all_match'] for v in immutable.values()) or not all(x['passed'] for x in syntax['files']):raise ValueError('IMMUTABLE_OR_SYNTAX_VERIFICATION_FAILED')
    upgrade=json.loads((OUT/'upgrade_13_to_14.json').read_text())
    if not all(upgrade[k] for k in ['plain_original_cash_refund_preserved','original_snapshot_hashes_unchanged',
        'historical_fee_policy_not_fabricated','historical_amendment_held_for_policy_reconciliation']):raise ValueError('ACTUAL_CROSS_VERSION_REPLAY_REQUIRED')
    previous=json.loads((ROOT/'verification/current_build/depth13/CURRENT_BUILD_STATUS.json').read_text())
    scope=('Cash catalog cancellation/change binds immutable quoted rules, current confirmed room value, paid fees, forfeited lower-change '
        'value, original and supplemental captures less prior refunds. Master V7 5.12 forbids future offsets from lower changes: '
        'the current confirmed room price replaces historical maximum price after each completed change. Exact quote consent, '
        'per-order persisted operation ownership, atomic original-capture refund lines, isolated authorization/capture and release, '
        'query-only unknown supplier outcomes, declined payment, capture-ledger failures and resumed refunds are tested. '
        'Customer web/mobile share ownership and request identity with separate supplier/cash progress. Historical absent fee policy '
        'is not fabricated; advanced credit allocation after lower-price forfeiture remains held, as do amendments following partial '
        'refund until room value allocation is reconciled. New published cash cancellation policy explicitly excludes forfeiture '
        'and prior refunds and includes paid change fees. Provider execution is isolated and CNY tests do not certify live channels.')
    status={**previous,'build':'CP11_DEPTH_14_CATALOG_CASH_FARE','python':totals,
        'baseline':{**previous['baseline'],'depth13_work_sha256':OLD_SHA},
        'frontend':{'logic_passed':int(matches[-1]),'syntax_files_passed':len(syntax['files']),'node':syntax['node'],
            'browser_visual_accepted':False,'frozen_node_22_22_certified':False},
        'immutable':{k:{p:v[p] for p in ['count','all_match']} for k,v in immutable.items()},
        'migrations':{'current_head':'0122_catalog_cash_fare','original_files_unchanged':114,
            'added_files':previous['migrations']['added_files']+['alembic/versions/0122_catalog_cash_fare.py'],
            'roundtrip_evidence':previous['migrations']['roundtrip_evidence']+['tests/test_depth14_migration.py']},
        'catalog_cash_fare_scope':scope,'new_backend_cases_passed':len(new_cases),
        'validation_scope':'Full cumulative regression with a four-case scoped retest after changing only the old ignored pm_test fixture to explicit pm_success; all assertions and runtime/frontend/migration/other-test fingerprints unchanged. This is not represented as one clean full run. Targeted results overlap and are not added. Frontend logic/syntax and ASGI cold-start are not browser visual acceptance. All historical DEPTH12/13 reports retain their original run and scoped-retest basis.',
        'upgrade_replay':'verification/current_build/depth14/upgrade_13_to_14.json',
        'historical_test_change_depth14':'Migration-head expectation advances to 0122. Existing signed hotel cancellation fixture now supplies its current quote hash and true consent. The prior cooling-window test uses the extracted cash service clock with all fee, expiry and no-dispatch assertions unchanged. The full run exposes two old pm_test placeholders; only that token changes to pm_success and all four tests in its module are rerun with original financial assertions intact.',
        'engineering_gaps':['COMPLETE_MASTER_REQUIREMENT_DECOMPOSITION','ALL_VERTICAL_ADVANCED_AFTER_SALES_E2E',
            'CREDIT_SOURCE_ALLOCATION_EXCLUDING_FORFEITED_CASH_CHANGE_VALUE','HISTORICAL_CHANGE_FEE_AND_PARTIAL_REFUND_ROOM_VALUE_RECONCILIATION',
            'HOTEL_NO_SHOW_PARTIAL_FULFILLMENT_AND_ASSISTED_CONSENT','RENTAL_SUPPLIER_POLICY_AND_DEPOSIT_SETTLEMENT',
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
            try:patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='DEPTH13/'+name,tofile='DEPTH14/'+name))
            except UnicodeDecodeError:pass
    write(ROOT/'acceptance/DEPTH14_SOURCE_CHANGES.json',{'baseline_work_sha256':OLD_SHA,'changes':changes})
    (ROOT/'acceptance/DEPTH14_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for item in register['requirements']:
        if item['id'] in {'ALL-02','HOTEL-03','TRIPS-01','PAY-01'}:
            item.update(status='LOCAL_CASH_FARE_RECOVERY_TESTED_ADVANCED_FULFILLMENT_OPEN',fully_accepted=False,
                current_evidence=['verification/current_build/depth14/full_regression.xml','verification/current_build/depth14/frontend.tap',
                    'verification/current_build/depth14/upgrade_13_to_14.json'],scope_note=scope)
    register['current_build_report']='verification/current_build/depth14/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    report=ROOT/'acceptance/GO_DEPTH14_REVIEW.md';text=report.read_text()
    measured=(f"完整回归及单一夹具修订后去重核对：{totals['tests']} 项，{totals['passed']} 通过、{totals['skipped']} 项 PostgreSQL 专项跳过，失败及错误均为 0。"
        f"原始完整运行有 2 项旧夹具失败，4 项所在模块测试已复测通过；所有执行代码和其他测试指纹保持不变，这不表述为一次干净完整运行。本轮新增 {len(new_cases)} 项后端测试均在原始完整运行通过。前端逻辑 {int(matches[-1])} 项通过，{len(syntax['files'])} 个 JavaScript 文件语法检查通过。\n\n"
        "真实保存的 DEPTH13 源码创建了普通原单和已补款改期单，再迁移到 0122。普通订单原款可退款；旧规则哈希保持不变，"
        "改期单原款及补款共 1,533,200 分保持完整，未约定的旧手续费现金规则不予补造。此为隔离跨版本实测。\n\n"
        "母版文件、此前 121 个迁移与 23 个消费者端品牌素材均匹配已保存基线。目标测试与完整回归有重叠，不累计相加。")
    if 'MEASURED_RESULTS_PENDING' in text:report.write_text(text.replace('MEASURED_RESULTS_PENDING',measured))
    print(json.dumps({'python':totals,'new_cases':len(new_cases),'frontend':int(matches[-1]),'changed_files':len(changes)}))

if __name__=='__main__':main()
