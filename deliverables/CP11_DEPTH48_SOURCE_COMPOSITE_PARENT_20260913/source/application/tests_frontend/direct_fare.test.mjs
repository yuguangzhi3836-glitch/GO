import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function setup(){
 let dialog,removed=false,complete=0;const calls=[];
 const document={createElement(){const nodes=new Map();return {className:'',innerHTML:'',setAttribute(){},showModal(){},close(){},remove(){removed=true},querySelector(k){if(!nodes.has(k))nodes.set(k,{disabled:false,checked:false,textContent:''});return nodes.get(k)}}},body:{append(d){dialog=d}}};
 const ctx={window:{},Intl,Date,document};vm.runInNewContext(fs.readFileSync('frontend/consumer/direct-fare.js','utf8'),ctx);
 const q={quote_id:'hfq_1',fee_minor:81001,currency:'CNY',authorization_release_minor:80999,cash_refund_minor:0,expires_at:'2099-01-01T00:10:00Z'};
 const s={ui:ctx.window.GODirectFare,calls,q,get dialog(){return dialog},get removed(){return removed},get complete(){return complete},onComplete:async()=>{complete++}};
 s.api=async(...args)=>{calls.push(args);return q};return s;
}
const r={hosted_reservation_id:'hdr_test',check_in:'2099-01-02',check_out:'2099-01-04'};
test('a cancellation quote never cancels a booking and closing preserves it',async()=>{
 const s=setup();await s.ui.cancel(r,(...a)=>s.api(...a),s.onComplete);
 assert.equal(s.calls.length,1);assert.ok(s.calls[0][0].endsWith('/cancellation-quote'));
 s.dialog.querySelector('[data-close]').onclick();assert.equal(s.calls.length,1);assert.ok(s.removed);
});
test('fee consent binds the server quote and keeps frozen release separate from cash refund',async()=>{
 const s=setup();await s.ui.cancel(r,(...a)=>s.api(...a),s.onComplete);
 const submit=s.dialog.querySelector('form').onsubmit;await submit({preventDefault(){}});assert.equal(s.calls.length,1);
 for(const text of ['810.01','809.99','现金退款','释放冻结额度','不发生真实扣款'])assert.ok(s.dialog.innerHTML.includes(text));
 s.dialog.querySelector('[data-consent]').checked=true;await submit({preventDefault(){}});
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[1][1])),{quote_id:'hfq_1',expected_fee_minor:81001,currency:'CNY'});
 assert.equal(s.complete,1);
});
test('interrupted cancellation retry uses exactly the same quote and fee',async()=>{
 const s=setup();await s.ui.cancel(r,(...a)=>s.api(...a),s.onComplete);s.dialog.querySelector('[data-consent]').checked=true;
 let attempts=0;s.api=async(...args)=>{s.calls.push(args);if(++attempts===1)throw Error('连接中断');return {}};
 const submit=s.dialog.querySelector('form').onsubmit;await submit({preventDefault(){}});assert.equal(s.removed,false);
 assert.equal(s.dialog.querySelector('[role=alert]').textContent,'连接中断');await submit({preventDefault(){}});
 assert.deepEqual(s.calls[1],s.calls[2]);assert.equal(s.complete,1);
});
test('double clicks cannot settle twice while a cancellation is pending',async()=>{
 const s=setup();await s.ui.cancel(r,(...a)=>s.api(...a),s.onComplete);s.dialog.querySelector('[data-consent]').checked=true;
 let finish;s.api=(...args)=>{s.calls.push(args);return new Promise(resolve=>finish=resolve)};
 const submit=s.dialog.querySelector('form').onsubmit,pending=submit({preventDefault(){}});await submit({preventDefault(){}});
 s.dialog.querySelector('[data-close]').onclick();assert.equal(s.removed,false);assert.equal(s.calls.length,2);finish({});await pending;
 assert.equal(s.complete,1);
});
test('unavailable fare actions have no executable buttons and rule text is escaped',()=>{
 const s=setup(),rules={fare_family:'<img src=x onerror=alert(1)>',timezone:'Asia/Shanghai',check_in_hour:14,cooling_off_minutes:30,cancellation_tiers:[{min_hours:24,fee_basis_points:0}],no_show_grace_hours:10,no_show_fee_basis_points:8000,change_allowed:true,change_fee_minor:0,stay_credit_enabled:true,stay_credit_days:365};
 const html=s.ui.options({configured:true,rules,options:[{action:'CANCEL_FOR_REFUND',available:true},{action:'CHANGE_DATE',available:false},{action:'CONVERT_TO_CREDIT',available:false},{action:'KEEP_BOOKING',available:true}]});
 assert.ok(html.includes('&lt;img'));assert.equal(html.includes('<img'),false);
 assert.equal((html.match(/<button/g)||[]).length,1);assert.ok(html.includes('改期 · 暂不可用'));assert.ok(html.includes('住宿额度 · 暂不可用'));
});

test('date changes quote first and require fresh consent after editing dates',async()=>{
 const s=setup();const q={...s.q,new_amount_minor:201000,additional_amount_minor:39000,fare_difference_minor:38000,change_fee_minor:1000,authorization_replacement_minor:201000,old_authorization_release_minor:162000,nights:[{stay_date:'2099-01-03',price_minor:100000}]};
 s.api=async(...args)=>{s.calls.push(args);return q};await s.ui.change(r,'CHANGE_DATE',(...a)=>s.api(...a),s.onComplete);
 s.dialog.querySelector('[name=check_in]').value='2099-01-03';s.dialog.querySelector('[name=check_out]').value='2099-01-05';
 const submit=s.dialog.querySelector('form').onsubmit;await submit({preventDefault(){}});
 assert.equal(s.calls.length,1);assert.ok(s.calls[0][0].endsWith('/change-quote'));
 await submit({preventDefault(){}});assert.equal(s.calls.length,1);
 s.dialog.querySelector('[data-consent]').checked=true;s.dialog.querySelector('[name=check_in]').onchange();
 assert.equal(s.dialog.querySelector('[data-consent]').checked,false);await submit({preventDefault(){}});
 assert.equal(s.calls.length,2);assert.ok(s.calls[1][0].endsWith('/change-quote'));
 s.dialog.querySelector('[data-consent]').checked=true;await submit({preventDefault(){}});
 assert.ok(s.calls[2][0].endsWith('/change'));assert.deepEqual(JSON.parse(JSON.stringify(s.calls[2][1])),{quote_id:'hfq_1',expected_total_minor:201000,expected_additional_minor:39000,currency:'CNY'});
 assert.equal(s.complete,1);
});

test('extension keeps check-in fixed and explains replacement authorization',async()=>{
 const s=setup();s.api=async(...args)=>{s.calls.push(args);return {...s.q,new_amount_minor:244000,additional_amount_minor:82000,fare_difference_minor:81000,change_fee_minor:1000,authorization_replacement_minor:244000,old_authorization_release_minor:162000,nights:[]}};
 await s.ui.change(r,'EXTEND_STAY',(...a)=>s.api(...a),s.onComplete);
 assert.ok(s.dialog.innerHTML.includes('readonly'));
 await s.dialog.querySelector('form').onsubmit({preventDefault(){}});
 for(const text of ['1,620.00','2,440.00','重新授权','不退差额'])assert.ok(s.dialog.querySelector('[data-quote]').innerHTML.includes(text));
 s.dialog.querySelector('[data-close]').onclick();assert.equal(s.calls.length,1);
});
