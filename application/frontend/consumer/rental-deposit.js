/* Deposit consent is not a charge. Financial facts remain with C11. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const keys = new Map();
  const requestKey = name => { if (!keys.has(name)) keys.set(name, crypto.randomUUID()); return keys.get(name); };
  const post = (path, body, name) => api(path, {method:'POST', headers:{'Idempotency-Key':requestKey(name)}, body:JSON.stringify(body)});
  // C04's stored naive timestamps are UTC. Never interpret them in browser time.
  const utcDate=value=>{
    const raw=String(value||'');
    const date=new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(raw)?raw:raw+'Z');
    if(!Number.isFinite(date.getTime()))throw Error('押金条款有效期无法核验。');
    return date;
  };
  const caseLabels = {AWAITING_CUSTOMER:'等待你的回应',REVIEW_REQUIRED:'等待独立审核',ADJUDICATED:'裁决已记录',APPEAL_REVIEW_REQUIRED:'申诉审核中'};
  let generation = 0;

  async function load(section, order, token) {
    const loadId=Symbol('deposit-view');section.depositLoadId=loadId;
    const current = () => section.depositLoadId===loadId && token === generation && section.isConnected && state.rentalOrder?.order_id === order.order_id;
    const base = `/v1/mobility/rentals/orders/${encodeURIComponent(order.order_id)}`;
    try {
      const caps = await api('/v1/consumer/checkout-capabilities');
      if (!current()) return;
      if (!caps.simulation_available) { section.remove(); return; }
      const [obligation, cases] = await Promise.all([api(`${base}/deposit-obligation`),api(`${base}/damage-cases`)]);
      if (!current()) return;
      section.innerHTML = '<h2>押金与车损处理</h2><div class="go-sim-note">隔离测试：以下条款和车辆资料仅用于验证流程，不产生真实押金或扣款。</div>';
      if (!obligation) {
        section.insertAdjacentHTML('beforeend','<p>尚未确认押金条款。订单显示的押金金额不代表已经收取。</p>');
        if (['CONFIRMED','IN_PROGRESS'].includes(order.status)) {
          const button = document.createElement('button'); button.className='btn ghost';button.textContent='查看测试押金条款';button.dataset.depositPropose='';section.append(button);
          button.onclick = async () => {
            button.disabled=true;
            try { await post(`${base}/deposit-obligation`, {}, `deposit-propose:${order.order_id}`); await load(section,order,token); }
            catch (_) { if(current()){ button.disabled=false; toast('暂时无法取得押金条款，请刷新后重试。'); } }
          };
        }
      } else {
        const source=obligation.source, terms=source.contract_snapshot;
        const expiry=utcDate(source.expires_at),expiryLabel=expiry.toLocaleString('zh-CN',{timeZoneName:'short'});
        section.insertAdjacentHTML('beforeend',`<div class="kv"><span>最高押金授权金额</span><strong>${esc(money(source.amount_minor,source.currency))}</strong></div><p>车损裁决上限：${esc(money(terms.maximum_damage_award_minor,source.currency))}</p><p>条款有效至 ${esc(expiryLabel)}。</p><p>${obligation.state==='ACTIVATED'?'你已同意本版本条款。该确认不代表押金已授权、已收取或已释放。':'请阅读并明确同意条款后，再进入押金处理。'}</p>`);
        if (obligation.state==='PROPOSED') {
          if(expiry.getTime()<=Date.now()){
            const renew=document.createElement('button');renew.className='btn ghost';renew.textContent='更新并重新核对过期条款';renew.dataset.depositRenew='';section.append(renew);
            renew.onclick=async()=>{renew.disabled=true;try{await post(`${base}/deposit-obligation/${encodeURIComponent(obligation.obligation_id)}/renew`,{expected_revision:obligation.revision,expected_source_hash:obligation.source_hash},`deposit-renew:${order.order_id}:${obligation.revision}:${obligation.source_hash}`);if(current())await load(section,order,token);}catch(_){if(current()){renew.disabled=false;toast('未能更新条款，请刷新并核对最新状态。');}}};
          } else {
          const button=document.createElement('button');button.className='btn primary';button.textContent='核对押金条款';button.dataset.depositAccept='';section.append(button);
          button.onclick=async()=>{
            const content=`<p>本次测试最高授权 ${esc(money(source.amount_minor,source.currency))}；车损裁决上限 ${esc(money(terms.maximum_damage_award_minor,source.currency))}。</p><p>车损费用须另行举证并由独立人员裁决。你可以提出异议；未回应不代表同意车损或扣款。</p><p>条款有效至 ${esc(expiryLabel)}。确认仅表示同意本版本押金义务，不会在此操作中收款。</p><div class="go-sim-note">隔离测试条款，不是真实租车合同。</div><label class="go-consent"><input type="checkbox" data-consent required><span>我已阅读上述金额与处理规则，同意本次测试押金条款。</span></label>`;
            try {
              const result=await GOBooking.dialog('核对测试押金条款',content,'同意本版本条款',async d=>{
                if(!d.querySelector('[data-consent]').checked)throw Error('请先阅读并确认条款。');
                if(!current())throw Error('当前订单已变化，请重新打开订单。');
                try { return await post(`${base}/deposit-obligation/${encodeURIComponent(obligation.obligation_id)}/accept`,{expected_revision:obligation.revision,expected_source_hash:obligation.source_hash,accepted:true},`deposit-accept:${order.order_id}:${obligation.source_hash}:${obligation.revision}`); }
                catch(error){if(error.status===409)throw Error('条款或订单状态已变化，请关闭弹窗并刷新后重新核对。');throw Error('未能确认结果，请勿重复同意其他条款，可重试本次请求。');}
              });
              if(result&&current())await load(section,order,token);
            } catch (_) { if(current())toast('暂时无法确认条款，请刷新后重试。'); }
          };
          }
        }
        if (obligation.state==='ACTIVATED') {
          let funds;
          try { funds=await api(`${base}/deposit-money/${encodeURIComponent(obligation.obligation_id)}?${new URLSearchParams({expected_revision:String(obligation.revision),expected_source_hash:obligation.source_hash})}`); }
          catch (_) { funds={state:'RECONCILIATION_REQUIRED'}; }
          if(!current())return;
          const labels={NOT_AUTHORIZED:'尚未授权',AUTHORIZED:'测试授权已记录',SETTLED:'测试资金处理已完成',RECONCILIATION_REQUIRED:'资金状态待核验'};
          section.insertAdjacentHTML('beforeend',`<h3>押金资金记录</h3><p data-deposit-money-state>${esc(labels[funds.state]||'资金状态待核验')}</p>`);
          if(['AUTHORIZED','SETTLED'].includes(funds.state)&&['authorized_minor','captured_minor','released_minor','remaining_minor'].every(k=>Number.isSafeInteger(funds[k])&&funds[k]>=0)){
            section.insertAdjacentHTML('beforeend',`<p>已授权 ${esc(money(funds.authorized_minor,funds.currency))} · 已扣收 ${esc(money(funds.captured_minor,funds.currency))} · 已释放 ${esc(money(funds.released_minor,funds.currency))} · 待处理授权 ${esc(money(funds.remaining_minor,funds.currency))}</p>`);
          }
        }
      }
      for (const item of cases.items || []) {
        section.insertAdjacentHTML('beforeend',`<article><h3>车损处理记录</h3><p>申报金额 ${esc(money(item.claimed_minor,item.currency))}</p><p>${esc(caseLabels[item.status]||'处理状态待核验')}</p>${item.money_instruction_state==='DISPUTE_HOLD'?'<p>异议未闭合，暂停新的扣款处理。</p>':''}<p>检查资料为提交方提供，真实性仍需审核。裁决记录不等于已经扣款，资金状态请查看押金资金记录。</p></article>`);
      }
      const refresh=document.createElement('button');refresh.className='btn ghost';refresh.textContent='刷新押金与争议状态';refresh.dataset.depositRefresh='';section.append(refresh);
      refresh.onclick=()=>load(section,order,token);
    } catch (_) {
      if(current())section.innerHTML='<h2>押金与车损处理</h2><p role="status">暂时无法核验当前记录。请重新打开订单查询，不要据此判断押金已收取或已释放。</p>';
    }
  }
  const previous=renderMobilityOrder;
  renderMobilityOrder=kind=>{
    const token=++generation;previous(kind);if(kind!=='RENTAL')return;
    const order=state.rentalOrder,section=document.createElement('section');section.className='card';section.dataset.rentalDeposit='';section.innerHTML='<p role="status">正在核对押金与车损记录…</p>';document.querySelector('#app').append(section);void load(section,order,token);
  };
})();
