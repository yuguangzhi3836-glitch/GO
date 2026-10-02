# C/B 注册条款 R2 全文复审包

版本 2026-10-02-review-draft-v3。七份以下完整修订稿取代本次复审中的 R1文本。R1保留作历史。原应用 registry 是 DRAFT 未更改，本包不自动成为线上版本。

# R2 补证与修订说明（2026-10-02）
状态：DRAFT / PARTIAL_EVIDENCE。不得将本包当作运营批准或已部署事实。
源候选：3cbc38a2ab254f7a28a6c2db9f9392d499aa2112；application tree：6f97ac5d572dae1de0b3e38b6201da2a6de14216。R1 审核 36995188378 结论 BLOCKED。本轮只新增完整修订文本及证据，不更改应用、生效 registry 或运行环境。

## 证据来源与可信范围
- H1：2026-08-10 用户历史确认，构行人工智能（黑龙江）有限公司，注册地址黑龙江省哈尔滨市松北区创新三路788号；本轮通过历史上下文检索找回。属于用户提供事实，尚未取得营业执照影像/官方登记原件及摘要，不伪装为官方核验。未找到该主体自身信用代码，不能借用股东或其他酒店公司代码。
- H2：2026-09-19 用户提供的邮件准备交接称 12 项核验通过、真实发信并确认收件。保留其完成状态，不要求重复准备账号；本轮未取得原始测试回执哈希，也不据此认定隐私申请收件、分派、答复流程已验证。无需提取任何邮件密码。
- H3：用户既有 GO 零佣金、订阅和延迟结算方向；代码 S7 可补充规划价依据，但不等于某家酒店签署价格、结算周期或税务合同。
- S1—S11：下方固定 Git blob 的源码证据，只能证明候选实现，不证明当前部署、实际履行、法规批准或受托合同存在。
- L1：电子商务法（市场监管总局官方全文）https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/art_14453aa523094819aa8f1d4530ce3cc4.html ，2026-10-02 核对第9、27、31—34条：平台身份及核验、特定商品/服务与交易记录的交易完成起算、规则公布变更要求。
- L2：个人信息保护法（四川省通信管理局官方全文）https://scca.miit.gov.cn/zwgk/zcwj/flfg/art/2024/art_1e503b8a7cbe4c8b8e973bb7c16cb56b.html ，2026-10-02 核对第13、17、19—23、28—31、47、50条。核对范围为依据、告知、角色、期限、敏感/未成年人、删除及权利机制；需按实际活动判断。
- L3：促进和规范数据跨境流动规定（网信办官方）https://www.cac.gov.cn/2024-03/22/c_1712776611775634.htm ，核对第5、10条。履约情形的程序豁免不能泛化成全部注册/日志/AI处理的豁免，亦不消除其他适用义务。
以上为审阅材料来源，不修改 C14 backend 规则权威。

## 注册接受与功能授权矩阵（拟实施文本；非已验收状态）
| 阶段 | 文件与动作 | 拒绝后影响 | 授权结果及证据 |
|---|---|---|---|
| C 基础账户 | 用户服务协议：独立接受；隐私政策：已阅读告知确认 | 拒绝账户合同不创建账户；隐私告知不冒充万能处理同意 | 绑定用户、文件版本/哈希、动作、时间；资料库 DEFERRED |
| C 资料库启用 | 资料库条款另行接受；逐项说明保存用途 | 不启用资料库，不影响基础账户 | 默认关闭；敏感信息处理及对外提供按适用要求另行确认 |
| C 具体预订与资料释放 | 展示该订单提供方、字段、目的和依据；依法取得所需单独同意 | 无法提供必要信息时说明对该次服务的影响 | 一次订单范围，不授权未来全部交易或营销 |
| C/B 营销、新目的、模型训练 | 明确独立选择，不预选 | 不影响基本注册 | 独立目的/范围/版本及撤回入口 |
| B 基础账户/草稿建库 | 合作伙伴协议中的账户服务范围、平台运营规范独立接受；隐私告知单列 | 不创建业务账户或不提供相应账户服务 | 仅声明身份和草稿管理，不认证酒店归属，不授签约、收退款或改收款账户权限 |
| B 酒店认领及发布 | 核验经营/管理方身份、授权期限、资料权属；逐范围确认图文授权 | 未通过则不认证、不公开相应资料 | 主体、酒店、人员、权限、期限、审核材料与版本留痕 |
| B 实际数据协作 | 数据处理活动附表和数据处理条款按真实角色另行签署 | 未完成不得开展对应数据交换 | 逐活动角色、接收方、期限、安全和权利分工 |
| B 订阅/结算/付款退款 | 具体商务附表和操作权限另行确认 | 不启用相应付费或资金功能 | 价格版本、范围、周期、税费、授权人员及可审计动作 |
| B 电子签约 | 具体合同与签约授权另行确认 | 不启用该次企业签约 | 不以邮箱验证或注册勾选替代企业授权和签署 |

实际差异：S1 required_decisions 将 supplier 除 privacy_policy 外全部文档统一设 CONTRACT_ACCEPTED，S5 _REQUIRED 包含电子签约和数据处理。所以上述 B 阶段矩阵尚需程序对齐和回归，不能声称已经执行。C 端代码可证明 privacy NOTICE_ACKNOWLEDGED、vault DEFERRED，尚不能证明实际移动端提示、撤回或后续训练控制。

## 数据活动附表（已核源码与待定事实分开）
所有活动的实际存储区域、云/邮件/AI 服务商法定名称、运维访问地区、委托合同与备份位置均未取得当前有效证据；不得将“香港 Staging”概括为完整数据流。

| 活动/角色拟定 | 已核字段与必要性 | 目的及依据候选 | 数据去向/拒绝影响 | 留存与证据 |
|---|---|---|---|---|
| C 账户：GO拟独立处理 | email/password必需；display_name/phone可选；密码存 password_hash，phone_ciphertext | 请求创建/维护账户，合同必要性需按字段确认；可选字段不得冒充必要 | GO账户库；缺邮箱/密码不能创建；拒绝可选字段应可注册 | S3/S10；账户生命周期删除证据待补 |
| B 账户/草稿酒店：GO拟独立处理 | email/password/organization_name/contact_name；phone可选；hotel_name可选回退组织名，province/city/street_address默认空 | 账户、联系、草稿建库；联系人为他人时需提供方有合法来源/告知，不能仅凭企业合同代表其同意 | GO身份/供应商/酒店库；必填字段必要性仍需业务说明，尤其基础账户是否需联系人姓名 | S4/S11；非已核验经营身份 |
| C/B 邮箱验证：GO拟独立处理、邮件方角色待合同 | 收件邮箱、验证码发送；DB为subject_key/challenge_id/code_digest/policy_digest/state/attempts/时间/consumed_by | 安全验证与反滥用，依据和最小范围待逐活动核定 | 邮件传输给实际SMTP方，名称/地区/日志期限待核；拒绝邮箱验证不能创建 | S2/S8；10分钟挑战，原始验证码仅传输处理不作为存储字段 |
| C/B 限流与审计：GO拟独立处理 | HMAC化限流键/计数/到期时间；审计中request_id/IP/版本与哈希；登录处理接收user-agent | 反滥用、审计；不将HMAC误称匿名信息；网络安全日志类别另核 | GO数据库/日志；不得因此承诺“无IP存储” | S1/S2/S3/S4；限流60秒/1小时窗口；普通登录日志期限未核 |
| 接受记录：GO拟独立处理 | user_id/audience/decisions/versions/hashes/创建到期时间 | 证明真实合同/告知动作；依据及必要期限需核定 | GO记录库；不复用为营销许可 | S1；当前1095天工程设置待审 |
| 权利申请：GO按角色处理 | 用户、申请类型、状态、时间、处理结果/依据/处理人 | 响应个人信息权利申请 | 登录用户入口；不能登录者需可达渠道，邮箱闭环仍待证 | S1/S9；15天内部到期标记不等同已承诺或已履约时限 |
| 资料库/订单/酒店住客 | 基础注册不需上传证件或完整行程；具体预订字段仅在场景必要时处理 | 按具体合同/法律义务/所需同意逐项核定 | 酒店独立处理/委托/共同处理不得一概判断；实际字段与接收方清单未完成 | 本轮仅注册源码盘点，不宣称覆盖全部旅行或支付链路 |
| AI整理/训练/跨境 | 无证明表明现行私密资料用于训练；也未完成全链路审计 | 新版默认禁止训练，任何新目的先评估及告知等程序 | 不因使用AI品牌就推定数据出境或不存在出境 | 真实服务商和数据流待证 |

## 分类留存和执行核对表
| 类别 | 固定源码中的期限/起算 | 已有机制 | 尚缺事项/责任角色 |
|---|---|---|---|
| 验证挑战 | 创建后600秒到期 | S1/S2到期删除；worker首次循环清挑战 | 线上worker部署及备份恢复证据，运行责任方 |
| 限流桶 | 所属60秒或1小时窗口结束 | S1/S2删除expires_ms到期记录 | 数据库/日志副本范围，运行与隐私责任方 |
| 接受记录 | 创建后1095天（工程设置） | S1过期删除 | 该期限必要性/法律依据及账户存续较久时证据保护评估；不是法定一律三年 |
| 三种注册/权利审计事件 | created_at超过1095天 | S1按特定action清理 | 不覆盖全部审计日志；需与权利/争议保留条件对齐 |
| 已完成/拒绝的权利申请 | updated_ms起1095天 | S1按状态清理 | 必要性、重新开启后起算、保留冻结处理待核 |
| 未决/受限保留申请 | 不自动删除；按due_ms计逾期 | S1告警最多统计100条；S9要求依据、受限范围及下次复核 | 明确接单/升级/复核责任，防止无限期未决；真实受理演练未有 |
| 账户、联系人、资料库、订单资料 | 目前未取得完整分类清单 | 删除/注销有申请入口，不等于自动完成 | 各表期限、依赖处理、删除证明及失败恢复待补 |
| 平台法定商品/服务与交易记录 | 适用电子商务法第31条时，交易完成起不少于三年，另有规定从其规定 | 本轮仅修订条款 | 确定GO适用身份与具体字段；不是全库三年；实现待核 |
| 备份、邮件方及其他副本 | 尚未取得可执行周期 | 无当前有效证据 | 运行/供应商责任方提交轮换周期、恢复后再清理、删除证明及失败告警 |
S6 worker每30秒尝试清理；S1以120秒心跳陈旧阻止新注册。仅源代码证据，不把注释“已部署”当现场证明。现有1095天不可自动批准为合规期限，需分类评估后改动并验证；本轮未改动删除任务。

