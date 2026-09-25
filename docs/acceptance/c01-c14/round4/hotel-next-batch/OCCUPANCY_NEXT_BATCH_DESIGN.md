# C01 下一批最小容量闭环设计（本批只读）

状态：DESIGN_ONLY / NOT_IMPLEMENTED。依据已冻结 v1.1 的 C01-CTRIP-OCCUPANCY 四个必要case与携程学习映射；本批产品交付仍仅租车已结算申诉补偿。未修改酒店源码、schema、fixture或冻结清单，未执行酒店新功能验收。此设计不是酒店真实规则批准。

## 为什么选容量而暂不选早餐

当前已有成人、儿童、总人数资料字段和预订入口，可以形成一个明确的物理房型约束闭环。早餐仅有generic JSON与部分展示，要形成身高区间计价、含早配额分配、成人儿童混合金额、服务日期时区及成交快照链，范围更大；只加JSON校验不能满足 C01-CTRIP-BREAKFAST 四case。早餐保留下一阶段义务，不宣布已完成。

## 已有实现与实际缺口

- hotel_partner_core.py:create_room_type 有 max_occupancy/max_adults/max_children 与组合可达性检查，但 int()会接受某些非严格整数；尚不能证明预订链消费此资料版本。
- hosted_reservation_operations.py:availability/reserve/reschedule 只检查每日rate.max_adults/max_children及extra_bed_allowed，未检查物理房型总人数和婴儿规则。允许成人2/儿童1不能据此推断总容量3。
- hosted_fare_change.py:context 独立处理已付款改期/延住，同样只有成人儿童上限；仅修reschedule会漏掉这条资金相关入口。
- hosted_stay_credit.py:redeem 调用 ops.reserve，额度兑换新单必须通过相同容量门。电话前台入口 hosted_frontdesk_uat.py:phone_reserve 也调用reserve。
- 订单Stay保存当次人数，FareSnapshot保存票规；未找到专用、完整的物理容量版本与入住人分类定义成交快照。
- HotelPartnerRoomTypeRow → HotelPartnerSellableProductRow → RatePlan 的图存在；来源房型映射也存在，但没有证实它与 HostedDirectInventoryPoolRow 的server-verified授权对应。相同酒店名、room_name、早餐数或客户端room ID不能替代绑定。

## 先解决权威来源，再接预订

政策必须来自被认证且有权维护该property的酒店操作者，绑定 supplier_id、property_id、source_room_type_id、hosted_hotel_id、inventory_pool_id/physical_room_key。优先复用已有direct-submission的review与canonical room映射结果，并检查它确实关联当前Hosted pool；不能仅因两个系统有同名房型就连接。若现有映射缺少这条关系，下一批需明确增加受控绑定记录与审核入口，再实施消费，不先落猜测映射。

旧 hosted_content_acceptance.approve 并不足以作为这个权威来源：路由验证GO_ADMIN身份，但未验证批准权限或酒店授权关系，body.approver_role字符串可声称HOTEL_AUTHORIZED_OPERATOR。精确只读风险与无业务写验证方案见 AUTHORITY_RISK.md。下一批先修这项身份/权限绑定，不沿用字符串批准。

建议完整容量契约字段：

| 类别 | 必须明确的内容 |
|---|---|
| 对象与来源 | 上述server-verified供应商/酒店/物理房型绑定、来源记录ID、提交/审核主体及schema版本 |
| 人数上限 | max_occupancy、max_adults、max_children，严格整数；下限/上限及可达性验证 |
| 年龄分类 | 酒店明确的成人/儿童年龄区间；是否区分婴儿、婴儿区间与是否计入儿童及总人数。未知时HOLD，不自动按行业习惯补齐 |
| 加床 | 是否允许及是否改变容量；未明示可增加总容量时，加床不能增加上限 |
| 适用与版本 | 明确生效/失效范围、状态、单调版本、前版引用和完整规范化内容hash；数值由酒店明确提供，不由AI拟定 |

