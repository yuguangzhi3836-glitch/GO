(() => {
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={UNDER_REVIEW:'正在核实',OPEN_EVIDENCE_COLLECTION:'已受理 · 正在收集信息',DECIDED:'处理方案已确认',CLOSED:'已结案',REFUND_ELIGIBLE_CONTRACT_ONLY:'退款已批准',REFUND_PENDING_SIMULATION:'退款处理中',REFUND_CONFIRMED_SIMULATION:'退款已完成',NO_REFUND_ELIGIBLE:'无需退款',SLA_ESCALATED:'已升级处理',MEDIATION_PROPOSED:'已有调解建议'};
  function disruption(c,currency){
    if(!c)return '';
    const states={EVIDENCE_REQUIRED:'酒店申请取消 · 正在补充信息',INDEPENDENT_REVIEW_REQUIRED:'正在独立核实责任',GUEST_LIABILITY_POLICY_REQUIRED:'正在复核住客责任条款',APPROVED:'处理方案已确认',SUPPLIER_CANCEL_PENDING:'正在向酒店确认取消',UNKNOWN_SUPPLIER_CANCEL:'正在核对酒店取消结果 · 暂未退款',CANCELLED_REFUND_PENDING:'已取消 · 正在退回原款',COMPENSATION_PENDING:'原款处理完成 · 额外赔付待完成',COMPLETED:'退款与赔付处理已完成'};
    const money=n=>new Intl.NumberFormat('zh-CN',{style:'currency',currency}).format(n/100);
    return `<section class="supplier-remedy card" aria-label="酒店取消处理"><h3>酒店取消与赔付</h3><p role="status">${escape(states[c.state]||'正在核实处理进度')}</p>${c.actual_paid_minor!=null&&c.refund_due_minor!=null?`<dl class="fare-breakdown">${[['实际已付计算基数',c.actual_paid_minor],['本次退回原款',c.refund_due_minor],['额外赔付',c.compensation_due_minor]].map(([label,n])=>`<div><dt>${label}</dt><dd>${money(n)}</dd></div>`).join('')}</dl><p>原款：${escape(labels[c.refund_state]||'无需现金退款')} · 额外赔付：${escape(({COMPLETED:'已完成',PENDING:'待完成',NOT_REQUIRED:'不适用'})[c.compensation_state]||'正在核实')}</p>${c.actual_paid_minor===0?'<p>未扣取的授权会释放，不作为现金退款或额外赔付的计算基数。</p>':''}`:'<p>酒店提交申请不会直接改变您的订单；处理方案及金额以审核通过的规则为准。</p>'}${c.retry_allowed?'<button class="primary btn" id="retrySupplierRemedy">继续已确认的退款与赔付</button>':''}<p class="fine">隔离测试记录 · 不发生真实交易。赔付进度与原款退款分别记录。</p></section>`;
  }
  function render(data,currency='CNY'){
    if(!data)return '';
    const money=n=>new Intl.NumberFormat('zh-CN',{style:'currency',currency}).format(n/100),f=data.funds;
    return `${disruption(data.disruption,currency)}${f?`<section class="funds-detail" aria-label="入住资金明细"><h3>资金明细</h3><p class="fine">隔离测试记录 · 未发生真实资金交易</p>${f.reconciliation_required?'<p role="alert">资金状态正在核对，请等待结果后再操作。</p>':''}<dl>${[['held_minor','仍在授权中'],['capture_minor','已扣款（房费或规则费用）'],['release_minor','已释放授权'],['refund_minor','已退回原扣款（现金部分）'],['prepaid_credit_minor','本单使用住宿额度'],['credit_refund_minor','住宿额度原扣款退款']].map(([key,label])=>`<div><dt>${label}</dt><dd>${money(f[key]||0)}</dd></div>`).join('')}</dl><p class="fine">释放授权不会产生退款；退款从已发生的扣款中退回。</p></section>`:''}${data.can_open_case?'<button class="text-button" id="openStayCase">入住有问题？申请售后</button>':''}${(data.cases||[]).map(c=>`<section class="stay-case"><h3>售后进度</h3><p>${escape(labels[c.state]||'正在处理')}</p>${c.approved_refund_minor!=null?`<p>已批准退款 ${money(c.approved_refund_minor)}</p>`:''}<p role="status">${escape(labels[c.refund_state]||'正在核实')}</p>${c.retry_allowed?`<button class="primary" data-refund-retry="${escape(c.refund_eligibility_id)}">继续已批准的退款</button>`:''}</section>`).join('')}`;
  }
  function tripLink(item){
    const id=String(item.order_id||'');
    const target='/go-app/direct.html?reservation='+encodeURIComponent(id);
    return item.vertical==='HOTEL'&&/^[a-zA-Z0-9_-]{1,100}$/.test(id)&&item.facts_json?.detail_url===target?target:null;
  }
  window.GODirectAfterSales={render,tripLink,disruption};
})();