## B端商务与权限附表（回收已有依据）
| 项目 | 已有事实/拟定修订 | 剩余决定性证据 |
|---|---|---|
| 零佣金 | 延续用户既有方向；合同明确适用范围与另选订阅分开 | 每个渠道适用交易范围、例外、签署版本 |
| 订阅 | S7规划/合同选择函数：Y1月价两钻及以下399、三钻699、四钻999、五钻1999元；Y2四钻按130间分999/1299，五钻按200/300间分1999/2999/3999；代码标注规划用途 | 正式价格版本、生效期、含税与开票、取消/续费方案；不将预算10个计费月写成合同赠送承诺 |
| 结算 | 用户方向为延迟结算；不得自行填T+N | 起算事件、周期、渠道、对账、争议款和退款处理、开票主体，由业务/财务确认 |
| 归属和代表权 | S4返回ownership_status=DECLARED、publication_state=DRAFT | 法人/管理方材料、授权范围/期限及争议认领流程；注册SUPPLIER_OWNER技术角色不等于法律授权 |
| 图文 | 仅按目的/渠道/期限有限授权，材料撤回后终止后续展示 | 权利人/授权书/原件与具体酒店房型对应证据 |
| 隐私权利 | 已有用户申请和admin:trust受理权限，状态核验/依据要求见S9 | 真实受理人职责、申诉和不可登录路径、邮件收件分派处理演练 |

## 未成年人实施方案草案（未批准、未实施）
基础注册不默认索取身份证。拟采用最少年龄段声明和针对性核验，避免收集不必要完整生日/证件；实际规则由产品与隐私负责人确认。不满十四周岁信息处理须监护人同意、专门规则及保护措施；监护人关系核验需比例适当、原始核验材料有最短期限与删除机制。成人代订儿童、资料库保存儿童证件不得以成人账户规避。措施不完备的相关处理路径不得启用；不能宣称现有代码已阻断。S3基础注册没有年龄/监护人字段，这是待实现差异，不伪称已验证。

## R1发现处置
C-001/B-001：已拟明确阶段矩阵，C代码部分可证，B程序差异保持OPEN。
C-002：私密资料训练语句已修订。
C-003：补具体方案与场景，产品确认和实施保持OPEN。
B-003：补官方第31条依据、主体、类别和起算点，需实际分类实现核验。
SHARED-001—004/B-002/B-004：补已知事实、源码字段和处理表；真实供应商、主体执照、周期及商务批准仍未齐，不请求据空白表PASS。


# 七份修订稿全文

## consumer_service_terms.md

# GO 用户服务协议

> 待确认草稿｜版本 2026-10-02-review-draft-v3｜修订日期 2026-10-02｜尚未生效，不供注册勾选。
>
> 本文是供运营方、业务负责人和法律顾问核定的完整条款草稿，不是法律认证。GO 为产品名称。运营主体为构行人工智能（黑龙江）有限公司，隐私联系邮箱为 postmaster@goaidirect.com（由业务负责人确认）。注册地址按既有用户确认记录为黑龙江省哈尔滨市松北区创新三路788号；该地址的登记原件尚待核验，统一社会信用代码、其他投诉渠道、具体留存期限、技术服务商及跨境安排尚待核定；未补齐文末附表并完成审核前，不构成平台已作出的运营承诺，也不能作为收集注册同意的依据。

## 1. 服务范围和合同关系

GO 提供账户、酒店信息展示、方案比较、订单协助及经实际开放的其他旅行服务。具体功能和供应渠道以交易页面明确披露为准。GO Direct 酒店直连业务中，住宿服务合同由消费者与页面列明的酒店经营者订立；消费者与 GO 运营方另行建立平台服务关系。通过其他供应商提供的产品，页面须明确实际销售方、服务提供方及责任，不能将其默认为酒店直销。平台应依法履行自身责任，不能以供应商责任为由免除应承担的义务。

## 2. 账户与验证

您应使用有权使用的联系方式并提供真实、必要的信息，妥善保管密码。邮箱格式通过不等于邮箱归属验证，手机号填写不等于短信验证。系统须如实展示已完成的验证步骤。发现冒用或账户异常可通过正式公布的渠道申请处理；平台采取限制措施应说明原因并提供申诉。未成年人使用需监护人参与，不具备相应同意机制时不开放相关采集和交易。

## 3. 方案展示与订单确认

下单前应展示酒店、房型、入住日期、入住人数、床型、餐食、含税总价、额外收费、支付及确认方式。图片与描述不能替代房型实物说明。参考价、会员优惠、券及适用门槛应有明确来源和有效条件。订单提交、确认、支付、入住等状态分别记录，不把提交成功等同于酒店已确认。

## 4. 取消、变更和退款

取消政策绑定具体报价方案，应在下单前突出展示免费取消截止时间及适用时区、超时扣费金额或算法、未入住规则和例外条件。不存在适用于全部酒店的统一“半小时免费取消”承诺。酒店或平台修改后续产品政策不得据此追溯改写已成立订单的约定。用户确认退订与退款到账分开显示；退款金额、原支付渠道、处理节点和预计时间需按实际结果告知，争议依法处理。

## 5. 支付、费用和发票

收费项目应在确认前说明，不默认勾选额外购买。支付由交易页列明的渠道处理；平台服务费、酒店费用及相关发票主体分别披露。尚未实现的支付、保险、垫付、担保或自动退款不得作为已有服务承诺。若开放自动续费，须另行清楚提示并提供便捷关闭方式。

## 6. 信息、资料库与第三方账户

个人资料库适用独立条款，上传及向酒店提供资料应按具体用途和范围进行。平台不要求提交携程等 OTA 密码或验证码，不因用户同意本协议而获得第三方账户操作授权。自动整理或辅助建议不能替代用户对实际订单的确认，发送、下单、取消等操作需具备对应授权和可追溯记录。

## 7. 纠错、责任与争议

您可就价格、描述、履约或个人信息提出更正和投诉。平台应保留必要交易证据并配合处理。涉及重大利益、责任限制或争议解决的条款需显著提示并可解释，不排除消费者依法享有的权利。因各方过错造成损失，依法律和有效约定确定责任，不设置概括性“全部免责”。适用中国法律；争议可协商、依法投诉或向有管辖权的法院起诉，不以本草稿指定未确认的专属管辖。

## 8. 退出、终止和版本

用户可申请账户注销；尚未结清的交易及法定留存信息按具体规则处理，不能将注销自动视为放弃退款请求。功能重大变化应提前告知；需要重新同意的变化不得以继续浏览一概推定接受。正式版本生效前须可完整阅读、保存并明确确认。

## 生效前必须补齐的附表

1. 平台运营主体：构行人工智能（黑龙江）有限公司（业务负责人已确认全称）；注册地址为黑龙江省哈尔滨市松北区创新三路788号（2026-08-10 用户确认记录，登记原件待核）；本主体统一社会信用代码及对外服务地址仍待核实。
2. 隐私与个人信息权利申请邮箱：postmaster@goaidirect.com（业务负责人已确认），用于查询、更正、删除等个人信息申请。邮箱收件及处理流程尚待实测；其他投诉渠道、负责人及处理时限待确认。本邮箱不代表短信或注册验证码发送服务已接入。
3. 数据清单：实际采集字段、用途、法律依据、保存位置、按数据类别确定的具体期限及删除方式；各项期限需结合履约、法定留存及争议处理确定。
4. 合作方清单：支付、短信、邮件、云服务、电子签约及其他接收方的主体、处理目的、数据类别和责任；没有接入的服务不得写成已提供。
5. 跨境清单：逐项确认是否发生、目的地、境外接收方、数据类别、权利方式、适用程序和必要的单独同意；不能以“可能跨境”替代明确告知。
6. 批准记录：业务与法律审核人、批准日期、正文校验值、正式版本、生效日期和已验证的用户提示流程。任何正文改动均需新版本重新核定，不沿用旧勾选记录。


## 注册告知、可选功能与未成年人补充
基础注册的合同接受和隐私告知分别呈现；隐私告知确认不代表同意全部处理。资料库默认不启用，营销、可选训练及其他非必要目的不预选，不同意不影响基础注册。具体预订、敏感信息处理及对外提供按活动明确目的、字段、接收方和依据，并依法完成所需单独动作。所需证据应绑定主体、目的、版本、正文哈希、明确动作和时间。
不满十四周岁相关信息处理须取得监护人同意并适用专门规则。成人代订或代存儿童资料仍须履行相应要求；基础注册不以常规采集身份证代替年龄和监护人机制。尚未落实必要措施的对应处理路径不得启用。具体实施方案见本送审包附表，其状态不等于当前程序已落实。


## 本次送审附表
本轮 FULL_REVIEW_INPUT_R2.md 中的接受矩阵、数据活动表、分类留存核对表、B端商务表及未成年人实施方案与本草稿共同审阅。表中源码事实不等于已上线控制，待核事项不得作为对外已兑现承诺；正式版本须将适用附表一并定稿、绑定并供用户读取。


---

## privacy_policy.md

# GO 隐私政策

> 待确认草稿｜版本 2026-10-02-review-draft-v3｜修订日期 2026-10-02｜尚未生效，不供注册勾选。
>
> 本文是供运营方、业务负责人和法律顾问核定的完整条款草稿，不是法律认证。GO 为产品名称。运营主体为构行人工智能（黑龙江）有限公司，隐私联系邮箱为 postmaster@goaidirect.com（由业务负责人确认）。注册地址按既有用户确认记录为黑龙江省哈尔滨市松北区创新三路788号；该地址的登记原件尚待核验，统一社会信用代码、其他投诉渠道、具体留存期限、技术服务商及跨境安排尚待核定；未补齐文末附表并完成审核前，不构成平台已作出的运营承诺，也不能作为收集注册同意的依据。

## 1. 适用范围与处理者

本政策拟适用于 GO 消费者及酒店经营人员账户。运营主体为构行人工智能（黑龙江）有限公司，个人信息权利申请可联系 postmaster@goaidirect.com；正式生效前仍需核验收件与处理流程。酒店对其依法独立取得的住客资料可能承担独立处理责任；GO 与酒店的实际角色应按处理活动确定，不以笼统称呼代替告知。

## 2. 按场景说明数据

注册涉及登录邮箱、密码的安全校验材料、可选姓名和联系方式；安全管理可能涉及登录时间、会话、必要的设备和网络日志。酒店建库涉及经营主体、地址、设施、房型、联系人及授权材料，其中自然人联系人信息应受保护。订单履约涉及订单、旅客必要身份和联系信息、支付结果及退订记录。个人资料库由用户按需存入，不以开户为由强制收集全部旅行证件。

每一场景的实际字段、是否必填、拒绝后影响及保存期限需在附表逐项列明。系统未实现或未开放的功能不得借此预先扩大收集。可选营销、精准定位、通讯录或其他非必要权限不得与基本注册捆绑。

## 3. 使用目的与依据

处理限于建立和保护账户、用户请求的预订履约、酒店资料维护、必要审计及法律义务等具体目的。依赖同意的活动须可撤回；依法不以同意为依据的处理须明确说明其依据。用于全新目的、营销或其他超出必要范围的活动，应重新履行适用的告知和同意程序。

## 4. 敏感信息与未成年人

