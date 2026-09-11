(function(){
  const c=window.GO_CONSOLE;if(!c)return;
  c.title='GO 全生态运营管理系统';
  c.subtitle='系统自动运行 · 人只处理异常';
  const zh={
    '/hotel-page-factory':'酒店数字基础设施','/dashboard':'运营总览','/r8-readiness':'R8 预发布就绪度','/phase1-closure':'一期闭环',
    '/vertical-hotel':'酒店运营','/vertical-flight':'机票运营','/vertical-rail':'铁路运营','/vertical-ride':'接送用车运营','/vertical-rental':'租车运营','/vertical-attraction':'景点门票与体验',
    '/supplier-registry':'供应商管理','/orders':'订单与履约','/refunds':'退款管理','/payment-operations':'支付状态','/finance-reconciliation':'平台交易证据核验','/settlement':'结算状态记录',
    '/dispute-reconciliation-command-center':'争议处理','/stay-operations-command-center':'入住履约运营中心','/hosted-frontdesk-command-center':'前台履约工作台','/hosted-reservation-operations':'预订运营','/hosted-reservations':'预订申请收件箱','/hosted-direct-pilot':'Hosted Direct 试点',
    '/alipay-safeguarded-settlement':'支付宝支付状态','/hosted-content-acceptance':'酒店内容验收',
    '/go-recommendations':'GO 推荐管理','/go-reviews':'点评管理','/go-truth':'GO Truth 真实评价','/go-stars':'GO 星级','/go-trips':'GO Trips 行程','/judgments':'GO 判断证据',
    '/good-hotel-standard':'GO 好酒店标准','/go-identity':'GO 身份凭证','/go-offer':'GO Offer 治理','/t20-finance':'T+20 平台记录','/supplier-fault':'供应商责任与赔付','/liabilities':'赔付管理','/risks':'风险事件','/queues':'异常队列','/approvals':'双人审批工作流','/audit':'审计日志',
    '/profile-import-governance':'旅行资料导入治理','/profile-data-release-audit':'旅行资料授权审计','/direct-value-governance':'官方直连价值治理','/consumer-cellular-growth':'消费者增长',
    '/connectors':'供应商连接器','/production-connectors':'生产连接器','/connector-certification':'连接器认证','/connector-live-gate':'上线门禁 / 熔断','/connector-runtime':'连接器运行状态','/connector-reconciliation':'连接器运行证据','/connector-webhook-safety':'回调安全',
    '/first-connector-activation':'首个连接器激活','/connector-credentials-network':'凭证与网络','/connector-certification-drills':'认证与演练','/connector-financial-closure':'支付/退款/结算证据',
    '/paired-connector-pilot':'双连接器试点','/pilot-evidence-reconciliation':'试点证据核验','/pilot-canary-kill-switch':'试点灰度与熔断',
    '/external-sandbox-certification':'外部沙箱认证','/supplier-input-intake':'供应商资料接入','/external-certification-evidence':'外部认证证据',
    '/named-supplier-execution':'指定供应商执行','/named-adapter-bindings':'指定适配器绑定','/external-execution-evidence':'外部执行证据',
    '/commercial-command':'商业运营中心','/commercial-policies':'商业规则','/distribution-authority':'直连优先 / 第三方兜底','/subscriptions':'T20 / 订阅','/hotel-net-guard':'酒店收益保护',
    '/recovery-control':'恢复控制','/recovery-experiments':'恢复实验','/recovery-learning':'恢复学习','/recovery-data-governance':'恢复数据治理','/recovery-learning-incidents':'学习事件控制','/recovery-releases':'恢复发布治理','/recovery-runtime-safety':'运行时发布安全','/recovery-telemetry-governance':'运行遥测治理','/recovery-telemetry-trust':'运行遥测可信','/recovery-identity-lifecycle':'运行身份生命周期','/recovery-identity-reissuance':'运行身份重签发','/recovery-credential-authority':'凭证授权','/recovery-federated-trust':'联邦信任执行','/external-trust':'外部信任与多地域','/trust-gossip':'信任传播与恢复','/trust-plane-dr':'信任平面独立与容灾','/trust-chaos-readiness':'信任混沌与就绪','/continuous-chaos-waivers':'持续混沌与豁免','/waiver-exposure-debt':'豁免暴露与技术债','/exception-debt-burndown':'异常债务清理','/enterprise-risk-portfolio':'企业风险组合','/enterprise-risk-appetite':'企业风险偏好','/enterprise-risk-forecast':'企业风险预测','/risk-forecast-calibration':'预测校准与准确性','/forecast-model-governance':'预测模型主备治理','/forecast-model-statistics':'预测统计晋级','/forecast-drift-governance':'预测漂移与刷新','/forecast-training-governance':'预测训练与可复现','/forecast-artifact-governance':'预测制品供应链','/forecast-serving-governance':'预测服务证明'
  };
  c.nav.forEach(x=>{if(zh[x.route])x.label=zh[x.route]});
  const all=c.nav.slice();
  const byRoute=r=>all.find(x=>x.route===r);
  const take=(r,label)=>{const x=byRoute(r);return x?Object.assign({},x,{label:label||x.label}):null};
  const main=[
    {route:'/operations',label:'运营',custom:'adminOperationsHub'},
    {route:'/exception-center',label:'异常中心',custom:'adminExceptionCenter'},
    {route:'/governance',label:'治理后台',custom:'adminGovernanceHub'}
  ];
  const mainRoutes=new Set(main.map(x=>x.route));
  c.hiddenNav=all.filter(x=>!mainRoutes.has(x.route));
  c.nav=main;
  c.mobileNav=[
    {route:'/operations',label:'运营',icon:'⌂'},
    {route:'/exception-center',label:'异常',icon:'!'},
    {route:'/governance',label:'治理',icon:'◇'}
  ];
})();
