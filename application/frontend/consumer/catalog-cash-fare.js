(() => {
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stages={AUTH_PENDING:'正在保留补款',READY:'申请已保存',SUPPLIER_PENDING:'酒店处理中',UNKNOWN_SUPPLIER:'正在核实酒店结果',REFUND_PENDING:'取消已确认，退款处理中',CAPTURE_PENDING:'酒店已确认改期，补款待完成',REJECTED_RELEASE_PENDING:'改期未获确认，正在释放补款',REJECTED:'酒店未接受改期，原行程保留',PAYMENT_DECLINED:'补款未获授权，原行程保留',COMPLETED:'处理完成'};
  const simulation='<p class="muted">当前为隔离演练，不会从真实账户扣款。</p>';
  const checkbox='<label><input type="checkbox" name="cashConfirmed" required>我已核对日期、费用和退款规则，同意执行本次申请。</label>';
  const consent=d=>{if(!d.querySelector('[name=cashConfirmed]').checked)throw Error('请先确认本次日期和费用。');return true};
  const base=oid=>'/v1/orders/'+encodeURIComponent(oid);
  const friendly=m=>/HOTEL_CHANGE_ONE_YEAR_VALIDITY/.test(m)?'改期入住日期须在原订单创建日起一年内，改期不会延长有效期。':/HOTEL_CHANGE_(FEE|POLICY)/.test(m)?'改期规则已更新，请重新查看免费改期报价。':/QUOTE.*EXPIRED/.test(m)?'报价已过期，请重新查看。':/QUOTE_STALE|FACT_CHANGED/.test(m)?'订单或金额已变化，请重新查看报价。':/HISTORICAL|RECONCILIATION_REQUIRED/.test(m)?'这笔订单的原规则或付款记录需要核对，确认后才能继续。':/IN_PROGRESS|FUNDS_RESERVED/.test(m)?'已有退改申请正在处理，请先查看当前进度。':/DATES|INVENTORY|CHANGE_NOT_AVAILABLE/.test(m)?'这些日期暂不可改订，请调整日期后重试。':/^[A-Z0-9_:]+$/.test(m)?'本次申请尚未完成，请查看订单进度后再试。':m;
  const post=async(ctx,path,body={},key)=>{try{return await ctx.api(path,{method:'POST',body:JSON.stringify(body),...(key?{headers:{'Idempotency-Key':key}}:{})})}catch(e){throw Error(friendly(e.message))}};
  const rows=(ctx,q,items)=>items.map(([label,n])=>`<div class="kv"><span>${label}</span><b>${esc(ctx.money(n,q.currency))}</b></div>`).join('');
  async function cancel(ctx,order){
    const q=JSON.parse(JSON.stringify(await post(ctx,base(order.order_id)+'/cancellation-quote')));
    const body=rows(ctx,q,[['累计实付',q.gross_paid_minor],['此前已退',q.prior_refund_minor],['当前净实付',q.paid_amount_minor],['历史已付改期费',q.paid_change_fees_minor],['低价改期已作废差额',q.forfeited_change_value_minor],['本次取消费',q.cancellation_fee_minor],['本次原路退款',q.refund_amount_minor]].filter(([label,n])=>label!=='历史已付改期费'||n>0))+`<p>本次取消费按净实付扣除已作废差额后的 ${esc(ctx.money(q.fee_basis_minor,q.currency))} 的 ${q.fee_basis_points/100}% 计算。原款和价差补款将分别退回各自原支付交易。</p><p>报价有效至 ${esc(new Date(q.expires_at).toLocaleString())}。</p>`+checkbox+simulation;
    const result=await ctx.dialog('确认取消和逐笔退款',body,'确认取消',d=>post(ctx,base(order.order_id)+'/cancel',{cancellation_quote_id:q.quote_id,quote_hash:q.quote_hash,confirmed:consent(d)},'cash-cancel:'+q.quote_id));
    if(result)await ctx.reload(order.order_id);
    return result;
  }
  async function change(ctx,order,stay){
    const dates=await ctx.dialog('选择新的入住日期',`<label>入住日期<input name="cashIn" type="date" required value="${esc(stay?.check_in)}"></label><label>退房日期<input name="cashOut" type="date" required value="${esc(stay?.check_out)}"></label>`,'查看报价',d=>({new_check_in:d.querySelector('[name=cashIn]').value,new_check_out:d.querySelector('[name=cashOut]').value}));
    if(!dates)return null;
    const q=JSON.parse(JSON.stringify(await post(ctx,base(order.order_id)+'/change-quote',dates)));
    const body=`<p>${esc(q.new_check_in)} → ${esc(q.new_check_out)}</p>`+rows(ctx,q,[['当前已确认房价',q.old_value_minor],['新日期房价',q.new_value_minor],['本次房价差额',q.fare_difference_minor],['本次合计补款',q.amount_due_minor],['本次低价改期作废差额',q.lower_price_difference_minor]])+`<p>改期免手续费。涨价只补本次差价，降价不退差价。更低房价的差额不形成余额，也不抵扣以后改期。</p><p>最晚入住期限：${esc(new Date(q.change_valid_until).toLocaleString())}。自原订单创建日起 365 天，连续改期不顺延。</p>`+checkbox+simulation;
    const result=await ctx.dialog('确认改期与补款',body,'确认改期',d=>post(ctx,base(order.order_id)+'/change',{change_quote_id:q.change_quote_id,quote_hash:q.quote_hash,confirmed:consent(d),payment_method_token:'pm_success'},'cash-change:'+q.change_quote_id));
    if(result)await ctx.reload(order.order_id);
    return result;
  }
  function progress(op,money){
    if(!op)return '';
    if(op.reconciliation_required)return '<section class="card"><h3>退改进度</h3><p>订单与付款记录正在核对，确认后将继续处理。</p></section>';
    let html=`<section class="card"><h3>${op.action==='CANCEL'?'取消与退款':'改期与补款'}</h3><p role="status">${esc(stages[op.state]||'正在核对')}</p>`;
    html+=`<div class="kv"><span>本次处理时累计付款（含补款）</span><b>${esc(money(op.gross_paid_minor,op.currency))}</b></div><div class="kv"><span>本次处理时累计退款</span><b>${esc(money(op.prior_refund_minor,op.currency))}</b></div>`;
    if(op.refund)html+=`<div class="kv"><span>${op.refund.status==='COMPLETED'?'原路退款已完成':'待原路退回'}</span><b>${esc(money(op.refund.amount_minor,op.currency))}</b></div>`;
    if(op.state==='UNKNOWN_SUPPLIER')html+='<p>原申请已保存。查询结果不会再次发送取消或改期指令。</p>';
    if(op.payment_retry_allowed)html+='<button id="cashRetryPayment" class="btn primary">继续补款</button>';
    else if(op.reconcile_allowed)html+='<button id="cashReconcile" class="btn ghost">查询并继续处理</button>';
    return html+'</section>';
  }
  function bind(ctx,op){
    if(!op||op.reconciliation_required)return;
    const route=base(op.order_id)+'/cash-after-sales/'+encodeURIComponent(op.operation_id);
    const wire=(id,fn)=>{const b=ctx.container.querySelector(id);if(b)b.onclick=async()=>{if(b.disabled)return;b.disabled=true;try{await fn()}catch(e){ctx.toast(e.message)}finally{b.disabled=false}}};
    wire('#cashReconcile',async()=>{await post(ctx,route+'/reconcile');await ctx.reload(op.order_id)});
    wire('#cashRetryPayment',async()=>{
      const result=await ctx.dialog('完成原改期的补款',rows(ctx,op,[['原报价待补款',op.amount_due_minor]])+'<p>酒店已经确认改期，这次只继续原报价补款。</p>'+checkbox+simulation,'确认补款',d=>post(ctx,route+'/retry-payment',{quote_hash:op.quote_hash,confirmed:consent(d),payment_method_token:'pm_success'}));
      if(result)await ctx.reload(op.order_id);
    });
  }
  window.GOCatalogCashFare={cancel,change,progress,bind};
})();