证件、金融账户、精确行踪等信息按敏感信息要求评估必要性、影响和保护措施；需单独同意时应单独取得。未满十四周岁未成年人的信息须落实监护人同意和专门规则；未具备这些措施前不得以普通勾选替代。不得默认把证件照、客人电话或订单截图写入公开酒店信息库。

## 5. 提供、委托与公开

向酒店或供应商提供信息时，只提供该次服务所需内容并告知接收方及目的；需要单独同意的场景须单独确认。委托服务商应有范围、期限、安全和删除约束，接收方清单不得留空。公开酒店联系方式也须核实其为对客服务渠道，不默认公开员工私人号码。无必要和合法依据不公开个人资料，不以注册同意授权出售个人信息。

## 6. 保存、安全与事件

信息按完成目的所需最短期间保存，法律另有规定的从其规定；具体期限、起算点及删除方式见正式附表。平台需采取适当的访问控制、传输保护、备份及风险处置措施；这些是上线核验要求，草稿不证明当前系统已全部达标。发生安全事件时依法采取措施并履行适用告知义务。

## 7. 境内外处理

必须核对实际服务器、运维访问、服务商及接收方所在地区。存在跨境处理时，在实施前提供具体告知、完成适用程序并取得所需同意；本政策不提供概括性跨境授权。尚未确定的境外接收方不应写成已获得用户授权。

## 8. 您的权利及账户注销

您可依法申请查阅、复制、更正、补充、删除个人信息，撤回同意、解释处理规则或注销账户，并通过正式公布的渠道提出。拒绝某项申请须说明依据，必要的身份核验应适度。撤回不影响撤回前合法处理；依法仍需保存的部分限制继续使用，期满删除或匿名化。响应时限与申诉渠道在生效附表明确。

## 9. 更新与通知

主体、目的、范围、接收方等重要事项变化时，按影响程度提示并履行必要的重新同意流程。历史版本和实际接受记录应可核对。日志只记录必要的版本、时间和证据，不收录明文密码或验证码。

## 生效前必须补齐的附表

1. 平台运营主体：构行人工智能（黑龙江）有限公司（业务负责人已确认全称）；注册地址为黑龙江省哈尔滨市松北区创新三路788号（2026-08-10 用户确认记录，登记原件待核）；本主体统一社会信用代码及对外服务地址仍待核实。
2. 隐私与个人信息权利申请邮箱：postmaster@goaidirect.com（业务负责人已确认），用于查询、更正、删除等个人信息申请。邮箱收件及处理流程尚待实测；其他投诉渠道、负责人及处理时限待确认。本邮箱不代表短信或注册验证码发送服务已接入。
3. 数据清单：实际采集字段、用途、法律依据、保存位置、按数据类别确定的具体期限及删除方式；各项期限需结合履约、法定留存及争议处理确定。
4. 合作方清单：支付、短信、邮件、云服务、电子签约及其他接收方的主体、处理目的、数据类别和责任；没有接入的服务不得写成已提供。
5. 跨境清单：逐项确认是否发生、目的地、境外接收方、数据类别、权利方式、适用程序和必要的单独同意；不能以“可能跨境”替代明确告知。
6. 批准记录：业务与法律审核人、批准日期、正文校验值、正式版本、生效日期和已验证的用户提示流程。任何正文改动均需新版本重新核定，不沿用旧勾选记录。


## 注册告知、可选功能与未成年人补充
基础注册的合同接受和隐私告知分别呈现；隐私告知确认不代表同意全部处理。资料库默认不启用，营销、可选训练及其他非必要目的不预选，不同意不影响基础注册。具体预订、敏感信息处理及对外提供按活动明确目的、字段、接收方和依据，并依法完成所需单独动作。所需证据应绑定主体、目的、版本、正文哈希、明确动作和时间。
不满十四周岁相关信息处理须取得监护人同意并适用专门规则。成人代订或代存儿童资料仍须履行相应要求；基础注册不以常规采集身份证代替年龄和监护人机制。尚未落实必要措施的对应处理路径不得启用。具体实施方案见本送审包附表，其状态不等于当前程序已落实。


## 本次送审附表
本轮 FULL_REVIEW_INPUT_R2.md 中的接受矩阵、数据活动表、分类留存核对表、B端商务表及未成年人实施方案与本草稿共同审阅。表中源码事实不等于已上线控制，待核事项不得作为对外已兑现承诺；正式版本须将适用附表一并定稿、绑定并供用户读取。


---

## personal_vault_terms.md

# GO 个人资料库服务条款

> 待确认草稿｜版本 2026-10-02-review-draft-v3｜修订日期 2026-10-02｜尚未生效，不供注册勾选。
>
> 本文是供运营方、业务负责人和法律顾问核定的完整条款草稿，不是法律认证。GO 为产品名称。运营主体为构行人工智能（黑龙江）有限公司，隐私联系邮箱为 postmaster@goaidirect.com（由业务负责人确认）。注册地址按既有用户确认记录为黑龙江省哈尔滨市松北区创新三路788号；该地址的登记原件尚待核验，统一社会信用代码、其他投诉渠道、具体留存期限、技术服务商及跨境安排尚待核定；未补齐文末附表并完成审核前，不构成平台已作出的运营承诺，也不能作为收集注册同意的依据。

## 1. 自主建立与用途

个人资料库用于用户自主保存和管理与旅行有关的资料，便于在明确授权的服务中使用。开户不以上传证件、既往订单或完整行程为前提。您应确认有权存入本人或受托人的资料，上传他人资料需具备相应依据；不得上传无关客人名册。

## 2. 分类保存与可见范围

系统应区分账户资料、出行人、证件、订单凭证与偏好，标注来源及更新时间。原始文件、自动识别结果和用户确认结果分开标识；识别错误可更正。资料默认为本人及经授权角色可见，不因保存在资料库而自动公开或向所有酒店共享。

## 3. 逐次使用授权

预订使用资料时，应展示接收主体、所需字段、用途和关联订单；只释放履约必要内容。保存资料不等于永久授权所有未来订单或所有供应商使用。撤回某项授权后停止后续依赖该授权的使用；已依法交付并由酒店独立履约保存的资料按对应政策处理，不虚假承诺可以一键删除第三方全部记录。

## 4. 外部导入边界

允许用户提供有权使用的文件或可公开资料；不得索取 OTA 密码、短信验证码、付款密码，也不绕过平台访问控制。导入前提示涉及的个人信息及处理范围，不把后台可见等同于可以无限复制、公开或转售。导入结果仅作为待核对资料，不自动触发预订、退款或其他外部操作。

## 5. AI 整理与风险

如实际开放自动识别、摘要或建议，应标明其辅助性质、数据处理位置和服务商。关键姓名、证件号、日期、金额和退改条件由用户确认；系统不得将模型推断伪装为订单原文。默认不将个人资料库内容用于模型训练、公开展示或其他新目的。拟改变处理目的时，应先说明必要性、数据类别、处理地点、服务商、保存期限和退出影响，完成适用评估、告知及所需同意；不得以继续使用、概括性授权或注册勾选替代。拒绝可选训练不影响基础账户及原有必要服务。

## 6. 导出、删除与保留

用户可按实际提供的渠道申请导出、纠正或删除。草稿不承诺尚未实现的格式或即时完成时限。订单审计、法定留存和备份清理应有具体周期并在正式附表说明，不能无限期保留所有上传件。注销账户与未结交易处理相互衔接。

## 7. 安全、异常和责任

平台应控制后台访问并保留必要审计。用户发现误传可申请撤回或删除；发现泄露时应及时报告。各方对自身过错依法承担责任，不因用户上传而排除平台的安全保护义务。本条款不替代隐私政策，对敏感信息、第三方提供和跨境场景仍须履行专门要求。

## 生效前必须补齐的附表

1. 平台运营主体：构行人工智能（黑龙江）有限公司（业务负责人已确认全称）；注册地址为黑龙江省哈尔滨市松北区创新三路788号（2026-08-10 用户确认记录，登记原件待核）；本主体统一社会信用代码及对外服务地址仍待核实。
2. 隐私与个人信息权利申请邮箱：postmaster@goaidirect.com（业务负责人已确认），用于查询、更正、删除等个人信息申请。邮箱收件及处理流程尚待实测；其他投诉渠道、负责人及处理时限待确认。本邮箱不代表短信或注册验证码发送服务已接入。
3. 数据清单：实际采集字段、用途、法律依据、保存位置、按数据类别确定的具体期限及删除方式；各项期限需结合履约、法定留存及争议处理确定。
4. 合作方清单：支付、短信、邮件、云服务、电子签约及其他接收方的主体、处理目的、数据类别和责任；没有接入的服务不得写成已提供。
5. 跨境清单：逐项确认是否发生、目的地、境外接收方、数据类别、权利方式、适用程序和必要的单独同意；不能以“可能跨境”替代明确告知。
6. 批准记录：业务与法律审核人、批准日期、正文校验值、正式版本、生效日期和已验证的用户提示流程。任何正文改动均需新版本重新核定，不沿用旧勾选记录。


## 本次送审附表
本轮 FULL_REVIEW_INPUT_R2.md 中的接受矩阵、数据活动表、分类留存核对表、B端商务表及未成年人实施方案与本草稿共同审阅。表中源码事实不等于已上线控制，待核事项不得作为对外已兑现承诺；正式版本须将适用附表一并定稿、绑定并供用户读取。


---

## supplier_service_terms.md

# GO 酒店合作伙伴服务协议

> 待确认草稿｜版本 2026-10-02-review-draft-v3｜修订日期 2026-10-02｜尚未生效，不供注册勾选。
>
> 本文是供运营方、业务负责人和法律顾问核定的完整条款草稿，不是法律认证。GO 为产品名称。运营主体为构行人工智能（黑龙江）有限公司，隐私联系邮箱为 postmaster@goaidirect.com（由业务负责人确认）。注册地址按既有用户确认记录为黑龙江省哈尔滨市松北区创新三路788号；该地址的登记原件尚待核验，统一社会信用代码、其他投诉渠道、具体留存期限、技术服务商及跨境安排尚待核定；未补齐文末附表并完成审核前，不构成平台已作出的运营承诺，也不能作为收集注册同意的依据。

## 1. 入驻和酒店身份

合作方应是酒店经营者或具有明确授权的管理方，提供真实经营主体、酒店地址、联系方式及必要资质。全国开放建库表示接受各地酒店申请，不代表自动核验通过、自动上架或承诺已在全部地区具备完整交易服务。注册人应说明代表权限，新增酒店或切换酒店均绑定独立身份和权限。

## 2. 信息库建设

合作方可维护酒店介绍、位置、设施、政策、房型和图片，并逐项声明来源。名称、床型、面积、可住人数、早餐、吸烟政策及收费设施应准确完整。信息缺失、来源冲突或过期时应标为待补齐，不以推测填充。不将供应商组合售卖房型直接等同为酒店正式物理房型。

## 3. 图文和来源授权

