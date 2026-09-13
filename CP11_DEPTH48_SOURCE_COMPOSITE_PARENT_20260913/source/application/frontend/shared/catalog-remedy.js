(() => {
  'use strict';
  const states={EVIDENCE_REQUIRED:'待补充证据',INDEPENDENT_REVIEW_REQUIRED:'待独立审核',GUEST_LIABILITY_POLICY_REQUIRED:'待住客条款复核',APPROVED:'方案已批准',SUPPLIER_CANCEL_PENDING:'酒店取消处理中',UNKNOWN_SUPPLIER_CANCEL:'取消结果待核对',CANCELLED_REFUND_PENDING:'原款退款待完成',COMPENSATION_PENDING:'额外赔付待完成',COMPLETED:'处理完成',HISTORICAL_REVIEW_REQUIRED:'历史记录需重新核对'};
  const causes={OVERBOOKING:'超售',NO_ROOM:'无房交付',HOTEL_OPERATIONAL_ERROR:'酒店运营错误',HOTEL_SYSTEM_ERROR:'酒店系统错误',PROPERTY_SELF_CLOSURE:'酒店自行停业',ROOM_UNAVAILABLE:'无法提供确认房型',UNJUSTIFIED_CANCELLATION:'擅自取消',GOVERNMENT_ORDER:'政府管制',NATURAL_DISASTER:'自然灾害',PUBLIC_SAFETY_EVENT:'重大公共安全',FORCE_MAJEURE:'其他不可抗力',GUEST_FRAUD:'住客欺诈',GUEST_INELIGIBLE:'住客资格问题'};
  const options=()=>'<option value="">请选择已核实的原因</option>'+Object.entries(causes).map(([v,t])=>`<option value="${v}">${t}</option>`).join('');
  const fields=()=>'<label>证据类别<select name="evidence_type"><option value="HOTEL_RECORD">酒店记录</option><option value="GUEST_RECORD">住客记录</option><option value="OFFICIAL_NOTICE">官方通知</option><option value="COMMUNICATION">沟通记录</option></select></label><label>归档证据引用<input name="reference" required maxlength="512"></label><label>证据文件 SHA256<input name="sha256" required pattern="[a-f0-9]{64}" minlength="64" maxlength="64"></label>';
  const proof=f=>({reference:f.elements.reference.value.trim(),sha256:f.elements.sha256.value.trim(),type:f.elements.evidence_type.value});
  function tools(ctx){return {get:async p=>ctx.unwrap(await ctx.request(p)),send:async(p,b,key)=>ctx.unwrap(await ctx.request(p,{method:'POST',body:b,...(key?{headers:{'Idempotency-Key':key}}:{})})),run:async(button,fn)=>{if(button.disabled)return;button.disabled=true;try{await fn()}catch(e){ctx.notice(e.message,true)}finally{button.disabled=false}}}}
  async function render(ctx){
    const {container,esc}=ctx,{get,send,run}=tools(ctx);let cases=[],next=null;
    async function load(){const d=await get('/internal/v1/supplier-fault/cases');cases=d.items;next=d.next_offset;paint()}
    function paint(){
      container.innerHTML=`<section class="card"><h2>平台酒店取消与赔付</h2><p>供应商提交的是申请。先独立核验证据，再确认取消、原款退款和额外赔付。当前为隔离执行。</p></section><section class="card"><h3>责任事件</h3>${cases.map(c=>`<article class="hosted-fault-row"><div><b>${esc(c.check_in||'入住日期待核对')} 至 ${esc(c.check_out||'离店日期待核对')}</b><p>订单 ${esc(c.order_id)} · 供应商 ${esc(c.supplier_id)}</p><p>${esc(states[c.state]||'历史记录需核对')}</p></div><button class="btn" data-case="${esc(c.case_id)}">查看处理</button></article>`).join('')||'<p>暂无酒店取消申请。</p>'}${next!=null?'<button class="btn" id="crMore">加载更多</button>':''}</section><section id="crDetail"></section>`;
      container.querySelectorAll('[data-case]').forEach(b=>b.onclick=()=>run(b,()=>detail(b.dataset.case)));
      const more=container.querySelector('#crMore');if(more)more.onclick=()=>run(more,async()=>{const d=await get('/internal/v1/supplier-fault/cases?offset='+next);cases.push(...d.items);next=d.next_offset;paint()});
    }
    async function detail(id){
      const base='/internal/v1/supplier-fault-cases/'+encodeURIComponent(id),c=await get(base),node=container.querySelector('#crDetail');
      if(!c.evidence_hash){node.innerHTML='<section class="card"><h3>历史记录需核对</h3><p>此记录没有新的独立审批和资金计划，不能直接重新执行退款或赔付。</p></section>';return}
      const cash=n=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:c.currency||'CNY'}).format(n/100),collect=['EVIDENCE_REQUIRED','INDEPENDENT_REVIEW_REQUIRED','GUEST_LIABILITY_POLICY_REQUIRED'].includes(c.state);
      node.innerHTML=`<section class="card"><h3>${esc(states[c.state]||'处理详情')}</h3><p>订单 ${esc(c.order_id)}</p><p>供应商说明：${esc(causes[c.claimed_cause]||c.claimed_cause)}；独立结论：${esc(causes[c.confirmed_cause]||'待审核')}</p>${c.financial_decision_approved?`<div class="business-facts-grid"><p>实际已付<br><b>${cash(c.actual_paid_minor)}</b></p><p>本次原款退款<br><b>${cash(c.refund_due_minor)}</b></p><p>额外赔付<br><b>${cash(c.compensation_due_minor)}</b></p></div>`:''}<h4>归档证据</h4>${c.evidence.map(x=>`<p>${esc(x.reference)}<br><small>${esc(x.sha256)}</small></p>`).join('')||'<p>尚未提供完整证据。</p>'}${collect?`<form id="crEvidence"><h4>补充可核验证据</h4>${fields()}<button class="btn" type="submit">保存证据</button></form>`:''}${c.state==='INDEPENDENT_REVIEW_REQUIRED'?`<form id="crReview"><h4>独立责任审核</h4><label>独立确认原因<select name="confirmed_cause" required>${options()}</select></label><fieldset><legend>已核验的证据</legend>${c.evidence.map(x=>`<label><input type="checkbox" data-evidence value="${esc(x.evidence_id)}">${esc(x.reference)}</label>`).join('')}</fieldset><label>审核记录<input name="decision_reference" required maxlength="512"></label><label><input name="confirmed" type="checkbox" required>我已独立核实责任和所选证据。</label><button class="btn primary" type="submit">批准责任与计算规则</button></form>`:''}${c.retry_allowed?'<form id="crExecute"><label><input name="confirmed" type="checkbox" required>已核对当前批准方案与金额。</label><button class="btn primary" type="submit">执行或继续批准方案</button></form>':''}${['UNKNOWN_SUPPLIER_CANCEL','SUPPLIER_CANCEL_PENDING'].includes(c.state)?'<p>先查询酒店取消结果，确认前不退款，不重复发送取消。</p><button class="btn" id="crReconcile">查询并核对酒店结果</button>':''}<button class="btn" id="crFinance">查看专项授权与追偿</button><div id="crFinanceView"></div></section>`;
      const proofForm=node.querySelector('#crEvidence');if(proofForm)proofForm.onsubmit=e=>{e.preventDefault();return run(proofForm.querySelector('button'),async()=>{await send(base+'/evidence',proof(proofForm));await detail(id)})};
      const review=node.querySelector('#crReview');if(review)review.onsubmit=e=>{e.preventDefault();return run(review.querySelector('button'),async()=>{await send(base+'/review',window.GOHostedDisruption.reviewBody(c,review));await load();await detail(id)})};
      const execute=node.querySelector('#crExecute');if(execute)execute.onsubmit=e=>{e.preventDefault();if(!execute.elements.confirmed.checked)return;return run(execute.querySelector('button'),async()=>{await send(base+'/execute',{expected_decision_hash:c.decision_hash});await load();await detail(id)})};
      const reconcile=node.querySelector('#crReconcile');if(reconcile)reconcile.onclick=()=>run(reconcile,async()=>{await send(base+'/reconcile');await load();await detail(id)});
      const finance=node.querySelector('#crFinance');finance.onclick=()=>run(finance,()=>window.GOHostedFaultFinance.render({...ctx,catalog:true},node.querySelector('#crFinanceView'),c.supplier_id));
      node.scrollIntoView({block:'nearest'});
    }
    try{await load()}catch(e){container.innerHTML='<section class="card"><p>暂时无法加载责任事件，请稍后重试。</p></section>';ctx.notice(e.message,true)}
  }
  async function supplierRequest(ctx,order){
    const {container,esc}=ctx,{get,send,run}=tools(ctx),base='/v1/supplier/orders/'+encodeURIComponent(order.order_id),key=crypto.randomUUID();
    async function load(){
      const c=await get(base+'/supplier-cancellation'),collect=c&&['EVIDENCE_REQUIRED','INDEPENDENT_REVIEW_REQUIRED','GUEST_LIABILITY_POLICY_REQUIRED'].includes(c.state);
      container.innerHTML=`<button class="btn" id="crBack">← 返回订单列表</button><section class="card"><h2>无法履约申请</h2><p>订单 ${esc(order.order_id)}</p><p>提交申请后由平台独立核实责任；不会仅凭酒店说明直接取消或判定赔付。</p>${c?`<p role="status">${esc(states[c.state]||'正在处理')}</p><button class="btn" id="crRefresh">刷新进度</button>`:`<form id="crRequest"><label>酒店说明的原因<select name="claimed_cause" required>${options()}<option value="OTHER">其他原因</option></select></label><label>已有证据引用<input name="references" maxlength="512" placeholder="可先填写已有引用，提交后补充文件指纹"></label><button class="btn primary" type="submit">提交核实申请</button></form>`}${collect?`<form id="crProof"><h3>补充证据</h3>${fields()}<button class="btn" type="submit">提交证据供独立核验</button></form>`:''}</section>`;
      container.querySelector('#crBack').onclick=()=>ctx.onBack?.();
      const refresh=container.querySelector('#crRefresh');if(refresh)refresh.onclick=()=>run(refresh,load);
      const form=container.querySelector('#crRequest');if(form)form.onsubmit=e=>{e.preventDefault();return run(form.querySelector('button'),async()=>{const reference=form.elements.references.value.trim();await send(base+'/unable-to-fulfill',{reason_code:form.elements.claimed_cause.value,evidence_ids:reference?[reference]:[]},key);await load()})};
      const f=container.querySelector('#crProof');if(f)f.onsubmit=e=>{e.preventDefault();return run(f.querySelector('button'),async()=>{await send(base+'/supplier-cancellation/evidence',proof(f));await load()})};
    }
    try{await load()}catch(e){container.innerHTML='<section class="card"><p>暂时无法加载酒店处理进度，请重试。</p></section>';ctx.notice(e.message,true)}
  }
  window.GOCatalogRemedy={render,supplierRequest};
})();
