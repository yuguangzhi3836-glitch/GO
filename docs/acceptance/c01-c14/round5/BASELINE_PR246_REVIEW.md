## 当前候选：结算后申诉减收补偿，C13限定范围验收通过

- Gate head: `cba99d085ffe8ff576e44120ac796e59b4ff11bf`
- Product: `1ee6fd666ac32bf712b951080ae9d80714a51d47`
- Application tree: `d487902d1bf40fdb1c50092265631575ab1e7c49`；1534 files；SHA256 `fe7dfed28cc3ce49d7666a9f18babccf4d5deb4917eff441074fdbb2eee87007`。
- 变更类别：PRODUCT_FEATURE、TEST_ONLY、DOCUMENTATION。未改变服务拓扑或新增迁移。

本批C04提供当前独立减收决定及历史来源校验；C11在同一资金根的原扣款上追加COMPENSATION与精确反向分录，金额由权威决定和已有资金计算。重复不重复退、多次减收只退差额、不恢复可扣余额。消费者显示原扣收、累计补偿、净收；状态读回也核历史来源/parent/账户，不凭总借贷平衡误报成功。

本地前端368 PASS；C13独立局部C04 18/18、C11 30/30（包含17项独立损坏探针）零失败/错误/跳过，14文件哈希匹配；C14十产品文件源审无新增规则阻断。**同一候选五组CI全部成功；C13已核对12份原始artifact的SHA256，最终结论SCOPED_PASS。旧候选PASS不转移。**

新增真实UI独立订单补偿及只读SQL前后精确对比，原26journeys/9widget/旧SQL不删；PG增量保留205原范围并新增31测试。

验收标准仍v1.1.0 305义务/1009场景。UNKNOWN没有独立可信回执，本批不实现成功恢复；旧完整账码补偿及上调再收费仍HOLD。酒店容量仅完成下一批设计/权限风险定位，未实现、不授PASS。

