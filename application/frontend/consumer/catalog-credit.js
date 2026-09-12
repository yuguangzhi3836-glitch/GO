/* Catalog credit: immutable quoted terms, explicit guests, and resumable progress. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={ACTIVE:'可使用',REDEEMED:'已兑换',EXPIRED:'已到期',CANCEL_PENDING:'正在确认取消',UNKNOWN_CANCEL:'正在核对取消结果',
    REDEMPTION_PENDING:'兑换处理中',PREBOOK_PENDING:'正在确认房价与库存',UNKNOWN_PREBOOK:'正在核对房价与库存',
    PAYMENT_PENDING:'正在准备补款',BOOK_PENDING:'正在确认预订',UNKNOWN_BOOK:'正在核对预订结果',CAPTURE_PENDING:'预订已确认，补款待完成',
    FAILED:'本次兑换未完成',CANCEL_REFUND_PENDING:'取消已确认，退款处理中',CANCELLED:'取消及退款已处理',REFUND_RESERVED:'酒店取消，原款退款处理中',REFUNDED:'酒店取消，原款退款已处理'};
  const requests=new Map();
  const key=name=>{if(!requests.has(name))requests.set(name,crypto.randomUUID());return requests.get(name)};
  const friendly=message=>/FORFEITED_CHANGE_VALUE_CREDIT_ALLOCATION_REQUIRED/.test(message)?'低价改期的差额已作废，剩余可保留价值需要完成逐笔核对后才能转换；不会把已作废差额重新计入额度。':/QUOTE.*EXPIRED/.test(message)?'报价已过期，请重新查看报价。':/STALE|QUOTE.*CHANGED/.test(message)?'金额或额度已变化，请重新查看报价。':/TRAVELER|CONSENT|GUEST_NAME/.test(message)?'请重新核对出行人资料与本次使用授权。':/DATES|INVENTORY/.test(message)?'所选日期暂不可订，请调整日期后重试。':/CREDIT_EXPIRED/.test(message)?'住宿额度已到期。':/NOT_ACTIVE|FUNDS_RESERVED/.test(message)?'该额度正在其他流程中处理，请先查看当前进度。':/^[A-Z0-9_:]+$/.test(message)?'本次处理尚未完成，请刷新当前进度后再试。':message;
  const post=async(ctx,path,body={},identity=path)=>{try{return await ctx.api(path,{method:'POST',headers:{'Idempotency-Key':key(identity)},body:JSON.stringify(body)})}catch(e){throw Error(friendly(e.message))}};
  const date=value=>new Date(value).toLocaleString('zh-CN');
  const consent='<label class="go-consent"><input type="checkbox" data-credit-consent required><span>我已核对金额、有效期与本次操作规则，确认继续。</span></label>';
  const simulation='<p class="go-sim-note">当前为隔离验收，不会扣真实款项或生成可实际入住的预订。</p>';
  function confirmed(dialog){if(!dialog.querySelector('[data-credit-consent]').checked)throw Error('请先确认本次金额与规则');return true}
  function rows(ctx,items){return items.map(([title,amount,currency])=>`<div class="kv"><span>${esc(title)}</span><b>${esc(ctx.money(amount,currency))}</b></div>`).join('')}
  function originalForfeiture(ctx,proof,currency){
    if(!proof||!Object.keys(proof).length)return '';
    return '<section class="card"><h3>原订单价值如何保留</h3>'+rows(ctx,[['原订单累计实付',proof.gross_paid_minor,currency],['原订单此前已退',proof.prior_refund_minor,currency],
      ['低价改期已作废差额',proof.excluded_minor,currency],['本次可保留住宿价值',proof.retained_minor,currency]])+
      '<p>已作废差额未计入住宿额度；以后兑换、取消或退款都不会恢复这一部分。</p></section>';
  }
  function cards(credits,currency){return credits.map(c=>`<section class="card"><div class="row"><h3>本店住宿额度</h3><span class="status">${esc(labels[c.status]||'待核对')}</span></div><p>有效至 ${esc(date(c.expires_at))}</p><button class="btn ghost" data-catalog-credit="${esc(c.stay_credit_id)}">查看额度与兑换进度</button></section>`).join('')}
  function redemptionCard(r){return r?`<section class="card"><h3>住宿额度兑换</h3><p>${esc(labels[r.status]||'处理中')}</p><button class="btn ghost" data-catalog-credit="${esc(r.stay_credit_id)}">查看额度、补款与退订</button></section>`:''}
  function bind(ctx){ctx.container.querySelectorAll('[data-catalog-credit]').forEach(b=>b.onclick=()=>open(ctx,b.dataset.catalogCredit).catch(e=>ctx.toast(e.message)))}
  async function convert(ctx,order){
    const q=JSON.parse(JSON.stringify(await post(ctx,`/v1/orders/${encodeURIComponent(order.order_id)}/stay-credit-quote`)));
    const r=await window.GOBooking.dialog('转为本店住宿额度',`${originalForfeiture(ctx,q.cash_change_forfeiture,q.currency)}${rows(ctx,[['转换额度',q.credit_value_minor,q.currency]])}<p>仅限原酒店使用，须在 ${esc(date(q.credit_expires_at))} 前按酒店入住时间办理入住。到期日不晚于原订单创建后 365 天，转换不会重新起算一年。兑换价格更高时补差价；更低时差额不退款、不留余额。</p><p>原预订取消确认后，额度才会激活。转换后可保留的原款将用于住宿额度。</p>${consent}${simulation}`,'确认转换',d=>post(ctx,`/v1/orders/${encodeURIComponent(order.order_id)}/convert-to-stay-credit`,{quote_id:q.quote_id,quote_hash:q.quote_hash,confirmed:confirmed(d)},'convert:'+q.quote_id));
    if(r)await open(ctx,r.stay_credit_id);
    return r;
  }
  async function quoteRedemption(ctx,c,checkIn,checkOut){
    const q=await post(ctx,`/v1/stay-credits/${encodeURIComponent(c.stay_credit_id)}/redemption-quote`,{check_in:checkIn,check_out:checkOut},`quote:${c.stay_credit_id}:${checkIn}:${checkOut}`);
    const tid=await window.GOBooking.traveler('HOTEL');if(!tid)return null;
    let consentId=null;
    const r=await window.GOBooking.dialog('确认本次住宿兑换',`<p>${esc(q.check_in)} → ${esc(q.check_out)}</p>${rows(ctx,[['本次房价',q.new_value_minor,q.currency],['住宿额度抵扣',q.applied_minor,q.currency],['需补款',q.amount_due_minor,q.currency],['本次放弃差额',q.forfeited_difference_minor,q.currency]])}<p>本次使用本店额度，有效期不延长；低价差额不退款、不留余额。仅为本次酒店预订使用刚才确认的出行人姓名和联系电话。</p>${consent}${simulation}`,'确认兑换',async d=>{
      confirmed(d);
      if(!consentId){const grant=await post(ctx,'/v1/consumer/profile/consents',{traveler_id:tid,consent_type:'SENSITIVE_DATA_RELEASE',purpose:'HOTEL_BOOKING',scope:['LEGAL_NAME','MOBILE'],expires_at:new Date(Date.now()+15*60000).toISOString()},'credit-guest:'+q.quote_id+':'+tid);consentId=grant.consent_id}
      return post(ctx,`/v1/stay-credits/${encodeURIComponent(c.stay_credit_id)}/redeem`,{redemption_quote_id:q.quote_id,quote_hash:q.quote_hash,confirmed:true,traveler_id:tid,consent_id:consentId,payment_method_token:'pm_success'},'redeem:'+q.quote_id+':'+tid);
    });
    if(r)await open(ctx,c.stay_credit_id);
    return r;
  }
  async function cancelRedemption(ctx,c,r){
    const base=`/v1/stay-credits/${encodeURIComponent(c.stay_credit_id)}/redemptions/${encodeURIComponent(r.order_id)}`;
    const q=await post(ctx,base+'/cancellation-quote');
    const result=await window.GOBooking.dialog('确认取消本次住宿',`${rows(ctx,[['取消费用',q.fee_minor,q.currency],['现金退回',q.cash_refund_minor,q.currency],['恢复至原住宿额度',q.restore_credit_minor,q.currency],['此前已放弃差额',q.forfeited_difference_minor,q.currency]])}<p>恢复后的额度仍有效至 ${esc(date(q.original_credit_expires_at))}；若处理完成时已过期，不会延长或变为现金。</p>${consent}`, '确认取消',d=>post(ctx,base+'/cancel',{quote_id:q.quote_id,quote_hash:q.quote_hash,confirmed:confirmed(d)},'credit-cancel:'+q.quote_id));
    if(result)await open(ctx,c.stay_credit_id);
    return result;
  }
  async function retryPayment(ctx,c,r){
    const result=await window.GOBooking.dialog('继续完成补款',`${rows(ctx,[['待补款',r.amount_due_minor,c.currency]])}<p>酒店预订已确认。本次只继续原订单补款。</p>${consent}${simulation}`,'确认补款',d=>post(ctx,`/v1/stay-credits/${encodeURIComponent(c.stay_credit_id)}/redemptions/${encodeURIComponent(r.order_id)}/retry-payment`,{quote_hash:r.quote_hash,confirmed:confirmed(d),payment_method_token:'pm_success'},'credit-payment:'+r.order_id));
    if(result)await open(ctx,c.stay_credit_id);
    return result;
  }
  function phaseActions(c,r){
    if(c.reconciliation_required)return '<p>这份历史额度正在核对原付款与适用规则。核对完成前不会再次扣款或兑换。</p>';
    if(['CANCEL_PENDING','UNKNOWN_CANCEL'].includes(c.status))return '<p>原酒店的取消结果尚待确认，额度暂不可用。</p><button class="btn ghost" id="ccCheckConversion">查询取消结果</button>';
    if(!r)return '';
    const progress=`<section class="card"><h3>最近一次兑换</h3><p>${esc(labels[r.status]||'处理中')}</p>`;
    if(['PREBOOK_PENDING','UNKNOWN_PREBOOK','PAYMENT_PENDING','BOOK_PENDING','UNKNOWN_BOOK'].includes(r.status))return progress+'<p>额度已保留。确认酒店结果后再继续处理。</p><button class="btn ghost" id="ccCheckRedemption">查询并继续处理</button></section>';
    if(r.status==='CAPTURE_PENDING')return progress+'<button class="btn primary" id="ccRetryPayment">继续补款</button></section>';
    if(['CANCEL_PENDING','UNKNOWN_CANCEL','CANCEL_REFUND_PENDING'].includes(r.status))return progress+'<button class="btn ghost" id="ccCheckCancellation">查询并继续退款</button></section>';
    if(r.status==='REDEEMED')return progress+'<button class="btn ghost" id="ccOpenOrder">查看订单</button><button class="btn ghost" id="ccCancel">查看取消报价</button></section>';
    if(r.customer_cancellation)return progress+`<p>现金退款与额度恢复已分别处理；额度是否可用以当前余额和原到期日为准。</p></section>`;
    return progress+'</section>';
  }
  async function open(ctx,cid){
    const c=await ctx.api(`/v1/stay-credits/${encodeURIComponent(cid)}`),r=c.latest_redemption;
    ctx.render(`<button class="back" id="ccBack">← 返回订单</button><section class="card"><div class="row"><h1>本店住宿额度</h1><span class="status">${esc(labels[c.status]||'待核对')}</span></div>${rows(ctx,[['原始额度',c.credit_value_minor,c.currency],['当前可用',c.available_minor||0,c.currency]])}<p>有效至 ${esc(date(c.expires_at))} · 仅限原酒店</p></section>${originalForfeiture(ctx,c.cash_change_forfeiture,c.currency)}${phaseActions(c,r)}${c.status==='ACTIVE'&&!c.reconciliation_required?'<section class="card"><h2>安排下一次入住</h2><form id="ccDates"><div class="field"><label for="ccIn">入住日期</label><input type="date" id="ccIn" name="checkIn" required></div><div class="field"><label for="ccOut">退房日期</label><input type="date" id="ccOut" name="checkOut" required></div><button class="btn primary" type="submit">查看报价</button></form></section>':''}`);
    const $=selector=>ctx.container.querySelector(selector);
    $('#ccBack').onclick=ctx.onBack;
    const run=async(button,fn)=>{if(button.disabled)return;button.disabled=true;try{await fn()}catch(e){ctx.toast(friendly(e.message))}finally{button.disabled=false}};
    const wire=(id,fn)=>{const b=$(id);if(b)b.onclick=()=>run(b,fn)};
    wire('#ccCheckConversion',async()=>{await post(ctx,`/v1/stay-credits/${encodeURIComponent(cid)}/reconcile-conversion`);await open(ctx,cid)});
    const base=r?`/v1/stay-credits/${encodeURIComponent(cid)}/redemptions/${encodeURIComponent(r.order_id)}`:'';
    wire('#ccCheckRedemption',async()=>{await post(ctx,base+'/reconcile');await open(ctx,cid)});
    wire('#ccCheckCancellation',async()=>{await post(ctx,base+'/reconcile-cancellation');await open(ctx,cid)});
    wire('#ccRetryPayment',()=>retryPayment(ctx,c,r));wire('#ccCancel',()=>cancelRedemption(ctx,c,r));wire('#ccOpenOrder',()=>ctx.onOrder(r.order_id));
    const form=$('#ccDates');if(form)form.onsubmit=e=>{e.preventDefault();const b=form.querySelector('button');return run(b,async()=>{try{return await quoteRedemption(ctx,c,form.elements.checkIn.value,form.elements.checkOut.value)}finally{b.disabled=false}})};
    return c;
  }
  window.GOCatalogCredit={cards,redemptionCard,bind,convert,quoteRedemption,cancelRedemption,retryPayment,phaseActions,open};
})();
