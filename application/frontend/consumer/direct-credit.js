(() => {
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=(n,c='CNY')=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:c}).format(n/100);
  const date=v=>new Date(v).toLocaleString('zh-CN');
  const labels={ACTIVE:'可使用',ALLOCATED:'已用于预订',FROZEN_REFUND:'退款处理中 · 暂停兑换',REFUNDED:'已退回原扣款',EXPIRED:'已到期'};
  function list(items,slug,selected=''){
    const local=items.filter(c=>c.hotel_slug===slug);
    if(!local.length)return '';
    return `<div class="credit-heading"><div><p class="eyebrow">STAY, ANOTHER DAY</p><h2>我的住宿额度</h2></div><p>仅限原酒店使用，保留原有效期。</p></div><label for="stayCreditChoice">本次预订方式</label><select id="stayCreditChoice"><option value="">普通预订 · 不使用住宿额度</option>${local.filter(c=>c.can_redeem).map(c=>`<option value="${esc(c.credit_id)}" ${selected===c.credit_id?'selected':''}>${money(c.available_minor,c.currency)} · ${esc(date(c.expires_at))} 前入住</option>`).join('')}</select><details><summary>查看额度及原订单</summary>${local.map(c=>`<article class="credit-item"><div><strong>${money(c.available_minor,c.currency)}</strong><span>${esc(c.reconciliation_required?'资金正在核对':labels[c.state]||'待核实')}</span></div><p>${esc(c.hotel_name)} · ${esc(date(c.expires_at))} 前入住</p><a href="/go-app/direct.html?reservation=${encodeURIComponent(c.original_reservation_id)}">查看原订单与处理进度 ↗</a></article>`).join('')}</details><p class="fine">兑换更贵的住宿只补差额；更便宜的住宿不退差额，也不保留剩余额度。选择房间后将单独列明金额，确认后才兑换。</p>`;
  }
  function form(title,content,label,execute,onComplete){
    const d=document.createElement('dialog');d.className='go-dialog';d.setAttribute('aria-labelledby','stayCreditTitle');
    d.innerHTML=`<form><h2 id="stayCreditTitle">${title}</h2>${content}<div class="go-sim-note">隔离测试 · 不发生真实交易</div><label class="go-consent"><input type="checkbox" required data-consent><span>${label}</span></label><p role="alert"></p><footer><button type="button" data-close>暂不处理</button><button class="primary" type="submit">确认金额与规则</button></footer></form>`;
    let busy=false;const close=()=>{if(!busy){d.close();d.remove()}};
    d.querySelector('[data-close]').onclick=close;d.oncancel=e=>{e.preventDefault();close()};
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();if(busy||!d.querySelector('[data-consent]').checked)return;
      busy=true;d.querySelector('[type=submit]').disabled=true;d.querySelector('[data-close]').disabled=true;
      try{const result=await execute(d);busy=false;close();await onComplete(result)}
      catch(error){d.querySelector('[role=alert]').textContent=error.message;busy=false;d.querySelector('[type=submit]').disabled=false;d.querySelector('[data-close]').disabled=false}
    };document.body.append(d);d.showModal();return d;
  }
  async function convert(r,api,onComplete){
    const path='/v1/direct/reservations/'+encodeURIComponent(r.hosted_reservation_id)+'/fare';
    const q=await api(path+'/credit-quote',{});
    return form('这次先留作下次入住',`<p>${esc(r.check_in)} → ${esc(r.check_out)}</p><dl class="fare-breakdown">${[['本次从冻结授权中扣取',q.funding_capture_minor],['此前改期已放弃差额',q.forfeited_change_value_minor||0],['获得原酒店住宿额度',q.retained_value_minor],['转换取消费',q.cancellation_fee_minor],['现金退款',q.cash_refund_minor]].map(([label,n])=>`<div><dt>${label}</dt><dd>${money(n,q.currency)}</dd></div>`).join('')}</dl><p>转换后取消本次入住安排，保留的价值用于原酒店新预订。额度到期不晚于原订单创建后 365 天，转换不会重新起算一年。需要在 ${esc(date(q.credit_expires_at))} 前入住，不可跨酒店、提现或转入钱包。</p><p>兑换低价住宿的差额不退、不保留。新预订取消或部分履约后，未使用额度按锁定规则返还同一份额度，原到期日不延长。现金退款须经独立售后复核；未兑换额度须在原有效期内获准退款，获准时整份关闭。</p><p class="fine">本报价有效至 ${esc(date(q.expires_at))}。</p>`,
      '我已核对扣取金额、原酒店限制和有效期，同意取消这次入住并转换为住宿额度。',
      ()=>api(path+'/convert-credit',{quote_id:q.quote_id,expected_value_minor:q.retained_value_minor,currency:q.currency}),onComplete);
  }
  async function redeem(c,rate,criteria,api,onComplete){
    const path='/v1/consumer/stay-credits/'+encodeURIComponent(c.credit_id);
    const q=await api(path+'/quote',{hosted_offer_id:rate.hosted_offer_id,...criteria});
    const vault=await api('/v1/consumer/profile/vault');
    if(!vault.travelers.length)throw Error('请先在 GO「我的」添加本次入住人的旅行资料。');
    return form('用住宿额度，开启新行程',`<p>${esc(rate.room_name)}<br>${esc(q.check_in)} → ${esc(q.check_out)} · ${q.adults} 位成人 · ${q.children} 位儿童</p><dl class="fare-breakdown">${[['新预订总额',q.new_amount_minor],['住宿额度抵扣',q.applied_credit_minor],['低价差额作废',q.forfeited_difference_minor],['需补授权金额',q.amount_due_minor],['兑换后剩余额度',q.remaining_credit_minor]].map(([label,n])=>`<div><dt>${label}</dt><dd>${money(n,q.currency)}</dd></div>`).join('')}</dl><p>确认后生成独立新订单。额度抵扣部分不重复扣款；补款部分先授权，按新订单的履约或退改规则结算。</p><p>须在 ${esc(date(q.credit_expires_at))} 前入住。低价差额不退现金、不保留为余额；取消返还的未使用额度继续沿用原有效期。</p>${window.GODirectFare.rulesSummary(q.fare_rule,q.currency)}<label for="creditTraveler">实际入住人</label><select id="creditTraveler" required><option value="">请重新选择本次入住人</option>${vault.travelers.map(t=>`<option value="${esc(t.traveler_id)}">${esc(t.full_name)}</option>`).join('')}</select><p class="fine">报价有效至 ${esc(date(q.expires_at))}。</p>`,
      '我已核对抵扣、补款、作废差额和预订规则，并同意为这次酒店预订使用所选入住人的姓名和联系电话。',
      async d=>{const tid=d.querySelector('#creditTraveler').value;if(!tid)throw Error('请选择本次实际入住人。');
        const consent=await api('/v1/consumer/profile/consents',{traveler_id:tid,consent_type:'SENSITIVE_DATA_RELEASE',purpose:'HOTEL_BOOKING',scope:['LEGAL_NAME','MOBILE'],expires_at:new Date(Date.now()+15*60000).toISOString()});
        return api(path+'/redeem',{quote_id:q.quote_id,expected_due_minor:q.amount_due_minor,currency:q.currency,traveler_id:tid,consent_id:consent.consent_id});
      },onComplete);
  }
  window.GODirectCredit={list,convert,redeem};
})();
