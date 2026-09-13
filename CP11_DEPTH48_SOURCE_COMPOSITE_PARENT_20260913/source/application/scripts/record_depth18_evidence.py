#!/usr/bin/env python3
"""Record actual frozen-build results and retain all incomplete acceptance gates."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth18'
BASE_SHA='1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def counts(path):
    root=ET.parse(path).getroot();suites=list(root.iter('testsuite'))
    result={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
    result['passed']=result['tests']-result['failures']-result['errors']-result['skipped']
    result['seconds']=sum(float(s.get('time','0')) for s in suites)
    return root,result


def main():
    frozen=json.loads((OUT/'full_run_source_fingerprint.json').read_text())['files']
    assert all(sha(ROOT/name)==h for name,h in frozen.items()),'FROZEN_SOURCE_CHANGED'
    root,total=counts(OUT/'full_regression.xml')
    assert total['tests']==1376 and total['failures']==total['errors']==0
    total['one_clean_full_run']=True
    new=[c for c in root.iter('testcase') if 'test_depth18_' in c.get('classname','')]
    assert len(new)==49 and not any(len(c) for c in new)
    _,restored=counts(OUT/'restored_regression.xml')
    assert restored['tests']==92 and not (restored['failures'] or restored['errors'] or restored['skipped'])
    skip=[{'case':c.get('classname')+'::'+c.get('name'),'reason':c.find('skipped').get('message')} for c in root.iter('testcase') if c.find('skipped') is not None]
    write(OUT/'skipped_cases.json',skip)
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    assert all(sha(ROOT/f['path'])==f['sha256'] for group in immutable.values() for f in group['files'])
    previous=json.loads((ROOT/'verification/current_build/depth17/CURRENT_BUILD_STATUS.json').read_text())
    assert json.loads((OUT/'restored_demo_check.json').read_text())['passed']
    old_frozen=json.loads((ROOT/'verification/current_build/depth17/full_run_source_fingerprint.json').read_text())['files']
    front={n:h for n,h in frozen.items() if n.startswith(('frontend/','tests_frontend/'))}
    assert front=={n:h for n,h in old_frozen.items() if n.startswith(('frontend/','tests_frontend/'))}
    write(OUT/'frontend_source_equivalence.json',{'all_match':True,'files':len(front),'baseline_iteration':'DEPTH17',
        'baseline_logic_passed':78,'baseline_syntax_passed':42,'rerun_in_depth18':False,'browser_visual_accepted':False})
    media=('Local SQLite metadata commits preserve concurrent admissions and every rights event across independent processes. '
        'One-time legacy JSON import retains its source hash and refuses malformed input. Revision-bound approvals reject stale writes; '
        'current owner/evidence/contract/expiry gates are rechecked, with no-store media responses. SIGKILL rollback, shared-file purge, '
        'failed writes and content tampering are tested. Each redirect target is checked before request; deployment private-test bypass is disabled. '
        'This does not certify distributed/network filesystems, comprehensive DNS pinning or retroactive removal of previously cached client copies.')
    regional=('Application database queue replaces destructive Redis pop for regional workers. Durable claims, database-time leases, heartbeats, '
        'fenced ACK, bounded backoff and SIGKILL recovery are tested locally. Stable child identities and enqueue evidence commit together; '
        'tier acceptance and next root commit together. Terminal failures have actionable records and atomically linked replacement tasks; '
        'duplicate/recovered incidents do not create duplicate retries or block current completion. Legacy JSON queue exports can be prevalidated '
        'and imported idempotently without deleting Redis. Semantics remain at least once: every discovery adapter side effect is not in one '
        'queue transaction, and real Redis cutover/PostgreSQL execution are not certified. Hotel quality acceptance remains distinct from queue ACK.')
    gaps=[g for g in previous['engineering_gaps'] if g!='REGIONAL_QUEUE_LEASE_ACK_AND_DURABLE_MEDIA_INDEX']
    gaps.append('REGIONAL_ADAPTER_EFFECT_FENCING_DISCOVERY_MEDIA_COUPLING_AND_BOOKING_POOL_PROJECTION')
    status={**previous,'build':'CP11_DEPTH_18_MEDIA_REGIONAL_DURABILITY','python':total,
        'baseline':{**previous['baseline'],'depth17_work_sha256':BASE_SHA,'depth17_github_commit':'b02f65db7c6ce4212e3a4d678b540fb286c14768'},
        'new_backend_cases_passed':len(new),'imported_backend_cases_passed':0,
        'frontend':{**previous['frontend'],'current_iteration_rerun':False,'basis':'DEPTH17_RESULTS_WITH_ALL_FRONTEND_SOURCE_AND_TEST_HASHES_UNCHANGED'},
        'immutable':{k:{a:v[a] for a in ('count','all_match')} for k,v in immutable.items()},
        'engineering_gaps':gaps,
        'blocked_gates':list(dict.fromkeys(previous['blocked_gates']+['REGIONAL_POSTGRESQL_AND_REAL_REDIS_CUTOVER_ACCEPTANCE'])),
        'media_durability_scope':media,'regional_queue_scope':regional,
        'hotel_catalog_consolidation_scope':'DEPTH17 catalog behavior is retained. DEPTH18 adds '+media+' '+regional,
        'validation_scope':'One clean full regression on 856 frozen files, including 49 new cases. Earlier interrupted run is not counted. '
            '107 targeted cases overlap; final queue operational rerun contains 23 cases; 92 cases also pass in an independently restored runtime. '
            'No PostgreSQL, visual, live supplier or production acceptance is claimed.',
        'independent_restored_runtime':restored,
        'migrations':{**previous['migrations'],'current_head':'0125_regional_queue','prior_124_files_unchanged':True,
            'added_files':previous['migrations']['added_files']+['alembic/versions/0125_regional_queue.py'],
            'roundtrip_evidence':previous['migrations']['roundtrip_evidence']+['tests/test_depth18_regional_queue.py::test_migration_roundtrip_preserves_data_and_blocks_loss_of_queue_evidence']},
        'upgrade_replay':{**previous['upgrade_replay'],'current':'0124_TO_0125_TESTED_WITH_RETAINED_DATA_AND_QUEUE_DOWNGRADE_PROTECTION'},
        'historical_test_change_depth18':'Only existing migration-head assertion advances from 0124 to 0125; existing business assertions are unchanged.',
        'master_trace':{'pages':63,'paragraphs':725,'path':'acceptance/MASTER_V7_PARAGRAPH_TRACE.json','full_requirement_decomposition_complete':False}}
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    write(ROOT/'CURRENT_DEPTH_CANDIDATE.json',{'build':status['build'],'report':'acceptance/GO_DEPTH18_REVIEW.md','status':'verification/current_build/depth18/CURRENT_BUILD_STATUS.json','FINAL_RELEASE_GATE':'HOLD','deployed':False})
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for item in register['requirements']:
        if item['id']=='HOTEL-01':
            item.update(status='LOCAL_DURABLE_MEDIA_REGIONAL_RECOVERY_TESTED_REPLICATION_OPEN',fully_accepted=False,
                current_evidence=['verification/current_build/depth18/full_regression.xml','tests/test_depth18_media_durability.py','tests/test_depth18_regional_queue.py','tests/test_depth09_hotel_replication.py'],scope_note=status['hotel_catalog_consolidation_scope'])
    register['source_trace']='acceptance/MASTER_V7_PARAGRAPH_TRACE.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    report=f'''# GO DEPTH18 工程审阅记录

**状态：HOLD；未全面完工，未部署。** 基线为指定 GitHub 仓库中提交 `b02f65d` 的 DEPTH17 WORK。本轮与 V7 母版对照推进媒体持久性和区域任务恢复。

## 本轮完成的实现与实测

- 媒体从整份 JSON 覆盖改为逐资产事务写入。跨进程并发、授权历史、旧 JSON 一次迁移、版本冲突、内容校验及共享文件清理均有运行测试。
- 公开取图重新检查当前授权，并发送 `no-store`；逐跳检查私网地址，部署环境不能启用私网测试开关。已下载的旧缓存不能被新服务追溯收回。
- 区域任务用应用数据库保存，加入租约、续租、完成确认、退避及有限重试。进程被强制终止后任务可恢复，旧租约不能确认新执行。
- 重放不重复产生同一子任务；入队事件与任务一起提交。分层验收与下一层根任务一起提交。耗尽重试会进入异常中心，重新处理与原失败任务的接续关系一并保存。
- 历史 Redis 队列导出可先完整校验，再幂等导入；不会删除 Redis 数据。真实 Redis 切换仍需独立验收。

## 验证结果

| 证据 | 结果 |
| --- | --- |
| 冻结源码完整 Python 回归 | {total['passed']} 通过，{total['skipped']} 跳过，0 失败/错误；共 {total['tests']} 项 |
| 本轮新增用例 | 49 项，包含在完整回归内 |
| 定向回归 | 107 项通过；异常中心最终复测 23 项通过，均与完整回归重叠 |
| 独立恢复副本 | 92 项通过；隔离演示启动检查通过 |
| 前端逻辑/语法 | 与 DEPTH17 全部源文件和测试指纹一致，沿用此前 78 项逻辑及 42 文件语法结果；本轮未重跑 |
| 母版与历史资产 | 124 个历史迁移、3 个母版文件、23 个品牌素材指纹不变 |

曾中止一轮回归以补齐耗尽重试的异常处理记录；该轮不计入最终通过结果。最终完整回归源码保持冻结。

## 验收边界

区域队列保证至少一次交付；租约、确认和入队有数据库约束，但未声称所有发现适配器副作用均与确认处于同一事务，也未声称真实 PostgreSQL 已通过。任务处理结束不等于酒店内容完整，酒店页面仍受目录、图片及质量门禁约束。

当前图片索引适用于本机持久磁盘；不宣称共享网络磁盘、分布式图片存储或完整 DNS 地址固定连接已认证。完整回归跳过的 6 项 PostgreSQL 测试、浏览器视觉验收及冻结 Node 工具链仍未通过。本轮前端未改动，不能据此声称体验已超过携程。

六品类高级售后、部分历史费用/履约结算、外部个人资料连接器、14 个自治单元的完整业务执行适配器、发现到图片/可订供给的联动等仍有缺口，详见状态 JSON。实时渠道接入与隔离功能验收继续分开；缺少真实渠道不作为停止实现隔离功能的理由。

母版追溯表逐段保留 63 页、725 段来源，未评估项仍显式标为未验收。收录母版并不等于完成全部需求分解。

恢复、迁移、旧任务导入及备份步骤见 `GO_DEPTH18_START_HERE.md`。累计源包仍在 DEPTH17 目录，本轮交付小体积增量，避免重复传输运行环境。
'''
    (ROOT/'acceptance/GO_DEPTH18_REVIEW.md').write_text(report)
    print(json.dumps({'python':total,'new_cases':len(new),'restored':restored},indent=2))


if __name__=='__main__':main()