合作方保留其依法享有的权利，并就明确选择发布的材料授予平台为展示、分发相应酒店产品所必需的有限使用权。范围、渠道、期限、撤回方式应在具体提交中确认，不设无限转授权。图片应核实高清原件、房型对应及著作权、人物或场地授权。可登录 OTA 后台不当然代表对全部文字图片拥有复制和再发布权；不提供 OTA 密码或验证码。

## 4. 审核、发布和更正

提交、审核、批准、发布和撤销是独立状态。平台可要求补证、拒绝冲突材料并给出理由；批准不自动免除合作方维护真实性的义务。正式房型和酒店身份应有可信证据对应。影响已售订单的更正应按订单约定处理，不以重发资料改写已成交条款。合作方可申请撤销发布，历史必要审计记录按规定保留。

## 5. 价格、库存与履约

价格计划应分别明确可售日期、库存、含税总价、早餐和入住限制。取消扣费规则属于具体报价，不以酒店统一标签覆盖全部方案。合作方应按有效订单履约，发生超售或服务差异及时处理。GO Direct 住宿合同与平台服务合同分开；经其他供应商销售时应披露实际交易关系，不冒称直销。

## 6. 结算、收费和发票

佣金、服务费、结算周期、对账及开票须另列已确认商务方案；未约定不得用默认数字替代。平台是否收款、代付或提供资金保障按真实链路披露。退款依据订单和适用法律处理，退订与资金到账分别记载。任何签约或营销活动报名需具备对应授权，不因建库而自动参加。

## 7. 人员权限与个人信息

合作方负责账户人员的授权范围和离岗回收。酒店间数据隔离，不得通过切换标识访问他店材料。住客信息只为必要履约使用，不写入公开介绍、培训资料或图册；相关委托和独立处理责任按数据处理条款落实。

## 8. 限制、终止与争议

存在冒用、侵权、虚假信息或安全风险时，平台可采取与风险相称的限制并说明原因、提供申诉；紧急措施应有后续复核。终止合作时处理未完成订单、款项、材料撤回和依法保存记录，不以停用账户免除已有义务。争议依中国法律及有效商务约定解决，不作无限免责或未经确认的专属管辖约定。

## 生效前必须补齐的附表

1. 平台运营主体：构行人工智能（黑龙江）有限公司（业务负责人已确认全称）；注册地址为黑龙江省哈尔滨市松北区创新三路788号（2026-08-10 用户确认记录，登记原件待核）；本主体统一社会信用代码及对外服务地址仍待核实。
2. 隐私与个人信息权利申请邮箱：postmaster@goaidirect.com（业务负责人已确认），用于查询、更正、删除等个人信息申请。邮箱收件及处理流程尚待实测；其他投诉渠道、负责人及处理时限待确认。本邮箱不代表短信或注册验证码发送服务已接入。
3. 数据清单：实际采集字段、用途、法律依据、保存位置、按数据类别确定的具体期限及删除方式；各项期限需结合履约、法定留存及争议处理确定。
4. 合作方清单：支付、短信、邮件、云服务、电子签约及其他接收方的主体、处理目的、数据类别和责任；没有接入的服务不得写成已提供。
5. 跨境清单：逐项确认是否发生、目的地、境外接收方、数据类别、权利方式、适用程序和必要的单独同意；不能以“可能跨境”替代明确告知。
6. 批准记录：业务与法律审核人、批准日期、正文校验值、正式版本、生效日期和已验证的用户提示流程。任何正文改动均需新版本重新核定，不沿用旧勾选记录。


## 注册与后续业务补充条款


以下为本次完整草稿的组成部分；商业与处理活动附表中未核实项目仍不生效。

**一、申请主体与代表权限。** 申请人应以实际酒店经营者或有明确授权的管理方身份申请，如实提交主体及代表权限材料。酒店信息建库、经营资质核验和产品销售分别办理。个人注册账户不当然取得代表酒店签约、修改结算账户或处分款项的权限；多人、多酒店操作须分别授权，授权到期或人员离岗应及时回收。

**二、账户开通与业务启用。** 账户注册、酒店认领、资料发布、库存销售、收费订阅、电子签约和结算分别以对应页面列明的条件为准。基础注册不视为购买付费服务、参与营销或授权平台操作第三方账户。需要后续启用的功能，应在启用前展示条件并取得相应确认。

**三、商务条件与收费确认。** 具体合作方案应分别列明交易佣金、订阅或增值服务费用、服务期间、税费与开票主体。采用零佣金的方案，应清楚说明适用交易范围，并与另行选择的订阅服务区分。新增收费或自动续费不得仅凭注册同意生效；如实际提供自动续费，应另行提示并提供便捷关闭方式。未确认的金额和周期不得以默认值补齐。

**四、订单履约与结算。** 酒店应按成立订单的价格、库存、退改及服务约定履约，并按自身责任处理超售、差异和售后；GO 按其实际交易角色承担相应义务。结算方案应另行列明结算起算事件、周期、可扣项目、退款与争议款处理、对账和异议渠道。不得将平台账面状态等同于支付机构实际到账，也不得以事后修改规则追溯改变已成立订单。

**五、资料使用与人员隐私。** 酒店仅就有权提交的资料授予明确用途和范围内的使用权限。联系人个人信息、住客资料和公开酒店资料分别处理；不因酒店注册即取得住客全部信息的使用授权。平台与酒店依各项活动确定实际处理角色，依《隐私政策》和《酒店合作数据处理条款》履行相应义务。

**六、电子确认与签约。** 注册协议接受、隐私告知及企业签约应分别记录其主体、文件版本、时间和对应权限。普通邮箱验证或注册勾选不当然代表公司印章授权，也不表明所有后续合同已获签署。电子签约功能未实际具备相应条件时，不展示认证完成或已正式签署状态。

**七、暂停、申诉与退出。** 对冒用、虚假资料、侵权或安全风险，平台可采取与风险相称的限制，说明依据并提供申诉及复核渠道。停止新增业务与处理存量订单分别安排。终止后应完成未结订单、退款与对账，按适用规则提供资料导出或返还、撤回发布和删除安排；需继续保存的资料应明确类别、依据、期限和限制用途。

**八、规则变更与生效。** 对收费、权限、数据处理或其他重大权益的变更，应依法履行公示、通知和必要的重新确认程序。正式文本应明确批准版本、生效时间及适用范围。草稿不供注册接受，旧版本接受记录不得移用于改动后的正文。



## 本次送审附表
本轮 FULL_REVIEW_INPUT_R2.md 中的接受矩阵、数据活动表、分类留存核对表、B端商务表及未成年人实施方案与本草稿共同审阅。表中源码事实不等于已上线控制，待核事项不得作为对外已兑现承诺；正式版本须将适用附表一并定稿、绑定并供用户读取。


---

## data_processing_terms.md

# GO 酒店合作数据处理条款

> 待确认草稿｜版本 2026-10-02-review-draft-v3｜修订日期 2026-10-02｜尚未生效，不供注册勾选。
>
> 本文是供运营方、业务负责人和法律顾问核定的完整条款草稿，不是法律认证。GO 为产品名称。运营主体为构行人工智能（黑龙江）有限公司，隐私联系邮箱为 postmaster@goaidirect.com（由业务负责人确认）。注册地址按既有用户确认记录为黑龙江省哈尔滨市松北区创新三路788号；该地址的登记原件尚待核验，统一社会信用代码、其他投诉渠道、具体留存期限、技术服务商及跨境安排尚待核定；未补齐文末附表并完成审核前，不构成平台已作出的运营承诺，也不能作为收集注册同意的依据。

## 1. 角色和活动表

每项活动须列出 GO 与酒店分别为独立处理者、共同处理者或受托方的实际角色。酒店建库、订单履约、平台账户管理不能一概归为委托。生效前形成活动附表，载明目的、数据类别、处理方式、期限、地点、双方责任和联系渠道。

## 2. 合法来源与最小必要

提供方应确认资料获取及提供有相应依据，并完成必要告知。公开酒店事实与员工、住客个人信息分开；无必要不传入住证件影像、支付信息或完整客人名册。平台可以拒收超范围材料，双方不得以本协议为未经告知的营销或扩展使用提供概括授权。

## 3. 受托处理限制

属于委托的活动，受托方仅按经确认的合法指令处理，超出目的应停止并重新确认。委托方有权按合理方式监督。转委托须遵守约定和法律要求，实际分包方及安全责任应事先列明；不能用“合作伙伴”统称替代接收方清单。

## 4. 提供和访问控制

向独立处理者提供个人信息应完成适用告知、授权等程序。双方应采用与风险相称的权限控制、最小字段传输和访问记录；跨酒店操作需验证所属关系。图片及文档中包含个人信息时，应先确认发布必要性或作适当处理。

## 5. 安全事件与权利请求

发现未经授权访问、误传或泄露应及时采取控制措施，通知受影响的合作方并配合履行依法应有的通知义务。收到个人查阅、更正、删除或撤回请求时，应按角色响应或转交有权处理方，并保留必要处理记录；不得相互推诿。

## 6. 期限与终止

按活动确定保存期限和起算点，不约定所有数据永久保存。委托终止后按有效约定返还或删除，法律要求保留的部分隔离限制使用并明确期限。备份清理周期及删除证明方式在附表确定，不能声称即时删除所有不可直接控制的副本。

## 7. 跨境、评估和变更

实施跨境提供、敏感处理或其他需评估的活动前，完成适用程序并形成记录。目的地、接收方及信息种类未确认时不实施跨境传输。处理目的、角色或分包方重大变化应更新活动附表，并履行需要的通知、同意或重新签署。

## 8. 责任与证据

各方对违反自身义务承担相应责任，合同分工不削弱个人法定权利。审计仅收集必要证据，不要求交换密码和验证码。上线前须核验实际控制措施，条款文本本身不证明系统符合全部要求。

## 生效前必须补齐的附表

1. 平台运营主体：构行人工智能（黑龙江）有限公司（业务负责人已确认全称）；注册地址为黑龙江省哈尔滨市松北区创新三路788号（2026-08-10 用户确认记录，登记原件待核）；本主体统一社会信用代码及对外服务地址仍待核实。
2. 隐私与个人信息权利申请邮箱：postmaster@goaidirect.com（业务负责人已确认），用于查询、更正、删除等个人信息申请。邮箱收件及处理流程尚待实测；其他投诉渠道、负责人及处理时限待确认。本邮箱不代表短信或注册验证码发送服务已接入。
3. 数据清单：实际采集字段、用途、法律依据、保存位置、按数据类别确定的具体期限及删除方式；各项期限需结合履约、法定留存及争议处理确定。
4. 合作方清单：支付、短信、邮件、云服务、电子签约及其他接收方的主体、处理目的、数据类别和责任；没有接入的服务不得写成已提供。
5. 跨境清单：逐项确认是否发生、目的地、境外接收方、数据类别、权利方式、适用程序和必要的单独同意；不能以“可能跨境”替代明确告知。
6. 批准记录：业务与法律审核人、批准日期、正文校验值、正式版本、生效日期和已验证的用户提示流程。任何正文改动均需新版本重新核定，不沿用旧勾选记录。


