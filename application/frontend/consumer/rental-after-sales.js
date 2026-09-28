(() => {
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function confirmChange(order,quote){
    const difference=quote.difference_minor;
    const label=difference>0?'本次补付':difference<0?'原支付退回':'本次差额';
    return GOBooking.dialog('核对租车改期',`<p>${esc(quote.new_pickup_at||order.pickup_at)} → ${esc(quote.new_return_at||order.return_at)}</p>${quote.new_amount_minor!=null?`<p>调整后总价 ${esc(money(quote.new_amount_minor,quote.currency))}</p>`:''}<h2>${label} ${esc(money(Math.abs(difference),quote.currency))}</h2><p>改期服务费为 0。押金与保险方案保持原订单约定。</p><div class="go-sim-note">隔离测试，不产生真实扣款或退款。</div><label class="go-consent"><input type="checkbox" data-consent required><span>已核对新行程及差额，同意按以上金额完成改期。</span></label>`,'确认改期',async d=>{
      if(!d.querySelector('[data-consent]').checked)throw Error('请先核对行程和金额');
      return api(`/v1/mobility/rentals/orders/${order.order_id}/changes/${quote.quote_id}`,{method:'POST',body:JSON.stringify({expected_difference_minor:difference,currency:quote.currency,mode:'CONTRACT_SIMULATOR'})});
    });
  }
  const previousModify=mobilityModify;
  mobilityModify=async kind=>{
    if(kind!=='RENTAL')return previousModify(kind);
    const order=state.rentalOrder;
    try{
      const quote=await GOBooking.dialog('选择新的取还车时间',`<div class="field"><label for="rentalPickup">取车时间</label><input id="rentalPickup" type="datetime-local" required value="${esc(order.pickup_at.slice(0,16))}"></div><div class="field"><label for="rentalReturn">还车时间</label><input id="rentalReturn" type="datetime-local" required value="${esc(order.return_at.slice(0,16))}"></div><p>先查看新总价与应补或应退金额，再确认改期。</p>`,'查看新报价',d=>api(`/v1/mobility/rentals/orders/${order.order_id}/change-quotes`,{method:'POST',body:JSON.stringify({pickup_at:d.querySelector('#rentalPickup').value,return_at:d.querySelector('#rentalReturn').value})}));
      if(quote&&await confirmChange(order,quote))await mobilityReload('RENTAL');
    }catch(e){toast(e.message);await mobilityReload('RENTAL')}
  };
  const previousRender=renderMobilityOrder;
  renderMobilityOrder=kind=>{
    previousRender(kind);if(kind!=='RENTAL')return;
    const order=state.rentalOrder,section=document.createElement('section');section.className='card';
    section.innerHTML=`<h2>取还车安排</h2><p>${esc(order.pickup_location)} · ${esc(order.pickup_at)}</p><p>${esc(order.return_location)} · ${esc(order.return_at)}</p><div class="kv"><span>当前订单总价</span><strong>${esc(money(order.total_amount_minor,order.currency))}</strong></div>`;
    if(order.pending_change)section.innerHTML+='<p role="status">改期差额尚未处理完，原取还车时间暂时保留。继续处理同一笔改期即可。</p><button class="btn primary" data-resume-change>继续改期</button>';
    if(order.status==='REFUND_PENDING')section.innerHTML+='<p role="status">退款处理中，暂不重复发起其他售后操作。</p><button class="btn primary" data-resume-refund>继续原路退款</button>';
    document.querySelector('#app .shared-consumer-content').append(section);
    const change=section.querySelector('[data-resume-change]');if(change)change.onclick=async()=>{try{if(await confirmChange(order,order.pending_change))await mobilityReload('RENTAL')}catch(e){toast(e.message)}};
    const refund=section.querySelector('[data-resume-refund]');if(refund)refund.onclick=async()=>{try{if(await GOBooking.dialog('继续原路退款','<p>继续处理先前确认的退款，同一笔退款不会重复退回。</p>','继续退款',()=>api(`/v1/mobility/orders/${order.order_id}/cancel`,{method:'POST'})))await mobilityReload('RENTAL')}catch(e){toast(e.message)}};
  };
})();
