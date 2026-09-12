import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const code=fs.readFileSync('frontend/consumer/catalog-cash-fare.js','utf8');
const hash='a'.repeat(64);
const order={order_id:'order-one',currency:'CNY'};
const quote={quote_id:'quote-one',change_quote_id:'quote-one',quote_hash:hash,currency:'CNY',
  gross_paid_minor:1583200,prior_refund_minor:43200,paid_amount_minor:1540000,paid_change_fees_minor:20000,
  forfeited_change_value_minor:0,lower_price_difference_minor:0,fee_basis_minor:1540000,fee_basis_points:125,cancellation_fee_minor:19250,refund_amount_minor:1520750,
  old_value_minor:1523200,new_value_minor:1563200,fare_difference_minor:40000,change_fee_minor:10000,amount_due_minor:50000,
  new_check_in:'2026-11-01',new_check_out:'2026-11-05',expires_at:'2026-10-01T10:00:00Z'};
function setup(dialog){
  const c={window:{},JSON,Date};vm.runInNewContext(code,c);
  const calls=[],ctx={money:n=>'¥'+(n/100).toFixed(2),dialog,
    api:async(path,request)=>{calls.push({path,request});return path.endsWith('quote')?quote:{state:'COMPLETED'}},
    reload:async oid=>calls.push({reload:oid}),toast(){}};
  return {api:c.window.GOCatalogCashFare,ctx,calls};
}
const accepted={querySelector:()=>({checked:true})};

test('cancel review shows every cash component and exact fee basis before submission',async()=>{
  const {api,ctx,calls}=setup(async(title,html,label,submit)=>{
    for(const text of ['¥15832.00','¥432.00','¥15400.00','¥200.00','¥192.50','¥15207.50','1.25%','分别退回'])assert.ok(html.includes(text),text);
    assert.ok(!html.includes(hash));return submit(accepted);
  });
  await api.cancel(ctx,order);
  const sent=calls.find(x=>x.path?.endsWith('/cancel'));
  assert.equal(JSON.parse(sent.request.body).quote_hash,hash);
  assert.equal(sent.request.headers['Idempotency-Key'],'cash-cancel:quote-one');
  assert.deepEqual(calls.at(-1),{reload:'order-one'});
});

test('closing cancel review never sends cancellation or reloads as completed',async()=>{
  const {api,ctx,calls}=setup(async()=>null);
  assert.equal(await api.cancel(ctx,order),null);
  assert.equal(calls.length,1);assert.ok(calls[0].path.endsWith('cancellation-quote'));
});

test('unchecked money confirmation cannot submit a cash action',async()=>{
  const {api,ctx,calls}=setup(async(t,h,l,submit)=>submit({querySelector:()=>({checked:false})}));
  await assert.rejects(api.cancel(ctx,order),/请先确认/);
  assert.equal(calls.length,1);
});

test('change confirmation keeps paid room value, incremental difference and fee separate',async()=>{
  let step=0;
  const {api,ctx,calls}=setup(async(title,html,label,submit)=>{
    if(step++===0)return {new_check_in:quote.new_check_in,new_check_out:quote.new_check_out};
    for(const text of ['¥15232.00','¥15632.00','¥400.00','¥100.00','¥500.00','只补本次增量','不形成余额'])assert.ok(html.includes(text),text);
    return submit(accepted);
  });
  await api.change(ctx,order,{check_in:'2026-10-01',check_out:'2026-10-05'});
  const sent=calls.find(x=>x.path?.endsWith('/change'));
  assert.equal(JSON.parse(sent.request.body).confirmed,true);
  assert.equal(sent.request.headers['Idempotency-Key'],'cash-change:quote-one');
});

test('cancelled date selection does not request new inventory or a payment',async()=>{
  const {api,ctx,calls}=setup(async()=>null);
  assert.equal(await api.change(ctx,order,{}),null);assert.equal(calls.length,0);
});

test('displayed quote hash stays bound across asynchronous source mutation',async()=>{
  const original=quote.quote_hash;
  try{
    const {api,ctx,calls}=setup(async(t,h,l,submit)=>{quote.quote_hash='b'.repeat(64);return submit(accepted)});
    await api.cancel(ctx,order);
    assert.equal(JSON.parse(calls[1].request.body).quote_hash,original);
  }finally{quote.quote_hash=original}
});

test('unknown supplier progress offers query only and binds the saved operation',async()=>{
  const {api,ctx,calls}=setup(async()=>null),button={disabled:false};
  const op={...quote,order_id:order.order_id,operation_id:'operation-one',action:'CHANGE',state:'UNKNOWN_SUPPLIER',reconcile_allowed:true};
  const html=api.progress(op,ctx.money);
  assert.ok(html.includes('正在核实酒店结果'));assert.ok(html.includes('cashReconcile'));assert.ok(!html.includes('cashRetryPayment'));
  ctx.container={querySelector:id=>id==='#cashReconcile'?button:null};api.bind(ctx,op);await button.onclick();
  assert.equal(calls[0].path,'/v1/orders/order-one/cash-after-sales/operation-one/reconcile');
  assert.equal(button.disabled,false);
});

test('cancel confirmed and refund pending remain distinct in the customer progress card',()=>{
  const {api,ctx}=setup(async()=>null);
  const op={...quote,action:'CANCEL',state:'REFUND_PENDING',reconcile_allowed:true,refund:{amount_minor:1520750,status:'PROCESSING'}};
  const html=api.progress(op,ctx.money);
  assert.ok(html.includes('取消已确认，退款处理中'));assert.ok(html.includes('待原路退回'));
  assert.ok(!html.includes('原路退款已完成'));
});