## 活动附表与停止条件
本条款以逐活动附表明确的实际角色为适用前提。账户管理、酒店人员信息、邮件验证、具体订单交付和住客资料交换应分别确定目的、字段、合法基础、期限、地点、接收方及权利请求责任；独立处理、共同处理与受托处理不能相互替代。附表中的待核项不构成已获得的授权。接收方、跨境路径或必要依据尚未明确的对应数据交换不得启用。处理者应对委托活动进行监督，转委托应履行适用同意和约定要求；终止时依法返还或删除，法定限制情形仅作必要存储及安全保护。


## 本次送审附表
本轮 FULL_REVIEW_INPUT_R2.md 中的接受矩阵、数据活动表、分类留存核对表、B端商务表及未成年人实施方案与本草稿共同审阅。表中源码事实不等于已上线控制，待核事项不得作为对外已兑现承诺；正式版本须将适用附表一并定稿、绑定并供用户读取。


---

## electronic_signature_authorization.md

# GO 电子签约与授权条款

> 待确认草稿｜版本 2026-10-02-review-draft-v3｜修订日期 2026-10-02｜尚未生效，不供注册勾选。
>
> 本文是供运营方、业务负责人和法律顾问核定的完整条款草稿，不是法律认证。GO 为产品名称。运营主体为构行人工智能（黑龙江）有限公司，隐私联系邮箱为 postmaster@goaidirect.com（由业务负责人确认）。注册地址按既有用户确认记录为黑龙江省哈尔滨市松北区创新三路788号；该地址的登记原件尚待核验，统一社会信用代码、其他投诉渠道、具体留存期限、技术服务商及跨境安排尚待核定；未补齐文末附表并完成审核前，不构成平台已作出的运营承诺，也不能作为收集注册同意的依据。

## 1. 适用和选择

双方可在适用法律允许范围内使用电子文件完成签约。本条款不等于已经签署未来全部合同。系统应在每次签署前展示完整文件、签署主体、版本、关键商务条件和签署动作，允许阅读、下载和确认；尚未接入电子认证时不得宣传已完成可靠电子签名认证。

## 2. 代表权限

企业用户须有权代表所列经营主体。授权应明确人员、文件类型、金额或业务范围、期限及撤回方式；代理人不得凭普通账户权限无限签约。酒店归属变化、人员离职或授权届满应及时更新，不能仅以注册邮箱推定具备公司印章权限。

## 3. 身份验证和意思表示

签署应采用与风险匹配的身份和意愿核验方式，并记录确认结果。验证码不应由平台工作人员代填或留存明文。普通注册勾选、登录成功或按钮点击不能自动宣称具备法律所要求的可靠电子签名全部条件。需要第三方认证时须确认服务商资格、证书、实际接入及验证能力。

## 4. 文件完整性和证据

签署前后应保证可核对文件内容、版本和主体，保存必要的时间、身份、授权及完整性证据。正文修改需新版本和必要的重新签署，不在既有签名下替换正文。用户应能取得已签文件副本；下载地址和保存期限需实际验证后告知。

## 5. 凭据、安全和异常

签署人应妥善保管签署凭据，发现冒用或泄露及时申请停用。平台应提供正式可达的报告途径并按权限处理。争议发生时，不以“系统记录存在”一概排除他方提出身份、授权或完整性质疑的权利。

## 6. 撤回与终止

用户可按流程撤回对未来签署的代理授权；已依法成立合同的效力及解除另按法律和合同处理。不得把撤回授权等同于无条件解除已有订单，也不得把本条款解释为自动批准付款、退款、营销报名或新的收费方案。

## 7. 待确认实施附表

须明确签约服务商、签署类型、身份验证方式、证据保存地及期限、证书验证和副本获取方式。实施附表为空或真实链路未验收时，仅保留文本审阅，不开放正式签约，不生成“认证完成”的误导性状态。

## 生效前必须补齐的附表

1. 平台运营主体：构行人工智能（黑龙江）有限公司（业务负责人已确认全称）；注册地址为黑龙江省哈尔滨市松北区创新三路788号（2026-08-10 用户确认记录，登记原件待核）；本主体统一社会信用代码及对外服务地址仍待核实。
2. 隐私与个人信息权利申请邮箱：postmaster@goaidirect.com（业务负责人已确认），用于查询、更正、删除等个人信息申请。邮箱收件及处理流程尚待实测；其他投诉渠道、负责人及处理时限待确认。本邮箱不代表短信或注册验证码发送服务已接入。
3. 数据清单：实际采集字段、用途、法律依据、保存位置、按数据类别确定的具体期限及删除方式；各项期限需结合履约、法定留存及争议处理确定。
4. 合作方清单：支付、短信、邮件、云服务、电子签约及其他接收方的主体、处理目的、数据类别和责任；没有接入的服务不得写成已提供。
5. 跨境清单：逐项确认是否发生、目的地、境外接收方、数据类别、权利方式、适用程序和必要的单独同意；不能以“可能跨境”替代明确告知。
6. 批准记录：业务与法律审核人、批准日期、正文校验值、正式版本、生效日期和已验证的用户提示流程。任何正文改动均需新版本重新核定，不沿用旧勾选记录。


## 与基础注册的关系
本文件在具体企业签约功能启用时，按该次合同和代表权限另行确认。基础账户注册仅对文件可查阅，不表示已签署本文件项下未来合同，也不授予公司印章、收付款或修改结算账户权限。需要另行签约的文件应明确主体、版本、范围、期限、身份与意愿核验及副本获取方式。


## 本次送审附表
本轮 FULL_REVIEW_INPUT_R2.md 中的接受矩阵、数据活动表、分类留存核对表、B端商务表及未成年人实施方案与本草稿共同审阅。表中源码事实不等于已上线控制，待核事项不得作为对外已兑现承诺；正式版本须将适用附表一并定稿、绑定并供用户读取。


---

## platform_operating_rules.md

# GO 酒店信息库与平台运营规范

> 待确认草稿｜版本 2026-10-02-review-draft-v3｜修订日期 2026-10-02｜尚未生效，不供注册勾选。
>
> 本文是供运营方、业务负责人和法律顾问核定的完整条款草稿，不是法律认证。GO 为产品名称。运营主体为构行人工智能（黑龙江）有限公司，隐私联系邮箱为 postmaster@goaidirect.com（由业务负责人确认）。注册地址按既有用户确认记录为黑龙江省哈尔滨市松北区创新三路788号；该地址的登记原件尚待核验，统一社会信用代码、其他投诉渠道、具体留存期限、技术服务商及跨境安排尚待核定；未补齐文末附表并完成审核前，不构成平台已作出的运营承诺，也不能作为收集注册同意的依据。

## 1. 全国申请和分阶段开放

全国酒店可按统一规则申请建立自己的信息库；账户、酒店建库、酒店身份核验、房型审核、图片授权、产品发布和实际交易分别受对应条件约束。资料未通过审核不得显示为已认证；全国申请范围不等于所有供应链和支付能力同时上线。

## 2. 信息完整度

至少按身份与位置、联系方式、房型、设施服务、入住与儿童政策、早餐、宠物、停车、费用、取消方案和图文授权分类维护。未知值保留待补齐，区分“不提供”“未核实”和“未填写”。营业时间、限制及额外费用尽量明确，不仅填“有”。检查来源和更新时间，完整度高不等于真实性已通过审核。

## 3. 房型和价格计划

酒店正式物理房型采用稳定身份。来源组合房型、套餐名、销售别名与正式房型建立可追溯映射，无法一一对应时记录差异并待审核。床型、面积和人数冲突不得静默覆盖。价格计划独立维护早餐、会员优惠、付款条件和取消扣费，不从其他方案继承未经确认的政策。

## 4. 图片准入

优先使用酒店有权提供的高清原件，核验文件完整性、清晰度、来源、用途和对应范围。酒店公区图不得冒充特定客房，示意图需标明；不得靠放大截图宣称原图高清。历史档案或第三方可见图片均需重新核对权利和当前事实。授权范围、有效期和撤回事件应可追溯。

## 5. 审核和发布

审核界面须显示酒店身份、房型差异、图片原件、授权和资料冲突。审批依据应绑定所见版本；资料变化后重新审核。发布结果需读回确认，不能仅凭按钮成功提示判定公众页面可用。撤销或权利失效后及时阻止后续展示，并记录实际处理状态。

## 6. 交易和营销边界

后台信息维护权限不等于接单、扣费、退款或营销活动授权。每类动作应有对应角色、确认和审计。订单状态、取消申请、退款处理和到账分开呈现。不得制作虚假原价、隐瞒强制收费或将默认加入活动作为注册条件。

## 7. 权限、安全和纠错

多酒店数据按归属隔离，人员变更及时回收权限。不得上传客人名单、未脱敏订单截图或账户密钥作为公共资料。平台提供纠错和申诉流程；对风险材料可暂缓展示并告知原因，审核记录不替代实际经营资质和授权。

## 8. 变更、保存与退出

规范重要变化须按适用要求公示、通知并给出合理处理安排，必要时重新确认。对适用《电子商务法》第三十四条的平台协议和交易规则修改，应在首页公开征求意见，并至少于实施前七日公示；经营者不接受修改要求退出的，应依法处理并按修改前规则承担相应责任。合作终止后处理存量订单、对账和法定记录。GO 在具体活动中属于《电子商务法》所规定的平台经营者时，对适用该法第三十一条的平台商品和服务信息、交易信息，自交易完成之日起保存不少于三年；法律、行政法规另有规定的，依其规定。应在分类清单中明确适用身份、记录类别和完成事件。该要求不自动适用于所有注册资料、验证码、图文原件或个人信息，其他类别按各自合法依据及必要期限处理。

## 生效前必须补齐的附表

1. 平台运营主体：构行人工智能（黑龙江）有限公司（业务负责人已确认全称）；注册地址为黑龙江省哈尔滨市松北区创新三路788号（2026-08-10 用户确认记录，登记原件待核）；本主体统一社会信用代码及对外服务地址仍待核实。
2. 隐私与个人信息权利申请邮箱：postmaster@goaidirect.com（业务负责人已确认），用于查询、更正、删除等个人信息申请。邮箱收件及处理流程尚待实测；其他投诉渠道、负责人及处理时限待确认。本邮箱不代表短信或注册验证码发送服务已接入。
3. 数据清单：实际采集字段、用途、法律依据、保存位置、按数据类别确定的具体期限及删除方式；各项期限需结合履约、法定留存及争议处理确定。
4. 合作方清单：支付、短信、邮件、云服务、电子签约及其他接收方的主体、处理目的、数据类别和责任；没有接入的服务不得写成已提供。
5. 跨境清单：逐项确认是否发生、目的地、境外接收方、数据类别、权利方式、适用程序和必要的单独同意；不能以“可能跨境”替代明确告知。
6. 批准记录：业务与法律审核人、批准日期、正文校验值、正式版本、生效日期和已验证的用户提示流程。任何正文改动均需新版本重新核定，不沿用旧勾选记录。


