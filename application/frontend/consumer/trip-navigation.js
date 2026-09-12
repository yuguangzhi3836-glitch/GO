/* The list supplies typed, owner-checked references. Never follow evidence URLs. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const kinds = {HOTEL_CATALOG:'HOTEL', HOTEL_DIRECT:'HOTEL', FLIGHT:'FLIGHT',
    RAIL:'RAIL', RIDE:'RIDE', RENTAL:'RENTAL', ATTRACTION:'ATTRACTION'};
  const endpoints = {HOTEL_CATALOG:'/v1/consumer/orders/', FLIGHT:'/v1/flights/orders/',
    RAIL:'/v1/rail/orders/', RIDE:'/v1/mobility/orders/', RENTAL:'/v1/mobility/orders/',
    ATTRACTION:'/v1/attractions/orders/'};
  function target(item) {
    const n = item?.navigation;
    if (!n || !Object.hasOwn(kinds, n.kind) || kinds[n.kind] !== item.vertical ||
        n.order_id !== item.order_id || !/^[A-Za-z0-9_-]{1,100}$/.test(n.order_id)) return null;
    const id = encodeURIComponent(n.order_id);
    return n.kind === 'HOTEL_DIRECT'
      ? {kind:n.kind, id:n.order_id, href:'/go-app/direct.html?reservation=' + id}
      : {kind:n.kind, id:n.order_id, path:endpoints[n.kind] + id + (n.kind === 'HOTEL_CATALOG' ? '/detail' : '')};
  }
  function cards(rows, label, money) {
    return rows.map((x, index) => `<section class="card"><div class="row"><h3>${esc(x.title)}</h3><span class="status">${esc(label(x.native_status || x.lifecycle_state))}</span></div><div class="kv"><span>订单号</span><b>${esc(x.order_id)}</b></div><div class="kv"><span>品类</span><b>${esc(label(x.vertical))}</b></div>${Number.isSafeInteger(x.total_amount_minor)?`<div class="kv"><span>${x.cash_after_sales?'原始下单金额':'订单金额'}</span><b>${esc(money(x.total_amount_minor,x.currency))}</b></div>`:''}${cashSummary(x.cash_after_sales,money)}<div class="kv"><span>支付</span><span>${esc(label(x.payment_state))}</span></div><div class="kv"><span>退款</span><span>${esc(label(x.refund_state))}</span></div>${target(x)?`<button class="btn ghost" data-go-trip-index="${index}">查看订单与后续操作</button>`:'<p class="muted">订单关联正在核对，暂时无法打开详情。</p>'}</section>`).join('');
  }
  function cashSummary(c,money) {
    if(!c)return '';
    const stages={AUTH_PENDING:'正在保留补款',READY:'申请已保存',SUPPLIER_PENDING:'酒店处理中',UNKNOWN_SUPPLIER:'正在核实酒店结果',REFUND_PENDING:'取消已确认，退款处理中',CAPTURE_PENDING:'酒店已确认改期，补款待完成',REJECTED_RELEASE_PENDING:'正在释放补款',REJECTED:'改期未获确认，原行程保留',PAYMENT_DECLINED:'补款未获授权，原行程保留',COMPLETED:'处理完成'};
    const rows=[['入住日期',c.check_in],['退房日期',c.check_out],['退改进度',stages[c.state]||'正在核对']];
    if(c.action==='CHANGE'&&!['COMPLETED','REJECTED','PAYMENT_DECLINED'].includes(c.state))rows.push(['申请入住日期',c.requested_check_in],['申请退房日期',c.requested_check_out]);
    for(const [label,key]of [['本次改期已补款','amount_paid_minor'],['累计实付（含补款）','gross_paid_minor'],['累计已退','refunded_minor'],['当前净实付','net_paid_minor']])
      if(Number.isSafeInteger(c[key])&&(key!=='amount_paid_minor'||c.action==='CHANGE'))rows.push([label,money(c[key],c.currency)]);
    return rows.map(([label,value])=>`<div class="kv"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('');
  }
  async function open(item, context) {
    const route = target(item);
    if (!route) throw Error('TRIP_REFERENCE_UNAVAILABLE');
    if (route.href) { context.navigate(route.href); return; }
    const value = await context.api(route.path);
    if (!context.current()) return;
    const id = route.kind === 'HOTEL_CATALOG' ? value?.order?.order_id : value?.order_id;
    if (id !== route.id || (value.vertical && value.vertical !== kinds[route.kind]))
      throw Error('TRIP_ORDER_IDENTITY_MISMATCH');
    context.render(route.kind, value);
  }
  async function resumePayment(item, context) {
    const route = target(item);
    if (!route?.path) throw Error('TRIP_REFERENCE_UNAVAILABLE');
    const value = await context.api(route.path);
    if (!context.current()) return;
    const order = route.kind === 'HOTEL_CATALOG' ? value?.order : value;
    if (order?.order_id !== route.id || (value.vertical && value.vertical !== kinds[route.kind]))
      throw Error('TRIP_ORDER_IDENTITY_MISMATCH');
    if (!['PAYMENT_PENDING','PAYMENT_AUTHORIZED'].includes(order.status)) {
      context.render(route.kind, value); return;
    }
    try { await context.pay(item.vertical, order); }
    finally {
      // A timeout is an unknown result. Read the same order, never create another.
      if (context.current()) await open(item, context);
    }
  }
  window.GOTrips = {target, cards, open, resumePayment};
})();
