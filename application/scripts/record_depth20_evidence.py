#!/usr/bin/env python3
"""Verify real evidence and record the bounded DEPTH20 engineering result."""
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth20'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def count(p):
    root=ET.parse(p).getroot();cases=list(root.iter('testcase'))
    result={'tests':len(cases),'failures':sum(c.find('failure') is not None for c in cases),
        'errors':sum(c.find('error') is not None for c in cases),'skipped':sum(c.find('skipped') is not None for c in cases)}
    result['passed']=result['tests']-result['failures']-result['errors']-result['skipped']
    suites=list(root.iter('testsuite'));result['seconds']=sum(float(s.get('time','0')) for s in suites)
    return root,result

def main():
    frozen=json.loads((OUT/'full_run_source_fingerprint.json').read_text())['files']
    assert all(sha(ROOT/n)==h for n,h in frozen.items()),'FROZEN_SOURCE_CHANGED'
    root,total=count(OUT/'full_regression.xml');old,prior=count(ROOT/'verification/current_build/depth19/full_regression.xml')
    ids=lambda r:{c.get('classname')+'::'+c.get('name') for c in r.iter('testcase')}
    before,after=ids(old),ids(root);new=after-before
    assert not before-after and len(new)==48 and all('test_depth20_' in n for n in new)
    assert total['tests']==prior['tests']+48 and total['failures']==total['errors']==0
    total['one_clean_full_run']=True
    _,targeted=count(OUT/'targeted.xml');_,restored=count(OUT/'restored_regression.xml');_,front=count(OUT/'frontend_logic.xml')
    assert targeted['tests']==targeted['passed']==77
    assert restored['passed']==restored['tests'] and restored['tests']>=77
    assert front['passed']==front['tests']==99
    syntax=json.loads((OUT/'frontend_syntax.json').read_text());assert syntax['failed']==0
    eq=json.loads((OUT/'restored_source_equivalence.json').read_text())
    assert all(sha(Path(eq['restored_root'])/n)==h for n,h in frozen.items())
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    assert all(sha(ROOT/f['path'])==f['sha256'] for group in immutable.values() for f in group['files'])
    write(OUT/'regression_case_continuity.json',{'baseline_tests':prior['tests'],'retained_case_identities':len(before),'new_case_identities':sorted(new),'removed':[],
        'historical_assertion_changes':'Head advances to 0127. Five historical attraction fixture files explicitly obtain required quotes and identify their participants; all historical testcase identities and behavioral assertions are retained.'})
    write(OUT/'skipped_cases.json',[{'case':c.get('classname')+'::'+c.get('name'),'reason':c.find('skipped').get('message')} for c in root.iter('testcase') if c.find('skipped') is not None])
    previous=json.loads((ROOT/'verification/current_build/depth19/CURRENT_BUILD_STATUS.json').read_text())
    scope=('Rail and attraction quotes durably bind party count, unit/total price, dates, journey/slot and policy. '
        'Signed-in quotes bind the account before consumption; anonymous browsing quotes allow one authenticated owner to claim. '
        'Order creation and quote consumption commit atomically, exact replay returns the same order, and different accounts, bodies or vault IDs cannot reuse it. '
        'Rail confirmations require distinct ticket identities matching party count and exact confirmed replay; reissue checks precede adjustment capture. '
        'Quoted rail fees scale per person; refunds include original and adjustment captures and retain paid change fees. '
        'Customer flows explicitly confirm count, participants, quote and payment; cancellation never substitutes nickname or creates unconfirmed orders. '
        'This is isolated engineering behavior, without provider capacity reservations, full age/ID certification or advanced after-sales concurrency closure.')
    status={**previous,'build':'CP11_DEPTH_20_PARTY_PREBOOK_TICKET_CONTRACT','python':total,
        'baseline':{**previous['baseline'],'depth19_github_commit':'5cb603438bd39699304f3c7b6682d739ba18f386','depth19_delta_sha256':'2dfe21d33f17ee949270f9d927803ba2b1495ebea5da95734ef1b5643cde27d4'},
        'new_backend_cases_passed':48,'targeted_runtime':targeted,'independent_restored_runtime':restored,
        'frontend':{'logic':front,'syntax':syntax,'visual_accepted':False,'frozen_node_22_certified':False,'current_iteration_rerun':True},
        'immutable':{k:{x:g[x] for x in ('count','all_match')} for k,g in immutable.items()},
        'party_prebook_ticket_scope':scope,
        'migrations':{**previous['migrations'],'current_head':'0127_vertical_prebook_contract','prior_126_files_unchanged':True,
            'added_files':previous['migrations']['added_files']+['alembic/versions/0127_vertical_prebook_contract.py']},
        'validation_scope':f"One clean full run over {len(frozen)} frozen source/test/script files. 48 new backend and 11 new frontend cases. Targeted and restored totals overlap the full suite. No browser, provider, production or PostgreSQL acceptance is implied.",
        'engineering_gaps':list(dict.fromkeys(previous['engineering_gaps']+['RAIL_ATTRACTION_CAPACITY_HOLDS_AND_SHARED_INVENTORY','RAIL_ATTRACTION_AGE_ID_QUALIFICATION','RAIL_ATTRACTION_DURABLE_AFTERSALES_CONCURRENCY_AND_RECONCILIATION'])),
        'FINAL_RELEASE_GATE':'HOLD','engineering_complete':False,'deployed':False}
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    write(ROOT/'CURRENT_DEPTH_CANDIDATE.json',{'build':status['build'],'report':'acceptance/GO_DEPTH20_REVIEW.md','status':'verification/current_build/depth20/CURRENT_BUILD_STATUS.json','FINAL_RELEASE_GATE':'HOLD','deployed':False})
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for item in register['requirements']:
        if item['id'] in {'RAIL-01','ATTRACTION-01'}:
            item.update(status='PARTY_QUOTE_BINDING_TESTED_CAPACITY_QUALIFICATION_ADVANCED_AFTERSALES_OPEN',fully_accepted=False,
                source_ids=['V7-P12-08','V7-P13-01','V7-P13-04','V7-P13-05','V7-P21-07' if item['id']=='RAIL-01' else 'V7-P21-08'],
                current_evidence=['tests/test_depth20_prebook_contract.py','tests/test_depth20_attraction_contract.py','tests/test_depth20_api_fulfillment.py','tests_frontend/rail_attraction_booking.test.mjs'],scope_note=scope)
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    report=f'''# GO DEPTH20 工程审阅记录

**HOLD；尚未全面完工，未部署。** 按 V7 P12/P13/P21 的人数、全价、铁路站点席别、门票场次与适用条件继续推进。

- 铁路与门票保存逐笔报价；人数、单价、总价、日期、场次和退改规则均绑定。报价与订单原子提交；相同请求返回原订单，跨账号或改换参与人不能复用。
- 登录后报价在下单前已绑定账号；匿名浏览报价只允许一位消费者领取。失效旧报价拒绝自动补造条款。新迁移 0127 保留历史，有新证据时禁止直接降级。
- 铁路出票要求与人数一致的不同票号；已确认票号不能被重放更换。改签按人数与原报价手续费计算，退款保留历次手续费并退回原票款和改签补款的各自支付来源。
- 客户页面明确选择人数、门票场次及个人库出行人，核对含税总价与规则后创建订单。取消确认不下单；付款取消或中断后仍能打开已有订单。

| 实测 | 结果 |
| --- | --- |
| 累计 Python 回归 | {total['tests']} 项，{total['passed']} 通过，{total['skipped']} PostgreSQL 跳过，0 失败/错误 |
| 本轮后端 / 前端新增 | 48 / 11 项，均包含于相应累计结果 |
| 后端专项 / 独立恢复副本 | {targeted['passed']} / {restored['passed']} 通过，和累计回归重叠 |
| 前端逻辑 / JavaScript 语法 | {front['passed']} / {syntax['passed']} 通过，Node {syntax['node']} |
| 冻结源文件 | {len(frozen)} 个，恢复副本逐个指纹一致 |
| 不变基线 | 126 个历史迁移、3 个母版文件、23 个品牌素材 |

旧用例身份和功能断言保留；5 份门票旧用例显式补齐新接口要求的报价与测试参加人，详见源码差异。

本轮未关闭：跨报价共享库存与持有/释放、独立年龄/证件资格证明、铁路真实新车次报价、改签与退款并发竞争、退款中断后的统一查询与人工核对、部分履约/部分退款。当前库存只是模拟可用数量的观察，不是供应商占位；模拟列车、价格和门票场次不构成真实官方承诺。

母版完整条款分解、六业务高级售后、14 个业务细胞真实执行、实时供应商/支付、PostgreSQL、Redis 切换和跨设备视觉仍需继续。99 项前端逻辑通过不代表视觉验收或冻结 Node 22 认证。
'''
    (ROOT/'acceptance/GO_DEPTH20_REVIEW.md').write_text(report)
    write(OUT/'WORKLOG.json',{'state':'LOCAL_VERIFIED_DELIVERY_PREPARATION','release_gate':'HOLD','github_delivery':'PENDING_REMOTE_READBACK'})
    print(json.dumps({'python':total,'frontend':front,'restored':restored,'source_files':len(frozen)},indent=2))

if __name__=='__main__':main()