## 本次送审附表
本轮 FULL_REVIEW_INPUT_R2.md 中的接受矩阵、数据活动表、分类留存核对表、B端商务表及未成年人实施方案与本草稿共同审阅。表中源码事实不等于已上线控制，待核事项不得作为对外已兑现承诺；正式版本须将适用附表一并定稿、绑定并供用户读取。


## 固定源码索引

S1：application/src/go_hotel/services/registration_privacy.py，Git blob 2e64411a87c7f32254c0314590767ce799580a2a。

S2：application/src/go_hotel/services/registration_verification.py，Git blob 9e8dccdc5bfd08968f90865a27251c758344db47。

S3：application/src/go_hotel/api/routes/consumer_identity.py，Git blob de24703012cf42b84ae29df57c7abcb06fcd1084。

S4：application/src/go_hotel/api/routes/bff.py，Git blob 5f9b655e93939b24d6320f0ac523114d36276851。

S5：application/src/go_hotel/services/registration_terms.py，Git blob 86c6781a5ff016923e5f1c210704f16e098c28e2。

S6：application/src/go_hotel/workers/reconciliation_worker.py，Git blob ab05e87b889a844f24a98eabe26c72685297fe5c。

S7：application/src/go_hotel/core/v61_commercial_policy.py，Git blob d83173e0fc20c4febf7232c49307cf79741ea4f2。

S8：application/src/go_hotel/services/registration_email.py，Git blob eb0dc7ac382fa58e4234360b5f270538ab5911d1。

S9：application/src/go_hotel/api/routes/registration_privacy.py，Git blob 21e7fcc0838d37171da114dda8edf2ab462133b0。

S10：application/src/go_hotel/consumer/service.py，Git blob 1f43a0f357154a0936d65db15439237e98eab543。

S11：application/src/go_hotel/services/supplier_onboarding.py，Git blob 83431e462434203648a394275d1d8bac3b341961。

### 源码原文摘录：services/registration_privacy.py
```python
"""Registration privacy controls. Evidence is operator supplied, never self-approved."""
import hashlib
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select, delete
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (RegistrationChallengeRow, RegistrationRateRow,
    RegistrationDecisionRow, RegistrationMaintenanceRow, PrivacyRequestRow, AuditEventRow)
from go_hotel.domain.models import new_id

DAY = 86_400_000
# GO engineering policy, not a claim that every category has a statutory 3-year term.
DECISION_DAYS = 1095
CLEANUP_MAX_AGE_MS = 120_000
logger = logging.getLogger(__name__)


def now_ms():
    return int(datetime.now(timezone.utc).timestamp()*1000)


def required_decisions(policy):
    return {k: ('NOTICE_ACKNOWLEDGED' if k == 'privacy_policy' else
                'DEFERRED' if k == 'personal_vault_terms' else 'CONTRACT_ACCEPTED')
            for k in policy['versions']}


def validate_decisions(policy, decisions):
    if decisions != required_decisions(policy):
        raise ValueError('REGISTRATION_SEPARATE_DECISIONS_REQUIRED')
    return dict(decisions)


def record_decisions(session, user_id, audience, policy, decisions):
    decisions = validate_decisions(policy, decisions)
    t = now_ms()
    session.add(RegistrationDecisionRow(decision_id=new_id('rd'),user_id=user_id,
        audience=audience,decisions=decisions,versions=dict(policy['versions']),
        hashes=dict(policy['term_hashes']),created_ms=t,expires_ms=t+DECISION_DAYS*DAY))


def cleanup_once(*, invalidate_challenges=False):
    """Independent of registration traffic; atomic cleanup + success heartbeat.

    Run by the already deployed reconciliation service every 30 seconds. A missing,
    failed or stale heartbeat closes new registrations instead of claiming cleanup.
    Expiry-based replay also removes restored expired rows before worker readiness.
    """
    t = now_ms()
    with SessionLocal.begin() as s:
        counts = {}
        if invalidate_challenges:
            s.execute(delete(RegistrationChallengeRow))
        for model, name in ((RegistrationChallengeRow,'challenges'),(RegistrationRateRow,'rate_buckets'),(RegistrationDecisionRow,'decisions')):
            result = s.execute(delete(model).where(model.expires_ms <= t))
            counts[name] = result.rowcount
        cutoff = datetime.fromtimestamp((t-DECISION_DAYS*DAY)/1000,timezone.utc)
        s.execute(delete(AuditEventRow).where(AuditEventRow.action.in_([
            'CONSUMER_REGISTRATION_TERMS_ACCEPTED','SUPPLIER_REGISTRATION_TERMS_ACCEPTED','PRIVACY_REQUEST_RESOLVED']),AuditEventRow.created_at <= cutoff))
        # Unresolved rights cases must not vanish; escalate them to the operator.
        s.execute(delete(PrivacyRequestRow).where(PrivacyRequestRow.status.in_(['COMPLETED','REJECTED']),PrivacyRequestRow.updated_ms <= t-DECISION_DAYS*DAY))
        from go_hotel.services.registration_verification import insert_for
        stmt=insert_for(s,RegistrationMaintenanceRow).values(key='cleanup',success_ms=t)
        s.execute(stmt.on_conflict_do_update(index_elements=['key'],set_={'success_ms':t}))
        overdue=len(s.scalars(select(PrivacyRequestRow.request_id).where(PrivacyRequestRow.status.in_(['RECEIVED','IN_REVIEW','RESTRICTED_RETENTION']),PrivacyRequestRow.due_ms<t).limit(100)).all())
    if overdue:
        logger.warning('PRIVACY_REQUESTS_OVERDUE count_capped=%d',overdue)
    return counts


def maintenance_status():
    try:
        with SessionLocal() as s:
            row=s.get(RegistrationMaintenanceRow,'cleanup')
            fresh=bool(row and 0 <= now_ms()-row.success_ms <= CLEANUP_MAX_AGE_MS)
        return {'ready':fresh,'max_age_seconds':CLEANUP_MAX_AGE_MS//1000}
    except Exception:
        return {'ready':False,'max_age_seconds':CLEANUP_MAX_AGE_MS//1000}


EVIDENCE_CATEGORIES = ('operator','data_inventory','smtp_processor','cross_border',
                       'retention_schedule','backups','rights_operations')


def operational_evidence_status():
    """Validate completeness/binding only, NOT authenticity or legal sufficiency.

    The fixed operator-mounted file must be reviewed before use. Hash references
    bind real records; this code cannot manufacture contracts or legal approval.
    No payload is exposed publicly; no credential is part of this file.
    """
    try:
        raw=Path(settings.registration_privacy_evidence_path).read_bytes()
        value=json.loads(raw)
        if value.get('schema_version')!=1 or value.get('status')!='APPROVED':
            raise ValueError()
        if value.get('terms_version')!=settings.registration_terms_version:
            raise ValueError()
        expiry=datetime.fromisoformat(value['valid_until'])
        if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):
            raise ValueError()
        for name in EVIDENCE_CATEGORIES:
            entry=value[name]
            if not isinstance(entry,dict) or not all(entry.get(k) for k in ('reviewer','reviewed_at','evidence_ref','sha256','scope')):
                raise ValueError()
            if len(entry['sha256'])!=64 or any(c not in '0123456789abcdef' for c in entry['sha256']):
                raise ValueError()
            reviewed=datetime.fromisoformat(entry['reviewed_at'])
            if reviewed.tzinfo is None or reviewed>datetime.now(timezone.utc):
                raise ValueError()
        return {'ready':True,'digest':hashlib.sha256(raw).hexdigest()}
    except (OSError,ValueError,KeyError,TypeError):
        return {'ready':False,'digest':None}


def ready():
    return operational_evidence_status()['ready'] and maintenance_status()['ready']


def own_history(user_id):
    with SessionLocal() as s:
        rows=s.scalars(select(RegistrationDecisionRow).where(RegistrationDecisionRow.user_id==user_id).order_by(RegistrationDecisionRow.created_ms)).all()
        return [dict(id=x.decision_id,decisions=x.decisions,versions=x.versions,hashes=x.hashes,created_ms=x.created_ms) for x in rows]


KINDS={'ACCESS','CORRECTION','DELETION','WITHDRAWAL','CLOSURE','RESTRICTION','TRANSFER'}


def case_view(x):
    return dict(request_id=x.request_id,kind=x.kind,status=x.status,created_ms=x.created_ms,due_ms=x.due_ms,resolution=x.resolution)


def submit_request(user_id,kind):
    if kind not in KINDS:
        raise ValueError('PRIVACY_REQUEST_KIND_INVALID')
    t=now_ms()
    with SessionLocal.begin() as s:
        # Bound duplicates; actual handling remains visible, never auto-completed.
        active=s.scalar(select(PrivacyRequestRow).where(PrivacyRequestRow.user_id==user_id,PrivacyRequestRow.kind==kind,PrivacyRequestRow.status.in_(['RECEIVED','IN_REVIEW','RESTRICTED_RETENTION'])))
        if active:return case_view(active)
        item=PrivacyRequestRow(request_id=new_id('prv'),user_id=user_id,kind=kind,status='RECEIVED',created_ms=t,due_ms=t+15*DAY,updated_ms=t,resolution={})
        s.add(item)
        return case_view(item)


def requests_for(user_id):
    with SessionLocal() as s:
        return [case_view(x) for x in s.scalars(select(PrivacyRequestRow).where(PrivacyRequestRow.user_id==user_id).order_by(PrivacyRequestRow.created_ms.desc()).limit(100))]

```