- [本批范围及后续](https://github.com/yuguangzhi3836-glitch/GO/blob/cba99d085ffe8ff576e44120ac796e59b4ff11bf/docs/acceptance/c01-c14/round4/README.md)
- [上一批完整验收及历史失败归档](https://github.com/yuguangzhi3836-glitch/GO/blob/cba99d085ffe8ff576e44120ac796e59b4ff11bf/docs/acceptance/c01-c14/round4/BASELINE_PR246_REVIEW.md)
- [固定验收清单](https://github.com/yuguangzhi3836-glitch/GO/blob/cba99d085ffe8ff576e44120ac796e59b4ff11bf/docs/acceptance/c01-c14/v1.1/README.md)

Draft未合并未部署。职责沿真人→指挥中心→调度→C01–C14，各域持续运营；C13独立验收、C14规则审查，部署仍需真人明确版本/环境/范围指令。

## 最终验证与边界

- 后端全量3128 PASS、7项PostgreSQL专用SQLite跳过；PG增量236 PASS、零跳过；Cell455 PASS；前端368 PASS；浏览器39检查、28旅程、9 widget/host检查全部通过。各组范围重叠，不合并为独立用例总数。
- 52笔隔离服务交易、零失败；逐单核对52资金根、104 movements、104平衡分录、52完成Trips。此结果不是生产吞吐承诺。
- 示例原扣收40元，独立申诉改为10元，同原扣款追加30元补偿；原记录保持，重复与过期请求不产生额外资金效果。仅隔离模拟，不证明真实到账。
- 顾客资金面板经显式刷新读回；另一运营卡片仍为标明的上次请求快照。跨组件自动同步未验证。移动端未进行真机验收，pod安装跳过。
- UNKNOWN可信恢复、旧账格式补偿、上调再收费仍HOLD。305义务/1009场景不因本批通过而自动授予整项PASS，不声称100%。
- 下一批优先补酒店内容审批权限与酒店授权绑定，再接入住容量政策→可售查询→预订→订单快照读回；携程学习映射继续用于验收，竞品默认规则不直接变为GO政策。

- [浏览器与PG16：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36138734683)
- [全量回归：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36138733958)
- [PG18：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36138733787)
- [Cell：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36138733782)
- [移动端工程检查：success](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36138734272)

<details>
<summary>c13/CBA_FINAL_REVIEW.md</summary>

```text
# C13 Round 4 independent review — SCOPED PASS

Conclusion: SCOPED PASS for the frozen isolated post-settlement compensation increment and enumerated regression gates. Fixed PR246 candidate: `cba99d085ffe8ff576e44120ac796e59b4ff11bf`; product `1ee6fd666ac32bf712b951080ae9d80714a51d47`; application tree `d487902d1bf40fdb1c50092265631575ab1e7c49`; 1534 files, fingerprint `fe7dfed28cc3ce49d7666a9f18babccf4d5deb4917eff441074fdbb2eee87007`.

Remote gate parent/product/application equality independently checked. All 1503 locally materialized application blobs match the remote Git tree; CI full 1534-file fingerprint also matches, including 31 inherited assets not materialized locally. The 10 changed application and four harness files match reviewed manifests. Historical cb8928f results were not transferred.

Confirmed same-candidate evidence:
- Browser: 39 checks, 28 journeys (original 26 plus two compensation journeys), nine mocked widget/host checks; all PASS, zero unhandled console errors. Independent SQL for previous two rental operations remains PASS; old accepted ride policy survives replacement/revocation.
- New compensation: original capture 4000 minor units, release 196000, independent appeal reduces award to 1000, additional same-capture compensation 3000. Customer money panel displays ¥30.00 compensated and ¥10.00 net. The original root/intent/fact, three movements and two ledger rows remain unchanged according to the bound read-only SQL auditor; final four movements/four ledger entries have exact reversed parent accounts. Replay200, stale409 and read-only403 cause no duplicate financial effects.
- Complete before-state snapshot SHA256 `2c842e2f5fcbfd7d6379de19bb428a4f5e4a950966aab29eaa3f35783decc76f` joins browser order/obligation/capture and SQL audit. Final database/full after-state was not archived; C13 verified the auditor source, execution result and bindings, not a local SQL rerun.
- Cell: 455 PASS, zero failures/errors/skips. Frontend: 368 PASS, zero skips; compatibility:34 PASS. PostgreSQL16:6 PASS; PostgreSQL18 C07:6 and C09:12 PASS.
- Independent local C13: C04 18 and C11 30 PASS, including 17 independent corruption probes. Rehashed historical semantic corruption and balanced-but-untrusted compensation never produce trusted status totals; both consumer and admin readers fail closed without writes. Full hashes/counts and reproducible probes are separately retained.

- Full Python retention: exact partition of 344 files, 3135 JUnit-counted cases = 3128 passed + 7 PostgreSQL-only SQLite skips, zero failures/errors. 3091 testcase nodes plus 44 subtest count difference; separate migration history seven PASS. Groups overlap and are not summed into one distinct system total.

- PostgreSQL18.4: actual increment 236 PASS, zero failures/errors/skips, including all 21 C11 compensation and 10 C04 authority cases. Separate process12/payment47/outbox1 gates also pass. Capacity: 52 actual service transactions, zero failures, concurrency1/4/8 achieved; raw results independently joined to 52 SQL orders/roots, each one attempt, one authorization/capture, 104 distinct movements and 104 balanced ledger entries, 52 completed Trips. Worker exit0, 12.58064776 seconds; cleanup returned without error, with no separate post-drop SQL proof. This is isolated service-transaction capacity, not HTTP/real-provider/production SLA.

All five runs completed successfully at this exact head: browser36138734683, retention36138733958, PG18 36138733787, Cell36138733782, mobile36138734272. All 12 original artifact ZIP SHA256 digests match GitHub metadata; enclosed payload hashes, test source and application fingerprints were checked. Full artifact digest table is CBA_COMPACT_EVIDENCE.json. No prior-head PASS was inherited.

Limits: isolated internal engineering only. UNKNOWN trusted recovery, legacy-account compensation and upward-charge authorization remain HOLD. No real supplier, PSP, HK deployment or production acceptance. Native type/contract/prebuild/module-linking checks are not physical-device acceptance; pod installation is skipped. Customer money panel was explicitly refreshed; a separate operations card remains an explicitly labeled last-request snapshot with manual refresh. Cross-component automatic synchronization is unproved. Hotel occupancy is next-batch design only.

The frozen v1.1 denominator remains 305 obligations/1009 cases. This limited integration review assigns no automatic whole-obligation PASS and makes no 100% completion claim. C13 independent evidence review does not establish permanent runner uptime or authorize deployment.
```

</details>

<details>
<summary>c13/CBA_COMPACT_EVIDENCE.json</summary>

```json
{
  "result": "SCOPED_PASS",
  "head": "cba99d085ffe8ff576e44120ac796e59b4ff11bf",
  "product": "1ee6fd666ac32bf712b951080ae9d80714a51d47",
  "application_tree": "d487902d1bf40fdb1c50092265631575ab1e7c49",
  "source_files": 1534,
  "source_fingerprint": "fe7dfed28cc3ce49d7666a9f18babccf4d5deb4917eff441074fdbb2eee87007",
  "runs": [
    {
      "id": 36138734683,
      "conclusion": "success"
    },
    {
      "id": 36138733958,
      "conclusion": "success"
    },
    {
      "id": 36138733787,
      "conclusion": "success"
    },
    {
      "id": 36138733782,
      "conclusion": "success"
    },
    {
      "id": 36138734272,
      "conclusion": "success"
    }
  ],
  "artifacts": [
    {
      "id": 10865802068,
      "sha256": "81f170fc19866b995566583a0bc86302e89c799be4409d6e7ca19679c971d790",
      "name": "v70-cell-closure",
      "payload_verified": 35
    },
    {
      "id": 10866327078,
      "sha256": "3c294347169b3908e25cf350729e22c8cb3b4c6df5456d293ee7ca233d8cc358",
      "name": "canonical-retention-shard-1",
      "payload_verified": 0
    },
    {
      "id": 10865944612,
      "sha256": "cd106012f54017446194ca7cf4adfa290c1ff1c20aa681d92312911a5ca728b5",
      "name": "v70-next-depth-pg-C11",
      "payload_verified": 112
    },
    {
      "id": 10866045613,
      "sha256": "748d1897cb5d2792f73621688d4237138cd7d2cecb35d148b431a214e5047f29",
      "name": "v70-next-depth-pg-C09",
      "payload_verified": 8
    },
    {
      "id": 10865870894,
      "sha256": "cfc27e1ba0b8ccc7e9cb3a0389b4ec186eb2751e470f5605d08ea85ea0c273c9",
      "name": "v70-next-depth-pg-C07",
      "payload_verified": 79
    },
    {
      "id": 10865903166,
      "sha256": "9283032f821f240a89e58a65b62acae4470c7c0e7d4debb1405b3a025919b9e7",
      "name": "canonical-retention-shard-2",
      "payload_verified": 0
    },
    {
      "id": 10866711165,
      "sha256": "7754f99e5cb89023af240bd41b72e4ba6add57511bb908b7f6232562d1206462",
      "name": "canonical-retention-shard-0",
      "payload_verified": 0
    },
    {
      "id": 10865751262,
      "sha256": "4b7cd993fab82884711f5ceb6046c7a65a0400f875ca5416b6ede551d8a6a189",
      "name": "depth47-browser",
      "payload_verified": 152
    },
    {
      "id": 10866095509,
      "sha256": "33aea59a195ddb583030f7fd1787998cd6f608e99252237e507f3f98a79a9b7e",
      "name": "canonical-mobile-linking",
      "payload_verified": 0
    },
    {
      "id": 10865997127,
      "sha256": "51aea783d7ca958632364fb43b9e030054ca4f492ce54858fad3a9f54aa51022",
      "name": "canonical-retention-shard-3",
      "payload_verified": 0
    },
    {
      "id": 10866255460,
      "sha256": "36a4d45f512f4aa071183ade427f86a4f6ad89c49d7decb5f62c1e1f7f904631",
      "name": "canonical-frontend-http-compat",
      "payload_verified": 0
    },
    {
      "id": 10864564733,
      "sha256": "a189ad028b26e6ee7bf4b2aff0216140bb2dac595341f978db43967bf142012b",
      "name": "depth47-postgres",
      "payload_verified": 0
    }
  ],
  "counts_separate_not_additive": {
    "sqlite_total": 3135,
    "sqlite_pass": 3128,
    "sqlite_skips": 7,
    "pg_increment_pass": 236,
    "new_pg_authority": 10,
    "new_pg_compensation": 21,
    "cell_pass": 455,
    "browser_checks": 39,
    "journeys": 28,
    "widget_host": 9,
    "frontend": 368,
    "compatibility": 34,
    "capacity_transactions": 52,
    "capacity_failures": 0
  },
  "local_probes": [
    "probe_c04_compensation_source.py",
    "probe_c11_compensation_readers.py"
  ],
  "acceptance_matrix_assignment": "NO_AUTOMATIC_WHOLE_OBLIGATION_PASS",
  "unknown_recovery": "HOLD_NO_TRUSTED_RECEIPT",
  "cross_component_automatic_sync": "NOT_VERIFIED",
  "deployment": "NOT_RUN",
  "physical_devices": "NOT_VERIFIED"
}
```

</details>

<details>
<summary>c13/LOCAL_INDEPENDENT_COUNTS.json</summary>

```json
{
  "C04": {
    "tests": 18,
    "failures": 0,
    "errors": 0,
    "skipped": 0
  },
  "C11": {
    "tests": 30,
    "failures": 0,
    "errors": 0,
    "skipped": 0
  }
}
```

</details>

<details>
<summary>c13/FROZEN_SOURCE_VERIFICATION.json</summary>

```json
[
  {
    "path": "application/src/go_hotel/mobility/rental/deposit_authority.py",
    "sha256": "cd8012281973d3591315a07a0dfa0a4b9b5c19409b2734e403d850919bd20521",
    "match": true
  },
  {
    "path": "application/tests/test_rental_compensation_authority.py",
    "sha256": "39d6b5127583b17fe62e9988a37d1f1b83b6407724113dded7512ab692b0c704",
    "match": true
  },
  {
    "path": "application/frontend/shared/rental-operations.js",
    "sha256": "e6f8828c1c1a09fe5c1844760ac3b8addf7df152cb93d981d2149c4b2b5330ff",
    "match": true
  },
  {
    "path": "application/src/go_hotel/services/rental_deposit_money.py",
    "sha256": "540c5c4b3abe4988c058e060cab25ff30fb8600195f2530a4ea25e82d4907aa6",
    "match": true
  },
  {
    "path": "application/src/go_hotel/services/rental_deposit_review.py",
    "sha256": "49b5c82572c012d01c9230e1886822ffdbac530e908cc257b5e969e54c634444",
    "match": true
  },
  {
    "path": "application/src/go_hotel/api/routes/rental_deposit_money.py",
    "sha256": "1a9cf7bf3ac6607f077a3e36adfc430a12a4c9f614aba6458e98b60c5acdaed1",
    "match": true
  },
  {
    "path": "application/frontend/admin/rental-deposit-finance.js",
    "sha256": "8fa5023caafa3551bf91bbd7f031043856a7c7e92bbca70be71bfaf1fc834ad6",
    "match": true
  },
  {
    "path": "application/frontend/consumer/rental-deposit.js",
    "sha256": "19e7b3011471d8294ab31998c2f1f0170f0ebec7903dd1dd0de1ed1c56e5cbb9",
    "match": true
  },
  {
    "path": "application/tests/payments/test_c11_deposit_compensation.py",
    "sha256": "814cc763d50dc9f3f3036c5887fa5a15b402d12362bdd9818fbff8d3c25b826c",
    "match": true
  },
  {
    "path": "application/tests_frontend/rental_deposit_operations.test.mjs",
    "sha256": "e853ea0a4ffa2f44494669fa0c03c906c516b759408fc7405be86abbf09f0925",
    "match": true
  },
  {
    "path": "ci/journey-v2/compensation-depth.mjs",
    "sha256": "192f426c6c7efdb3d3c5cb34eccc8682a776411935529e6d13297e54a6e8c0cb",
    "match": true
  },
  {
    "path": "ci/journey-v2/compensation-ledger.py",
    "sha256": "c30da1764e3a864d452566d57f132cdde484d3f737c591467f1d6a109f7ed9c8",
    "match": true
  },
  {
    "path": "ci/journey-v2/operations-depth.mjs",
    "sha256": "2dea2ede4166c10a2053c990ba1a573e464f52c9a5c7fb86b6439570499a9994",
    "match": true
  },
  {
    "path": "ci/journey-v2/run.py",
    "sha256": "b8a18d056f44c9cf91dc2967afd36221477e001e523efb039116909f7daa4f6f",
    "match": true
  }
]
```

</details>

<details>
<summary>c13/probe_c04_compensation_source.py</summary>

```python
"""Independent C13 corruption probes; no product code modifications."""
from copy import deepcopy
import pytest
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as EvidenceRow,OmnichannelMoneyMovementRow as Movement
from go_hotel.services.rc20_vertical_evidence import _stable_hash
from go_hotel.mobility.rental import deposit_authority as authority
from tests.test_rental_compensation_authority import case,reduce,CHECKER
from tests.test_rental_damage_disputes import order

@pytest.mark.parametrize('field',['currency','claimed_minor','opened_by','reviewer_id','binding','actor_id','actor_type','contract'])
def test_rehashed_historical_semantic_tamper_fails_closed(case,field):
 oid,obligation,cid,_=case;reduce(case)
 with SessionLocal.begin() as s:
  rows=list(s.scalars(select(EvidenceRow).where(EvidenceRow.execution_id==f'rc20:RENTAL:{oid}').order_by(EvidenceRow.sequence_no)));prev='GENESIS'
  for row in rows:
   body=deepcopy(row.evidence_json)
   if body['kind']=='DAMAGE_CASE_EVENT' and body['payload']['case']['version']==3:
    payload=body['payload'];c=payload['case']
    if field=='binding':c['deposit_obligation']['source_hash']='f'*64
    elif field=='actor_id':payload['actor_id']='other-reviewer'
    elif field=='actor_type':payload['actor_type']='CONSUMER'
    elif field=='contract':c['contract_snapshot']['insurance']='OTHER'
    elif field=='claimed_minor':c[field]=11000
    else:c[field]='OTHER'
   body['previous_hash']=prev;row.previous_hash=prev;row.evidence_json=body;row.evidence_hash=_stable_hash(body)
   row.entry_hash=_stable_hash({'evidence_hash':row.evidence_hash,'previous_hash':prev,'sequence_no':row.sequence_no});prev=row.entry_hash
 with pytest.raises(ValueError):authority.compensation_preview(CHECKER,oid,obligation['obligation_id'],cid)
 with SessionLocal.begin() as s:
  with pytest.raises(ValueError):authority.resolve_compensation_history(s,oid,obligation['obligation_id'])
  assert s.scalar(select(func.count()).select_from(Movement))==0
```

</details>

<details>
<summary>c13/probe_c11_compensation_readers.py</summary>

```python
from copy import deepcopy
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as EvidenceRow
from go_hotel.services.rc20_vertical_evidence import _stable_hash
from tests.payments.test_c11_deposit_compensation import obligation,settled,appeal,execute,service,review,OWNER,CHECKER,args,Movement,Ledger

@pytest.mark.parametrize('fault',['historical_reviewer','historical_amount','historical_actor','capture_key','parent_release','parent_foreign','both_accounts','currency','unknown'])
def test_both_readers_reject_balanced_but_untrusted_compensation(obligation,settled,fault):
 decision=appeal(obligation,settled,1000);execute(obligation,decision)
 with SessionLocal.begin() as s:
  rows=list(s.scalars(select(Movement)));comp=next(x for x in rows if x.movement_type=='COMPENSATION');capture=next(x for x in rows if x.movement_type=='CAPTURE')
  if fault.startswith('historical_'):
   prev='GENESIS'
   for row in s.scalars(select(EvidenceRow).where(EvidenceRow.execution_id=='rc20:RENTAL:deposit-order').order_by(EvidenceRow.sequence_no)):
    body=deepcopy(row.evidence_json)
    if body['kind']=='DAMAGE_CASE_EVENT' and body['payload']['case']['version']==3:
     c=body['payload']['case']
     if fault=='historical_reviewer':c['reviewer_id']='forged-reviewer'
     elif fault=='historical_amount':c['awarded_minor']=4001
     else:body['payload']['actor_type']='CONSUMER'
    body['previous_hash']=prev;row.previous_hash=prev;row.evidence_json=body;row.evidence_hash=_stable_hash(body);row.entry_hash=_stable_hash({'evidence_hash':row.evidence_hash,'previous_hash':prev,'sequence_no':row.sequence_no});prev=row.entry_hash
  elif fault=='capture_key':capture.idempotency_key='untrusted-capture'
  elif fault=='parent_release':comp.parent_movement_id=next(x for x in rows if x.movement_type=='RELEASE').money_movement_id
  elif fault=='parent_foreign':comp.parent_movement_id='foreign-capture'
  elif fault=='currency':comp.currency='USD'
  elif fault=='unknown':comp.state='UNKNOWN_EXTERNAL_STATE'
  else:
   for row in s.scalars(select(Ledger).where(Ledger.transaction_id==comp.money_movement_id)):row.account_code='RD:foreign' if row.direction=='DEBIT' else 'CLEARING:foreign'
 with SessionLocal() as s:before=[(x.money_movement_id,x.state,x.amount_minor) for x in s.scalars(select(Movement))]
 result=service.status(OWNER,*args(obligation));assert result['state']=='RECONCILIATION_REQUIRED' and result['net_captured_minor'] is None and result['compensated_minor'] is None
 result=review(CHECKER,'deposit-order');assert result['money']['state']=='RECONCILIATION_REQUIRED' and not any(x.get('can_compensate') for x in result['decisions'])
 with SessionLocal() as s:assert before==[(x.money_movement_id,x.state,x.amount_minor) for x in s.scalars(select(Movement))]
```

</details>

<details>
<summary>c13/CBA_RETENTION_SKIPS.json</summary>

```json
[
  {
    "classname": "tests.test_p0_0100_postgres_concurrency",
    "name": "test_order_payment_root_unique_under_postgres_race",
    "reason": "POSTGRES_TEST_DATABASE_URL not configured"
  },
  {
    "classname": "tests.test_outbox_resilience",
    "name": "test_postgresql_two_workers_claim_one_row_once",
    "reason": "requires PostgreSQL row-lock semantics"
  },
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
  }
]
```

</details>

<details>
<summary>c14/FINAL_CBA99D_BINDING.md</summary>

```text
# Round4 C14 最终候选绑定

Head `cba99d085ffe8ff576e44120ac796e59b4ff11bf`；product `1ee6fd666ac32bf712b951080ae9d80714a51d47`；app tree `d487902d1bf40fdb1c50092265631575ab1e7c49`；1534文件；fingerprint `fe7dfed28cc3ce49d7666a9f18babccf4d5deb4917eff441074fdbb2eee87007`。

**10/10** 冻结应用文件已从精确远端head完整取回，独立SHA256与冻结源审记录及当前本地全部一致。相对cb8928f的应用变更恰为这10文件；product→head无应用变化。v1/v1.1冻结定义未改，305项/1009case范围保持；新增round4文件仅审查/设计材料。应用身份与远端CANDIDATE一致，本次未重算全树指纹。

限定规则结论：隔离申诉减收补偿增量未发现新增权限或规则阻断。当前独立减收授权与历史只读证明分开；同根原capture追加补偿、精确反向账码、净额预算及原事实保留已经源审。UNKNOWN无独立可信回执和旧账格式执行仍HOLD。

C13所报本地48例及正在运行的5项CI归其独立质量证据，本报告不代其最终验收。真实合同、收费、法律、PSP与部署批准不变；不声称完整305项PASS或正式C14服务已运行。未改源码、PR或远端，可原文保留PRbody而不移动head。
```

</details>

