import test from 'node:test';
import assert from 'node:assert/strict';
import {createOrderActions,orderRef,readOrder,detailTarget} from '../mobile/go-app/src/domain/orderActions.ts';
import {bookingIntent} from '../mobile/go-app/src/domain/bookingIntent.ts';
import {requestFingerprint} from '../mobile/go-app/src/domain/requestFingerprint.ts';
import {createHash} from 'node:crypto';
const verticals=['HOTEL','FLIGHT','RAIL','RENTAL','RIDE','ATTRACTION'];
function fixture(v,{lost=false,simulation=true,amount=10000,fee=0}={}){
 let order={order_id:'owned30',vertical:v,status:'PAYMENT_PENDING',total_amount_minor:amount,currency:'CNY'};const calls=[];
 const request=async(path,init={})=>{calls.push({path,...init});
   if(path.endsWith('checkout-capabilities'))return {data:{simulation_available:simulation,external_live:false}};
   if(path.includes('/checkout/')){order={...order,status:v==='FLIGHT'||v==='RAIL'?'TICKETED':'CONFIRMED'};if(lost)throw Object.assign(Error('lost'),{uncertain:true});return {data:{...order,external_live:false}};}
   if(path.endsWith('refund-quote')||path.endsWith('cancellation-quote'))return {data:{order_id:order.order_id,refund_amount_minor:amount-fee,currency:'CNY',...(v==='HOTEL'?{cancellation_fee_minor:fee,quote_hash:'a'.repeat(64),quote_id:'quote30'}:['RIDE','RENTAL'].includes(v)?{fee_minor:fee}:{refund_fee_minor:fee})}};
   if(path.endsWith('/refund')||path.endsWith('/cancel')){order={...order,status:'REFUND_PENDING'};return {data:{status:'PROCESSING'}};}
   return {data:v==='HOTEL'?{order}:order};};
 return {request,calls,set:(x)=>{order={...order,...x};},get:()=>order};}
for(const v of verticals){
 test(`${v}: payment binds fresh amount and re-reads the same order after lost response`,async()=>{
   const f=fixture(v,{lost:true}),ref=orderRef(v,'owned30'),a=createOrderActions(f.request);
   const result=await a.pay(ref,f.get());assert.equal(result.order.order_id,'owned30');assert.equal(result.notice,'PAYMENT_RESULT_UNKNOWN');assert.ok(['CONFIRMED','TICKETED'].includes(result.order.status));
   const posts=f.calls.filter(x=>x.path.includes('/checkout/'));assert.equal(posts.length,1);assert.deepEqual(JSON.parse(posts[0].body),{mode:'CONTRACT_SIMULATOR',expected_amount_minor:10000,currency:'CNY'});assert.match(f.calls.at(-1).path,/owned30/);assert.ok(!f.calls.at(-1).method);
 });
 test(`${v}: changed amount and unavailable channel cannot execute payment`,async()=>{
   for(const options of [{amount:10001},{simulation:false}]){const f=fixture(v,options);await assert.rejects(createOrderActions(f.request).pay(orderRef(v,'owned30'),{...f.get(),total_amount_minor:10000}),/CHANGED|NOT_READY/);assert.equal(f.calls.filter(x=>x.method==='POST').length,0);}
 });
 test(`${v}: refund confirms quoted amount, submits once and does not invent refunded state`,async()=>{
   const f=fixture(v);f.set({status:v==='FLIGHT'||v==='RAIL'?'TICKETED':'CONFIRMED'});const ref=orderRef(v,'owned30'),a=createOrderActions(f.request),quote=(await a.refundQuote(ref)).quote;
   const result=await a.refund(ref,quote);assert.equal(result.order.status,'REFUND_PENDING');assert.equal(result.notice,'REFUND_SUBMITTED_CHECK_ORDER');
   const posted=f.calls.filter(x=>x.path.endsWith('/cancel')||x.path.endsWith('/refund'));assert.equal(posted.length,1);assert.match(posted[0].path,/owned30/);
   if(v==='HOTEL')assert.deepEqual(JSON.parse(posted[0].body),{cancellation_quote_id:'quote30',quote_hash:'a'.repeat(64),confirmed:true});
 });
 test(`${v}: changed refund terms need reconfirmation before any cancellation`,async()=>{
   const f=fixture(v,{fee:500});f.set({status:'CONFIRMED'});const ref=orderRef(v,'owned30'),a=createOrderActions(f.request),q=(await a.refundQuote(ref)).quote;
   await assert.rejects(a.refund(ref,{...q,refund_amount_minor:q.refund_amount_minor+1}),/RECONFIRM/);assert.equal(f.calls.filter(x=>x.path.endsWith('/cancel')||x.path.endsWith('/refund')).length,0);
 });
}
test('identity substitution and concurrent payment submission are blocked',async()=>{
 const f=fixture('RAIL'),a=createOrderActions(f.request),ref=orderRef('RAIL','owned30');await assert.rejects(a.pay(ref,{...f.get(),order_id:'other'}),/IDENTITY/);
 const results=await Promise.allSettled([a.pay(ref,f.get()),a.pay(ref,f.get())]);assert.equal(results.filter(x=>x.status==='fulfilled').length,1);assert.equal(f.calls.filter(x=>x.path.includes('/checkout/')).length,1);
 await assert.rejects(readOrder(ref,async()=>({data:{order_id:'other'}})),/IDENTITY/);
 assert.throws(()=>detailTarget({vertical:'__proto__',orderId:'owned30'}),/REFERENCE/);
});
test('screen/session change prevents a mutation after read-only preflight',async()=>{
 const f=fixture('FLIGHT');let current=true;const request=async(...x)=>{const r=await f.request(...x);current=false;return r;};
 await assert.rejects(createOrderActions(request,()=>current).pay(orderRef('FLIGHT','owned30'),f.get()),/SESSION_OR_SCREEN/);assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});
