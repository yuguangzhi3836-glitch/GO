/* Coupon identities and amounts are issued by the server, never inferred by position. */
(() => {
  'use strict';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label=c=>`${c.passenger_name} · 第 ${c.leg_index+1} 程 · ${c.leg.origin} → ${c.leg.destination} · ${c.leg.departure_date}`;
  const states={ISSUED:'已出票',UNISSUED:'等待出票',REFUNDED:'已退票',REFUND_PENDING:'退款处理中',CHANGE_PENDING:'改签处理中',UNKNOWN_EXTERNAL_STATE:'等待核实',FAILED:'处理失败'};
  function cards(order){return (order.coupons||[]).map(c=>`<article class="j-panel"><h3>${esc(label(c))}</h3><p>${esc(states[c.state]||c.state)}${c.usable?' · 票券有效':''}</p><p>票号 ${esc(c.ticket_number||'等待确认')} · 预订编号 ${esc(c.supplier_reference||'等待确认')}</p></article>`).join('');}
  function confirmation(q){return {quote_hash:q.quote_hash,expected_refund_amount_minor:q.refund_amount_minor,currency:q.currency,confirmed:true};}
  async function refund(order,request,reload,current=()=>true){
    const original=JSON.parse(JSON.stringify(order)),oid=original.order_id,path='/v1/flights/orders/'+oid;
    const check=()=>{if(!current())throw Error('当前订单已变化，请重新核对。');};
    const money=n=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:original.currency}).format(n/100);
    try{
      let q=(original.coupon_refunds||[]).find(x=>x.status==='PREPARED');
      if(!q){
        q=await window.GOBooking.dialog('选择退票乘客与航段',
          '<p>每张票券单独选择；提交前将核对手续费和原路退款金额。</p>'+(original.coupons||[]).filter(c=>c.usable).map(c=>
          `<label><input type="checkbox" data-flight-refund-coupon="${esc(c.coupon_id)}">${esc(label(c))}</label>`).join(''),
          '核对退票费用',async()=>{
            check();const ids=Array.from(document.querySelectorAll('[data-flight-refund-coupon]:checked')).map(x=>x.dataset.flightRefundCoupon);
            if(!ids.length)throw Error('请至少选择一张票券。');
            const quote=await request(path+'/coupon-refund-quotes',{method:'POST',body:JSON.stringify({coupon_ids:ids})});check();
            if(quote.order_id!==oid||quote.currency!==original.currency||!/^[a-f0-9]{64}$/.test(quote.quote_hash)
              ||!Number.isSafeInteger(quote.refund_amount_minor)||quote.refund_amount_minor<0
              ||!Array.isArray(quote.coupon_ids)||quote.coupon_ids.length!==ids.length||ids.some(id=>!quote.coupon_ids.includes(id)))throw Error('退票方案与所选票券不一致。');
            return quote;
          });
      }
      if(!q)return;let sent=false;
      const selected=(original.coupons||[]).filter(c=>q.coupon_ids.includes(c.coupon_id));
      await window.GOBooking.dialog(q.status==='PREPARED'?'继续核对原退票申请':'确认所选票券退票',
        selected.map(c=>`<p>${esc(label(c))}</p>`).join('')+`<p>手续费 ${money(q.refund_fee_minor)}；原路退款 ${money(q.refund_amount_minor)}。</p><p>未选票券保留。提交后的处理结果可在其他设备查看。</p>`,
        q.status==='PREPARED'?'查询并继续原申请':'确认票券与金额并退票',async()=>{
          check();if(sent)throw Error('已提交，请刷新查看原申请。');
          if(q.status!=='PREPARED'&&!(q.expires_ms>Date.now()))throw Error('报价已过期，请重新核对。');
          sent=true;try{return await request(path+'/coupon-refunds/'+q.refund_id,{method:'POST',body:JSON.stringify(confirmation(q))});}
          finally{await reload();}
        });
    }catch(e){if(typeof toast==='function')toast(e.message||'请刷新查看退票进度。');}
  }
  window.GOFlightCoupons={cards,confirmation,refund};
})();
