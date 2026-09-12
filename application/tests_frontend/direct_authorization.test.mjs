import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('frontend/consumer/direct.js','utf8');
const fn=source.slice(source.indexOf('  async function authorizeReservation('),source.indexOf('  async function showReservation('));
function setup(){
 let dialog,removed=false;const calls=[];
 const document={createElement(){const nodes=new Map();return {className:'',innerHTML:'',showModal(){},close(){},remove(){removed=true},querySelector(key){if(!nodes.has(key))nodes.set(key,{disabled:false,checked:false,textContent:''});return nodes.get(key)}}},body:{append(d){dialog=d}}};
 const ctx={document,esc:v=>String(v),money:(n,c)=>`${c} ${n/100}`,api:async(path,body)=>{calls.push({path,body});return{}},showReservation:async()=>{}};
 vm.runInNewContext(fn,ctx);return {ctx,calls,get dialog(){return dialog},get removed(){return removed}};
}
const order={hosted_reservation_id:'official-reservation-1',amount_minor:162000,currency:'CNY',check_in:'2026-10-01',check_out:'2026-10-03'};
test('closing hotel authorization leaves funds untouched',async()=>{
 const s=setup();await s.ctx.authorizeReservation(order);s.dialog.querySelector('[data-close]').onclick();assert.equal(s.calls.length,0);assert.equal(s.removed,true);
});
test('hotel checkout requires confirmation and binds the complete stay amount',async()=>{
 const s=setup();await s.ctx.authorizeReservation(order);const submit=s.dialog.querySelector('form').onsubmit;
 await submit({preventDefault(){}});assert.equal(s.calls.length,0);
 s.dialog.querySelector('[data-consent]').checked=true;await submit({preventDefault(){}});
 assert.equal(s.calls[0].path,'/v1/direct/reservations/official-reservation-1/checkout');
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].body)),{mode:'CONTRACT_SIMULATOR',expected_amount_minor:162000,currency:'CNY'});
});
test('a second click cannot create another hotel authorization while the first is pending',async()=>{
 const s=setup();let finish;s.ctx.api=(path,body)=>{s.calls.push({path,body});return new Promise(r=>{finish=r})};
 await s.ctx.authorizeReservation(order);s.dialog.querySelector('[data-consent]').checked=true;
 const submit=s.dialog.querySelector('form').onsubmit,pending=submit({preventDefault(){}});
 await submit({preventDefault(){}});s.dialog.querySelector('[data-close]').onclick();
 assert.equal(s.calls.length,1);assert.equal(s.removed,false);finish({});await pending;assert.equal(s.removed,true);
});
test('a failed hotel authorization remains visible and can be retried',async()=>{
 const s=setup();await s.ctx.authorizeReservation(order);s.ctx.api=async()=>{throw Error('授权连接中断')};
 s.dialog.querySelector('[data-consent]').checked=true;await s.dialog.querySelector('form').onsubmit({preventDefault(){}});
 assert.equal(s.dialog.querySelector('[role=alert]').textContent,'授权连接中断');assert.equal(s.dialog.querySelector('[type=submit]').disabled,false);assert.equal(s.removed,false);
});
