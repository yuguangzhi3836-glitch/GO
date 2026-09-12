(() => {
  'use strict';
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const amount=(n,c='CNY')=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:c}).format(n/100);
  function rulesSummary(fare,currency='CNY'){
    if(!fare?.rules)return '';
    const r=fare.rules;
    return `<details class="fare-rules"><summary>查看退改与未到店规则</summary><p>${escape(r.fare_family)} · 酒店时间 ${escape(r.timezone)}</p><p>入住日 ${escape(r.check_in_hour)}:00 起算；下单后 ${escape(r.cooling_off_minutes)} 分钟内且未到入住时间，可适用冷静期。</p><ul>${(r.cancellation_tiers||[]).map(t=>`<li>距入住至少 ${escape(t.min_hours)} 小时取消：收取订单金额的 ${escape(t.fee_basis_points/100)}%。</li>`).join('')}</ul><p>超过入住时间 ${escape(r.no_show_grace_hours)} 小时未到店，经复核可按规则收取 ${escape(r.no_show_fee_basis_points/100)}%。</p><p>${r.change_allowed?`改期免手续费；原订单创建日起 365 天内入住，连续改期不顺延。涨价补差额，降价不退差额。`:'此价格规则不允许改期。'}${r.stay_credit_enabled?`规则允许转为原酒店住宿额度，有效期最长 ${escape(r.stay_credit_days)} 天，不可提现或转入余额。`:'此价格规则不提供住宿额度。'}</p><p class="fine">是否可执行以订单下方可用选项为准。取消费用和授权释放金额会在您确认前单独列出。</p></details>`;
  }
  function options(fare,currency='CNY'){
    if(!fare?.configured)return '';
    const labels={CANCEL_FOR_REFUND:'核对取消费用',CHANGE_DATE:'改期',EXTEND_STAY:'续住',CONVERT_TO_CREDIT:'转为住宿额度',KEEP_BOOKING:'保留预订'};
    return `<section class="fare-options" aria-label="预订退改选项"><h3>按预订规则处理</h3>${rulesSummary(fare,currency)}<div>${(fare.options||[]).map(o=>o.action==='CANCEL_FOR_REFUND'&&o.available?'<button class="text-button" id="quoteFareCancellation">核对取消费用</button>':(o.action==='CONVERT_TO_CREDIT'&&o.available?'<button class="text-button" id="convertStayCredit">转为住宿额度并核对规则</button>':(['CHANGE_DATE','EXTEND_STAY'].includes(o.action)&&o.available?`<button class="text-button" id="quoteFareChange" data-action="${escape(o.action)}">${escape(labels[o.action])}并核对费用</button>`:`<span class="fare-option ${o.available?'':'unavailable'}">${escape(labels[o.action]||'其他选项')}${o.available?'':' · 暂不可用'}</span>`))).join('')}</div></section>`;
  }
  async function cancel(r,api,onComplete){
    const path='/v1/direct/reservations/'+encodeURIComponent(r.hosted_reservation_id)+'/fare';
    const q=await api(path+'/cancellation-quote',{});
    const d=document.createElement('dialog');d.className='go-dialog';d.setAttribute('aria-labelledby','fareCancelTitle');
    d.innerHTML=`<form><h2 id="fareCancelTitle">取消前，再核对一次</h2><p>${escape(r.check_in)} → ${escape(r.check_out)}</p><dl class="fare-breakdown"><div><dt>取消费</dt><dd>${amount(q.fee_minor,q.currency)}</dd></div><div><dt>释放冻结额度</dt><dd>${amount(q.authorization_release_minor,q.currency)}</dd></div><div><dt>现金退款</dt><dd>${amount(q.cash_refund_minor,q.currency)}</dd></div></dl>${q.prepaid_fee_minor||q.restored_credit_minor||q.expired_credit_minor?`<dl class="fare-breakdown">${[['住宿额度支付取消费',q.prepaid_fee_minor],['现金授权支付取消费',q.cash_fee_minor],['返还原住宿额度',q.restored_credit_minor],['已到期未使用额度',q.expired_credit_minor]].map(([label,n])=>`<div><dt>${label}</dt><dd>${amount(n||0,q.currency)}</dd></div>`).join('')}</dl><p>额度返还不产生现金退款，继续沿用原到期日；兑换时作废的低价差额不返还。</p>`:'<p>当前订单尚未支付房费。取消费从已冻结授权中扣取，其余授权释放，不会产生重复退款。</p>'}<p>报价有效至 ${escape(new Date(q.expires_at).toLocaleString('zh-CN'))}。超时或订单变化后需要重新核对。</p><div class="go-sim-note">隔离测试 · 不发生真实扣款</div><label class="go-consent"><input type="checkbox" required data-consent><span>我已核对取消费与释放金额，确认取消这次预订。</span></label><p role="alert"></p><footer><button type="button" data-close>保留预订</button><button class="primary" type="submit">确认取消并结清费用</button></footer></form>`;
    let busy=false;const close=()=>{if(!busy){d.close();d.remove()}};
    d.querySelector('[data-close]').onclick=close;d.oncancel=e=>{e.preventDefault();close()};
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();if(busy||!d.querySelector('[data-consent]').checked)return;
      busy=true;d.querySelector('[type=submit]').disabled=true;d.querySelector('[data-close]').disabled=true;
      try{await api(path+'/cancel',{quote_id:q.quote_id,expected_fee_minor:q.fee_minor,currency:q.currency});busy=false;close();await onComplete()}
      catch(error){d.querySelector('[role=alert]').textContent=error.message;busy=false;d.querySelector('[type=submit]').disabled=false;d.querySelector('[data-close]').disabled=false}
    };document.body.append(d);d.showModal();
  }
  async function change(r,action,api,onComplete){
    const path='/v1/direct/reservations/'+encodeURIComponent(r.hosted_reservation_id)+'/fare';
    const extension=action==='EXTEND_STAY',d=document.createElement('dialog');d.className='go-dialog';d.setAttribute('aria-labelledby','fareChangeTitle');
    d.innerHTML=`<form><h2 id="fareChangeTitle">${extension?'继续住一晚，或更久':'调整入住日期'}</h2><label>入住<input type="date" name="check_in" required value="${escape(r.check_in)}" ${extension?'readonly':''}></label><label>退房<input type="date" name="check_out" required value="${escape(r.check_out)}"></label><p>先查看新日期的逐夜库存与总价，再决定是否改动。当前预订会保留到您最终确认。</p><div data-quote></div><label class="go-consent" data-consent-label hidden><input type="checkbox" data-consent><span>我已核对日期、补付费用与新授权总额，同意按上述报价调整预订。</span></label><p role="alert"></p><footer><button type="button" data-close>保留原预订</button><button class="primary" type="submit">查询变更报价</button></footer></form>`;
    let busy=false,q=null;const close=()=>{if(!busy){d.close();d.remove()}},reset=()=>{q=null;d.querySelector('[data-quote]').innerHTML='';d.querySelector('[data-consent-label]').hidden=true;d.querySelector('[data-consent]').checked=false;d.querySelector('[type=submit]').textContent='查询变更报价'};
    for(const name of ['check_in','check_out'])d.querySelector('[name='+name+']').onchange=reset;
    d.querySelector('[data-close]').onclick=close;d.oncancel=e=>{e.preventDefault();close()};
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();if(busy||q&&!d.querySelector('[data-consent]').checked)return;
      busy=true;d.querySelector('[type=submit]').disabled=true;d.querySelector('[data-close]').disabled=true;
      for(const name of ['check_in','check_out'])d.querySelector('[name='+name+']').disabled=true;
      try{
        if(!q){
          q=await api(path+'/change-quote',{action,check_in:d.querySelector('[name=check_in]').value,check_out:d.querySelector('[name=check_out]').value});
          d.querySelector('[data-quote]').innerHTML=`<h3>这次调整需要补付 ${amount(q.additional_amount_minor,q.currency)}</h3><dl class="fare-breakdown">${[['房价差额',q.fare_difference_minor],['调整后订单总额',q.new_amount_minor]].map(([label,n])=>`<div><dt>${label}</dt><dd>${amount(n,q.currency)}</dd></div>`).join('')}</dl><p>改期免手续费，降价不退差额。最晚入住期限：${escape(new Date(q.change_valid_until).toLocaleString('zh-CN'))}，连续改期不顺延。</p>${q.authorization_replacement_minor?`<p>确认后先释放原冻结授权 ${amount(q.old_authorization_release_minor,q.currency)}，再按所需现金金额 ${amount(q.authorization_replacement_minor,q.currency)} 重新授权。不会重复冻结两份额度。</p>`:'<p>总额不变，继续使用原有授权。</p>'}<details><summary>逐晚报价</summary>${q.nights.map(n=>`<p>${escape(n.stay_date)} · ${amount(n.price_minor,q.currency)}</p>`).join('')}</details><p class="fine">隔离测试 · 不产生真实交易。报价有效至 ${escape(new Date(q.expires_at).toLocaleString('zh-CN'))}。</p>`;
          d.querySelector('[data-consent-label]').hidden=false;d.querySelector('[data-consent]').checked=false;d.querySelector('[type=submit]').textContent='确认日期与费用';
        }else{
          await api(path+'/change',{quote_id:q.quote_id,expected_total_minor:q.new_amount_minor,expected_additional_minor:q.additional_amount_minor,currency:q.currency});busy=false;close();await onComplete();
        }
      }catch(error){d.querySelector('[role=alert]').textContent=error.message}
      finally{busy=false;d.querySelector('[type=submit]').disabled=false;d.querySelector('[data-close]').disabled=false;for(const name of ['check_in','check_out'])d.querySelector('[name='+name+']').disabled=false}
    };document.body.append(d);d.showModal();
  }
  window.GODirectFare={rulesSummary,options,cancel,change};
})();
