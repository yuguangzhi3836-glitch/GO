/* Party size, quoted total and slot remain bound through explicit confirmation. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const seats = {SECOND_CLASS:'二等座',FIRST_CLASS:'一等座',BUSINESS_CLASS:'商务座'};
  const eligibilityText = e => {
    if (!e || typeof e !== 'object') return String(e || '请核对适用条件');
    const age = {'all':'所有年龄','12+ adult':'12 岁及以上（成人票）','6+':'6 岁及以上'}[e.age] || String(e.age || '以票种年龄要求为准');
    return `年龄要求：${age}；${e.id_required ? '需持有效身份证件入场' : '请按票种说明入场'}。`;
  };
  function validateQuote(q, vertical, offer, selection, now = Date.now()) {
    if (!q || !q.prebook_id || !q.terms_hash || q.offer_id !== offer.offer_id ||
        q.quantity !== selection.quantity || q.currency !== 'CNY' ||
        !Number.isSafeInteger(q.unit_amount_minor) || q.unit_amount_minor <= 0 ||
        !Number.isSafeInteger(q.total_amount_minor) || q.total_amount_minor !== q.unit_amount_minor * q.quantity ||
        !Number.isSafeInteger(q.expires_ms) || q.expires_ms <= now) throw Error('报价已变化或过期，请重新选择。');
    if (vertical === 'ATTRACTION' && (q.visit_date !== selection.visit_date || q.session_time !== selection.session_time))
      throw Error('日期或场次与所选不一致，请重新选择。');
    if (vertical === 'RAIL' && (!q.journey || ['travel_date','train_no','origin_station','destination_station','seat_class'].some(k => q.journey[k] !== offer[k])))
      throw Error('车次信息已变化，请重新搜索。');
    return q;
  }
  function createFlow(d) {
    let busy = false;
    return async (vertical, offer, criteria) => {
      if (busy) return null;
      busy = true;
      try {
        const rail = vertical === 'RAIL', title = rail ? '火车票' : '门票';
        const sessions = rail ? [] : [...new Set(offer.available_sessions || [offer.session_time])].filter(Boolean);
        const max = Math.min(9, Number(rail ? offer.inventory_left : offer.inventory_units));
        if (!Number.isInteger(max) || max < 1 || (!rail && !sessions.length)) throw Error('当前暂无可选名额，请重新搜索。');
        const selection = await d.dialog(`选择${title}人数${rail ? '' : '与场次'}`,
          `<p>${esc(rail ? `${offer.travel_date} · ${offer.train_no} · ${seats[offer.seat_class] || offer.seat_class}` : `${criteria.visit_date} · ${offer.product_name}`)}</p><div class="field"><label for="goPartyCount">${rail ? '成人乘车人数' : '参加人数'}</label><select id="goPartyCount">${Array.from({length:max},(_,i)=>`<option value="${i+1}">${i+1} 人</option>`).join('')}</select></div>${rail ? '<p>本次为成人票，儿童票需另行报价。</p>' : `<div class="field"><label for="goPartySession">入场场次</label><select id="goPartySession">${sessions.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('')}</select></div><p>${esc(offer.ticket_type)} · ${esc(eligibilityText(offer.eligibility))}</p>`}<p>下一步将按所选人数核验含税总价。当前展示名额尚未占用。</p>`,'核验总价', el => {
            const quantity = Number(el.querySelector('#goPartyCount').value);
            const session_time = rail ? null : el.querySelector('#goPartySession').value;
            if (!Number.isInteger(quantity) || quantity < 1 || quantity > max || (!rail && !sessions.includes(session_time))) throw Error('请重新选择人数与场次。');
            return {quantity, ...(rail ? {} : {visit_date:criteria.visit_date, session_time})};
          });
        if (!selection) return null;
        const raw = await d.post(rail ? `/v1/rail/offers/${encodeURIComponent(offer.offer_id)}/prebook` : '/v1/attractions/prebook',
          rail ? {quantity:selection.quantity} : {offer_id:offer.offer_id,...selection,currency:'CNY'}, d.uuid());
        const q = validateQuote(raw, vertical, offer, selection, d.now());
        const ids = await d.travelers(vertical, q.quantity);
        if (!ids) return null;
        if (ids.length !== q.quantity || new Set(ids).size !== q.quantity) throw Error('出行人数与报价不一致，请重新核对。');
        const policy = (label,p) => p?.allowed ? `${label}手续费 ${d.money(p.fee_minor * q.quantity,q.currency)} / 本次 ${q.quantity} 人${label==='改签'?'，票价差额另行核验。':'。'}` : `此票种不支持${label}。`;
        const rules = rail ? [policy('改签',q.change_policy),policy('退票',q.refund_policy)] : [eligibilityText(q.eligibility), q.changeable ? '支持按规则申请改期，需确认新场次。' : '此票种不支持改期。', q.refundable ? '支持按规则申请退款，以退款核验结果为准。' : '此票种不可退款。'];
        const o = await d.dialog(`核对${title}与总价`,
          `<p>${esc(rail ? `${q.journey.travel_date} · ${q.journey.train_no} · ${seats[q.journey.seat_class] || q.journey.seat_class}` : `${q.product_name} · ${q.visit_date} · ${q.session_time}`)}</p><div class="kv"><span>${q.quantity} 人 × ${esc(d.money(q.unit_amount_minor,q.currency))}</span><strong>${esc(d.money(q.total_amount_minor,q.currency))}</strong></div><p>以上为本次含税应付总额。</p>${rules.filter(Boolean).map(r=>`<p>${esc(r)}</p>`).join('')}<div class="go-sim-note">当前为隔离测试，不会购买真实车票或门票。测试凭证不能用于出行。</div><label class="go-consent"><input type="checkbox" data-quote-consent required><span>我已核对人数、日期${rail ? '、车次与席别' : '、场次与适用条件'}、含税总价及退改规则。</span></label>`,'确认订单', async el => {
            if (!el.querySelector('[data-quote-consent]').checked) throw Error('请先核对并确认预订信息。');
            validateQuote(q,vertical,offer,selection,d.now());
            const body = {prebook_id:q.prebook_id,traveler_ids:ids,...(rail ? {} : {offer_id:q.offer_id,visit_date:q.visit_date,session_time:q.session_time,quantity:q.quantity,currency:q.currency})};
            return d.post(rail ? '/v1/rail/orders' : '/v1/attractions/orders',body,`party:${vertical}:${q.prebook_id}:${ids.join(':')}`);
          });
        if (!o) return null;
        try { await d.pay(vertical,o); }
        finally { await d.show(vertical,o.order_id); }
        return o;
      } finally { busy = false; }
    };
  }
  window.GOPartyBooking = {validateQuote,createFlow};
  if (!window.GOBooking || typeof state === 'undefined') return;
  const keys = new Map();
  const book = createFlow({
    ...window.GOBooking, now:()=>Date.now(), uuid:()=>crypto.randomUUID(), money,
    post:(path,body,name)=>{if(!keys.has(name))keys.set(name,crypto.randomUUID());return api(path,{method:'POST',headers:{'Idempotency-Key':keys.get(name)},body:JSON.stringify(body)});},
    show:async(vertical,id)=>{if(vertical==='RAIL'){state.railOrder=await api(`/v1/rail/orders/${id}`);renderRailOrder();}else{state.attractionOrder=await api(`/v1/attractions/orders/${id}`);renderAttractionOrder();}}
  });
  const start = async (vertical,id) => {
    try {
      if(!state.me){showAuth();return;}
      const rail=vertical==='RAIL', offer=(rail?state.railSearch:state.attractionSearch)?.find(x=>x.offer_id===id);
      if(!offer)throw Error('此结果已过期，请重新搜索。');
      await book(vertical,structuredClone(offer),structuredClone(rail?state.railCriteria:state.attractionCriteria));
    } catch(e) {toast(e.message);}
  };
  railSelect=id=>start('RAIL',id);
  attractionBook=id=>start('ATTRACTION',id);
})();
