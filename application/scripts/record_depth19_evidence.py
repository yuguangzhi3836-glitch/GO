#!/usr/bin/env python3
"""Record actual DEPTH19 results only; never convert simulations to live acceptance."""
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth19'
BASE_COMMIT='0037614a4a8339323b40f1904f10c55869b22e34'
BASE_DELTA='e730b477e46b6eea3960bf4bb41912ec78988893867d3d7239c1fce4fabcc4ea'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def count(path):
    root=ET.parse(path).getroot();cases=list(root.iter('testcase'))
    result={'tests':len(cases),'failures':sum(c.find('failure') is not None for c in cases),
        'errors':sum(c.find('error') is not None for c in cases),'skipped':sum(c.find('skipped') is not None for c in cases)}
    result['passed']=result['tests']-result['failures']-result['errors']-result['skipped']
    suites=list(root.iter('testsuite'))
    result['seconds']=sum(float(s.get('time','0')) for s in suites) if suites else sum(float(c.get('time','0')) for c in cases)
    return root,result


def main():
    frozen=json.loads((OUT/'full_run_source_fingerprint.json').read_text())['files']
    assert all(sha(ROOT/n)==h for n,h in frozen.items()),'FROZEN_SOURCE_CHANGED'
    root,total=count(OUT/'full_regression.xml')
    old_root,old_total=count(ROOT/'verification/current_build/depth18/full_regression.xml')
    ids=lambda root:{c.get('classname')+'::'+c.get('name') for c in root.iter('testcase')}
    before,after=ids(old_root),ids(root)
    assert not before-after,'HISTORICAL_CASE_REMOVED'
    new=after-before
    assert len(new)==63 and all('test_depth19_' in n for n in new)
    assert total['tests']==old_total['tests']+len(new) and total['failures']==total['errors']==0
    total['one_clean_full_run']=True
    write(OUT/'regression_case_continuity.json',{'baseline_tests':old_total['tests'],'current_tests':total['tests'],
        'retained_case_identities':len(before),'new_case_identities':sorted(new),'removed':[],
        'historical_assertion_changes':'Migration head advances to 0126. Two legacy P0 cases keep their identities but now require signed current-ticket fixtures and distinguish pending fleet proposals from confirmed pickup time.'})
    _,targeted=count(OUT/'targeted.xml');_,restored=count(OUT/'restored_regression.xml');_,frontend=count(OUT/'frontend_logic.xml')
    assert targeted['tests']==73 and targeted['passed']==73
    assert restored['tests']==122 and restored['passed']==122
    assert frontend['tests']==88 and frontend['passed']==88
    syntax=json.loads((OUT/'frontend_syntax.json').read_text());assert syntax['passed']==43
    assert json.loads((OUT/'restored_worker_cli.json').read_text())['passed']
    assert json.loads((OUT/'restored_demo_check.json').read_text())['passed']
    restored_root=Path(json.loads((OUT/'restored_source_equivalence.json').read_text())['restored_root'])
    assert all(sha(restored_root/n)==h for n,h in frozen.items()),'RESTORED_RUNTIME_DIFFERS'
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    assert all(sha(ROOT/item['path'])==item['sha256'] for g in immutable.values() for item in g['files'])
    skipped=[{'case':c.get('classname')+'::'+c.get('name'),'reason':c.find('skipped').get('message')} for c in root.iter('testcase') if c.find('skipped') is not None]
    write(OUT/'skipped_cases.json',skipped)
    previous=json.loads((ROOT/'verification/current_build/depth18/CURRENT_BUILD_STATUS.json').read_text())
    fact_scope=('Ed25519 signed facts bind current itinerary, traveler, ticket and leg; current independently reviewed authority, '
        'carrier/kind scope, exact HTTPS link hosts, provider/event identity, ordered source sequence and validity are checked. '
        'Reads are owner-scoped and do not create official states. Revocation, amendment or invalid latest evidence removes stale pass links; '
        'official corrections may move to an earlier state. Legacy unsigned records stay unverified. Only local engineering/sandbox sources are supported; '
        'registration cannot enable live providers. Check-in is displayed per traveler and leg on the flight order page.')
    ride_scope=('Server-created immutable engineering offer policy snapshots bound waiting benefits; client rule overrides are rejected. '
        'Extra waiting applies only to signed DELAYED events; early, landed and corrected facts do not automatically gain the benefit. Explicit version-bound tracking matches carrier/flight/date/arrival airport and excludes closed orders. '
        'Verified arrivals create proposals without changing confirmed pickup time. Durable dispatch is recorded before the isolated fleet call; '
        'UNKNOWN/DISPATCHED recovery queries only, including SIGKILL after a separately committed fleet receipt. '
        'Current authority, binding, fact, order, terms and request hash are rechecked before local confirmation. '
        'Conflicting confirmed outcomes remain HOLD in the operational queue. Legacy naive pickup times remain opaque comparison values; '
        'new signed proposed times require offsets. The supplied CLI processes a bounded batch with a disk-backed simulator; '
        'no real fleet/driver workflow, timeout-fee settlement or automatic manual-HOLD resolution is certified.')
    status={**previous,'build':'CP11_DEPTH_19_SIGNED_TRAVEL_FLEET_RECOVERY','python':total,
        'baseline':{**previous['baseline'],'depth18_github_commit':BASE_COMMIT,'depth18_delta_sha256':BASE_DELTA},
        'new_backend_cases_passed':len(new),'frontend':{'logic':frontend,'syntax':{'passed':43,'node':syntax['node']},
            'current_iteration_rerun':True,'visual_accepted':False,'frozen_node_22_certified':False},
        'immutable':{k:{a:v[a] for a in ('count','all_match')} for k,v in immutable.items()},
        'signed_travel_fact_scope':fact_scope,'ride_flight_recovery_scope':ride_scope,
        'engineering_gaps':list(dict.fromkeys(previous['engineering_gaps']+[
            'CHECK_IN_GO_TRIPS_LIST_AND_PREDEPARTURE_UNIFIED_ENTRY',
            'FLEET_DRIVER_ETA_WAIT_EXPIRY_FEES_AND_MANUAL_HOLD_RECONCILIATION'])),
        'blocked_gates':list(dict.fromkeys(previous['blocked_gates']+['LIVE_AIRLINE_FLEET_SIGNER_AND_DRIVER_WORKFLOW_ACCEPTANCE'])),
        'independent_restored_runtime':restored,'targeted_runtime':targeted,
        'migrations':{**previous['migrations'],'current_head':'0126_travel_operational_facts','prior_125_files_unchanged':True,
            'added_files':previous['migrations']['added_files']+['alembic/versions/0126_travel_operational_facts.py'],
            'roundtrip_evidence':previous['migrations']['roundtrip_evidence']+['tests/test_depth19_api_migration.py::test_migration_roundtrip_preserves_legacy_and_refuses_fact_evidence_loss']},
        'upgrade_replay':{**previous['upgrade_replay'],'current':'0125_TO_0126_RETAINS_LEGACY_AND_BLOCKS_EVIDENCE_LOSS'},
        'historical_test_change_depth19':'Two legacy P0 cases retain identities but replace unsigned source-string fixtures with signed current-ticket facts and assert proposal/confirmed-time separation. Existing migration-head assertion advances to 0126. Other historical cases remain unchanged.',
        'validation_scope':f"One clean full run over {len(frozen)} frozen runtime/source/test files. {len(new)} new cases; 73 targeted and 122 independently restored cases overlap. Earlier full runs were interrupted to support legacy naive pickup tokens and to restrict extra wait to verified delays; both are excluded. Final source is independently restored and rechecked. 88 frontend logic and 43 JavaScript syntax checks pass under Node 24.19.0; no visual or Node 22 certification. Isolated worker CLI confirms one request, a second batch does not resend, and production invocation is refused.",
        'next_vertical_audit':'acceptance/RAIL_ATTRACTION_NEXT_CLOSURE_CONTRACT.md',
        'FINAL_RELEASE_GATE':'HOLD','engineering_complete':False,'deployed':False}
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    write(ROOT/'CURRENT_DEPTH_CANDIDATE.json',{'build':status['build'],'report':'acceptance/GO_DEPTH19_REVIEW.md','status':'verification/current_build/depth19/CURRENT_BUILD_STATUS.json','FINAL_RELEASE_GATE':'HOLD','deployed':False})
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for item in register['requirements']:
        if item['id']=='FLIGHT-02':item.update(status='SIGNED_PER_LEG_TRAVELER_FACTS_TESTED_TRIPS_ENTRY_OPEN',fully_accepted=False,
            master_clause='V7 2.6 / P06 / P13',implementation='src/go_hotel/services/travel_operational_facts.py',
            current_evidence=['tests/test_depth19_travel_facts.py','tests/test_depth19_api_migration.py','tests_frontend/travel_status.test.mjs'],
            source_ids=['V7-P06-10','V7-P13-02'],scope_note=fact_scope)
        if item['id']=='RIDE-01':item.update(status='SIGNED_EXACT_FLIGHT_DURABLE_ISOLATED_FLEET_TESTED_DRIVER_SETTLEMENT_OPEN',fully_accepted=False,
            master_clause='V7 4.6 / P22',implementation='src/go_hotel/mobility/ride/flight_sync.py',
            current_evidence=['tests/test_depth19_ride_sync.py','verification/current_build/depth19/restored_worker_cli.json','tests_frontend/travel_status.test.mjs'],
            source_ids=['V7-P06-11','V7-P22-03','V7-P44-05'],scope_note=ride_scope,
            source_correction='The former V5.2-9 label is superseded by the current V7 4.6 clause.')
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    report=f'''# GO DEPTH19 工程审阅记录

**状态：HOLD；尚未全面完工，未部署。** 从已保存的 DEPTH18 提交 `{BASE_COMMIT}` 继续，按 V7 第 2.6、4.6 节及 P06/P13/P22/P44 相关条款完成本轮实现与隔离实测。

## 本轮变化

- 值机改为逐航段、逐乘机人、逐客票事实。登记的公钥验证完整正文签名；来源权限、当前授权、有效时间及顺序均须通过核对。
- 读取不再把缺少事实显示为“值机未开放”。旧无签名记录保留为未验证；正常来源更正可以撤回过时状态。改签、更换客票、乘机人变更或授权撤销后不继续展示旧登机牌。
- 接送规则来自下单时服务器保存的模拟产品条款；客户只能选择条款内的保护，不能自己填写已授权等待上限。
- 航班按航司、航班号、出发日期及到达机场匹配。已关闭订单隔离。事实只产生建议时间；确认前保留原接送安排。
- 外部申请意图先落库。车队模拟器在独立数据库保存回执，断线和 SIGKILL 后只查询原申请。执行和确认均复验当前状态；冲突结果进入待人工核对队列。
- 客户订单页增加值机/登机牌和航班接送面板；明确显示建议时间、已确认时间和未知结果。关联、保护选择及暂停均有明确确认。

## 运行证据

| 检查 | 实测结果 |
| --- | --- |
| 完整 Python 回归 | {total['tests']} 项：{total['passed']} 通过，{total['skipped']} PostgreSQL 跳过，0 失败/错误 |
| 新增后端用例 | {len(new)} 项，包含签名、并发、进程终止与恢复 |
| 专项检查 | 73 项通过，与完整回归重叠 |
| 独立恢复副本 | 122 项通过；原有隔离演示启动检查通过 |
| 隔离车队 CLI | 首批确认一笔，第二批不重发；生产环境调用被拒绝 |
| 前端逻辑 / JavaScript 语法 | 88 / 43 项通过，Node {syntax['node']} |
| 冻结源文件 | {len(frozen)} 个，复测副本逐个指纹相同 |
| 不变基线 | 125 个历史迁移、3 个母版文件、23 个品牌素材 |

旧测试身份全部保留。两项旧 P0 测试替换了无授权来源字符串与直接改时间的旧预期，使用实际签名事实和独立车队确认；详见差异。前两次完整测试为修复旧订单时间兼容和延误保护触发条件而主动中止，不计入通过证据。

## 交付和边界

增量相对 GitHub 中的 DEPTH17 WORK 累计封装，包含 DEPTH18；无需再叠加 DEPTH18。恢复命令见 `GO_DEPTH19_START_HERE.md`。新迁移 `0126_travel_operational_facts` 有数据时禁止直接降级。

本轮签名由隔离供应商真实执行 Ed25519 算法，但不等于实际航司授权已接入。私钥不存入应用。算法接口依据 [cryptography 官方文档](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)。

当前模拟规则的到达至接车偏移为 0；不代表真实机场通关或车队等待承诺。历史无时区接车值作为原始比较条件保留，不推断其时区。车队确认前始终不改订单时间。

隔离创建检查还复现铁路两位成人仍使用一人报价、同一 prebook 跨账号复用，以及门票人数与自由场次缺少绑定。检查未扣款；详见 `next_vertical_audit.json` 与 `acceptance/RAIL_ATTRACTION_NEXT_CLOSURE_CONTRACT.md`，这些缺口尚未关闭。

仍待继续：GO Trips 列表及出发前统一值机入口、司机/ETA 流程、等待超时的费用与取消、未知结果人工核对闭环；六品类高级售后、完整费用结算、14 细胞业务执行与母版完整需求分解。真实供应商、PostgreSQL、Redis 切换、跨设备视觉及冻结 Node 22 工具链均未验收。不得将本轮测试数量、源文索引或工程模拟当作全面完工。
'''
    (ROOT/'acceptance/GO_DEPTH19_REVIEW.md').write_text(report)
    # Baseline the source diff against the sealed DEPTH18 payload, not an earlier scratch copy.
    work=ROOT/'deliverables/GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip'
    delta=ROOT/'deliverables/GO_CP11_DEPTH_18_MEDIA_REGIONAL_DURABILITY_DELTA_20260908.zip'
    assert sha(delta)==BASE_DELTA
    patch=[];changes=[]
    with zipfile.ZipFile(work) as w,zipfile.ZipFile(delta) as d:
        old={f['path']:f for f in json.loads(d.read('RESULT_FILE_MANIFEST.json'))['files']}
        dn=set(d.namelist())
        for name in sorted(set(old)|set(frozen)|{'scripts/assemble_depth19_review.py','scripts/build_depth19_delivery.py','scripts/record_depth19_evidence.py','GO_DEPTH19_START_HERE.md','acceptance/GO_DEPTH19_REVIEW.md','acceptance/DEPTH19_IMPLEMENTATION_BOUNDARY.md','acceptance/RAIL_ATTRACTION_NEXT_CLOSURE_CONTRACT.md','CURRENT_DEPTH_CANDIDATE.json','acceptance/MASTER_CLOSURE_REGISTER.json'}):
            p=ROOT/name
            if not p.is_file():continue
            current=sha(p);prior=old.get(name)
            if prior and current==prior['sha256']:continue
            changes.append({'path':name,'before_sha256':prior['sha256'] if prior else None,'after_sha256':current})
            if p.suffix not in {'.py','.js','.css','.md','.html','.json'}:continue
            original=(d.read('payload/'+name) if 'payload/'+name in dn else w.read(name)) if prior else b''
            patch.extend(difflib.unified_diff(original.decode().splitlines(keepends=True),p.read_text().splitlines(keepends=True),fromfile='DEPTH18/'+name,tofile='DEPTH19/'+name))
    (OUT/'SOURCE_DIFF.patch').write_text(''.join(patch));write(OUT/'SOURCE_CHANGES.json',{'baseline_commit':BASE_COMMIT,'files':changes})
    print(json.dumps({'full':total,'new':len(new),'restored':restored,'release_gate':'HOLD'},indent=2))


if __name__=='__main__':main()