酒店资料维护只生成候选版本；未核实绑定、缺定义、失效或撤销不供新交易。已生效版本不可原地改写。内容hash涵盖上述全部字段及绑定，不接受客户自报hash当来源证明。专用权限依据真实session和持久化角色/酒店关系，不接收approved_by等自证字段。

## 单一闭环及并发规则

1. 已授权酒店提交并核验一个物理房型容量版本；同pool下所有组合售卖方案引用它，不独立扩容。
2. availability从当前版本与每日rate限制共同计算可订性。显示成人、儿童、总人数上限、年龄/婴儿计数规则、适用版本和具体不可订原因；未知不返回bookable=true。
3. 客户确认人数后，预订请求带服务器发出的容量摘要。reserve核验当前版本、人数及每日限制，再扣库存，订单/库存/容量接受快照同事务提交。过时hash或越界请求原子失败，零费用副作用。
4. 改期、已付款改期/延住、额度兑换和电话预订使用同一门，不能绕过。交易确需改变容量适用版本时，重新报价和确认，不重写原成交快照；保留变更事件的新旧版本关系。
5. 订单只读回显原接受版本和当时计数。后续来源修改/撤销不得篡改历史；新操作的权限、资金和履约门控仍独立执行。

锁的要求：不得凭此文档直接插入任意锁序。实施前画出现有资金root/source→reservation/stay→offer/rate→inventory实际锁图；Paid change目前先资金来源/订单再rate/inventory，新增policy/pool锁须放在所有入口一致的位置且版本写入不得反向锁订单。按稳定pool ID及日期排序锁资源；policy切换/撤销与reserve/change的当前版本确认使用同一DB事务锁。SQLite BEGIN IMMEDIATE只作本地补充；隔离PG必须证明撤销先提交后旧报价拒绝、预订先提交后历史快照保留，以及并发不会多占库存/死锁。不能以理论锁图替代PG测试。

## 旧订单与兼容

旧单无容量快照保留原事实并显示“历史容量规则未核验”，不自动安装工程规则，不改订单价格、不补伪同意、不拒绝只读或已有合法退款查询。要求新分配库存、扩住、改变人数等操作时需新可信容量规则和明确确认，否则HOLD；具体是否影响既有在途履约须单独定义，不能本批暗中冻结原合同。

普通未接真实供应商的工程旅程也不能永久失去预订路径。已有fixtures必须明确注册隔离供应商/房型绑定及合成容量版本，然后先读availability再发送当前摘要；不得用全局autouse批准或删掉原金额/权限断言。默认adult2/child1的bootstrap_calendar不是酒店授权来源，不能转写为完整容量契约。

## 影响范围与下一批文件

IMPACT_MATRIX.json记录7个直接引用ops/旧工程种子的测试文件，扩大到改期/额度/票规/前台调用链共有23个候选测试文件。这是需检查的文件数，不是已确认失败数；尚未改代码或跑新迁移测试。源码读取hash一并保留。

预计新增独立 hosted_occupancy_policy.py 与专用后端/PG/前端测试；修改 hotel_partner_core.py、hosted_reservation_operations.py、hosted_fare_change.py、hosted_stay_credit.py、hosted_frontdesk_uat.py及 hosted_direct_booking.py 路由/读回。若现有review/schema无法表达物理room授权绑定及不可变版本，应提交最小专用表迁移评审，不能挤入不相干事件表或把旧content approval当许可。最终数据存储方案待下一批确认。

消费者容量独立widget和供应商版本维护页面由模块实现，shared app/index/main由root整合。下一批浏览器必须正常酒店角色提交→审核→消费者人数/容量可见→预订→规则换版→旧单回读，不能用API setup冒充运营点击。

验收只映射 C01-CTRIP-OCCUPANCY 的4个必需case及v1的权限/并发/跨端/运营义务；不声称完成早餐或全部C01。v1.1清单不修改。
