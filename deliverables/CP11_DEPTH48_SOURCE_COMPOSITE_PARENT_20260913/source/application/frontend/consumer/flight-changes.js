/* Explicit segment selection; each confirmation is bound to one immutable quote. */
(() => {
  'use strict';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function selection(order,dates){
    if(!Array.isArray(order.itinerary)||dates.length!==order.itinerary.length)throw Error('无法核对完整行程，请刷新订单。');
    const changes=dates.flatMap((day,index)=>day===order.itinerary[index].departure_date?[]:[{leg_index:index,new_departure_date:day}]);
    if(!changes.length)throw Error('请至少调整一程的出发日期。');
    return changes;
  }
  function confirmation(q){return {quote_hash:q.quote_hash,expected_total_due_minor:q.total_due_minor,currency:q.currency,confirmed:true};}
  async function open(order,request,reload,current=()=>true){
    const original=JSON.parse(JSON.stringify(order)),oid=original.order_id;
    const path='/v1/flights/orders/'+oid, legs=original.itinerary||[];
    const money=n=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:original.currency}).format(n/100);
    const check=()=>{if(!current())throw Error('当前订单已变化，请重新核对。');};
    try{
      const q=await window.GOBooking.dialog('选择需要改签的航段',
        '<p>可修改一程或多程；日期不变的航段保留。当前申请包含本单全部乘机人。</p>'+legs.map((leg,i)=>
          `<label>第 ${i+1} 程 · ${esc(leg.origin)} → ${esc(leg.destination)}<input data-flight-change-date="${i}" type="date" required value="${esc(leg.departure_date)}"></label>`).join(''),
        '核对改签费用',async()=>{
          check();const dates=Array.from(document.querySelectorAll('[data-flight-change-date]')).map(x=>x.value);
          const changes=selection(original,dates);
          const quote=await request(path+'/change-quote',{method:'POST',body:JSON.stringify({changes})});check();
          if(quote.order_id!==oid||!Array.isArray(quote.changes)||quote.changes.length!==changes.length||!/^[a-f0-9]{64}$/.test(quote.quote_hash)
             ||quote.currency!==original.currency||!Number.isSafeInteger(quote.total_due_minor)||quote.total_due_minor<0
             ||quote.changes.some((x,i)=>x.leg_index!==changes[i].leg_index||x.new_departure_date!==changes[i].new_departure_date))throw Error('返回方案与所选航段不一致，请重新核对。');
          return quote;
        });
      if(!q)return;let sent=false;
      await window.GOBooking.dialog('确认本次改签',q.changes.map(c=>
        `<p>第 ${c.leg_index+1} 程 · ${esc(c.origin)} → ${esc(c.destination)}<br>${esc(c.old_departure_date)} → ${esc(c.new_departure_date)}</p>`).join('')+
        `<p>票价差额 ${money(q.fare_difference_minor)}；改签手续费 ${money(q.change_fee_minor)}。</p><p>合计需补 ${money(q.total_due_minor)}。其余航段保持原安排。</p><p>提交后等待供应商确认，原订单将保留全部处理记录。</p>`,
        '确认航段、费用并提交',async()=>{
          check();if(sent)throw Error('请求已提交，请查看原订单处理状态。');
          const expires=Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(q.expires_at)?q.expires_at:q.expires_at+'Z');
          if(!(expires>Date.now()))throw Error('报价已过期，请重新核对。');
          sent=true;
          try{return await request(path+'/execute-change/'+q.quote_id,{method:'POST',headers:{'Idempotency-Key':`flight-change:${oid}:${q.quote_id}`},body:JSON.stringify(confirmation(q))});}
          finally{await reload();}
        });
    }catch(error){if(typeof toast==='function')toast(error.message||'请查看原订单的改签处理状态。');}
  }
  window.GOFlightChanges={selection,confirmation,open};
})();
