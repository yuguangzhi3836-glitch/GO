# Round5 酒店内容批准链：独立规则源审与最小边界

状态：现有链存在真实工程权限/消费缺口；本报告不是新实现通过或真实酒店授权。读取字节身份见 BASELINE_SOURCE_SHA256.json。本轮只读，不改产品/远端；正式组织与部署边界不变。

| 位置 | 当前实际行为 | 必须关闭的缺口 |
|---|---|---|
| hosted_content_acceptance.py:10–14 snapshot | actor未保存；max(version)+1；复制contact_json及其自报status | 明确创建权限、对象绑定、creator、规范化hash、并发唯一version；自报status不得升级可信度 |
| hosted_direct_booking.py 路由:69–76；security/deps.py:35 | 只验证GO_ADMIN actor_type；传user_id而非完整权限主体 | GO_READ_ONLY也能通过角色门槛；必须具体操作权限和对象所属关系，服务内部不能只信路由 |
| hosted_content_acceptance.py:15–20 approve | caller填HOTEL_AUTHORIZED_OPERATOR字符串及任意reference即可记录APPROVE | 权限标签由服务端可信关系派生；酒店明确授权与GO内部admin权力分开 |
| models.py:6287 HostedDirectHotel | supplier_name但无supplier_id/property_id关系 | 同名/slug/contact字段不是身份映射；没有可信唯一关系时HOLD |
| models.py:1071、5126 | IdentityUser有supplier_id，HotelPartnerProperty有supplier_id | 可复用其所属链，但还需验证Hosted酒店与property的受权映射、有效状态及内容审批范围 |
| hosted_content_acceptance.py:32 gate | latest snapshot中存在任意APPROVE即通过内容检查；无后续REJECT/撤销优先级、hash重验 | 不得用旧APPROVE盖过新拒绝；明确当前有效决定、批准完整内容及映射版本、撤权后新消费 |
| hosted_direct_booking.py 服务:19 publish/:32 page | publish只要求active offer；page读取当前live contact_json；未见调用content gate | 新审批必须接到明确发布/读取/使用路径，不能批准旧snapshot却展示未批live内容 |
| hosted_content_acceptance.py:21–29 media | 固定酒店名称+任意权利引用即RIGHTS_VERIFIED | 内容批准不等于真实图片权利；媒体权利链单列，不能借本批批准伪造 |

最小可接受方案：

1. 使用真实认证Principal；在服务端读取当前用户、角色和有效会话，检查动作权限。酒店审批优先由确有该酒店内容授权的供应商主体完成；GO管理审批仅标GO_INTERNAL_REVIEW，除非有明确酒店委托记录，不能自动标HOTEL_AUTHORIZED_OPERATOR。
2. 复用IdentityUser.supplier_id→HotelPartnerProperty.supplier_id；再通过明确、唯一、受权且可撤销的Hosted酒店↔property关联定位对象。名称相等、import来源、账号角色、可查看酒店本身均不等于内容审批授权。既有关系若不具备所需语义，只能HOLD或增加最小可审计委托记录，不能伪装已经存在授权。
3. 分开创建草稿、酒店确认、GO发布审核和消费；明确每步actor及目的。若声称独立审核，maker不得自批；若产品允许酒店自行确认自身资料，应准确记为酒店确认而非独立质量/法律认证。
4. 每次批准绑定snapshot_id/version/content_hash、hotel/property/supplier、授权关系ID/version/scope、认证actor、决定及时间。记录来源类型。客户端不得提交effective approver_role/verified/批准摘要等权威字段；旧自由Payload不能绕过严格专用schema。
5. 已批snapshot不可原地改写；新内容生成新版本。旧记录只作历史，最新拒绝/撤销不得被旧APPROVE盖过。版本分配、批准/拒绝/撤销和审计在同一持久事务，按酒店序列化并发；同key不同内容冲突。
6. 消费时校验被批准内容hash、当前授权/映射状态和允许用途；来源缺失、冲突、被撤销、过期、版本不匹配时停止新的发布/新用途。正常审批会话到期不等于历史批准被删除；用户撤权/授权撤销对新使用如何生效应明确测试。历史成交快照与资金事实不可静默改写。
7. page/publish/后续booking等实际消费者必须明确读取哪个approved snapshot及其用途。若页面仅草稿预览，显著标未批准并限制使用；不可将OPERATIONS_ACCEPTED当支付、媒体版权或真实商业批准。
8. 工程fixture可验证完整内部链，但必须隔离且provenance明确；不能建立标称真实酒店授权记录以让测试转绿。真实授权材料仍需有权来源另行提供。

必需负向与恢复验证：

- GO_READ_ONLY、消费者、其他供应商、供应商无该property、无映射/同名映射、错用途授权均拒绝，且零批准记录。
- caller伪造HOTEL_AUTHORIZED_OPERATOR、approved_by、verified、其他snapshot ID/hash均不能授权。
- 内容变更后旧批准不可授权新内容；先批准再拒绝/撤销、先报价/预览再撤权、重新分配酒店关系等必须按当前规则HOLD新消费。
- 并发snapshot/version、双批准/拒绝、写审计故障、事务回滚和失联重试；原始失败保留。
- 真实角色页面通过正常操作完成确认/发布/读回；持久化状态与展示同版本，无手填技术hash或强制点击替代正常授权。
- 消费路径越过新服务、直接publish/live contact变更、旧approval混入、媒体权益借用均有反例；不得只测新API自洽。

结论：当前无法把任意GO_ADMIN加字符串声明视作“酒店授权运营者”。最小改造应基于可信所属关系和明确委托用途闭合批准→消费；缺关系时保持HOLD。上述缺口是现有源码行为判断，不是具体法规解释。真实酒店授权、商业条款、图片权利及部署许可不由本报告授予。
