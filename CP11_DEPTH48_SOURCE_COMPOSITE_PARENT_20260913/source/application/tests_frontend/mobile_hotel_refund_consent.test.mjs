import test from 'node:test';
import assert from 'node:assert/strict';
import {createOrderActions,orderRef} from '../mobile/go-app/src/domain/orderActions.ts';

function fixture({reject=false}={}) {
  const calls=[];let quoted=0;
  const order={order_id:'hotel34',status:'CONFIRMED',total_amount_minor:12000,currency:'CNY'};
  const request=async(path,init={})=>{
    calls.push({path,...init});
    if(path.endsWith('/cancellation-quotes/cq1'))return {data:{order_id:order.order_id,quote_id:'cq1',quote_hash:'1'.repeat(64),refund_amount_minor:11000,cancellation_fee_minor:1000,currency:'CNY',expires_at:'2099-01-01T00:00:00Z'}};
    if(path.endsWith('/cancellation-quote')){
      quoted++;
      return {data:{order_id:order.order_id,quote_id:'cq'+quoted,quote_hash:String(quoted).repeat(64),
        refund_amount_minor:11000,cancellation_fee_minor:1000,currency:'CNY',expires_at:'2099-01-01T00:00:00Z'}};
    }
    if(path.endsWith('/cancel')){
      if(reject)throw Object.assign(Error('CASH_FARE_QUOTE_STALE'),{status:409});
      order.status='CANCEL_PENDING';return {data:{state:'READY'}};
    }
    return {data:{order}};
  };
  return {request,calls};
}
test('hotel cancellation sends the displayed quote identity without silently creating another quote',async()=>{
  const f=fixture(),a=createOrderActions(f.request),ref=orderRef('HOTEL','hotel34');
  const accepted=(await a.refundQuote(ref)).quote;
  const result=await a.refund(ref,accepted);
  assert.equal(f.calls.filter(x=>x.path.endsWith('/cancellation-quote')).length,1);
  assert.deepEqual(JSON.parse(f.calls.find(x=>x.path.endsWith('/cancel')).body),{
    cancellation_quote_id:'cq1',quote_hash:'1'.repeat(64),confirmed:true});
  assert.equal(result.order.status,'CANCEL_PENDING');
});
test('hotel server rejects a stale accepted quote without replacing it or retrying cancellation',async()=>{
  const f=fixture({reject:true}),a=createOrderActions(f.request),ref=orderRef('HOTEL','hotel34');
  const accepted=(await a.refundQuote(ref)).quote;
  await assert.rejects(a.refund(ref,accepted),/CASH_FARE_QUOTE_STALE/);
  assert.equal(f.calls.filter(x=>x.path.endsWith('/cancel')).length,1);
  assert.equal(f.calls.filter(x=>x.path.endsWith('/cancellation-quote')).length,1);
});
test('hotel malformed, expired or foreign accepted quote cannot send cancellation',async()=>{
  for(const patch of [{quote_hash:'bad'},{quote_id:''},{order_id:'other'},{expires_at:'2000-01-01T00:00:00Z'},{refund_amount_minor:-1}]){
    const f=fixture(),a=createOrderActions(f.request),ref=orderRef('HOTEL','hotel34');
    const q=(await a.refundQuote(ref)).quote;
    await assert.rejects(a.refund(ref,{...q,...patch}),/QUOTE|IDENTITY/);
    assert.equal(f.calls.filter(x=>x.path.endsWith('/cancel')).length,0);
  }
});
