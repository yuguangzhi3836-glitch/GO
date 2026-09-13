import test from 'node:test';
import assert from 'node:assert/strict';
import {createChangeActions,validateChangeFields} from '../mobile/go-app/src/domain/changeActions.ts';
const input={HOTEL:{new_check_in:'2026-10-01',new_check_out:'2026-10-02'},FLIGHT:{new_departure_date:'2026-10-01'},RAIL:{new_travel_date:'2026-10-01'},ATTRACTION:{new_visit_date:'2026-10-01',new_session_time:'10:00'},RENTAL:{pickup_at:'2026-10-01T10:00:00+08:00',return_at:'2026-10-02T10:00:00+08:00'}};
function fixture(v,options={}){
 let time=Date.parse('2026-09-10T00:00:00Z'),live=true;
 const ref={vertical:v,orderId:'owned31'},calls=[];
 const order={order_id:ref.orderId,vertical:v,status:'CONFIRMED',currency:'CNY',...options.order};
 const terms={HOTEL:{old_value_minor:1000,new_value_minor:1100,fare_difference_minor:100,change_fee_minor:0,amount_due_minor:100,change_policy:'GO_HOTEL_FREE_CHANGE_365D_V1',change_validity_days:365,change_valid_until:'2027-09-12T00:00:00Z',lower_price_no_refund:true,lower_price_difference_minor:0,lower_price_rule:'FORFEIT_NO_REFUND_NO_FUTURE_OFFSET'},FLIGHT:{new_flight_number:'GO720',fare_difference_minor:100,change_fee_minor:20},RAIL:{new_train_no:'G7319',new_seat_class:'SECOND',fare_difference_minor:100,change_fee_minor:20},ATTRACTION:{change_fee_minor:0,total_due_minor:0},RENTAL:{old_amount_minor:240,new_amount_minor:120,daily_rate_minor:120,rental_days:1,change_fee_minor:0,refund_to:'ORIGINAL_PAYMENT_METHOD'}};
 const q={order_id:ref.orderId,quote_id:'q31',change_quote_id:'q31',quote_hash:'a'.repeat(64),currency:'CNY',amount_due_minor:120,total_due_minor:120,difference_minor:-120,expires_at:'2026-09-10T00:10:00Z',...terms[v],...Object.fromEntries(Object.entries(input[v]).map(([k,val])=>[v==='RENTAL'?'new_'+k:k,val])),...options.quote};
 const request=async(path,init={})=>{
  calls.push({path,...init});
  if(path.endsWith('checkout-capabilities'))return {data:{simulation_available:options.simulation!==false,external_live:false}};
  if(path.endsWith('/change-quote')||path.endsWith('/change-quotes'))return {data:q};
  if(init.method==='POST'){if(options.lost)throw Error('NETWORK_LOST');return {data:{status:'PENDING_SUPPLIER'}};}
  return {data:v==='HOTEL'?{order}:order};
 };
 return {ref,calls,q,a:createChangeActions(request,()=>live,()=>time),expire:()=>{time+=600001;},leave:()=>{live=false;}};
}
for(const v of Object.keys(input)){
 test(`${v}: explicit confirmation consumes one quote and reads original order`,async()=>{
  const f=fixture(v);const view=await f.a.quote(f.ref,input[v]);
  view.quote.quote_hash='b'.repeat(64);view.quote.total_due_minor=99999;
  await assert.rejects(f.a.submit(f.ref,input[v],false),/CONFIRMATION/);
  const r=await f.a.submit(f.ref,input[v],true);assert.equal(r.order.order_id,'owned31');assert.equal(r.notice,'CHANGE_SUBMITTED_CHECK_ORDER');
  const posts=f.calls.filter(c=>c.method==='POST');assert.equal(posts.length,2);
  if(v==='HOTEL')assert.deepEqual(JSON.parse(posts[1].body),{change_quote_id:'q31',quote_hash:'a'.repeat(64),confirmed:true});
  if(v==='FLIGHT')assert.deepEqual(JSON.parse(posts[1].body),{quote_hash:'a'.repeat(64),expected_total_due_minor:120,currency:'CNY',confirmed:true});
  if(v==='RENTAL')assert.deepEqual(JSON.parse(posts[1].body),{expected_difference_minor:-120,currency:'CNY',mode:'CONTRACT_SIMULATOR'});
  assert.ok(!f.calls.at(-1).method);await assert.rejects(f.a.submit(f.ref,input[v],true),/FRESH/);
 });
 test(`${v}: expiry, edit and session changes prevent submission`,async()=>{
  for(const action of ['expire','edit','leave']){const f=fixture(v);await f.a.quote(f.ref,input[v]);if(action==='edit')f.a.invalidate();else f[action]();await assert.rejects(f.a.submit(f.ref,input[v],true),/EXPIRED|FRESH|CONTEXT/);assert.equal(f.calls.filter(c=>c.method==='POST').length,1);}
 });
 test(`${v}: wrong identity or unavailable isolated channel cannot execute`,async()=>{
  for(const options of [{quote:{order_id:'other'}},{simulation:false}]){const f=fixture(v,options);await assert.rejects(f.a.quote(f.ref,input[v]),/UNVERIFIED|ISOLATED/);await assert.rejects(f.a.submit(f.ref,input[v],true),/FRESH/);}
 });
 test(`${v}: timeout is unknown and never auto-retried`,async()=>{
  const f=fixture(v,{lost:true});await f.a.quote(f.ref,input[v]);assert.equal((await f.a.submit(f.ref,input[v],true)).notice,'CHANGE_RESULT_UNKNOWN');assert.equal(f.calls.filter(c=>c.method==='POST').length,2);await assert.rejects(f.a.submit(f.ref,input[v],true),/FRESH/);
 });
}
test('invalid replacement quote destroys old consent; dates are canonical',async()=>{
 const f=fixture('HOTEL');await f.a.quote(f.ref,input.HOTEL);await assert.rejects(f.a.quote(f.ref,{new_check_in:'2026-02-30',new_check_out:'2026-03-04'}),/INPUT/);await assert.rejects(f.a.submit(f.ref,input.HOTEL,true),/FRESH/);
 assert.throws(()=>validateChangeFields('RENTAL',{pickup_at:'2026-10-01T10:00:00',return_at:'2026-10-02T10:00:00'}),/INPUT/);
 assert.throws(()=>validateChangeFields('RIDE',{}),/NOT_SUPPORTED/);
});
test('double submit makes only one mutation',async()=>{
 const f=fixture('RAIL');await f.a.quote(f.ref,input.RAIL);const r=await Promise.allSettled([f.a.submit(f.ref,input.RAIL,true),f.a.submit(f.ref,input.RAIL,true)]);assert.equal(r.filter(x=>x.status==='fulfilled').length,1);assert.equal(f.calls.filter(c=>c.method==='POST').length,2);
});

test('multi-leg flight requires selection and binds the selected leg',async()=>{
 const options={order:{itinerary:[{departure_date:'2026-09-20'},{departure_date:'2026-10-03'}]}};
 const missing=fixture('FLIGHT',options);
 await assert.rejects(missing.a.quote(missing.ref,input.FLIGHT),/INPUT/);
 assert.equal(missing.calls.filter(x=>x.method==='POST').length,0);
 const fields={...input.FLIGHT,leg_index:'1'};
 const wrong=fixture('FLIGHT',{...options,quote:{leg_index:0}});
 await assert.rejects(wrong.a.quote(wrong.ref,fields),/UNVERIFIED/);
 const ok=fixture('FLIGHT',{...options,quote:{leg_index:1}});
 await ok.a.quote(ok.ref,fields);await ok.a.submit(ok.ref,fields,true);
 assert.equal(JSON.parse(ok.calls.find(x=>x.method==='POST').body).leg_index,1);
 assert.equal(ok.calls.filter(x=>x.method==='POST').length,2);
});
