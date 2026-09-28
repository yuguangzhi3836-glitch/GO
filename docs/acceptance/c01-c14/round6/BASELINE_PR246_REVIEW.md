# Historical PR #246 review before Round 6

Bound to 4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3. These conclusions do not transfer to the new candidate.

## 当前候选：酒店内容审批权限修复，C13限定范围验收通过

- Gate head: `4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3`
- Product: `0bee8d59841ac387b572f2a953e829774f9089b1`
- Application tree: `6ca210c5d459f0e5ff45929a31df0d1edf77d843`；1535 files；SHA256 `92f03f997986b7a45ba150478177a182f10c09c5319ac785a7badbcc8356237a`。
- PRODUCT_FEATURE / TEST_ONLY / DOCUMENTATION；四个应用文件，无迁移、拓扑或部署变更。

已认证只读管理员过去可进入内容审批服务；现路由先检查具体权限，服务再核当前用户/会话/权限与酒店范围的专用隔离绑定。v2快照记录制单主体与完整内容摘要；审批绑定授权ID/摘要和快照摘要。maker不能自批；旧快照、撤权、替换授权、重签改内容、后来拒绝与延迟旧批准重放均不能沿用旧批准。改变决定须明确确认当前决定ID。

开发者31项通过；C13独立42项通过（包括原4个真实HTTP权限探针及7个独立损坏探针），零跳过；C14冻结四文件源审无新增限定规则阻断。**五组同候选CI全部成功；C13核验12份原始ZIP摘要及对应源码/结果，最终结论SCOPED_PASS。历史PASS不转移。** PostgreSQL实际267项全通过：原236范围保留，另含本批26项权限测试及5项既有内容运营测试。

真实酒店授权来源尚未闭环，默认/生产审批HOLD。专用授权只有显式启用的隔离fixture，无公开授予接口，不冒充真实酒店委托。publish/page/booking消费链、媒体权利验证、入住容量闭环仍未完成；本批不声称这些功能通过。继续采用携程学习映射，固定分母305义务/1009场景不变，不自动授予整项PASS、不报100%。

