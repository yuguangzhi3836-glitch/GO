# DEPTH35R2 浏览器验收准备与断点

2026-09-10，按用户“继续下一关”推进。当前候选仍为 DEPTH35R2；业务源码没有变化。

本轮完成：重新核对冻结候选 1243 个文件；核对消费者、供应商、管理员及 Direct 详情 4 个入口页面直接引用的 55 项脚本和样式均存在且纳入指纹；确认 GitHub 候选分支仍指向 `a758f4d7b2f8cc9437a2a8c4b315ca41a19320f4`；检查当前浏览器仅有 about:blank，未提供视口设置能力。

以上仅是源码与环境预检，不是页面渲染、真实登录或浏览器旅程验收。

## 需要补齐的输入

`ENVIRONMENT_INPUT.template.json` 已锁定候选、源码树、三端路由和角色。其余空项需要来自已批准隔离环境的真实记录：

- 浏览器政策允许访问的三端地址，以及该环境批准范围的记录。
- 当前运行进程／镜像和安装包身份、运行源码指纹、实际提供的前端资源证据。
- 合成测试账户的非秘密别名、预期身份／供应商归属与既有隔离订单引用；登录通过 browserAuth 交接。
- 浏览器版本和可真实执行的桌面／移动视口能力。

仅提供网址或历史香港部署文档不足以证明当前候选运行绑定。没有要求在聊天中提供密码或令牌。

## 唯一下一动作

取得并核验上述正式隔离验收入口及运行绑定后，先执行 `ACCEPTANCE_MATRIX.md` 的 C-D 消费者桌面登录旅程并保存原始证据，再推进其余角色与移动视口。当前六组主旅程均 NOT_RUN，四级发布门禁均 HOLD。

## 文件

- `SOURCE_AND_ENTRYPOINTS.json`：本次指纹核对与页面入口资源清单。
- `ENVIRONMENT_INPUT.template.json`：待填写的非秘密环境交接表；不是运行证据。
- `ACCEPTANCE_MATRIX.md`：六组旅程、身份隔离与 V14 Direct 详情检查。
- `BROWSER_CAPABILITIES.json`：本轮浏览器标签和公开能力的原始观察。
- `HISTORICAL_BROWSER_DENIAL.json`：此前拒绝记录，明确标为历史材料。
- `GATE_STATE.json`：本轮实际执行范围、未执行项与门禁状态。
- `SHA256SUMS`：本包其他文件的校验值。

既有候选与通过／失败原始证据均保留。本轮不启动服务、不修改账户或权限、不触发 CI、不合并、不部署、不连接香港。

[既有候选](https://github.com/yuguangzhi3836-glitch/GO/tree/a758f4d7b2f8cc9437a2a8c4b315ca41a19320f4/deliverables/CP11_DEPTH35R2_SESSION_TRANSITIONS_20260910) · [原始隔离验收](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34440381225)
