import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const order={order_id:'flight48',currency:'CNY',itinerary:[
 {origin:'SHA',destination:'PEK',departure_date:'2099-10-01'},
 {origin:'PEK',destination:'SHA',departure_date:'2099-10-10'}]};
function fixture(options={}){
 const calls=[],dialogs=[],errors=[];let reloads=0;
 const q={order_id:order.order_id,quote_id:'q48',quote_hash:'a'.repeat(64),currency:'CNY',
  total_due_minor:80000,fare_difference_minor:60000,change_fee_minor:20000,expires_at:'2099-09-01T00:00:00Z',
  changes:[{leg_index:1,new_departure_date:'2099-10-12'}],...options.quote};
 const ctx={Intl,Date,toast:x=>errors.push(x),document:{querySelectorAll:()=>[
  {value:'2099-10-01'},{value:'2099-10-12'}]},window:{GOBooking:{dialog:async(...args)=>{
   dialogs.push(args);if(options.cancel===dialogs.length)return null;return args[3]();
  }}}};
 vm.runInNewContext(fs.readFileSync('frontend/consumer/flight-changes.js','utf8'),ctx);
 const request=async(path,init)=>{calls.push({path,...init});if(path.endsWith('/change-quote'))return q;
  if(options.lost)throw Error('NETWORK_LOST');return {status:'PENDING_SUPPLIER'};};
 return {ui:ctx.window.GOFlightChanges,calls,dialogs,errors,get reloads(){return reloads},
  run:()=>ctx.window.GOFlightChanges.open(order,request,async()=>{reloads++})};
}
test('selected return leg has separate quote and exact confirmation, then reloads original order',async()=>{
 const f=fixture();await f.run();assert.equal(f.dialogs.length,2);assert.equal(f.errors.length,0);
 assert.deepEqual(JSON.parse(f.calls[0].body),{changes:[{leg_index:1,new_departure_date:'2099-10-12'}]});
 assert.deepEqual(JSON.parse(f.calls[1].body),{quote_hash:'a'.repeat(64),expected_total_due_minor:80000,currency:'CNY',confirmed:true});
 assert.equal(f.calls[1].headers['Idempotency-Key'],'flight-change:flight48:q48');assert.equal(f.reloads,1);
});
for(const cancel of [1,2])test(`closing dialog ${cancel} never executes a change`,async()=>{
 const f=fixture({cancel});await f.run();assert.equal(f.calls.length,cancel-1);assert.equal(f.reloads,0);
});
for(const quote of [{order_id:'other'},{changes:[{leg_index:0,new_departure_date:'2099-10-12'}]},
 {quote_hash:'bad'},{total_due_minor:1.5},{currency:'USD'}])test('mismatched or invalid quote cannot execute '+JSON.stringify(quote),async()=>{
 const f=fixture({quote});await f.run();assert.equal(f.calls.length,1);assert.equal(f.errors.length,1);
});
test('unknown result reloads and does not repeat the financial request',async()=>{
 const f=fixture({lost:true});await f.run();assert.equal(f.calls.length,2);assert.equal(f.reloads,1);
 await assert.rejects(f.dialogs[1][3](),/已提交/);assert.equal(f.calls.length,2);
});
test('no date changes cannot request a quote',()=>{
 const f=fixture();assert.throws(()=>f.ui.selection(order,order.itinerary.map(x=>x.departure_date)),/至少/);
});
