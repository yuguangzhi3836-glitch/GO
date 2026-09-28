# A方案限定规则意见

根协调者选择本批仅紧急权限防护，不实现真实Hosted↔supplier/property授权链。该方案可以继续隔离工程实现，但不得描述成酒店真实授权、发布消费或容量闭环。

必须同时满足：

- persistent active GO_ADMIN与admin:approve只代表GO内部动作权限；它们不能单独证明酒店委托。
- reserved HOTEL_CONTENT_APPROVER必须来自独立server-held酒店scope及provenance记录，绑定授权ID/version、适用用途、生效/撤销状态。仅多写一个roles字符串仍不充分。
- 如仅隔离fixture提供授权，须显式配置并限定local/test/demo，创建与消费两侧验证；默认无记录、非隔离环境HOLD。来源字段明确fixture，不能输出无保留真实HOTEL_AUTHORIZED_OPERATOR认证。
- 所有可公开写身份/角色/scope的入口均不能自授reserved权限，包括assign_role/create_user/patch/import及相关bootstrap路径；不可只封一个路由而留等效入口。
- maker/checker独立；snapshot creator可追溯，当前version/hash绑定。没有creator的历史弱快照/批准不能默认为可信。
- gate只消费新可信批准记录，最近REJECT/撤销/版本变化不能被旧APPROVE掩盖；批准与审计原子持久，缺失或损坏HOLD。
- 真实酒店首次授权仍待独立可信来源；旧publish/page与媒体权利未闭合之处继续作为内部缺口，不把新增审批防护当全链已完成。

待冻结源码独立核查；这是设计边界意见，不授实现PASS或真实商业/法律/部署许可。


## 本批最小实现收敛（后续明确，优先于上文泛化授权生命周期）

可直接复用HostedStaffRoleRow的id/hotel/staff/role/state/evidence/created_at作为明确测试fixture绑定，无需新增真实授权系统、表或期限架构。无expiry时可仅test环境消费；若扩local/demo必须同样显式fixture开关与消费门控，所有非允许环境尤其production全部HOLD。

必要核验是exact hotel+staff+reserved role+ACTIVE及结构化fixture来源；公开assign_role等既有等效授予入口不能创建reserved权限。approval保存绑定row ID及这些现存字段摘要，gate重算识别撤销/替换；新增记录不伪称酒店委托。maker/checker、当前snapshot/hash、最近拒绝及旧弱批准排除仍必需。无需凭空增加商业授权有效期；生产首次真实授权另行取得可信来源。publish/page消费闭环本批未完成，继续留分母。