- [本批范围与边界](https://github.com/yuguangzhi3836-glitch/GO/blob/4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3/docs/acceptance/c01-c14/round5/README.md)
- [上一批最终验收及原件摘要归档](https://github.com/yuguangzhi3836-glitch/GO/blob/4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3/docs/acceptance/c01-c14/round5/BASELINE_PR246_REVIEW.md)
- [基线失败与本批审查输入](https://github.com/yuguangzhi3836-glitch/GO/tree/4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3/docs/acceptance/c01-c14/round5/review-inputs)

Draft未合并未部署。真人→指挥中心→调度中心→C01–C14，各领域承担持续运营；C13独立验收、C14规则审查，真人另行对明确版本/环境/范围下达部署指令。

## 最终验收记录

后端全量3154 PASS、7项PostgreSQL专用SQLite跳过，345个文件无漏无重；PG增量267 PASS零跳过，包含两个实际并发用例。Cell455、前端368、兼容34、原有浏览器39检查/28旅程/9 widget-host均通过；这些组有重叠，不相加为独立系统用例总数。

52笔隔离服务交易逐单核对资金根、104 movements、104平衡分录和52完成Trips，零失败；不代表真实支付或生产SLA。移动端pod安装跳过，未做真机验收；旧浏览器回归不计为新酒店界面验收。部署保持未执行。

- [浏览器与PG16：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36192561036)
- [全量回归：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36192561113)
- [PG18与本批增量：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36192561030)
- [Cell：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36192561048)
- [移动端工程检查：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36192561078)

<details>
<summary>c13/candidate/LOCAL_SOURCE_REVIEW.md</summary>

```text
# Round 5 independent local source review

Conclusion: no new blocker found in the four frozen files; suitable for fixed-candidate CI. Not a complete C01 authority, publication, occupancy or operations acceptance.

42 independently executed local tests PASS, zero failures/errors/skips: 31 author cases rerun, original four HTTP permission probes, seven independent approval readback corruption probes. INDEPENDENT.xml records counts. All four frozen file hashes match FROZEN_SOURCE_VERIFICATION.json. Baseline 3PASS/1FAIL and OBSERVED_* remain byte-identical to BASELINE_EVIDENCE_SHA256.json.

The real JWT/DB-session router negative probe now returns readonly403 before absent-snapshot service lookup (baseline409), alongside anonymous401, consumer403 and supplier403. No principal override or hotel approval business write; isolated identity fixture/session writes only. This is the real router auth dependency chain, not the complete main middleware/browser.

Route permissions and service-side persistent active identity/session checks are both present. The reserved hotel/staff role is explicitly test-provisioned and excluded from the existing public staff-role allowlist. Source search found the production row creator only in that restricted staff service; no new public grant route was introduced. Exact hotel/staff/role/state and fixed engineering provenance are checked. Consumption requires local/test/demo plus explicit ISOLATED_FIXTURE configuration; production/missing configuration remains HOLD, and output keeps real_hotel_authority_state=HOLD_UNVERIFIED.

Snapshot maker/checker separation, content/hash/version, current persistent permission, binding-row ID and binding-field digest, latest decision fencing and idempotent replay are checked. The seven independent readback probes corrupt binding_id, binding_hash, snapshot_hash, schema, blank reference, binding creation time, or rehash snapshot maker to the checker while updating the approval snapshot hash. All reject trusted content approval, remain HOLD and add no approval rows. Existing rerun tests also exercise replacement/revocation, latest REJECT with stale APPROVE replay rejection, concurrency and weak legacy snapshots.

Scope limitations: local SQLite only until new PostgreSQL CI; no real hotel grant or proof of hotel delegation, no publication/page gate completion, no media rights completion, no hotel occupancy functionality, no new UI or complete operational loop. Expiry of the login session after a valid decision does not retroactively revoke that decision; current user permission and hotel binding are rechecked. No frozen whole obligation receives automatic PASS; 305 obligations/1009 cases remain unchanged. No deployment performed.
```

</details>

<details>
<summary>c13/candidate/COUNTS.json</summary>

```json
{
  "tests": 42,
  "failures": 0,
  "errors": 0,
  "skipped": 0
}
```

</details>

<details>
<summary>c13/candidate/FROZEN_SOURCE_VERIFICATION.json</summary>

```json
[
  {
    "path": "application/src/go_hotel/services/hosted_content_acceptance.py",
    "sha256": "b283c97b7c36af3938a9cdc1f5bf392433580542dabe1075e362167dd6162db6",
    "match": true
  },
  {
    "path": "application/src/go_hotel/api/routes/hosted_direct_booking.py",
    "sha256": "afa739fe5bb2c2a6848b4c213712fb962b75eeb7d449ee24675747da8e9c49e3",
    "match": true
  },
  {
    "path": "application/tests/test_hosted_content_operations_acceptance.py",
    "sha256": "7a957d79537bdb0e17e26d42afe38c3b987e3070f7a2af8b42cbe3bb06924d4e",
    "match": true
  },
  {
    "path": "application/tests/test_c01_hosted_content_authority.py",
    "sha256": "90bbfa279491b3bb4d5e79fb2d759fc1dabf1d583955f1dea12850bb6d5b640b",
    "match": true
  }
]
```

</details>

<details>
<summary>c13/probe_hotel_approve_permission_candidate.py</summary>

```python
"""Real JWT/DB-session negative route probe; no snapshot or approval writes."""
import json,secrets,os
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from go_hotel.api.routes.hosted_direct_booking import router
from go_hotel.security.service import identity_service
from go_hotel.security.mfa import totp
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedContentApprovalRow

@pytest.mark.parametrize('kind,actor,supplier,roles,expected',[
 ('anonymous',None,None,[],401),('consumer','CONSUMER',None,[],403),
 ('supplier','SUPPLIER_USER','isolated-supplier',['SUPPLIER_OWNER'],403),
 ('readonly','GO_ADMIN',None,['GO_READ_ONLY'],403)])
def test_missing_snapshot_forbidden_before_service(kind,actor,supplier,roles,expected):
 headers={}
 if actor:
  username='c13-r5-'+kind;password=secrets.token_urlsafe(32)
  identity_service.ensure_user(username,password,actor,supplier,roles)
  kw={}
  if actor=='GO_ADMIN':
   e=identity_service.begin_admin_mfa_enrollment(username,password)
   identity_service.confirm_admin_mfa_enrollment(e['enrollment_token'],totp(e['secret']));kw['totp_code']=totp(e['secret'])
  token=identity_service.login(username,password,expected_actor_type=actor,**kw)['access_token']
  p=identity_service.authenticate(token);assert p.actor_type==actor
  if kind=='readonly':assert p.permissions=={'admin:read'}
  headers={'Authorization':'Bearer '+token}
 with SessionLocal() as s:before=s.scalar(select(func.count()).select_from(HostedContentApprovalRow))
 app=FastAPI();app.include_router(router)
 with TestClient(app) as c:
  result=c.post('/internal/v1/hosted-direct/content-snapshots/c13-definitely-missing-round5/approve',headers=headers,json={'approver_role':'HOTEL_AUTHORIZED_OPERATOR','decision':'APPROVE','evidence_reference':'isolated://c13-negative-probe'})
 with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(HostedContentApprovalRow))==before
 (Path(os.environ['C13_OBSERVATION_DIR'])/('OBSERVED_'+kind+'.json')).write_text(json.dumps({'kind':kind,'expected_status':expected,'actual_status':result.status_code,'body':result.json(),'approval_rows_unchanged':True,'authentication':'real password + JWT + DB session; admin MFA; no dependency overrides','scope':'isolated actual router; not full main middleware'},indent=2)+'\n')
 assert result.status_code==expected
```

</details>

<details>
<summary>c14/FINAL_4CAC302_BINDING.md</summary>

```text
# Round5 最终候选限定规则绑定

Head `4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3`；product `0bee8d59841ac387b572f2a953e829774f9089b1`；application tree `6ca210c5d459f0e5ff45929a31df0d1edf77d843`；1535文件；fingerprint `92f03f997986b7a45ba150478177a182f10c09c5319ac785a7badbcc8356237a`。

**4/4冻结文件**已从精确远端head完整取回，独立SHA256与源审冻结记录及本地一致。相对cba99d应用变更恰为这4文件；product→gate无应用变化；v1/v1.1冻结标准无漂移。应用身份与远端CANDIDATE一致，本次未重算全树指纹。

Option A隔离权限修复的限定规则意见保持：持久认证/权限、专用酒店范围fixture、maker/checker、snapshot/hash、批准绑定、最新拒绝与expected_decision_id、旧弱记录HOLD均未发现新增阻断。

这不是酒店真实授权闭环。真实酒店授权及生产批准仍HOLD；publish/page/booking消费、媒体权益、容量和完整UI/运营未闭合。C13独立负责质量与CI，本报告不授305项PASS、真实商业/法律/PSP或部署许可。未修改源码、PR或远端，可保留PRbody而不移动head。
```

</details>

<details>
<summary>c13/probe_approval_readback.py</summary>

```python
import json
from datetime import timedelta
from copy import deepcopy
import pytest
from sqlalchemy import select,func
from tests.test_c01_hosted_content_authority import context,svc,approval_body,SessionLocal,HostedContentApprovalRow,HostedStaffRoleRow,HostedContentSnapshotRow,HostedDirectHotelRow,digest

@pytest.mark.parametrize('fault',['binding_id','binding_hash','snapshot_hash','schema','blank_reference','binding_created','maker_rehashed'])
def test_damaged_approval_or_changed_provenance_is_not_trusted(context,fault):
 hotel,maker,checker,binding,snap=context
 approval=svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 with SessionLocal.begin() as s:
  row=s.get(HostedContentApprovalRow,approval['content_approval_id']);meta=json.loads(row.evidence_reference)
  if fault=='binding_created':s.get(HostedStaffRoleRow,binding).created_at+=timedelta(seconds=1)
  elif fault=='maker_rehashed':
   snapshot=s.get(HostedContentSnapshotRow,snap['content_snapshot_id']);body=deepcopy(snapshot.content_json);body['created_by']=checker.user_id;snapshot.content_json=body;snapshot.content_hash=digest(body);meta['snapshot_hash']=snapshot.content_hash;row.evidence_reference=json.dumps(meta)
  else:
   meta[{'blank_reference':'reference'}.get(fault,fault)]='' if fault=='blank_reference' else 'FORGED';row.evidence_reference=json.dumps(meta)
 with SessionLocal() as s:before=s.scalar(select(func.count()).select_from(HostedContentApprovalRow))
 result=svc.gate(hotel);assert not result['content_approval_verified'] and result['authority_mode']=='HOLD' and result['real_hotel_authority_state']=='HOLD_UNVERIFIED'
 with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(HostedContentApprovalRow))==before
```

</details>

<details>
<summary>c01/NEXT_AUTHORITY_MAPPING.md</summary>

```text
# 下一批：真实资料与 Hosted 酒店／房型的授权关联

本文件是 Round 5 冻结候选 `4cac302` 等待 CI 期间的只读源码评估和下一批建议，不是产品实现、真实酒店授权或新验收 PASS。未访问真实资料库、凭据、供应商或数据库；不能据本次代码阅读断言已有某家酒店的真实 APPROVED manifest。未修改源码、冻结标准或历史证据。

## 结论

现有 direct-submission 审核链可作为**已审资料身份关联的来源**：供应商 → property → canonical hotel，以及 partner room → canonical room。它不能直接授权 Hosted 酒店／库存池，也不能授权某个人代表酒店批准内容。缺少的不是另一个供应商名称字段，而是明确审核的 Hosted 目标关联和酒店人员授权来源。下一批最小交付应先做可撤销、可重验的 Hosted 关联记录与只读诊断，缺真实来源保持 HOLD；容量和发布消费另列后续，不假定随关联记录自动完成。

## 已有关系与代码证据

路径均相对仓库根目录；下述是当前实现观察，不代表实际生产数据已核验。

| 关系 | 当前实现 | 可以复用／限制 |
|---|---|---|
| 登录供应商 → property | `application/src/go_hotel/api/routes/hotel_direct_submission.py:33` 用 supplier principal 的 supplier_id/user_id；`hotel_partner_core._property` 验证 property 所属 | 复用持久身份及 ownership；不得接受 body supplier_id 覆盖主体 |
| property → canonical hotel | `services/hotel_direct_submission_verification.py:38` 要求 registration 的 supplier_id、hotel_id、official_supplement.property_id 对应，且 APPROVED + reviewer/time；canonical 为 GO_DIRECT_VERIFIED/LIVE | 有现成关联检查，但 supplement 是提交资料，真实证据真实性仍依赖审核来源 |
| partner room → canonical room | `services/hotel_direct_submission_manifest.py` 对库存集合和一一对应校验；verification 要求两个全集与当前资料一致 | 映射必须覆盖清单、不得凭相同名称或房数猜测；同房型多个售卖方案不等于多个物理房型 |
| manifest → server review | `services/hotel_direct_submission_review.py:220` approve 锁 review/property，保存 manifest hash + 当前事实 hash；`:261` resolve 重验状态、归属、全部摘要 | 复用不可变提案及失效检查。APPROVED 来源撤销、事实变化均阻断。现服务只接 actor 字符串，未内置 maker-checker；不能原样视为更强人员授权服务 |
| HTTP 审核权限 | `api/routes/hotel_direct_submission.py` writer 先 admin_principal，再检查 admin:rules；批准请求强制两种 hash | 当前 HTTP 不是公开无权限入口。其权限是 GO 资料审核权限，不等于酒店委托；服务扩展须继续验证实际主体 |
| 已审 manifest → canonical 网页 | `services/hotel_direct_submission_publication.py` resolve 后将 review_id/manifest hash 写 direct_submission marker，调用 autopage factory 并读回指针 | 已有 canonical 发布消费；不等于 Hosted 发布路径 |
| Hosted 酒店 | `db/models.py:6287` 只有 hosted_hotel_id、supplier_name、page_slug、city、contact_json 等 | 无 supplier_id/property_id/canonical_hotel_id。pilot 固定名称也不能证明归属 |
| Hosted 物理库存池 | `db/models.py:6347` 有 hosted_hotel_id + physical_room_key 唯一约束、room_details、容量；rate variant 关联 pool→offer | 无 partner_room_id/canonical_room_id/source review。`aoluguya_supply_truth` 的 room_key/rate_plan_key 仅解决 Hosted 内部房型与售卖方案身份 |
| 人员内容授权 | Round 5 `services/hosted_content_acceptance.py` 使用隔离 reserved binding + 当前权限 + snapshot/审批证据摘要 | 明确 fixture-only，不能由真实 manifest 自动生成真实 HOTEL_CONTENT_APPROVER。现公开 staff assign_role 不是可信首授根 |

补充：`hotel_autopage_factory.register_for_go_direct/decide_registration_direct` 保存提交的 evidence、审核者和状态。代码存在审核过程不证明证据已经独立验证，更不证明对 Hosted 目标或酒店人员的授权。不能把 GO_DIRECT_VERIFIED 文案当新的无限权限。

## 下一批最小实现建议（未实施）

优先复用现有 `HotelPartnerChangeRequestRow`，以新专用 `field_group=HOSTED_SUPPLY_BINDING` 保存严格版本化提案，不复用泛化 approve 方法；不把授权字段塞入 contact_json/room_details_json。

1. 一个必要迁移：为 `HostedDirectHotelRow` 增加 nullable 的当前关联记录指针 `active_supply_binding_id`，指向该专用提案记录；历史酒店默认 NULL/HOLD，不按名字回填。提案文档保存 hosted_hotel_id、supplier_id、property_id、canonical_hotel_id、source_review_id、源 manifest/facts hash、版本、完整房型映射及目标事实摘要。映射中每项明确 partner_room_id、canonical_room_id、inventory_pool_id。版本在锁定酒店后分配；受控状态改变不能改写原提案文档。
2. 新服务限定 submit / inspect / approve / revoke / resolve。submit 只产生待审记录，不能替换当前指针。inspect 展示匹配事实、差异、证据与 HOLD 原因。approve 才原子替换当前指针并将旧关联 SUPERSEDED；revoke 原子清空对应当前指针，保留历史。resolve 只认指针指向的有效记录，绝不扫描任意旧 APPROVED 当当前版本。
3. 所有写动作校验服务器持久身份、会话和具体权限，审核人与提交人不同；body 不接受角色自证。复用内部资料审核入口的 UI/权限边界，但**关联资料审核和酒店人员授予是不同操作**，本批不新增公开人员 grant API。审阅者必须看到服务端取出的源 hash 和目标事实差异，客户端只回传乐观锁版本，不手填“批准证明”。
4. Hosted 目标归属必须有独立可核验的关联依据（能指向准确 hosted_hotel_id 和物理库存池的服务端审核记录），不能只引用 manifest 已审、名称相同或管理员选中。现代码未找到这份依据；没有来源时只能提交/诊断 HOLD，不能激活真实绑定。隔离合成 fixture 必须显式标记来源并限制环境，不能当真实迁移数据。
5. 新关联只表达资料身份映射，不授媒体权利、支付资格、真实收费、入住容量政策或个人酒店权限。首次酒店人员权限仍需独立证明其当前供应商归属和具体委托范围；既有 IdentityUser.supplier_id 只证明平台账户归属，不自动证明酒店法定委托。

建议单一闭环验收：**已审源资料 + 明确 Hosted 目标提案 → 独立审核关联 → 当前指针读回 → 源撤销／源事实变化／目标映射变化使新消费 HOLD**。真实源缺失时交付上述隔离工程验证及清晰 HOLD，不宣称真实酒店已开通。

## 并发、撤销及历史兼容

- 新服务统一锁序：source review → partner property → Hosted hotel → 按 ID 排序的 pools。与现 review.approve 的 review→property 顺序一致；消费者不得先拿 Hosted 锁再反向调用开启独立事务的旧 resolve。需新增同事务 resolver，避免检查后撤销竞态与嵌套事务假保护。
- 批准和撤销采用 expected current binding/revision；同一请求重放只返回同一事实，陈旧批准不得覆盖撤销。目标池必须全属于目标酒店，来源 room 必须全属于该 property；禁止重复占用同一物理 pool。是否允许多个 Hosted 酒店映射同 canonical 酒店须先固定业务约束，默认不自动扩 scope。
- 目标事实摘要只覆盖身份和稳定物理资料，不纳入 capacity_available 等销售可变值，避免每次预订令关联失效。房量和入住人数规则不混为一谈。
- 源 review.resolve 当前要求全部当前事实摘要相等，改变早餐/政策等也可能使源失效。诊断必须解释具体源变化；不可为了降低 HOLD 放宽旧摘要。
- 已成交订单和 accepted snapshot 保留原事实，不追溯写入新关联或重算费用。接入 reserve/change 时再增加关联版本成交快照；旧订单只读与已有履约/退款不能因为新关联缺失被抹除。新授予与新消费在来源不足时 HOLD。

## 影响路径与分批范围

| 路径 | 建议处理 |
|---|---|
| models + migration | 仅当前关联 nullable 指针；专用提案和审计复用现表，正式实施前校验 FK/删除策略与 SQLite/PG 兼容 |
| 新 hosted supply binding service / router / 独立 widget | 第一批完整实现范围；root 挂共享导航。真实启用依赖来源，不把 admin 全局权限换名成酒店权限 |
| direct submission review/verification | 复用严格解析与当前事实检查，补同事务 resolver 和权限绑定所需最小接口；不改变已批准 hash 算法或直接迁移历史批准为更强授权 |
| hosted_content_acceptance | 后续消费真实关联仍需独立人员授权；Round 5 fixture 分支不能静默升级 |
| hosted_direct_booking.publish/page | 仍未调用内容审批 gate，page 仍读 live contact；这是明确后续发布消费缺口，不因关联新增而关闭 |
| reserve、hosted_fare_change、hosted_stay_credit、电话订房等 | 后续容量/政策闭环共用当前关联并在成交冻结版本；不要只守 reserve 漏掉改签。当前批不擅改这些产品路径 |
| canonical public_page / direct-submission media | 保留其独立 review/rights 检查；关联不授媒体版权 |

## 必需验证与现有测试起点

现有可复用测试文件：`test_hotel_direct_submission_manifest.py`、`test_hotel_direct_submission_verification.py`、`test_hotel_direct_submission_review.py`、`test_hotel_direct_submission_real_identity.py`、`test_hotel_direct_submission_publication.py`、`test_hotel_direct_submission_full_app.py`、`test_hotel_source_room_mapping.py`、`test_ctrip_rate_plan_identity.py`、Round 5 `test_c01_hosted_content_authority.py`。本次未重跑，不能将它们列为新增功能 PASS。

下一批新增专用测试至少覆盖：真实会话只读 403/供应商跨租户拒绝；maker 自批拒绝；缺真实来源 HOLD；manifest 或事实 hash 变化；foreign hotel/pool 与重复 pool 零写；批准回读同版本；撤销后新 resolve HOLD；旧批准重放不复活；并发批准只一个当前指针；撤销与消费事务竞争；关联替换保留旧文档；生产拒绝合成来源；库存日常变化不误撤关联；已成交快照不改写。SQLite 和 PG 均验证，浏览器实际操作审核/撤销并核 API/DB 事实，不用页面成功提示替代状态断言。

上述属于下一批提案，应由 C13 对照现有 v1.1 义务确认覆盖或正式增版；本文件不增删冻结分母。C14 需确认真实来源与人员委托边界后，才决定可否从 HOLD 进入实际供应商运营。
```

</details>

<details>
<summary>C13 R5_FINAL_REVIEW.md</summary>

```text
# C13 Round 5 independent review — SCOPED PASS

Fixed PR246 head `4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3`; product `0bee8d59841ac387b572f2a953e829774f9089b1`; application `6ca210c5d459f0e5ff45929a31df0d1edf77d843`, 1535 files, fingerprint `92f03f997986b7a45ba150478177a182f10c09c5319ac785a7badbcc8356237a`. No inherited PASS. Conclusion: SCOPED PASS for the isolated hotel content permission/authority fixture repair and enumerated same-candidate regressions.

Remote gate/product parent and equal application tree verified. All 1504 materialized application blobs match remote bytes; CI verifies complete1535 fingerprint including31 inherited assets not locally materialized. Four reviewed product hashes match frozen manifests.

## Increment independently checked

Baseline retained: real password/MFA/JWT/database-session GO_READ_ONLY administrator with only admin:read reached absent-snapshot approval service (409 instead of403). Anonymous401/consumer403/supplier403 controls passed. Approval rows unchanged; no real environment or existing-object unauthorized approval performed. BASELINE_HTTP.xml retains3PASS/1FAIL and original OBSERVED files remain byte-identical.

Frozen repair independently rerun locally:42PASS/0fail/error/skip =31 developer tests +4 original real-session HTTP probes +7 independent readback corruption probes. Read-only now403 before lookup. Both route permission and service current persistent identity/session are enforced. Reserved hotel/staff fixture requires server-held exact scope/state/provenance, local/test/demo plus explicit configuration; default/production remain HOLD. Public staff assignment cannot grant reserved role.

Approval stores binding row ID/digest and snapshot hash; gate checks current persistent permission, binding and immutable content/maker. Replaced/revoked binding, changed/rehashed content, latest REJECT, stale APPROVE replay and legacy weak records cannot silently restore acceptance. Independent corrupt bindingID/hash/snapshotHash/schema/blank-reference/creation-time/rehashed-maker probes all fail closed without new approvals. Idempotency and concurrent snapshots/duplicate decisions are included in31 cases; production grant/race scalability is not established.

## Current-head regression evidence

Browser39checks/28journeys/9widget-host PASS, zero console errors. These are existing regression journeys, not new hotel-authority UI acceptance. Prior rental dispute and no-damage SQL plus same-root compensation4000→3000 reversal→1000net remain valid. Explicit replay200/stale409/readonly403 have no duplicate funds. Read-only SQL source and payload verified; full before-state preserved but final database intentionally not archived, so this is not a local database rerun. Separate operations card automatic synchronization remains unproved.

Frontend368/compatibility34 PASS. Native type/contract/prebuild/module-linking checks PASS; pod install skipped and no physical-device acceptance. PG16six/C07six/C09twelve PASS, zero skip.

Cell455 PASS, zero failures/errors/skips.

Full retention:345 files partitioned exactly once;3161 JUnit-counted cases=3154PASS+7 PostgreSQL-only SQLite skips, zero failures/errors;3117 testcase nodes plus44 subtest count difference. Separate migration seven PASS. The26 increase versus prior full suite is the new authority file; five existing content-operations tests were already in full regression. Groups overlap and must not be added into a distinct system total.

PostgreSQL18.4 original XML:267 PASS, zero failures/errors/skips, including all26 authority tests and five content-operations tests. Both concurrent snapshot versions and duplicate-decision tests actually execute in this group. Separate process12/payment47/outbox1 gates pass. Capacity52 actual isolated service transactions,0 failures: raw-to-SQL52 joins,52 distinct roots, one attempt and authorization/capture per order,104 movements/104 balanced entries,52 completed Trips; concurrency1/4/8 achieved. Workerexit0,14.596984552seconds; cleanup returned without error, no separate post-drop SQL observation. Not an HTTP/real-provider/production SLA measure.

All five exact-head runs completed success: browser36192561036, retention36192561113, PG1836192561030, Cell36192561048, mobile36192561078. All12 original ZIP SHA256 digests match GitHub metadata; enclosed payload/source hashes and counts independently verified. Artifact table: R5_COMPACT_EVIDENCE.json. Previous cba99d PASS is historical only and was not transferred.

## Limits

This scope closes the demonstrated isolated permission-gate defect and verifies the fixture-bound approval/readback mechanism. Real hotel delegation/source grant remains HOLD_UNVERIFIED. It does not complete publication/page consumption, media rights, hotel occupancy, new role UI or the whole operational lifecycle. UNKNOWN money recovery, legacy compensation and upward charging remain outside this increment. No suppliers/PSP/HK/deployment/production were exercised.

Frozen v1.1 remains305 obligations/1009cases; no whole item receives automatic PASS, no100% completion claim, no deployment authorization. Permanent-team configuration and this independent review do not prove continuous runner uptime.
```

</details>

<details>
<summary>C13 R5_COMPACT_EVIDENCE.json</summary>

```json
{
  "result": "SCOPED_PASS",
  "head": "4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3",
  "product": "0bee8d59841ac387b572f2a953e829774f9089b1",
  "application_tree": "6ca210c5d459f0e5ff45929a31df0d1edf77d843",
  "files": 1535,
  "fingerprint": "92f03f997986b7a45ba150478177a182f10c09c5319ac785a7badbcc8356237a",
  "runs": [
    {
      "id": 36192561036,
      "conclusion": "success"
    },
    {
      "id": 36192561113,
      "conclusion": "success"
    },
    {
      "id": 36192561030,
      "conclusion": "success"
    },
    {
      "id": 36192561048,
      "conclusion": "success"
    },
    {
      "id": 36192561078,
      "conclusion": "success"
    }
  ],
  "artifacts": [
    {
      "id": 10888936336,
      "sha256": "705e09f31f94dfb66ea00e3f5e43afbea049661878c65a54f329509f02a3d318",
      "name": "v70-next-depth-pg-C09",
      "payload_verified": 8
    },
    {
      "id": 10889320295,
      "sha256": "dd28fa2e3eb4c5335dd0dc219b33da834c47a913fc84794aa76373987ec67937",
      "name": "canonical-mobile-linking",
      "payload_verified": 0
    },
    {
      "id": 10888733083,
      "sha256": "6f3fd9519ee239dd8b30bcc2588b740f63ecd24f68054894805a45a983b100cc",
      "name": "depth47-browser",
      "payload_verified": 152
    },
    {
      "id": 10888553533,
      "sha256": "37d2e6c05a99083e9e1f82248c9007dacf442de0e8d7f628879912b56a4eec56",
      "name": "v70-cell-closure",
      "payload_verified": 35
    },
    {
      "id": 10888888126,
      "sha256": "968de43b477ea7f22a739f724e79da31bb05e7c9f6618fa9d28c2bab573e331a",
      "name": "canonical-retention-shard-2",
      "payload_verified": 0
    },
    {
      "id": 10888739747,
      "sha256": "f3e900ed1ab2d8a8518fde6ac3337e1accd1d4808f3844e7ab6f0cc2e1d9daaf",
      "name": "canonical-retention-shard-1",
      "payload_verified": 0
    },
    {
      "id": 10888743737,
      "sha256": "690dee43c44badf9b6011aa0559d7c2453c20561142e6d8feee45efb89e295f0",
      "name": "canonical-retention-shard-3",
      "payload_verified": 0
    },
    {
      "id": 10889060964,
      "sha256": "98adad9d194cedddaf952aafe18c3fda5ee0d72ce3038e0f61f51007ddb5cdf1",
      "name": "canonical-frontend-http-compat",
      "payload_verified": 0
    },
    {
      "id": 10889206074,
      "sha256": "a0479058af2680549dcc06b44b222efdf28f7f10958e450da1839ade1f0f00a5",
      "name": "v70-next-depth-pg-C07",
      "payload_verified": 79
    },
    {
      "id": 10888522939,
      "sha256": "1514167147930f5fa5bf5614a8b6d27ff335d4a6f253b4cf51a6b1463ddaf08f",
      "name": "depth47-postgres",
      "payload_verified": 0
    },
    {
      "id": 10889541632,
      "sha256": "cd31ba9afeec082e2315e045a1b56c59e310fccc49b1637e3e1ccbfbc67102af",
      "name": "v70-next-depth-pg-C11",
      "payload_verified": 112
    },
    {
      "id": 10888379090,
      "sha256": "1c4d880a6f7dce5fdd2ece41368442a0cdcbd245a408f0e928d41379e85565e0",
      "name": "canonical-retention-shard-0",
      "payload_verified": 0
    }
  ],
  "separate_counts_not_additive": {
    "sqlite_tests": 3161,
    "sqlite_pass": 3154,
    "sqlite_pg_only_skips": 7,
    "pg_increment": 267,
    "pg_hotel_authority": 26,
    "pg_hotel_content_operations": 5,
    "cell": 455,
    "browser": 39,
    "journeys": 28,
    "widget_host": 9,
    "frontend": 368,
    "compatibility": 34,
    "capacity_transactions": 52,
    "capacity_failures": 0,
    "local_independent": 42
  },
  "baseline_defect": "READ_ONLY absent approval409; retained failed HTTP evidence",
  "fixed_result": "READ_ONLY403 before object lookup",
  "limits": [
    "real hotel delegation HOLD_UNVERIFIED",
    "publication/media rights/occupancy not completed",
    "old browser regressions do not prove new hotel UI",
    "native pod installation skipped; no physical devices",
    "UNKNOWN money recovery remains HOLD",
    "no automatic305obligation PASS",
    "no deployment"
  ]
}
```

</details>

<details>
<summary>C13 R5_RETENTION_REVIEW.json</summary>

```json
{
  "head": "4cac30225c3094ded0bc1d2aa06d1b3960c7bfe3",
  "counts": {
    "selected_files": 345,
    "tests": 3161,
    "passed": 3154,
    "failures": 0,
    "errors": 0,
    "skipped": 7
  },
  "all_inventory_partition_verified": true,
  "testcase_nodes": 3117,
  "subtest_difference": 44,
  "separate_migration_tests": 7,
  "shards": [
    {
      "exit_code": 0,
      "selected_files": 87,
      "shard": 0,
      "real_providers": "NOT_RUN",
      "hong_kong": "NOT_ACCESSED",
      "tests": 841,
      "failures": 0,
      "errors": 0,
      "skipped": 1,
      "passed": 840
    },
    {
      "exit_code": 0,
      "selected_files": 86,
      "shard": 1,
      "real_providers": "NOT_RUN",
      "hong_kong": "NOT_ACCESSED",
      "tests": 825,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "passed": 825
    },
    {
      "exit_code": 0,
      "selected_files": 86,
      "shard": 2,
      "real_providers": "NOT_RUN",
      "hong_kong": "NOT_ACCESSED",
      "tests": 822,
      "failures": 0,
      "errors": 0,
      "skipped": 5,
      "passed": 817
    },
    {
      "exit_code": 0,
      "selected_files": 86,
      "shard": 3,
      "real_providers": "NOT_RUN",
      "hong_kong": "NOT_ACCESSED",
      "tests": 673,
      "failures": 0,
      "errors": 0,
      "skipped": 1,
      "passed": 672
    }
  ]
}
```

</details>

<details>
<summary>C13 R5_RETENTION_SKIPS.json</summary>

```json
[
  {
    "classname": "tests.test_p0_0101_postgres_race_matrix",
    "name": "test_0101_order_payment_root_exactly_once_postgres",
    "reason": "POSTGRES_TEST_DATABASE_URL not configured"
  },
  {
    "classname": "tests.test_p0_0101_postgres_race_matrix",
    "name": "test_0101_webhook_delivery_replay_unique_postgres",
    "reason": "POSTGRES_TEST_DATABASE_URL not configured"
  },
  {
    "classname": "tests.test_p0_0101_postgres_race_matrix",
    "name": "test_0101_capture_refund_serialization_postgres",
    "reason": "POSTGRES_TEST_DATABASE_URL not configured"
  },
  {
    "classname": "tests.test_p0_0101_postgres_race_matrix",
    "name": "test_0101_finance_close_approval_race_postgres",
    "reason": "POSTGRES_TEST_DATABASE_URL not configured"
  },
  {
    "classname": "tests.test_p0_0101_postgres_race_matrix",
    "name": "test_0101_postgres_server_is_real_postgres",
    "reason": "POSTGRES_TEST_DATABASE_URL not configured"
  },
  {
    "classname": "tests.test_p0_0100_postgres_concurrency",
    "name": "test_order_payment_root_unique_under_postgres_race",
    "reason": "POSTGRES_TEST_DATABASE_URL not configured"
  },
  {
    "classname": "tests.test_outbox_resilience",
    "name": "test_postgresql_two_workers_claim_one_row_once",
    "reason": "requires PostgreSQL row-lock semantics"
  }
]
```

</details>

