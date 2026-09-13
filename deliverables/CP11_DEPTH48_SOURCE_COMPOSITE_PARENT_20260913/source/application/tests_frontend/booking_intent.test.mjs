import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const script=fs.readFileSync('frontend/consumer/booking-travelers.js','utf8');
function setup(){
 const calls=[];let currentDialog;
 const document={activeElement:{focus(){}},body:{append(d){currentDialog=d}},createElement(){const nodes=new Map();const listeners={};return {className:'',innerHTML:'',setAttribute(){},showModal(){},close(){},remove(){},addEventListener(type,fn){listeners[type]=fn},querySelector(selector){if(!nodes.has(selector))nodes.set(selector,{value:'',checked:false,disabled:false,textContent:'',focus(){}});return nodes.get(selector)},querySelectorAll(){return this.selectedTravelers||[]},cancel(){listeners.cancel({preventDefault(){}})}}}};
 const noop=()=>{};const context={document,window:{},state:{me:{display_name:'NOT A TRAVELER'}},crypto:{randomUUID:()=>`key-${calls.length}`},setTimeout,clearTimeout,Date,Blob,URL,toast:noop,$:noop,setVerticalVIMode:noop,bindNav:noop,shell:noop,money:v=>`CNY ${v/100}`,
 api:async(path,opts)=>{calls.push({path,opts});if(path==='/v1/consumer/profile/vault')return {travelers:[{traveler_id:'trav-1',full_name:'REAL TRAVELER',relationship_type:'SELF',facts:[{field_type:'DRIVER_LICENSE_NUMBER',sensitive:true}]}]};if(path==='/v1/consumer/checkout-capabilities')return {simulation_available:true};return {status:'OK'}}};
 for(const name of ['renderPay','renderFlightOrder','renderRailOrder','renderMobilityOrder','renderAttractionOrder','createOrder','createFlightOrderAndCheckout','railSelect','mobilityBook','attractionBook','showAccount','showHome','showAuth','showTrip','attractionReload','mobilityReload'])context[name]=noop;
 vm.runInNewContext(script,context);
 return {context,calls,dialog:()=>currentDialog,booking:context.window.GOBooking};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('HTTP helper retains CSRF together with idempotency header',async()=>{
 const full=fs.readFileSync('frontend/consumer/app.js','utf8');const source=full.slice(full.indexOf('let consumerRefreshPending'),full.indexOf('\nfunction toast('));let options;
 const ctx={cookie:()=>encodeURIComponent('csrf-token'),fetch:async(path,opts)=>{options=opts;return {ok:true,json:async()=>({data:{ok:true}})}}};
 vm.runInNewContext(source,ctx);await ctx.api('/action',{method:'POST',headers:{'Idempotency-Key':'one-order'}});
 assert.equal(options.headers['X-CSRF-Token'],'csrf-token');assert.equal(options.headers['Idempotency-Key'],'one-order');assert.equal(options.credentials,'same-origin');
});
test('Escape cancels traveler selection without authorizing or creating an order',async()=>{
 const s=setup();const pending=s.booking.traveler('RENTAL');await tick();s.dialog().cancel();assert.equal(await pending,null);assert.deepEqual(s.calls.map(x=>x.path),['/v1/consumer/profile/vault']);
});
test('rental consent is bound to the selected traveler, field and purpose',async()=>{
 const s=setup();const pending=s.booking.traveler('RENTAL');await tick();const d=s.dialog();d.querySelector('[data-consent]').checked=true;d.querySelector('#goTraveler').value='trav-1';await d.querySelector('form').onsubmit({preventDefault(){}});
 assert.equal(await pending,'trav-1');const consent=JSON.parse(s.calls[1].opts.body);assert.equal(consent.traveler_id,'trav-1');assert.equal(consent.purpose,'RENTAL_BOOKING');assert.deepEqual(consent.scope,['DRIVER_LICENSE_NUMBER']);assert.ok(new Date(consent.expires_at).getTime()<=Date.now()+15*60000);assert.equal(s.calls.length,2);
});
test('payment is cancelled without any checkout mutation',async()=>{
 const s=setup();const pending=s.booking.pay('FLIGHT',{order_id:'order-1',total_amount_minor:42000,currency:'CNY'});await tick();s.dialog().querySelector('[data-cancel]').onclick();assert.equal(await pending,null);assert.deepEqual(s.calls.map(x=>x.path),['/v1/consumer/checkout-capabilities']);
});
test('a failed confirmed payment stays visible and can be retried',async()=>{
 const s=setup();const pending=s.booking.pay('RAIL',{order_id:'rail-1',total_amount_minor:9000,currency:'CNY'});await tick();const d=s.dialog();d.querySelector('[data-consent]').checked=true;s.context.api=async()=>{throw Error('connection lost')};await d.querySelector('form').onsubmit({preventDefault(){}});assert.equal(d.querySelector('[role=alert]').textContent,'connection lost');assert.equal(d.querySelector('[type=submit]').disabled,false);d.cancel();assert.equal(await pending,null);
});

function partySetup(){
 const s=setup();s.context.api=async(path,opts)=>{s.calls.push({path,opts});return {travelers:[{traveler_id:'person-a',full_name:'ADULT A',relationship_type:'SELF',booking_permission:true,facts:[]},{traveler_id:'person-b',full_name:'ADULT B',relationship_type:'FAMILY',booking_permission:true,facts:[]}]}};return s;
}
test('cancelling a party selection creates no order or grant',async()=>{
 const s=partySetup();const pending=s.booking.travelers('FLIGHT',2);await tick();s.dialog().cancel();assert.equal(await pending,null);assert.equal(s.calls.length,1);assert.equal(s.calls[0].path,'/v1/consumer/profile/vault');
});
test('a party must contain the exact number of different travelers',async()=>{
 const s=partySetup();const pending=s.booking.travelers('FLIGHT',2);await tick();const d=s.dialog();d.querySelector('[data-consent]').checked=true;d.selectedTravelers=[{value:'person-a'},{value:'person-a'}];await d.querySelector('form').onsubmit({preventDefault(){}});assert.match(d.querySelector('[role=alert]').textContent,/不同/);assert.equal(s.calls.length,1);d.cancel();assert.equal(await pending,null);
});
test('party confirmation returns only the explicitly selected traveler references',async()=>{
 const s=partySetup();const pending=s.booking.travelers('FLIGHT',2);await tick();const d=s.dialog();d.querySelector('[data-consent]').checked=true;d.selectedTravelers=[{value:'person-b'},{value:'person-a'}];await d.querySelector('form').onsubmit({preventDefault(){}});assert.deepEqual(Array.from(await pending),['person-b','person-a']);assert.equal(s.calls.length,1);
});
test('party selection cannot submit without confirming adult travelers and purpose',async()=>{
 const s=partySetup();const pending=s.booking.travelers('FLIGHT',2);await tick();const d=s.dialog();d.selectedTravelers=[{value:'person-a'},{value:'person-b'}];await d.querySelector('form').onsubmit({preventDefault(){}});assert.match(d.querySelector('[role=alert]').textContent,/用途/);assert.equal(s.calls.length,1);d.cancel();assert.equal(await pending,null);
});