### 源码原文摘录：services/registration_verification.py
```python
"""Durable, email/purpose/policy-bound, single-use registration challenges."""
import hashlib
import hmac
import json
import re
import secrets
import time
from sqlalchemy import select, update, delete
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RegistrationChallengeRow as Challenge, RegistrationRateRow as Rate
from go_hotel.services import registration_email

TTL_MS = 600_000
MAX_ATTEMPTS = 5


def now_ms():
    return int(time.time() * 1000)


def normalize_email(value):
    value = value.strip().lower()
    if len(value) > 128 or not re.fullmatch(r'[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+', value):
        raise ValueError('VALID_EMAIL_REQUIRED')
    return value


def digest(value):
    key = settings.jwt_signing_key
    if len(key) < 32 or key.startswith('dev-'):
        raise ValueError('REGISTRATION_VERIFICATION_NOT_READY')
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def ready():
    try:
        digest('readiness')
        from go_hotel.services import registration_privacy
        return registration_email.ready() and registration_privacy.ready()
    except ValueError:
        return False


def policy_digest(policy):
    return hashlib.sha256(json.dumps({'versions': policy['versions'], 'hashes': policy['term_hashes']}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def subject(audience, email):
    if audience not in ('consumer', 'supplier'):
        raise ValueError('REGISTRATION_AUDIENCE_INVALID')
    return digest(audience + '\0' + normalize_email(email))


def insert_for(session, table):
    if session.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    elif session.bind.dialect.name == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise ValueError('REGISTRATION_DATABASE_UNSUPPORTED')
    return insert(table)


def issue(audience, email, client_ip, policy):
    if not ready():
        raise ValueError('REGISTRATION_VERIFICATION_NOT_READY')
    email = normalize_email(email)
    key, t = subject(audience, email), now_ms()
    challenge_id, code = secrets.token_urlsafe(24), f'{secrets.randbelow(1_000_000):06d}'
    with SessionLocal.begin() as s:
        # Shared durable limits: per address, per transport peer and globally.
        # Never trust an arbitrary forwarded-for header here.
        s.execute(delete(Rate).where(Rate.expires_ms < t))
        s.execute(delete(Challenge).where(Challenge.expires_ms < t - 86_400_000))
        for name, identity, window, limit in (
            ('cooldown', email, 60_000, 1), ('email', email, 3_600_000, 5),
            ('peer', client_ip or 'unknown', 3_600_000, 20), ('global', 'all', 3_600_000, 500),
        ):
            bucket = digest(f'{name}\0{identity}\0{t // window}')
            s.execute(insert_for(s, Rate).values(bucket_key=bucket, count=0, expires_ms=(t // window + 1) * window).on_conflict_do_nothing(index_elements=['bucket_key']))
            if s.execute(update(Rate).where(Rate.bucket_key == bucket, Rate.count < limit).values(count=Rate.count + 1)).rowcount != 1:
                raise ValueError('REGISTRATION_CODE_RATE_LIMITED')
        # Sliding resend interval as well as fixed-window anti-abuse counters.
        old = s.scalar(select(Challenge).where(Challenge.subject_key == key))
        if old and old.created_ms > t - 60_000:
            raise ValueError('REGISTRATION_CODE_RATE_LIMITED')
        values = dict(subject_key=key, challenge_id=challenge_id, code_digest=digest(challenge_id + '\0' + code), policy_digest=policy_digest(policy), state='SENDING', attempts=0, expires_ms=t + TTL_MS, created_ms=t, consumed_by=None)
        stmt = insert_for(s, Challenge).values(**values)
        # INSERT rowcount is not portable across drivers. RETURNING also yields
        # no row when the concurrent resend predicate rejects the update.
        written = s.scalar(stmt.on_conflict_do_update(index_elements=['subject_key'], set_=values, where=Challenge.created_ms <= t - 60_000).returning(Challenge.challenge_id))
        if written != challenge_id:
            raise ValueError('REGISTRATION_CODE_RATE_LIMITED')
    try:
        registration_email.send_code(email, code)
    except ValueError:
        with SessionLocal.begin() as s:
            s.execute(update(Challenge).where(Challenge.challenge_id == challenge_id).values(state='FAILED'))
        raise
    with SessionLocal.begin() as s:
        if s.execute(update(Challenge).where(Challenge.challenge_id == challenge_id, Challenge.state == 'SENDING').values(state='SENT')).rowcount != 1:
            raise ValueError('REGISTRATION_CODE_REPLACED')
    return {'challenge_id': challenge_id, 'expires_in': 600, 'resend_after': 60, 'status': 'SENT'}


def check(audience, email, challenge_id, code, policy):
    """Wrong attempts commit independently; successful proof is not yet consumed."""
    if not ready():
        raise ValueError('REGISTRATION_VERIFICATION_NOT_READY')
    key, t = subject(audience, email), now_ms()
    valid = False
    with SessionLocal.begin() as s:
        row = s.scalar(select(Challenge).where(Challenge.subject_key == key, Challenge.challenge_id == challenge_id))
        if row and row.state == 'SENT' and row.expires_ms > t and row.attempts < MAX_ATTEMPTS:
            valid = (hmac.compare_digest(row.code_digest, digest(challenge_id + '\0' + code)) and row.policy_digest == policy_digest(policy))
            if not valid:
                s.execute(update(Challenge).where(Challenge.challenge_id == challenge_id, Challenge.attempts < MAX_ATTEMPTS).values(attempts=Challenge.attempts + 1))
    if not valid:
        raise ValueError('REGISTRATION_CODE_INVALID_OR_EXPIRED')
    return {'subject_key': key, 'challenge_id': challenge_id, 'code_digest': digest(challenge_id + '\0' + code), 'policy_digest': policy_digest(policy)}


def consume(session, proof, user_id):
    """Same transaction as account+audit: commit together or rollback together."""
    result = session.execute(update(Challenge).where(
        Challenge.subject_key == proof['subject_key'], Challenge.challenge_id == proof['challenge_id'],
        Challenge.code_digest == proof['code_digest'], Challenge.policy_digest == proof['policy_digest'],
        Challenge.state == 'SENT', Challenge.expires_ms > now_ms(), Challenge.attempts < MAX_ATTEMPTS,
    ).values(state='CONSUMED', consumed_by=user_id))
    if result.rowcount != 1:
        raise ValueError('REGISTRATION_CODE_INVALID_OR_EXPIRED')
    if 'registration_decisions' in proof:
        from go_hotel.services.registration_privacy import record_decisions
        record_decisions(session,user_id,proof['audience'],proof['policy'],proof['registration_decisions'])

```

### 源码原文摘录：services/registration_terms.py
```python
"""Versioned, hash-bound registration documents; bundled drafts never enable signup."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from go_hotel.core.config import settings
from pathlib import Path

_REGISTRY_ROOT = Path(__file__).resolve().parents[1] / 'legal' / 'registration'
_DRAFT_VERSION = '2026-09-19-draft-v2'
_REQUIRED = {
    'consumer': ('consumer_service_terms', 'privacy_policy', 'personal_vault_terms'),
    'supplier': ('supplier_service_terms', 'privacy_policy', 'data_processing_terms',
                 'electronic_signature_authorization', 'platform_operating_rules'),
}
_REQUIRED_RELEASE_FIELDS = ('operator', 'contact_channels', 'retention_schedule',
                            'recipients', 'cross_border_assessment')


def _load_registry() -> dict:
    version = settings.registration_terms_version
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,80}', version):
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    return json.loads((_REGISTRY_ROOT / version / 'registry.json').read_text(encoding='utf-8'))


def _document(registry: dict, term_id: str, version: str) -> dict:
    # Resolve ONLY a server-registered id/version; no client-supplied filesystem path.
    entries = [x for x in registry['documents'] if x['id'] == term_id and x['version'] == version]
    if len(entries) != 1:
        raise ValueError('REGISTRATION_TERMS_NOT_FOUND')
    item = entries[0]
    root = _REGISTRY_ROOT.resolve()
    path = (root / item['version'] / item['file']).resolve()
    if root not in path.parents or path.suffix != '.md':
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    try:
        raw = path.read_bytes()
        content = raw.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR') from exc
    digest = sha256(raw).hexdigest()
    if digest != item['sha256'] or not content.strip():
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    return {key: item[key] for key in ('id', 'title', 'version', 'status')} | {
        'sha256': digest, 'content_url': f"/v1/registration-terms/{term_id}/{version}",
        'content': content, 'content_type': 'text/markdown; charset=utf-8',
        'effective_at': item.get('effective_at'),
    }


def read_registration_term(term_id: str, version: str) -> dict:
    return _document(_load_registry(), term_id, version)


def registration_terms_status(audience: str) -> dict:
    if audience not in _REQUIRED:
        raise ValueError('REGISTRATION_TERMS_AUDIENCE_INVALID')
    registry = _load_registry()
    entries = {x['id']: x for x in registry['documents']}
    if len(entries) != len(registry['documents']):
        raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
    documents = []
    ready = registry.get('release_status') == 'APPROVED' and not registry.get('unresolved')
    ready = ready and all(registry.get(key) for key in _REQUIRED_RELEASE_FIELDS)
    operator = registry.get('operator') or {}
    contact = registry.get('contact_channels') or {}
    ready = ready and all(operator.get(k) for k in ('legal_name', 'registration_address', 'unified_social_credit_code'))
    ready = ready and contact.get('delivery_verified') is True
    for ident in _REQUIRED[audience]:
        if ident not in entries:
            raise ValueError('REGISTRATION_TERMS_INTEGRITY_ERROR')
        item = entries[ident]
        doc = _document(registry, ident, item['version'])
        approval = item.get('approval') or {}
        approved = (item['status'] == 'APPROVED' and '待确认草稿｜版本' not in doc['content'] and
                    'draft' not in item['version'].lower() and
                    approval.get('sha256') == doc['sha256'] and
                    all(approval.get(k) for k in ('reviewer', 'approved_at', 'evidence_ref')))
        try:
            effective = datetime.fromisoformat(item.get('effective_at') or '')
            approved_at = datetime.fromisoformat(approval.get('approved_at') or '')
            now = datetime.now(timezone.utc)
            approved = (approved and effective.tzinfo is not None and effective <= now and
                        approved_at.tzinfo is not None and approved_at <= now)
        except (TypeError, ValueError):
            approved = False
        ready = ready and approved
        documents.append({k: v for k, v in doc.items() if k != 'content'})
    return {'audience': audience, 'status': 'APPROVED' if ready else 'DRAFT',
            'acceptance_enabled': bool(ready), 'enabled': bool(ready),
            'versions': {x['id']: x['version'] for x in documents},
            'term_hashes': {x['id']: x['sha256'] for x in documents},
            'documents': documents, 'unresolved': list(registry.get('unresolved') or [])}


def require_registration_terms_ready(audience: str) -> dict:
    status = registration_terms_status(audience)
    if not status['acceptance_enabled']:
        raise ValueError('REGISTRATION_TERMS_NOT_READY')
    return status

```

### 源码原文摘录：workers/reconciliation_worker.py
```python
from __future__ import annotations
import asyncio, time, logging
from go_hotel.services.reconciliation import reconciliation_service
from go_hotel.services.registration_privacy import cleanup_once


def main():
    first_cycle=True
    while True:
        try:
            cleanup_once(invalidate_challenges=first_cycle)
            first_cycle=False
        except Exception:
            # Never log database parameters/PII. Stale heartbeat blocks new signup.
            logging.getLogger(__name__).error('REGISTRATION_PRIVACY_CLEANUP_FAILED')
        try:
            asyncio.run(reconciliation_service.run_once(100))
        except Exception:
            logging.getLogger(__name__).error('RECONCILIATION_CYCLE_FAILED')
        time.sleep(30)
if __name__ == "__main__": main()

```

