import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
function setup(){
 let dialog,removed=false,complete=0;const calls=[];
 const document={createElement(){const nodes=new Map();return {innerHTML:'',setAttribute(){},showModal(){},close(){},remove(){removed=true},querySelector(k){if(!nodes.has(k))nodes.set(k,{disabled:false,checked:false,textContent:'',value:''});return nodes.get(k)}}},body:{append(d){dialog=d}}};
 const ctx={window:{GODirectFare:{rulesSummary:r=>'LOCKED_RULE_'+r?.rule_hash}},Intl,Date,document};vm.runInNewContext(fs.readFileSync('frontend/consumer/direct-credit.js','utf8'),ctx);
 const q={quote_id:'hfq_credit',currency:'CNY',funding_capture_minor:162000,retained_value_minor:162000,cancellation_fee_minor:0,cash_refund_minor:0,credit_expires_at:'2099-02-01T00:00:00Z',expires_at:'2099-01-01T00:10:00Z',check_in:'2099-01-02',check_out:'2099-01-04',adults:1,children:0,new_amount_minor:80000,applied_credit_minor:80000,forfeited_difference_minor:82000,amount_due_minor:0,remaining_credit_minor:0,fare_rule:{rule_hash:'current-rule'}};
 const s={ui:ctx.window.GODirectCredit,q,calls,get dialog(){return dialog},get removed(){return removed},get complete(){return complete},done:async()=>complete++};
 s.api=async(...args)=>{calls.push(args);return args[0].endsWith('/consents')?{consent_id:'current-consent'}:args[0].endsWith('/vault')?{travelers:[{traveler_id:'current-person',full_name:'ACTUAL PERSON'}]}:q};return s;
}
const r={hosted_reservation_id:'original',check_in:'2099-01-02',check_out:'2099-01-04'},c={credit_id:'credit'},rate={hosted_offer_id:'offer',room_name:'ROOM',fare_rule:{rule_hash:'stale-rule'}},criteria={check_in:'2099-01-02',check_out:'2099-01-04',adults:1,children:0};
const submit=d=>d.querySelector('form').onsubmit({preventDefault(){}});
test('conversion clearly shows capture and value and closing does not convert',async()=>{
 const s=setup();await s.ui.convert(r,(...a)=>s.api(...a),s.done);
 for(const label of ['从冻结授权中扣取','1,620.00','现金退款','不可跨酒店','到期日不延长'])assert.ok(s.dialog.innerHTML.includes(label));
 await submit(s.dialog);assert.equal(s.calls.length,1);s.dialog.querySelector('[data-close]').onclick();assert.equal(s.calls.length,1);assert.ok(s.removed);
});
test('conversion retry keeps original quote, amount and original expiry',async()=>{
 const s=setup();await s.ui.convert(r,(...a)=>s.api(...a),s.done);s.dialog.querySelector('[data-consent]').checked=true;
 let attempts=0;s.api=async(...args)=>{s.calls.push(args);if(++attempts===1)throw Error('断开连接');return {}};
 await submit(s.dialog);assert.equal(s.removed,false);await submit(s.dialog);assert.deepEqual(s.calls[1],s.calls[2]);
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[1][1])),{quote_id:'hfq_credit',expected_value_minor:162000,currency:'CNY'});assert.equal(s.complete,1);
});
test('redemption uses server quote policy and displays forfeiture before consent',async()=>{
 const s=setup();await s.ui.redeem(c,rate,criteria,(...a)=>s.api(...a),s.done);
 for(const label of ['低价差额作废','820.00','兑换后剩余额度','LOCKED_RULE_current-rule','请重新选择'])assert.ok(s.dialog.innerHTML.includes(label));
 assert.ok(!s.dialog.innerHTML.includes('LOCKED_RULE_stale-rule'));await submit(s.dialog);assert.equal(s.calls.length,2);
 s.dialog.oncancel({preventDefault(){}});assert.equal(s.calls.length,2);assert.ok(s.removed);
});
test('redemption confirms a fresh traveler and only releases hotel fields',async()=>{
 const s=setup();await s.ui.redeem(c,rate,criteria,(...a)=>s.api(...a),s.done);s.dialog.querySelector('[data-consent]').checked=true;
 await submit(s.dialog);assert.equal(s.calls.length,2);assert.match(s.dialog.querySelector('[role=alert]').textContent,/实际入住人/);
 s.dialog.querySelector('#creditTraveler').value='current-person';await submit(s.dialog);
 const consent=s.calls[2][1];assert.equal(consent.traveler_id,'current-person');assert.equal(consent.purpose,'HOTEL_BOOKING');assert.deepEqual(Array.from(consent.scope),['LEGAL_NAME','MOBILE']);
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[3][1])),{quote_id:'hfq_credit',expected_due_minor:0,currency:'CNY',traveler_id:'current-person',consent_id:'current-consent'});assert.equal(s.complete,1);
});
test('double click and Escape cannot duplicate or dismiss pending redemption',async()=>{
 const s=setup();await s.ui.redeem(c,rate,criteria,(...a)=>s.api(...a),s.done);s.dialog.querySelector('[data-consent]').checked=true;s.dialog.querySelector('#creditTraveler').value='current-person';
 let finish;s.api=(...args)=>{s.calls.push(args);return new Promise(resolve=>finish=resolve)};
 const pending=submit(s.dialog);await submit(s.dialog);s.dialog.oncancel({preventDefault(){}});assert.equal(s.removed,false);assert.equal(s.calls.length,3);
 finish({});await new Promise(resolve=>setImmediate(resolve));assert.equal(s.calls.length,4);finish({});await pending;assert.equal(s.complete,1);
});
test('credit list filters property and disables frozen, expired or reconciliation credits',()=>{
 const s=setup(),base={credit_id:'one',hotel_slug:'hotel',hotel_name:'<img src=x>',original_reservation_id:'original',state:'ACTIVE',available_minor:1000,can_redeem:true,expires_at:'2099-01-01T00:00:00Z'};
 const html=s.ui.list([base,{...base,credit_id:'frozen',state:'FROZEN_REFUND',can_redeem:false},{...base,credit_id:'foreign',hotel_slug:'other'}],'hotel');
 assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));assert.ok(html.includes('value="one"'));assert.ok(!html.includes('value="frozen"'));assert.ok(!html.includes('foreign'));assert.ok(html.includes('暂停兑换'));
});