test('all six booking intents use explicit vault identities with stable keys and no fabricated people',()=>{
 const base={prebook:{prebook_id:'pb30',currency:'CNY',quantity:1,fare_rule:{offer_rule_hash:'a'.repeat(64)}},offer:{offer_id:'offer30',visit_date:'2026-10-20',currency:'CNY'},quantity:1,search:{pickup:'A',dropoff:'B',pickup_location:'A',return_location:'B',pickup_at:'2026-10-20T10:00:00',return_at:'2026-10-21T10:00:00'}};
 for(const v of verticals){const first=bookingIntent(v,base,'owner30',['traveler30'],true,true),retry=bookingIntent(v,base,'owner30',['traveler30'],true,true);assert.deepEqual(first,retry);
   const b=JSON.parse(first.init.body);assert.equal(v==='HOTEL'?b.traveler_id:b.traveler_ids[0],'traveler30');assert.ok(!b.passengers&&!b.attendees&&!b.drivers&&!b.flight_tracking_enabled);assert.throws(()=>bookingIntent(v,base,'owner30',['traveler30'],false),/CONSENT/);
   assert.notEqual(first.init.headers['Idempotency-Key'],bookingIntent(v,base,'other30',['traveler30'],true,true).init.headers['Idempotency-Key']);}
 assert.throws(()=>bookingIntent('HOTEL',base,'owner30',['traveler30'],true,false),/FARE_CONSENT/);
 assert.throws(()=>bookingIntent('ATTRACTION',{...base,quantity:2},'owner30',['traveler30'],true),/MISMATCH/);
 const one=bookingIntent('RIDE',base,'owner30',['traveler30'],true);
 const two=bookingIntent('RIDE',{...base,search:{...base.search,pickup_at:'2026-10-22T10:00:00'}},'owner30',['traveler30'],true);
 assert.notEqual(one.init.headers['Idempotency-Key'],two.init.headers['Idempotency-Key']);
});
test('portable request fingerprint matches standard SHA-256 for Unicode and block boundaries',()=>{
 for(const text of ['', 'abc','香港 · 出行人 🚗', 'x'.repeat(55),'x'.repeat(56),'x'.repeat(64),'z'.repeat(1025)])assert.equal(requestFingerprint(text),createHash('sha256').update(text).digest('hex'));
});