### 源码原文摘录：core/v61_commercial_policy.py
```python
"""GO V6.1 2026-08-22 hotel commercial, Virtual Direct and star-equivalent policy.

Controlling assumptions for planning and system guardrails. Supplier prices/inventory remain
supplier-owned facts and must never be mutated by these helpers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CommercialTier = Literal["UP_TO_TWO_DIAMOND", "THREE_DIAMOND", "FOUR_DIAMOND", "FIVE_DIAMOND"]

Y1_LAUNCH_MONTHLY_CNY = {
    "UP_TO_TWO_DIAMOND": 399,
    "THREE_DIAMOND": 699,
    "FOUR_DIAMOND": 999,
    "FIVE_DIAMOND": 1999,
}

EQUIVALENT_BILLING_MONTHS = 10
T20_FINAL_COMPLETION_TARGET = 1.0
LIVE_HOTEL_TARGETS = {"Y1": 60_000, "Y2": 300_000, "Y3": 540_000}
Y1_TOTAL_OPERATING_BUDGET_CNY = 160_000_000
Y1_ADVERTISING_BRAND_BUDGET_CNY = 30_000_000
AI_BASE_INFRASTRUCTURE_CALL_PRICE_CNY = 0

# Internal planning mix only; not an authoritative market statistic.
NATIONAL_TIER_WORKING_ASSUMPTION = {
    "UP_TO_TWO_DIAMOND": 270_000,
    "THREE_DIAMOND": 200_000,
    "FOUR_DIAMOND": 80_000,
    "FIVE_DIAMOND": 30_000,
}

# Y2+ room-band working assumptions used only for financial planning.
FOUR_DIAMOND_ROOM_MIX = {"LE_130": 0.75, "GT_130": 0.25}
FIVE_DIAMOND_ROOM_MIX = {"LT_200": 0.20, "R200_300": 0.40, "GT_300": 0.40}

STAR_EQUIVALENT_LABELS = {
    3: "GO ★★★",
    4: "GO ★★★★",
    5: "GO ★★★★★",
    6: "GO ★★★★★+",
}
STAR_EQUIVALENT_REFERENCE = "GB/T 14308-2023"

VIRTUAL_DIRECT_PRINCIPLES = (
    "HOTEL_OWNS_PRICE",
    "HOTEL_CONTROLS_INVENTORY",
    "GO_PROVIDES_INDEPENDENT_LOW_COST_OFFICIAL_DIRECT_CHANNEL",
    "VIRTUAL_DIRECT_FIRST_NOT_DEEP_PMS_REQUIRED",
    "GO_MUST_NOT_AUTO_CHANGE_SUPPLIER_PRICE",
    "PRICE_AND_BENEFIT_ADVANTAGE_MUST_BE_SUPPLIER_AUTHORIZED",
)

AI_DISTRIBUTION_PRINCIPLES = (
    "GO_DOES_NOT_BUY_DISTRIBUTION",
    "GO_EARNS_DISTRIBUTION_THROUGH_VALUE",
    "NO_PAID_AI_RECOMMENDATION_RANKING",
    "AUTHORIZED_AI_BASE_CALLS_ARE_FREE",
)


def monthly_subscription_cny(tier: CommercialTier, room_count: int | None = None, *, year: int = 1) -> int:
    """Return the controlled subscription price for planning/contract selection.

    This does not mutate a supplier's price/inventory and is independent of GO Judgment or GO Star Equivalent.
    """
    if year <= 1:
        return Y1_LAUNCH_MONTHLY_CNY[tier]
    if tier == "UP_TO_TWO_DIAMOND":
        return 399
    if tier == "THREE_DIAMOND":
        return 699
    if room_count is None or room_count < 0:
        raise ValueError("room_count is required for FOUR_DIAMOND/FIVE_DIAMOND from Y2 onward")
    if tier == "FOUR_DIAMOND":
        return 999 if room_count <= 130 else 1299
    if tier == "FIVE_DIAMOND":
        if room_count < 200:
            return 1999
        if room_count <= 300:
            return 2999
        return 3999
    raise ValueError(f"unknown tier: {tier}")


def star_equivalent_label(level: int, *, official_award: bool = False) -> str:
    if level not in STAR_EQUIVALENT_LABELS:
        raise ValueError("GO Star Equivalent supports 3, 4, 5 and 5+ only")
    label = STAR_EQUIVALENT_LABELS[level]
    if official_award and level != 6:
        return f"官方 {label.replace('GO ', '')}"
    return label


def y1_weighted_monthly_cny() -> float:
    total = sum(NATIONAL_TIER_WORKING_ASSUMPTION.values())
    return sum(NATIONAL_TIER_WORKING_ASSUMPTION[t] * Y1_LAUNCH_MONTHLY_CNY[t] for t in NATIONAL_TIER_WORKING_ASSUMPTION) / total


def mature_weighted_monthly_cny() -> float:
    n = NATIONAL_TIER_WORKING_ASSUMPTION
    four_avg = FOUR_DIAMOND_ROOM_MIX["LE_130"] * 999 + FOUR_DIAMOND_ROOM_MIX["GT_130"] * 1299
    five_avg = FIVE_DIAMOND_ROOM_MIX["LT_200"] * 1999 + FIVE_DIAMOND_ROOM_MIX["R200_300"] * 2999 + FIVE_DIAMOND_ROOM_MIX["GT_300"] * 3999
    total = sum(n.values())
    return (n["UP_TO_TWO_DIAMOND"]*399 + n["THREE_DIAMOND"]*699 + n["FOUR_DIAMOND"]*four_avg + n["FIVE_DIAMOND"]*five_avg) / total


def base_subscription_revenue_cny(year_key: Literal["Y1", "Y2", "Y3"]) -> float:
    avg = y1_weighted_monthly_cny() if year_key == "Y1" else mature_weighted_monthly_cny()
    return LIVE_HOTEL_TARGETS[year_key] * avg * EQUIVALENT_BILLING_MONTHS

```

### 源码原文摘录：api/routes/registration_privacy.py
```python
"""Authenticated privacy intake; recorded requests are not deletion receipts."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from go_hotel.security.deps import consumer_principal, supplier_principal, admin_principal
from go_hotel.security.service import Principal
from go_hotel.services import registration_privacy as privacy
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import PrivacyRequestRow, AuditEventRow
from go_hotel.domain.models import new_id
from datetime import datetime, timezone

router=APIRouter(tags=['registration-privacy'])


class RequestBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: Literal['ACCESS','CORRECTION','DELETION','WITHDRAWAL','CLOSURE','RESTRICTION','TRANSFER']


def overview(p,response):
    response.headers['Cache-Control']='no-store'
    return {'data':{'decisions':privacy.own_history(p.user_id),'requests':privacy.requests_for(p.user_id),
        'intake_available':True,'operational_readiness':privacy.operational_evidence_status()['ready'],
        'notice':'申请提交后等待核验处理，不表示数据已删除或账号已注销。',
        'vault_consents_url':'/v1/consumer/profile/consents' if p.actor_type=='CONSUMER' else None}}


@router.get('/v1/consumer/privacy')
def consumer_overview(response:Response,p:Principal=Depends(consumer_principal)):
    return overview(p,response)


@router.get('/bff/privacy')
def supplier_overview(response:Response,p:Principal=Depends(supplier_principal)):
    return overview(p,response)


@router.post('/v1/consumer/privacy/requests',status_code=202)
def consumer_request(body:RequestBody,p:Principal=Depends(consumer_principal)):
    return {'data':privacy.submit_request(p.user_id,body.kind)}


@router.post('/bff/privacy/requests',status_code=202)
def supplier_request(body:RequestBody,p:Principal=Depends(supplier_principal)):
    return {'data':privacy.submit_request(p.user_id,body.kind)}


def privacy_operator(p:Principal=Depends(admin_principal)):
    if 'admin:trust' not in p.permissions:
        raise HTTPException(403,detail='PRIVACY_OPERATOR_REQUIRED')
    return p


@router.get('/internal/privacy/requests')
def queue(response:Response,p:Principal=Depends(privacy_operator)):
    response.headers['Cache-Control']='no-store'
    with SessionLocal() as s:
        rows=s.scalars(select(PrivacyRequestRow).where(PrivacyRequestRow.status.in_(['RECEIVED','IN_REVIEW','RESTRICTED_RETENTION'])).order_by(PrivacyRequestRow.due_ms).limit(100))
        return {'data':{'items':[privacy.case_view(x) for x in rows],'maintenance':privacy.maintenance_status()}}


class ResolutionBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_status: Literal['RECEIVED','IN_REVIEW','RESTRICTED_RETENTION']
    status: Literal['IN_REVIEW','COMPLETED','REJECTED','RESTRICTED_RETENTION']
    evidence_ref: str=Field(min_length=1,max_length=512)
    summary: str=Field(min_length=1,max_length=1000)
    legal_basis: str=Field(default='',max_length=500)
    restricted_scope: str=Field(default='',max_length=500)
    next_review_ms: int|None=None


@router.post('/internal/privacy/requests/{request_id}/resolution')
def resolve(request_id:str,body:ResolutionBody,p:Principal=Depends(privacy_operator)):
    with SessionLocal.begin() as s:
        row=s.scalar(select(PrivacyRequestRow).where(PrivacyRequestRow.request_id==request_id).with_for_update())
        if not row:raise HTTPException(404,detail='PRIVACY_REQUEST_NOT_FOUND')
        if row.status!=body.expected_status:raise HTTPException(409,detail='PRIVACY_REQUEST_CHANGED')
        if row.status=='RECEIVED' and body.status!='IN_REVIEW':raise HTTPException(409,detail='PRIVACY_REVIEW_REQUIRED')
        if body.status in ('REJECTED','RESTRICTED_RETENTION') and not body.legal_basis.strip():
            raise HTTPException(422,detail='PRIVACY_LEGAL_BASIS_REQUIRED')
        if body.status=='RESTRICTED_RETENTION' and (not body.restricted_scope.strip() or not body.next_review_ms or body.next_review_ms<=privacy.now_ms()):
            raise HTTPException(422,detail='PRIVACY_RESTRICTION_SCOPE_AND_REVIEW_REQUIRED')
        before=row.status
        row.status=body.status;row.updated_ms=privacy.now_ms()
        row.resolution={'operator':p.user_id,'evidence_ref':body.evidence_ref,'summary':body.summary,
                        'legal_basis':body.legal_basis,'restricted_scope':body.restricted_scope}
        if body.status=='RESTRICTED_RETENTION':row.due_ms=body.next_review_ms
        s.add(AuditEventRow(audit_id=new_id('aud'),actor_id=p.user_id,actor_type=p.actor_type,
            supplier_id=p.supplier_id,roles=list(p.roles),session_id=p.session_id,
            action='PRIVACY_REQUEST_RESOLVED',resource_type='PRIVACY_REQUEST',resource_id=request_id,
            request_id=None,client_ip=None,http_method='POST',path='/internal/privacy/requests/resolution',
            before_state={'status':before},after_state={'status':row.status},decision_id=None,
            evidence_id=None,approval_id=None,metadata_json=row.resolution,created_at=datetime.now(timezone.utc)))
        return {'data':privacy.case_view(row)}

```
