(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const unwrap = value => value && Object.prototype.hasOwnProperty.call(value, 'data') ? value.data : value;
  const labels = {NOT_AUTHORIZED:'尚未授权', AUTHORIZED:'授权余额已核验', SETTLED:'本次授权已结清', RECONCILIATION_REQUIRED:'资金状态待核对'};
  const reasons = {DEPOSIT_OBLIGATION_NOT_FOUND:'尚无押金条款，请先由客人查看并接受。',
    DEPOSIT_CONSUMER_ACCEPTANCE_REQUIRED:'客人尚未接受当前押金条款。', DEPOSIT_SOURCE_EXPIRED:'条款已过期：不能新授权或扣款；符合条件的既有余额仍可释放。',
    DEPOSIT_DECISION_HELD:'争议尚未形成可执行决定，或正在申诉复核。', DEPOSIT_CASE_UNBOUND:'案件没有绑定已接受的押金条款。',
    SETTLED_MONEY_REQUIRES_SEPARATE_COMPENSATION_REVIEW:'资金已经结清；新申诉需要单独补偿审核，不能再次执行原结算。'};
  const cash = (n, currency) => Number.isSafeInteger(n) && n >= 0
    ? new Intl.NumberFormat('zh-CN', {style:'currency',currency:currency || 'CNY'}).format(n/100) : '尚未核验';
  function actions(snapshot) {
    if (!snapshot?.source || !snapshot.money || snapshot.money.state === 'RECONCILIATION_REQUIRED') return [];
    const s=snapshot.source, base='/internal/v1/mobility/rentals/orders/'+encodeURIComponent(snapshot.order_id)+'/deposit-money/'+encodeURIComponent(s.obligation_id);
    const body={expected_revision:s.revision,expected_source_hash:s.source_hash};
    const items=[];
    if(snapshot.can_authorize) items.push({id:'authorize',title:'授权押金',url:base+'/authorize',body,
      summary:'将按客人已接受的条款授权 '+cash(s.amount_minor,s.currency)+'。这不是车损扣款。'});
    for(const item of snapshot.decisions || []) if(item.can_settle && item.decision){
      const d=item.decision;
      items.push({id:'settle:'+d.case_id,title:'执行已裁决结算',url:base+'/settle',body:{...body,case_id:d.case_id,
        expected_case_version:d.case_version,expected_decision_hash:d.decision_hash},
        summary:'按第 '+d.case_version+' 版裁决扣款 '+cash(d.awarded_minor,s.currency)+'，释放其余授权余额。案件：'+d.case_id});
    }
    for(const item of snapshot.decisions || []) if(item.can_compensate && item.compensation){
      const plan=item.compensation;
      items.push({id:'compensate:'+plan.case_id,title:'执行申诉减收补偿',url:base+'/compensate',body:{...body,
        case_id:plan.case_id,expected_case_version:plan.case_version,expected_decision_hash:plan.decision_hash},
        summary:'按最新独立复核退回 '+cash(plan.amount_minor,s.currency)+'，补偿后净收 '+cash(plan.target_net_captured_minor,s.currency)+'。原扣款及释放记录保留，不重新授权。'});
    }
    if(snapshot.release?.can_release){
      const f=snapshot.release.fact;
      items.push({id:'release',title:'释放已核验余额',url:base+'/release',body:{...body,
        expected_release_revision:f.release_revision,expected_release_hash:f.release_hash},
        summary:'依据已确认的'+(f.reason==='CANCELLED_REFUNDED'?'取消退款':'无损归还')+'记录，释放 '+cash(snapshot.money.remaining_minor,s.currency)+'。不扣款。'});
    }
    return items;
  }
  function sameAction(left,right){return !!left && !!right && left.url===right.url && JSON.stringify(left.body)===JSON.stringify(right.body);}
  async function render({container,orderId,request}) {
    if(!container || !orderId || typeof request!=='function') throw Error('租车资金工作区参数不完整');
    const generation=(container.__rentalFinanceGeneration || 0)+1;container.__rentalFinanceGeneration=generation;
    let snapshot=null,pending=null,busy=false,readSequence=0,message='',readFailed=false;
    const live=()=>container.__rentalFinanceGeneration===generation && container.isConnected!==false;
    const readUrl='/internal/v1/admin/mobility/rentals/orders/'+encodeURIComponent(orderId)+'/deposit-money-review';
    function draw(){
      if(!live())return;
      const s=snapshot?.source,m=snapshot?.money,available=readFailed?[]:actions(snapshot),currency=s?.currency || m?.currency || 'CNY';
      const unknown=m?.state==='RECONCILIATION_REQUIRED';
      const retry=pending && !readFailed && available.find(action=>sameAction(action,pending));
      container.innerHTML=`<section class="card rental-deposit-finance"><h3>押金资金核对</h3><p>隔离演练 · 不接真实支付渠道。条款接受、争议裁决和资金事实分别核验。</p>
        <p role="status" aria-live="polite">${esc(message)}</p>
        <button class="btn" data-refresh ${busy?'disabled':''}>读取最新资金与决定</button>
        ${s?`<p>已接受条款版本：${esc(s.revision)} · ${s.state==='ACTIVATED'?'客人已确认':'等待客人确认'}<br>约定押金：${esc(cash(s.amount_minor,currency))} · 到期 ${esc(s.expires_at)}</p>`:''}
        ${m?`<h4>${esc(readFailed?'旧快照：当前资金尚未核验':(labels[m.state] || '资金状态待核对'))}</h4><div class="business-facts-grid">${[['原授权',m.authorized_minor],['已扣款',m.captured_minor],['已释放',m.released_minor],['已补偿',m.compensated_minor],['净收',m.net_captured_minor],['授权剩余',m.remaining_minor]].map(([name,value])=>`<p>${name}<br><b>${esc(cash(value,currency))}</b></p>`).join('')}</div>`:''}
        ${unknown?'<p role="alert">存在未知或不一致的资金证据。当前仅可核对，不提供授权、扣款或释放操作，也不会把缺记录解释为未执行。</p>':''}
        ${(snapshot?.blockers || []).map(code=>`<p>${esc(reasons[code] || '来源或资金证据需要核对，暂不执行。')}</p>`).join('')}
        ${(snapshot?.decisions || []).map(item=>`<p>案件 ${esc(item.case_id)} · 第 ${esc(item.case_version)} 版${item.blocker?'<br>'+esc(reasons[item.blocker] || '该案件当前不能执行结算。'):''}</p>`).join('')}
        ${pending?`<aside><p>上次提交结果尚未确认。先读取权威记录；仅在最新快照仍允许相同请求时，可确认重试原请求。</p>
          <form data-retry><p>${esc(pending.summary)}</p><label><input type="checkbox" data-confirm ${!retry || busy?'disabled':''}>已核对最新快照，确认重试原请求</label><button class="btn" ${!retry || busy?'disabled':''}>重试原请求</button></form>
          ${!readFailed && !unknown?'<button class="btn" data-reset>放弃待确认请求，按最新快照重新审核</button>':''}</aside>`:''}
        ${!pending?available.map((action,index)=>`<form data-action="${index}"><h4>${esc(action.title)}</h4><p>${esc(action.summary)}</p><label><input type="checkbox" data-confirm ${busy?'disabled':''}>已核对条款、金额及当前决定，确认执行本次隔离操作</label><button class="btn primary" ${busy?'disabled':''}>${esc(action.title)}</button></form>`).join(''):''}
        <details><summary>版本与核对记录</summary><pre>${esc(JSON.stringify({source:s,blockers:snapshot?.blockers || [],movements:snapshot?.movements || []},null,2))}</pre><p>流水记录用于核对；单条记录不代表整笔资金已经确认。</p></details></section>`;
      container.querySelector('[data-refresh]').onclick=()=>load();
      container.querySelectorAll('[data-action]').forEach(form=>{const action=available[Number(form.dataset.action)];form.onsubmit=event=>{event.preventDefault();if(!form.querySelector('[data-confirm]').checked || busy)return;return send(action);};});
      const retryForm=container.querySelector('[data-retry]');if(retryForm)retryForm.onsubmit=event=>{event.preventDefault();if(!retry || !retryForm.querySelector('[data-confirm]').checked || busy)return;return send(pending);};
      const reset=container.querySelector('[data-reset]');if(reset)reset.onclick=()=>{if(busy)return;pending=null;message='请按最新快照重新核对并确认。';draw();};
    }
    async function load(){
      if(busy)return;
      const sequence=++readSequence;busy=true;draw();
      try{
        const result=unwrap(await request(readUrl));if(!live() || sequence!==readSequence)return;
        if(!result || result.order_id!==orderId || result.read_only!==true)throw Error('返回的资金工作区不匹配当前订单');
        snapshot=result;readFailed=false;
        if(pending && (pending.id==='authorize' && ['AUTHORIZED','SETTLED'].includes(result.money?.state)
            || !pending.id.startsWith('compensate:') && pending.id!=='authorize' && result.money?.state==='SETTLED'
            || pending.id.startsWith('compensate:') && result.decisions?.some(item=>item.compensation?.already_applied && item.compensation.decision_hash===pending.body.expected_decision_hash)))pending=null;
        message='已读取服务端资金事实；操作仍需明确确认。';
      }catch(error){if(live()){readFailed=true;message='读取失败，暂停操作：'+String(error.message || error);}}
      finally{busy=false;draw();}
    }
    async function send(action){
      if(busy || readFailed || !action || !live())return;
      pending=JSON.parse(JSON.stringify(action));busy=true;draw();
      try{
        const response=unwrap(await request(action.url,{method:'POST',body:action.body}));
        // Even a returned success is followed by a fresh authoritative review.
        if(response?.state==='RECONCILIATION_REQUIRED')message='资金结果仍待核对。';
      }catch(error){message='提交结果尚未确认：'+String(error.message || error);}
      finally{busy=false;draw();}
      await load();
      if(live() && typeof window.dispatchEvent==='function')window.dispatchEvent(new CustomEvent('go:rental-money-changed',{detail:{orderId}}));
    }
    const changed=event=>{if(event.detail?.orderId===orderId && live())load();};
    window.addEventListener?.('go:rental-operation-changed',changed);
    await load();
    return ()=>{if(live())container.__rentalFinanceGeneration++;window.removeEventListener?.('go:rental-operation-changed',changed);};
  }
  window.GORentalDepositOperations={render};
})();
